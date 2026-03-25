"""
分析管线模块 v3.0

核心处理流程：
1. PDF 解析（MinerU 优先）
2. 文本降噪（过滤噪声章节）
3. LLM 语义提取（嵌套式 JSON Schema）
4. 数据校验（Pydantic）
5. 报告生成（Excel/JSON）
"""

from __future__ import annotations

import time
import sys
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote

from tqdm import tqdm

from paperinsight.core.cache import CacheManager
from paperinsight.core.extractor import DataExtractor
from paperinsight.core.if_strategy import IFRequestContext, IFSourceFactory
from paperinsight.core.reporter import ReportGenerator
from paperinsight.models.schemas import PaperData, ExtractionResult
from paperinsight.parser.mineru import MinerUParser
from paperinsight.parser.base import ParseResult
from paperinsight.cleaner.section_filter import SectionFilter, clean_paper_content
from paperinsight.utils.hash_utils import calculate_md5
from paperinsight.utils.file_renamer import FileRenamer
from paperinsight.utils.logger import ErrorLogger, setup_logger
from paperinsight.utils.pdf_utils import extract_text_with_fallback
from paperinsight.web.impact_factor_fetcher import ImpactFactorLookupResult
from paperinsight.web.journal_resolver import MJLJournalResolution
from paperinsight.utils.journal_metadata import canonicalize_journal_title
from paperinsight.exceptions import (
    PaperInsightError,
    ParseError,
    ExtractionError,
    IFLookupError,
    IFSourceError,
    NetworkError,
    CacheVersionError,
    is_recoverable,
)


class AnalysisPipeline:
    """
    v3.0 分析管线

    整合 MinerU 解析 + 文本清洗 + LLM 提取的完整流程。
    """

    def __init__(
        self,
        output_dir: Union[str, Path],
        config: Optional[Dict[str, Any]] = None,
        cache_dir: Union[str, Path] = ".cache",
        fetchers: Optional[Any] = None,
    ):
        """
        初始化分析管线

        Args:
            output_dir: 输出目录
            config: 完整配置字典（包含 mineru, llm, cleaner 等配置）
            cache_dir: 缓存目录
            fetchers: 可选的 WebFetchers 实例（依赖注入）。
                      如果为 None，则从 config 自动创建。
        """
        self.config = config or {}
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.cache_dir = Path(cache_dir)
        self.enable_cache = self.config.get("cache", {}).get("enabled", True)

        # 初始化日志记录器（放在最前面，确保其他初始化可以使用）
        self.logger = setup_logger("paperinsight.pipeline")

        # 初始化缓存管理器
        self.cache_manager = CacheManager(self.cache_dir) if self.enable_cache else None

        # 初始化 MinerU 解析器
        self.parser = self._init_parser()

        # 初始化文本清洗器
        self.cleaner = SectionFilter(self.config.get("cleaner", {}))

        # 初始化数据提取器
        self.extractor = DataExtractor(config=self.config)

        # 初始化 Web 检索器（支持依赖注入）
        if fetchers is not None:
            self.journal_resolver = fetchers.journal_resolver
            self.if_fetcher = fetchers.if_fetcher
            self.letpub_if_fetcher = fetchers.letpub_if_fetcher
            self.search_crawler_fetcher = fetchers.search_crawler_fetcher
            self.wos_if_fetcher = fetchers.wos_if_fetcher
            self.ai_model_if_fetcher = fetchers.ai_model_if_fetcher
        else:
            from paperinsight.core.web_fetcher_factory import WebFetcherFactory

            web_config = self.config.get("web_search", {})
            f = WebFetcherFactory.build(web_config)
            self.journal_resolver = f.journal_resolver
            self.if_fetcher = f.if_fetcher
            self.letpub_if_fetcher = f.letpub_if_fetcher
            self.search_crawler_fetcher = f.search_crawler_fetcher
            self.wos_if_fetcher = f.wos_if_fetcher
            self.ai_model_if_fetcher = f.ai_model_if_fetcher

        # 初始化报告生成器
        self.reporter = ReportGenerator(self.output_dir)

        # 初始化错误日志记录器
        self.error_logger = ErrorLogger(self.output_dir)

        # 构建 IF 策略链
        self._if_strategy_chain = IFSourceFactory.build_chain(
            if_fetcher=self.if_fetcher,
            letpub_if_fetcher=self.letpub_if_fetcher,
            search_crawler_fetcher=self.search_crawler_fetcher,
            wos_if_fetcher=self.wos_if_fetcher,
            ai_model_if_fetcher=self.ai_model_if_fetcher,
            web_config=web_config,
        )
        self._has_any_if_fetcher = IFSourceFactory.has_any_fetcher(
            if_fetcher=self.if_fetcher,
            letpub_if_fetcher=self.letpub_if_fetcher,
            search_crawler_fetcher=self.search_crawler_fetcher,
            wos_if_fetcher=self.wos_if_fetcher,
            ai_model_if_fetcher=self.ai_model_if_fetcher,
        )

        # 性能计时器（各阶段累计耗时，秒）
        self._timing: Dict[str, float] = {}

    def _init_parser(self) -> Optional[MinerUParser]:
        """初始化文档解析器"""
        mineru_config = self.config.get("mineru", {})

        if not mineru_config.get("enabled", True):
            return None

        try:
            parser = MinerUParser(config=mineru_config)
            if parser.is_available():
                self.logger.info(f"[Parser] using MinerU ({mineru_config.get('mode', 'cli')} mode)")
                return parser
            else:
                self.logger.warning("[Parser] MinerU unavailable; falling back to basic PDF parsing")
                return None
        except ParseError as e:
            self.logger.warning(f"[Parser] MinerU initialization failed: {e}")
            return None

    def process_pdf(
        self,
        pdf_path: Path,
        max_pages: Optional[int] = None,
        use_cache: bool = True,
    ) -> Tuple[Optional[PaperData], Optional[Dict[str, Any]]]:
        """
        处理单个 PDF 文件（v3.0 流程）

        流程：
        1. 计算文件 MD5，检查缓存
        2. 使用 MinerU 解析 PDF -> Markdown
        3. 文本降噪，提取核心章节
        4. LLM 提取结构化数据
        5. Pydantic 校验

        Args:
            pdf_path: PDF 文件路径
            max_pages: 最大读取页数
            use_cache: 是否使用缓存

        Returns:
            (提取结果, 错误信息)
        """
        start_time = time.time()
        pdf_name = pdf_path.name
        md5 = calculate_md5(pdf_path) if self.enable_cache else ""

        # Step 1: 检查缓存
        if self.enable_cache and use_cache and self.cache_manager.has_data_cache(md5):
            self.logger.info(f"[CacheHit] {pdf_name}")
            cached_result = self.cache_manager.load_data_cache(md5)
            if cached_result:
                try:
                    paper_data = PaperData(**cached_result)
                    return paper_data, None
                except Exception:
                    self.logger.info(f"[Cache] cache data incompatible for {pdf_name}, re-processing")

        # Step 2: PDF 解析
        parse_stage_time = time.time()
        parse_result = self._parse_pdf(pdf_path, md5, use_cache)
        self._timing["parsing"] = self._timing.get("parsing", 0) + (time.time() - parse_stage_time)

        if not parse_result.success:
            return None, self._build_error_info(
                pdf_name,
                "ParseFailed",
                parse_result.error_message or "PDF 解析失败",
                "PDF解析",
                pdf_path=str(pdf_path),
            )

        return self._extract_from_parse_result(
            pdf_path=pdf_path,
            parse_result=parse_result,
            md5=md5,
            use_cache=use_cache,
            start_time=start_time,
        )

    def _extract_from_parse_result(
        self,
        pdf_path: Path,
        parse_result: ParseResult,
        md5: str,
        use_cache: bool,
        start_time: Optional[float] = None,
    ) -> Tuple[Optional[PaperData], Optional[Dict[str, Any]]]:
        """对解析后的 Markdown 执行清洗、提取、校验与缓存。"""
        pdf_name = pdf_path.name
        start_time = start_time or time.time()
        timing = self._timing
        stage_time = time.time()

        self.logger.info(
            f"[Debug] markdown length: {len(parse_result.markdown) if parse_result.markdown else 0}"
        )
        cleaned_content = self.cleaner.clean(parse_result.markdown)
        extraction_text = cleaned_content.get_text_for_extraction()
        timing["cleaning"] = timing.get("cleaning", 0) + (time.time() - stage_time)
        stage_time = time.time()
        self.logger.info(
            f"[Debug] extraction text length after cleaning: {len(extraction_text) if extraction_text else 0}"
        )
        self.logger.info(
            f"[Debug] full_text={len(cleaned_content.full_text) if cleaned_content.full_text else 0}, "
            f"abstract={len(cleaned_content.abstract) if cleaned_content.abstract else 0}, "
            f"introduction={len(cleaned_content.introduction) if cleaned_content.introduction else 0}, "
            f"experimental={len(cleaned_content.experimental) if cleaned_content.experimental else 0}, "
            f"results={len(cleaned_content.results) if cleaned_content.results else 0}"
        )

        if not extraction_text.strip():
            timing["cleaning"] = timing.get("cleaning", 0) + (time.time() - stage_time)
            return None, self._build_error_info(
                pdf_name,
                "NoContentAfterCleaning",
                "No usable content remained after cleaning",
                "TextCleaning",
                pdf_path=str(pdf_path),
            )

        extraction_result = self.extractor.extract(
            markdown_text=parse_result.markdown,
            cleaned_text=extraction_text,
            parse_result=parse_result,
        )
        timing["extraction"] = timing.get("extraction", 0) + (time.time() - stage_time)
        stage_time = time.time()

        if not extraction_result.success or not extraction_result.data:
            return None, self._build_error_info(
                pdf_name,
                "ExtractionFailed",
                extraction_result.error_message or "Data extraction failed",
                "Extraction",
                pdf_path=str(pdf_path),
            )

        paper_data = extraction_result.data

        journal_resolution = self._resolve_journal_metadata(paper_data)
        if self._has_any_if_fetcher:
            self._supplement_impact_factor(paper_data, journal_resolution)
        timing["if_supplement"] = timing.get("if_supplement", 0) + (time.time() - stage_time)
        stage_time = time.time()
        if self._needs_lite_backfill(paper_data):
            self.logger.info(
                f"[LLM] lite backfill triggered: {pdf_name} | missing={','.join(self._collect_missing_core_fields(paper_data))}"
            )
            paper_data = self.extractor.lite_backfill_paper_info(
                paper_data,
                extraction_text,
                parse_result,
            )
            journal_resolution = self._resolve_journal_metadata(paper_data)
            if any(
                [
                    self.letpub_if_fetcher,
                    self.if_fetcher,
                    self.ai_model_if_fetcher,
                    self.search_crawler_fetcher,
                    self.wos_if_fetcher,
                ]
            ):
                self._supplement_impact_factor(paper_data, journal_resolution)
        timing["if_supplement"] = timing.get("if_supplement", 0) + (time.time() - stage_time)
        stage_time = time.time()

        if self.enable_cache and use_cache:
            self.cache_manager.save_data_cache(md5, paper_data.model_dump())

        timing["cache_save"] = timing.get("cache_save", 0) + (time.time() - stage_time)
        processing_time = time.time() - start_time
        self.logger.info(
            f"[Done] {pdf_name} ({processing_time:.1f}s) "
            f"[clean={timing.get('cleaning', 0):.1f}s "
            f"extract={timing.get('extraction', 0):.1f}s "
            f"if={timing.get('if_supplement', 0):.1f}s]"
        )

        return paper_data, None

    @staticmethod
    def _needs_lite_backfill(paper_data: PaperData) -> bool:
        paper_info = paper_data.paper_info
        return any(
            [
                not paper_info.title,
                not (paper_info.journal_name or paper_info.raw_journal_title),
                paper_info.impact_factor in (None, 0),
                not paper_info.year,
            ]
        )

    @staticmethod
    def _collect_missing_core_fields(paper_data: PaperData) -> list[str]:
        paper_info = paper_data.paper_info
        missing = []
        if not paper_info.title:
            missing.append("title")
        if not (paper_info.journal_name or paper_info.raw_journal_title):
            missing.append("journal")
        if paper_info.impact_factor in (None, 0):
            missing.append("impact_factor")
        if not paper_info.year:
            missing.append("year")
        return missing

    def _parse_pdf(
        self,
        pdf_path: Path,
        md5: str,
        use_cache: bool,
    ) -> ParseResult:
        """
        解析 PDF 文件

        优先使用 MinerU，失败则回退到基础解析。
        """
        # 检查 Markdown 缓存
        if self.enable_cache and use_cache and self.cache_manager.has_markdown_cache(md5):
            cached_text = self.cache_manager.load_markdown_cache(md5) or ""
            return ParseResult(
                markdown=cached_text,
                raw_text=cached_text,
                success=True,
                parser_name="cache",
            )

        # 使用 MinerU 解析
        if self.parser and self.parser.is_available():
            try:
                result = self.parser.parse(pdf_path)
                if result.success and result.markdown:
                    # 保存 Markdown 缓存
                    if self.enable_cache:
                        self.cache_manager.save_markdown_cache(md5, result.markdown)
                    return result
            except Exception as e:
                self.logger.error(f"[MinerU] parse failed: {e}; falling back to basic parsing", exc_info=True)

        # 回退到基础 PDF 解析
        text_ratio_threshold = self.config.get("pdf", {}).get("text_ratio_threshold", 0.1)
        full_text, front_text, metadata = extract_text_with_fallback(
            pdf_path,
            min_text_ratio=text_ratio_threshold,
        )

        return ParseResult(
            markdown=full_text,
            raw_text=full_text,
            success=bool(full_text),
            parser_name="pymupdf",
            metadata=metadata,
        )

    def _resolve_journal_metadata(self, paper_data: PaperData) -> Optional[MJLJournalResolution]:
        """补全期刊标准信息。"""
        if not self.journal_resolver:
            return None

        paper_info = paper_data.paper_info
        raw_journal_title = paper_info.raw_journal_title or paper_info.journal_name
        raw_issn = paper_info.raw_issn
        raw_eissn = paper_info.raw_eissn

        if not any((raw_journal_title, raw_issn, raw_eissn)):
            return None

        try:
            resolution = self.journal_resolver.resolve(
                journal_title=raw_journal_title,
                issn=raw_issn,
                eissn=raw_eissn,
            )
        except Exception as e:
            self.logger.error(f"[JournalResolve] failed: {e}", exc_info=True)
            return None

        if raw_journal_title and not paper_info.raw_journal_title:
            paper_info.raw_journal_title = raw_journal_title

        if resolution.match_method:
            paper_info.match_method = resolution.match_method

        selected_candidate = self._select_journal_candidate(resolution, raw_journal_title)

        if selected_candidate:
            paper_info.matched_journal_title = (
                selected_candidate.display_title or paper_info.matched_journal_title
            )
            paper_info.matched_issn = selected_candidate.issn or selected_candidate.eissn or paper_info.matched_issn
            paper_info.journal_profile_url = selected_candidate.search_url
            paper_info.journal_name = selected_candidate.display_title or paper_info.journal_name or raw_journal_title
            if resolution.status != "OK":
                paper_info.match_method = f"{paper_info.match_method or resolution.status}_selected"
        elif resolution.candidate:
            paper_info.matched_journal_title = resolution.matched_journal_title
            paper_info.matched_issn = resolution.matched_issn
            paper_info.journal_profile_url = resolution.candidate.search_url
            paper_info.journal_name = resolution.matched_journal_title or paper_info.journal_name
        elif resolution.search_value and not paper_info.journal_profile_url:
            search_value = resolution.search_value
            if "-" in search_value and len(search_value) == 9:
                paper_info.journal_profile_url = (
                    f"{self.journal_resolver.SEARCH_RESULTS_URL}?issn={quote(search_value)}"
                )
            else:
                paper_info.journal_profile_url = (
                    f"{self.journal_resolver.SEARCH_RESULTS_URL}?search={quote(search_value)}"
                )

        return resolution

    @staticmethod
    def _select_journal_candidate(
        resolution: MJLJournalResolution,
        raw_journal_title: Optional[str],
    ):
        if resolution.candidate:
            return resolution.candidate
        if not resolution.candidates:
            return None

        raw_canonical = canonicalize_journal_title(raw_journal_title)
        if raw_canonical:
            exact_matches = [
                candidate
                for candidate in resolution.candidates
                if canonicalize_journal_title(candidate.display_title) == raw_canonical
            ]
            if len(exact_matches) == 1:
                return exact_matches[0]
            if exact_matches:
                return None
        return None

    def _supplement_impact_factor(
        self,
        paper_data: PaperData,
        journal_resolution: Optional[MJLJournalResolution] = None,
    ) -> None:
        """补全影响因子（v3.2 策略链重构）。

        使用 IFSourceFactory 构建策略链，按优先级调用各 IF 来源，
        并通过交叉验证选择最佳结果。
        """
        paper_info = paper_data.paper_info
        journal_name = paper_info.journal_name or paper_info.raw_journal_title
        paper_title = paper_info.title

        try:
            current_if = paper_info.impact_factor
            web_config = self.config.get("web_search", {})
            should_correct_existing = bool(web_config.get("correct_existing_impact_factor", True))
            fetch_official_impact_factor = bool(web_config.get("fetch_official_impact_factor", True))
            validation_tolerance = float(web_config.get("impact_factor_validation_tolerance", 0.6))

            # 已有有效 IF 且不需要修正时跳过
            if current_if and not should_correct_existing and 0.1 <= current_if <= 200 and not fetch_official_impact_factor:
                return

            # 期刊解析
            resolution = journal_resolution
            candidate = None
            if any((journal_name, paper_info.raw_issn, paper_info.raw_eissn)):
                resolution = resolution or self._resolve_journal_metadata(paper_data)
                if resolution is not None:
                    candidate = self._select_journal_candidate(resolution, journal_name)

            if resolution is not None and resolution.status == "MULTI_MATCH" and candidate is None:
                paper_info.impact_factor_source = "MJL_RESOLVER"
                paper_info.impact_factor_status = resolution.status
                return

            # NO_MATCH resolution: 设置状态并返回
            if resolution is not None and resolution.status == "NO_MATCH":
                paper_info.impact_factor_source = "MJL_RESOLVER"
                paper_info.impact_factor_status = "NO_MATCH"
                return

            # 构建请求上下文
            ctx = IFRequestContext(
                paper_info=paper_info,
                journal_name=journal_name,
                paper_title=paper_title,
                journal_resolution=resolution,
                journal_candidate=candidate,
                current_if=current_if,
                should_correct_existing=should_correct_existing,
                validation_tolerance=validation_tolerance,
            )

            # 通过策略链收集各来源结果
            official_result = self._collect_official_if(ctx, fetch_official_impact_factor)
            secondary_results = self._collect_secondary_ifs(ctx)
            letpub_result = self._collect_letpub_if(ctx)

            # 尝试从官方结果中获取有效 IF
            if self._try_apply_official_result(
                paper_info, official_result, letpub_result, secondary_results,
                current_if, should_correct_existing, validation_tolerance,
            ):
                return

            # 官方无结果或 NO_ACCESS，尝试次级来源
            if official_result and official_result.status == "NO_ACCESS":
                self._apply_impact_factor_status(paper_info, official_result)
                self.logger.info("[IFLookup] official IF unavailable due to NO_ACCESS")
                return

            # 尝试从次级来源中选择验证过的结果
            selected_result = self._select_validated_impact_factor_result(
                letpub_result=letpub_result,
                secondary_results=secondary_results,
                tolerance=validation_tolerance,
            )
            if selected_result and self._apply_impact_factor_result(
                paper_info, selected_result, current_if=current_if,
                should_correct_existing=should_correct_existing,
            ):
                self.logger.info(
                    f"[IFLookup] selected IF={selected_result.impact_factor}, source={selected_result.source_name}"
                )
                return

            # 尝试 AI 模型方式
            ai_result = self._try_ai_model_if(ctx, web_config)
            if ai_result and self._apply_impact_factor_result(
                paper_info, ai_result, current_if=current_if,
                should_correct_existing=should_correct_existing,
            ):
                return

            # 最终回退：应用官方状态（如果有）
            if official_result is not None:
                self._apply_impact_factor_status(paper_info, official_result)

        except Exception as e:
            self.logger.error(f"[IFLookup] failed: {e}", exc_info=True)

    def _collect_official_if(
        self, ctx: IFRequestContext, fetch_official: bool,
    ) -> Optional[ImpactFactorLookupResult]:
        """通过官方策略（MJL Profile API）获取 IF。"""
        if not fetch_official or self.if_fetcher is None or ctx.journal_candidate is None:
            return None
        try:
            return self.if_fetcher.lookup(ctx.journal_candidate)
        except Exception as e:
            self.logger.error(f"[IFLookup] MJL_PROFILE_API lookup failed: {e}", exc_info=True)
            return ImpactFactorLookupResult(
                status="ERROR",
                source_name="MJL_PROFILE_API",
                source_url=ctx.paper_info.journal_profile_url or "",
                error_message=str(e),
            )

    def _collect_secondary_ifs(self, ctx: IFRequestContext) -> List[ImpactFactorLookupResult]:
        """收集所有次级来源的 IF 结果。"""
        results: List[ImpactFactorLookupResult] = []

        # CuratedFallbackStrategy — 使用 if_fetcher.lookup_by_title
        if self.if_fetcher is not None:
            journal = ctx.paper_info.journal_name or ctx.paper_info.raw_journal_title
            if journal:
                try:
                    result = self.if_fetcher.lookup_by_title(journal)
                    if result is not None:
                        results.append(result)
                except Exception as e:
                    self.logger.error(f"[IFLookup] CURATED_FALLBACK lookup failed: {e}", exc_info=True)

        # SearchCrawlerStrategy
        if self.search_crawler_fetcher is not None:
            journal = ctx.paper_info.journal_name or ctx.paper_info.raw_journal_title
            if journal:
                try:
                    result = self.search_crawler_fetcher.lookup(
                        journal_title=journal,
                        issn=ctx.paper_info.matched_issn or ctx.paper_info.raw_issn,
                        eissn=ctx.paper_info.raw_eissn,
                    )
                    if result is not None:
                        results.append(result)
                except Exception as e:
                    self.logger.error(f"[IFLookup] SEARCH_CRAWLER lookup failed: {e}", exc_info=True)

        # WOS Journals
        if self.wos_if_fetcher is not None:
            journal = ctx.paper_info.journal_name or ctx.paper_info.raw_journal_title
            if journal:
                try:
                    result = self.wos_if_fetcher.lookup(
                        journal_title=journal,
                        issn=ctx.paper_info.matched_issn or ctx.paper_info.raw_issn,
                        eissn=ctx.paper_info.raw_eissn,
                    )
                    if result is not None:
                        results.append(result)
                except Exception as e:
                    self.logger.error(f"[IFLookup] WOS_JOURNALS lookup failed: {e}", exc_info=True)

        return results

    def _collect_letpub_if(self, ctx: IFRequestContext) -> Optional[ImpactFactorLookupResult]:
        """通过 LetPub 策略获取 IF。"""
        if self.letpub_if_fetcher is None:
            return None
        letpub_journal_name = (
            ctx.journal_candidate.display_title
            if ctx.journal_candidate and ctx.journal_candidate.display_title
            else None
        ) or ctx.journal_name
        if not any((letpub_journal_name, ctx.paper_info.raw_issn, ctx.paper_info.raw_eissn)):
            return None
        return self.letpub_if_fetcher.lookup(
            journal_title=letpub_journal_name,
            issn=ctx.paper_info.matched_issn or ctx.paper_info.raw_issn,
            eissn=ctx.paper_info.raw_eissn,
        )

    def _try_ai_model_if(
        self, ctx: IFRequestContext, web_config: Dict[str, Any],
    ) -> Optional[ImpactFactorLookupResult]:
        """尝试 AI 模型方式获取 IF。"""
        use_ai = bool(web_config.get("use_ai_model_if", False))
        if not use_ai or self.ai_model_if_fetcher is None:
            return None
        logger = self.logger
        logger.info(
            f"[IFLookup] query via AI method: journal={ctx.journal_name}, "
            f"title={ctx.paper_title[:30] if ctx.paper_title else 'N/A'}..."
        )
        try:
            fetch_result = self.ai_model_if_fetcher.lookup(
                paper_title=ctx.paper_title or "",
                journal_name=ctx.journal_name,
            )
            if fetch_result.status == "OK" and fetch_result.impact_factor is not None:
                logger.info(
                    f"[IFLookup] AI method succeeded: IF={fetch_result.impact_factor}, "
                    f"source={fetch_result.source_name}"
                )
                return fetch_result
            else:
                logger.warning(f"[IFLookup] AI method failed: {fetch_result.error_message}")
                return None
        except Exception as e:
            logger.warning(f"[IFLookup] AI method error: {e}")
            return None

    def _try_apply_official_result(
        self,
        paper_info,
        official_result: Optional[ImpactFactorLookupResult],
        letpub_result: Optional[ImpactFactorLookupResult],
        secondary_results: List[ImpactFactorLookupResult],
        current_if: Optional[float],
        should_correct_existing: bool,
        tolerance: float,
    ) -> bool:
        """尝试使用官方 IF 结果（含交叉验证）。"""
        if not official_result or official_result.status != "OK" or official_result.impact_factor is None:
            return False

        validators = [
            result
            for result in [letpub_result, *secondary_results]
            if result is not None
            and result.status == "OK"
            and result.impact_factor is not None
            and abs(result.impact_factor - official_result.impact_factor) <= tolerance
        ]
        selected = self._merge_impact_factor_results(
            primary=official_result,
            validators=validators,
            status="OK_VALIDATED" if validators else "OK",
        )
        if self._apply_impact_factor_result(
            paper_info, selected, current_if=current_if,
            should_correct_existing=should_correct_existing,
        ):
            self.logger.info(
                f"[IFLookup] selected IF={selected.impact_factor}, source={selected.source_name}"
            )
            return True
        return False

    def _select_validated_impact_factor_result(
        self,
        *,
        letpub_result: Optional[ImpactFactorLookupResult],
        secondary_results: List[ImpactFactorLookupResult],
        tolerance: float,
    ) -> Optional[ImpactFactorLookupResult]:
        valid_secondaries = [
            result
            for result in secondary_results
            if result.status in {"OK", "OK_STALE"}
            and result.impact_factor is not None
        ]

        if letpub_result and letpub_result.status == "OK" and letpub_result.impact_factor is not None:
            matched_secondaries = [
                result
                for result in valid_secondaries
                if abs(result.impact_factor - letpub_result.impact_factor) <= tolerance
            ]
            if matched_secondaries:
                return self._merge_impact_factor_results(
                    primary=letpub_result,
                    validators=matched_secondaries,
                    status="OK_VALIDATED",
                )

            authoritative_secondaries = [
                result for result in valid_secondaries if self._is_authoritative_if_source(result.source_name)
            ]
            authoritative_consensus = self._select_consensus_secondary_result(
                authoritative_secondaries,
                tolerance=tolerance,
            )
            if authoritative_consensus:
                return self._merge_impact_factor_results(
                    primary=authoritative_consensus,
                    validators=[letpub_result],
                    status="OK_VALIDATED_SECONDARY",
                )

            consensus_secondary = self._select_consensus_secondary_result(
                valid_secondaries,
                tolerance=tolerance,
            )
            if consensus_secondary:
                return self._merge_impact_factor_results(
                    primary=consensus_secondary,
                    validators=[letpub_result],
                    status="OK_VALIDATED_SECONDARY",
                )

            return self._merge_impact_factor_results(
                primary=letpub_result,
                validators=valid_secondaries,
                status="OK_LETPUB_UNCONFIRMED" if valid_secondaries else "OK_LETPUB_ONLY",
            )

        consensus_secondary = self._select_consensus_secondary_result(
            valid_secondaries,
            tolerance=tolerance,
        )
        if consensus_secondary:
            return self._merge_impact_factor_results(
                primary=consensus_secondary,
                validators=[result for result in valid_secondaries if result is not consensus_secondary],
                status="OK_SECONDARY_VALIDATED",
            )

        return self._select_best_secondary_result(valid_secondaries)

    def _select_consensus_secondary_result(
        self,
        results: List[ImpactFactorLookupResult],
        *,
        tolerance: float,
    ) -> Optional[ImpactFactorLookupResult]:
        if len(results) < 2:
            return None

        for base in sorted(results, key=self._impact_factor_result_sort_key):
            matches = [
                result
                for result in results
                if abs(result.impact_factor - base.impact_factor) <= tolerance
            ]
            if len(matches) >= 2:
                return self._merge_impact_factor_results(
                    primary=base,
                    validators=[result for result in matches if result is not base],
                    status="OK_VALIDATED",
                )
        return None

    def _merge_impact_factor_results(
        self,
        *,
        primary: ImpactFactorLookupResult,
        validators: List[ImpactFactorLookupResult],
        status: str,
    ) -> ImpactFactorLookupResult:
        ordered = [primary, *validators]
        source_name = "+".join(dict.fromkeys(result.source_name for result in ordered if result.source_name))
        source_url = next((result.source_url for result in ordered if result.source_url), "")
        year = next((result.year for result in ordered if result.year), primary.year)
        return ImpactFactorLookupResult(
            status=status,
            source_name=source_name or primary.source_name,
            source_url=source_url or primary.source_url,
            impact_factor=primary.impact_factor,
            year=year,
            error_message=primary.error_message,
        )

    def _select_best_secondary_result(
        self,
        results: List[ImpactFactorLookupResult],
    ) -> Optional[ImpactFactorLookupResult]:
        valid_results = [
            result
            for result in results
            if result.status in {"OK", "OK_STALE"}
            and result.impact_factor is not None
        ]
        if not valid_results:
            return None
        return sorted(valid_results, key=self._impact_factor_result_sort_key)[0]

    @staticmethod
    def _impact_factor_result_sort_key(result: ImpactFactorLookupResult) -> tuple[int, int, float]:
        return (
            -(result.year or 0),
            AnalysisPipeline._impact_factor_source_priority(result.source_name),
            -(result.impact_factor or 0.0),
        )

    @staticmethod
    def _impact_factor_source_priority(source_name: Optional[str]) -> int:
        priorities = {
            "WOS_JOURNALS_API": 0,
            "MJL_PROFILE_API": 1,
            "CURATED_FALLBACK": 2,
            "SEARCH_CRAWLER": 3,
            "LETPUB": 4,
        }
        source_tokens = [token for token in (source_name or "").split("+") if token]
        if not source_tokens:
            return 9
        return min(priorities.get(token, 9) for token in source_tokens)

    @staticmethod
    def _is_authoritative_if_source(source_name: Optional[str]) -> bool:
        return (source_name or "") in {"WOS_JOURNALS_API", "MJL_PROFILE_API", "CURATED_FALLBACK"}

    @staticmethod
    def _apply_impact_factor_result(
        paper_info,
        fetch_result: Any,
        *,
        current_if: Optional[float],
        should_correct_existing: bool,
    ) -> bool:
        source_url = fetch_result.source_url
        if source_url:
            paper_info.journal_profile_url = source_url

        result_status = fetch_result.status or ""
        new_source_name = fetch_result.source_name
        impact_factor = fetch_result.impact_factor
        if not str(result_status).startswith("OK") or impact_factor is None:
            return False

        if (
            current_if is not None
            and abs(current_if - impact_factor) < 1e-6
            and paper_info.impact_factor_source
            and new_source_name
        ):
            combined_sources = "+".join(
                dict.fromkeys(
                    source
                    for source in [*paper_info.impact_factor_source.split("+"), *new_source_name.split("+")]
                    if source
                )
            )
            paper_info.impact_factor_source = combined_sources
        else:
            paper_info.impact_factor_source = new_source_name

        if not (paper_info.impact_factor_status and str(paper_info.impact_factor_status).startswith("OK_VALIDATED")):
            paper_info.impact_factor_status = result_status

        paper_info.impact_factor_year = fetch_result.year

        if current_if is None or current_if <= 0:
            paper_info.impact_factor = impact_factor
            return True

        if current_if < 0.1 or current_if > 200:
            paper_info.impact_factor = impact_factor
            return True

        source_tokens = set((new_source_name or "").split("+"))
        if should_correct_existing and "MJL_PROFILE_API" in source_tokens and abs(current_if - impact_factor) > 1e-6:
            paper_info.impact_factor = impact_factor
        elif should_correct_existing and abs(current_if - impact_factor) >= 0.5:
            paper_info.impact_factor = impact_factor

        return True

    @staticmethod
    def _apply_impact_factor_status(paper_info, fetch_result: Any) -> None:
        source_url = fetch_result.source_url
        if source_url:
            paper_info.journal_profile_url = source_url

        source_name = fetch_result.source_name
        if source_name:
            paper_info.impact_factor_source = source_name

        status = fetch_result.status
        if status:
            paper_info.impact_factor_status = status

        paper_info.impact_factor_year = fetch_result.year

        if status == "NO_ACCESS":
            paper_info.impact_factor = None

    def process_batch(
        self,
        pdf_files: List[Path],
        max_pages: Optional[int] = None,
        use_cache: bool = True,
        batch_size: int = 1,
    ) -> Tuple[List[PaperData], List[Dict[str, Any]], List[Tuple[Path, PaperData]]]:
        """
        批量处理 PDF 文件

        Args:
            pdf_files: PDF 文件列表
            max_pages: 最大读取页数
            use_cache: 是否使用缓存

        Returns:
            (成功结果列表, 错误列表, 处理项列表)
        """
        results: List[PaperData] = []
        errors: List[Dict[str, Any]] = []
        processed_items: List[Tuple[Path, PaperData]] = []

        pending_files: List[Tuple[Path, str]] = []

        use_progress = bool(getattr(sys.stdout, "isatty", lambda: False)())

        with tqdm(total=len(pdf_files), desc="Processing PDFs", disable=not use_progress) as progress_bar:
            for pdf_path in pdf_files:
                md5 = calculate_md5(pdf_path) if self.enable_cache else ""
                if self.enable_cache and use_cache and self.cache_manager.has_data_cache(md5):
                    self.logger.info(f"[CacheHit] {pdf_path.name}")
                    cached_result = self.cache_manager.load_data_cache(md5)
                    if cached_result:
                        try:
                            paper_data = PaperData(**cached_result)
                            results.append(paper_data)
                            processed_items.append((pdf_path, paper_data))
                            progress_bar.update(1)
                            continue
                        except Exception:
                            self.logger.info(f"[Cache] stale cache for {pdf_path.name}, re-processing")
                pending_files.append((pdf_path, md5))

            use_mineru_batch = (
                bool(pending_files)
                and self.parser
                and isinstance(self.parser, MinerUParser)
                and self.parser.mode == "api"
                and batch_size > 1
                and len(pending_files) > 1
                and hasattr(self.parser, "parse_batch")
            )

            if use_mineru_batch:
                total_batches = ceil(len(pending_files) / batch_size)
                for batch_index, batch_items in enumerate(self._chunk_items(pending_files, batch_size), start=1):
                    batch_paths = [pdf_path for pdf_path, _ in batch_items]
                    self.logger.info(
                        f"[MinerU Batch] batch {batch_index}/{total_batches}, files={len(batch_paths)}"
                    )
                    try:
                        parse_results = self.parser.parse_batch(
                            batch_paths,
                            progress_callback=lambda info, batch_index=batch_index, total_batches=total_batches: (
                                progress_bar.set_postfix_str(
                                    "batch "
                                    f"{batch_index}/{total_batches} | "
                                    f"done {info.get('done', 0)}/{info.get('total', 0)} | "
                                    f"running {info.get('running', 0)}"
                                )
                                if use_progress
                                else None
                            ),
                        )
                    except Exception as e:
                        self.logger.error(
                            f"[MinerU Batch] batch parse failed; retrying one by one: {e}",
                            exc_info=True,
                        )
                        parse_results = {}

                    for pdf_path, md5 in batch_items:
                        parse_result = parse_results.get(pdf_path)
                        if parse_result and parse_result.success:
                            paper_data, error_info = self._extract_from_parse_result(
                                pdf_path=pdf_path,
                                parse_result=parse_result,
                                md5=md5,
                                use_cache=use_cache,
                            )
                        else:
                            paper_data, error_info = self.process_pdf(pdf_path, max_pages, use_cache)

                        self._collect_batch_item_result(
                            pdf_path,
                            paper_data,
                            error_info,
                            results,
                            errors,
                            processed_items,
                        )
                        progress_bar.update(1)
            else:
                for pdf_path, _ in pending_files:
                    paper_data, error_info = self.process_pdf(pdf_path, max_pages, use_cache)
                    self._collect_batch_item_result(
                        pdf_path,
                        paper_data,
                        error_info,
                        results,
                        errors,
                        processed_items,
                    )
                    progress_bar.update(1)

        return results, errors, processed_items

    def run(
        self,
        pdf_dir: Union[str, Path],
        recursive: bool = False,
        max_pages: Optional[int] = None,
        use_cache: bool = True,
        sort_by_if: bool = True,
        rename_pdfs: bool = False,
        rename_template: Optional[str] = None,
        pdf_files: Optional[List[Path]] = None,
        batch_size: int = 1,
    ) -> Dict[str, Any]:
        """
        运行分析管线

        Args:
            pdf_dir: PDF 目录
            recursive: 是否递归扫描
            max_pages: 最大读取页数
            use_cache: 是否使用缓存
            sort_by_if: 是否按影响因子排序
            rename_pdfs: 是否重命名 PDF
            rename_template: 重命名模板

        Returns:
            运行统计信息
        """
        pdf_dir = Path(pdf_dir)

        # 重置性能计时器
        self._timing = {}

        # 收集 PDF 文件
        if pdf_files is None:
            if recursive:
                pdf_files = list(pdf_dir.rglob("*.pdf"))
            else:
                pdf_files = list(pdf_dir.glob("*.pdf"))

        pdf_files = [Path(f) for f in pdf_files if Path(f).is_file()]
        self.logger.info(f"Found {len(pdf_files)} PDF files")

        if not pdf_files:
            self.logger.warning("No PDF files found")
            return {"status": "no_files", "pdf_count": 0}

        # 批量处理
        results, errors, processed_items = self.process_batch(
            pdf_files, max_pages, use_cache, batch_size=batch_size
        )

        # 重命名 PDF
        renamed_count = 0
        if rename_pdfs and processed_items:
            renamed_count = self._rename_pdfs(
                processed_items, rename_template or "[{year}_{impact_factor}_{journal}]_{title}.pdf"
            )

        # 生成报告
        report_files = self._generate_reports(processed_items, errors, sort_by_if)

        # 保存错误日志
        if self.error_logger.errors:
            error_log_path = self.error_logger.save()
            if error_log_path:
                report_files["error_log"] = str(error_log_path)
                self.logger.info(f"[ErrorLog] saved: {error_log_path}")

        # 统计信息
        stats = {
            "status": "completed",
            "pdf_count": len(pdf_files),
            "success_count": len(results),
            "error_count": len(errors),
            "report_files": report_files,
            "renamed_count": renamed_count,
            "timestamp": datetime.now().isoformat(),
            "timing": dict(self._timing) if self._timing else {},
        }

        # 输出统计
        self._print_summary(stats)

        return stats

    def _rename_pdfs(
        self,
        processed_items: List[Tuple[Path, PaperData]],
        rename_template: str,
    ) -> int:
        """重命名 PDF 文件"""
        renamer = FileRenamer(output_dir=None, dry_run=False)

        # 转换为旧格式以兼容 FileRenamer
        old_format_items = []
        for pdf_path, paper_data in processed_items:
            old_result = paper_data.to_excel_row()
            old_result["_cache_md5"] = calculate_md5(pdf_path)
            old_format_items.append((pdf_path, old_result))

        rename_results = renamer.batch_rename(old_format_items, format_template=rename_template)

        renamed_count = 0
        for index, (_, new_path) in enumerate(rename_results):
            if new_path is None:
                continue
            renamed_count += 1
            # 更新缓存
            if self.enable_cache:
                paper_data = processed_items[index][1]
                md5 = calculate_md5(processed_items[index][0])
                self.cache_manager.save_data_cache(md5, paper_data.model_dump())

        return renamed_count

    def _generate_reports(
        self,
        processed_items: List[Tuple[Path, PaperData]],
        errors: List[Dict[str, Any]],
        sort_by_if: bool,
    ) -> Dict[str, str]:
        """生成报告"""
        report_files = {}

        output_config = self.config.get("output", {})
        formats = output_config.get("format", ["excel"])

        if not processed_items:
            return report_files

        dict_results = []
        json_results = []
        for pdf_path, paper_data in processed_items:
            row = paper_data.to_excel_row()
            row["File"] = pdf_path.name
            row["URL"] = pdf_path.resolve().as_uri()
            row["processing_status"] = self._build_processing_summary(paper_data)
            dict_results.append(row)

            json_row = paper_data.model_dump()
            json_row["File"] = pdf_path.name
            json_row["URL"] = pdf_path.resolve().as_uri()
            json_row["processing_status"] = row["processing_status"]
            json_results.append(json_row)

        for error in errors:
            error_row = ReportGenerator.empty_result_row(
                file_name=error.get("pdf_name", ""),
                file_url=Path(error["pdf_path"]).resolve().as_uri() if error.get("pdf_path") else "",
                processing_status=self._build_error_summary(error),
            )
            dict_results.append(error_row)

            json_results.append(
                {
                    "File": error.get("pdf_name", ""),
                    "URL": Path(error["pdf_path"]).resolve().as_uri() if error.get("pdf_path") else "",
                    "processing_status": error_row["processing_status"],
                    "error": error,
                }
            )

        # 生成 Excel
        if "excel" in formats:
            excel_path = self.reporter.generate_excel_report(dict_results, sort_by_if=sort_by_if)
            if excel_path:
                report_files["excel"] = str(excel_path)

        # 生成 JSON
        if "json" in formats:
            json_path = self.reporter.generate_json_report(json_results, sort_by_if=sort_by_if)
            if json_path:
                report_files["json"] = str(json_path)

        return report_files

    def _print_summary(self, stats: Dict[str, Any]) -> None:
        """打印处理摘要"""
        self.logger.info("=" * 70)
        self.logger.info("Processing complete")
        self.logger.info(f"PDF count: {stats['pdf_count']}")
        self.logger.info(f"Success: {stats['success_count']}")
        self.logger.info(f"Failed: {stats['error_count']}")
        timing = stats.get("timing", {})
        if timing:
            total = sum(timing.values())
            self.logger.info(f"Timing total: {total:.1f}s")
            for stage, elapsed in sorted(timing.items(), key=lambda x: -x[1]):
                pct = (elapsed / total * 100) if total > 0 else 0
                self.logger.info(f"  {stage}: {elapsed:.1f}s ({pct:.0f}%)")
        self.logger.info("=" * 70)

    @staticmethod
    def _build_error_info(
        pdf_name: str,
        error_type: str,
        error_message: str,
        context: str = "PDF处理",
        pdf_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构建错误信息"""
        return {
            "pdf_name": pdf_name,
            "pdf_path": pdf_path,
            "error_type": error_type,
            "error_message": error_message,
            "context": context,
        }

    @staticmethod
    def _build_processing_summary(paper_data: PaperData) -> str:
        info = paper_data.paper_info
        missing = []
        if not info.journal_name:
            missing.append("journal")
        if info.impact_factor in (None, 0):
            missing.append("impact factor")
        if not paper_data.devices:
            missing.append("device data")
        else:
            best_device = paper_data.get_best_device()
            if not best_device or not best_device.eqe:
                missing.append("EQE")
            if not best_device or not best_device.structure:
                missing.append("structure")

        warnings = []
        if_status = str(info.impact_factor_status or "")
        if "STALE" in if_status:
            year_display = info.impact_factor_year or "?"
            warnings.append(f"IF year {year_display} may be outdated")

        parts = []
        if not missing:
            parts.append("Completed: core fields are available")
        elif len(missing) >= 4:
            parts.append("Partial extraction: missing " + ", ".join(missing[:5]))
        else:
            parts.append("Completed with gaps: " + ", ".join(missing))

        if warnings:
            parts.append("Warnings: " + "; ".join(warnings))

        return " | ".join(parts)

    @staticmethod
    def _build_error_summary(error: Dict[str, Any]) -> str:
        context = error.get("context", "Pipeline")
        message = error.get("error_message", "Unknown error").strip()
        if len(message) > 70:
            message = message[:67].rstrip() + "..."
        return f"Failed: {context} - {message}"

    def _collect_batch_item_result(
        self,
        pdf_path: Path,
        paper_data: Optional[PaperData],
        error_info: Optional[Dict[str, Any]],
        results: List[PaperData],
        errors: List[Dict[str, Any]],
        processed_items: List[Tuple[Path, PaperData]],
    ) -> None:
        """收集批量处理单个文件的结果。"""
        if paper_data:
            results.append(paper_data)
            processed_items.append((pdf_path, paper_data))
            return

        if error_info:
            errors.append(error_info)
            self.error_logger.log_error(
                error_info["pdf_name"],
                Exception(error_info["error_message"]),
                context=error_info.get("context", "PDF"),
            )

    @staticmethod
    def _chunk_items(items: List[Tuple[Path, str]], chunk_size: int) -> List[List[Tuple[Path, str]]]:
        """按批次切分列表。"""
        if chunk_size <= 0:
            chunk_size = 1
        return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    def cleanup_temp_files(self):
        """清理临时文件"""
        temp_extensions = [".tmp", ".temp"]
        temp_files = []

        for ext in temp_extensions:
            temp_files.extend(self.output_dir.glob(f"*{ext}"))
            temp_files.extend(Path(".").glob(f"*{ext}"))

        for temp_file in temp_files:
            try:
                temp_file.unlink()
                self.logger.info(f"Temporary file removed: {temp_file}")
            except OSError as e:
                self.logger.error(f"Temporary file cleanup failed: {temp_file}, {e}")
