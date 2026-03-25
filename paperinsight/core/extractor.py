"""
数据提取器模块 v3.1

功能：
1. 使用 LLM 进行语义化数据提取
2. 嵌套式 JSON Schema 输出
3. Pydantic 数据校验
4. 正则表达式兜底方案

v3.1 重构：将正则提取逻辑拆分为独立纯函数模块（composition 模式），
    DataExtractor 方法委托到子模块函数，保持公共 API 不变。
    - journal_utils: 期刊名称提取、ISSN 提取、别名查找
    - device_extractor: 器件数据提取、去重、排序
    - metadata_extractor: 标题/作者提取、论文属性检测
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from paperinsight.models.schemas import (
    DeviceData,
    PaperData,
    PaperInfo,
    ExtractionResult,
    DataSourceReference,
    OptimizationInfo,
    PAPER_DATA_JSON_SCHEMA,
)
from paperinsight.parser.base import ParseResult
from paperinsight.llm.base import BaseLLM
from paperinsight.llm import create_llm_client
from paperinsight.llm.prompt_templates import (
    format_bilingual_postprocess_prompt,
    format_extraction_prompt_v3,
    format_lite_paper_info_backfill_prompt,
)
from paperinsight.utils.logger import setup_logger

# ── 子模块导入（composition） ───────────────────────────────────

from paperinsight.core.journal_utils import (
    JOURNAL_DOMAIN_HINTS,
    JOURNAL_TITLE_ALIASES,
    JOURNAL_LINE_PATTERNS,
    load_journal_aliases,
    extract_raw_journal_metadata,
    extract_journal_name,
    extract_journal_name_from_subject,
    extract_journal_name_from_filename,
    extract_issn_from_text,
    extract_pdf_metadata_from_source,
    normalize_journal_title_candidate,
    coerce_metadata_value,
    first_non_empty,
)
from paperinsight.core.device_extractor import (
    extract_devices,
    extract_candidate_devices,
    extract_all_structures,
    extract_all_eqe,
    extract_all_cie,
    extract_all_lifetime,
    build_device_segments,
    segment_signal_score,
    extract_first_structure,
    extract_first_eqe,
    extract_first_cie,
    extract_first_lifetime,
    extract_device_label,
    build_device_notes,
    merge_inferred_devices,
    sanitize_devices,
    sanitize_device,
    device_signal_score,
    device_signature,
    refresh_best_eqe,
)
from paperinsight.core.metadata_extractor import (
    TITLE_STOP_PATTERNS,
    extract_title,
    extract_title_candidates_from_lines,
    build_title_blocks,
    normalize_title_candidate,
    is_bad_title_candidate,
    score_title_candidate,
    extract_authors,
    extract_impact_factor,
    extract_year,
    detect_research_type,
    detect_emitter_type,
    extract_optimization_level,
    extract_optimization_strategy,
    extract_metric_source,
)


class DataExtractor:
    """
    v3.1 数据提取器

    支持两种提取模式：
    - LLM 模式：语义化提取，输出嵌套 JSON
    - Regex 模式：正则表达式提取（兜底）

    正则提取逻辑委托到子模块纯函数（journal_utils / device_extractor / metadata_extractor）。
    """

    # 从 config/journal_aliases.yaml 加载（支持用户自定义扩展）
    JOURNAL_DOMAIN_HINTS: dict[str, str] = JOURNAL_DOMAIN_HINTS
    JOURNAL_TITLE_ALIASES: dict[str, str] = JOURNAL_TITLE_ALIASES

    # 正则模式常量（保持向后兼容，实际使用子模块中的同名常量）
    JOURNAL_LINE_PATTERNS = JOURNAL_LINE_PATTERNS
    TITLE_STOP_PATTERNS = TITLE_STOP_PATTERNS

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        use_llm: Optional[bool] = None,
    ):
        """
        初始化数据提取器

        Args:
            config: 配置字典，包含 LLM 配置等
        """
        if use_llm is not None:
            config = dict(config or {})
            config.setdefault("llm", {})
            config["llm"]["enabled"] = bool(use_llm)

        self.config = config or {}
        if "use_llm" in self.config:
            self.config.setdefault("llm", {})
            self.config["llm"]["enabled"] = bool(self.config["use_llm"])
        self.llm_config = self.config.get("llm", {})
        self.logger = setup_logger("paperinsight.extractor")

        # 初始化 LLM 客户端
        self.llm: Optional[BaseLLM] = None
        self.lite_backfill_llm: Optional[BaseLLM] = None
        self._init_llm_client()

    # ── LLM 客户端初始化 ─────────────────────────────────────────

    def _init_llm_client(self) -> None:
        """初始化 LLM 客户端"""
        if not self.llm_config.get("enabled", True):
            self.logger.info("[LLM] disabled; using regex fallback")
            return

        try:
            self.llm = create_llm_client(self.llm_config)
            provider = self.llm_config.get("provider", "unknown")
            self.lite_backfill_llm = self._init_lite_backfill_client()

            if self.llm:
                try:
                    available = self.llm.is_available()
                except Exception as e:
                    self.logger.warning(f"[LLM] connectivity check raised an error; will try extraction directly: {e}")
                    available = True

                if available:
                    self.logger.info(f"[LLM] client ready: {provider}")
                else:
                    self.logger.warning(f"[LLM] connectivity check failed for {provider}; extraction will still be attempted")
            else:
                self.logger.warning(f"[LLM] could not create client: {provider}")

        except Exception as e:
            self.logger.warning(f"[LLM] client initialization failed: {e}")
            self.llm = None
            self.lite_backfill_llm = None

    def _init_lite_backfill_client(self) -> Optional[BaseLLM]:
        provider = str(self.llm_config.get("provider", "")).lower()
        if provider != "longcat":
            return None

        longcat_config = self.llm_config.get("longcat", {})
        if not longcat_config.get("enable_lite_backfill", True):
            return None

        api_key = str(self.llm_config.get("api_key", "")).strip()
        if not api_key:
            return None

        lite_config = dict(self.llm_config)
        lite_longcat_config = dict(longcat_config)
        lite_longcat_config["model"] = lite_longcat_config.get("backfill_model", "LongCat-Flash-Lite")
        lite_config["longcat"] = lite_longcat_config

        try:
            client = create_llm_client(lite_config)
            if client:
                self.logger.info(f"[LLM] lite backfill model ready: {lite_longcat_config['model']}")
            return client
        except Exception as e:
            self.logger.warning(f"[LLM] lite backfill model init failed: {e}")
            return None

    # ── 主提取入口 ───────────────────────────────────────────────

    def extract(
        self,
        markdown_text: str,
        cleaned_text: str,
        parse_result: Optional[ParseResult] = None,
    ) -> ExtractionResult:
        """
        提取论文结构化数据

        Args:
            markdown_text: 原始 Markdown 文本
            cleaned_text: 清洗后的文本（用于提取）
            parse_result: 解析结果（包含元数据）

        Returns:
            提取结果
        """
        start_time = time.time()

        # 优先使用 LLM 提取
        if self.llm:
            self.logger.info(f"[LLM] extracting structured data with {self.llm_config.get('provider', 'unknown')}")
            result = self._extract_with_llm(cleaned_text, parse_result)
            if result.success and result.data:
                result.processing_time = time.time() - start_time
                result.extraction_method = "llm"
                result.llm_model = self.llm_config.get("provider", "unknown")
                self.logger.info(f"[LLM] extraction succeeded: {result.llm_model}")
                return result
            self.logger.warning(f"[LLM] extraction failed; falling back to regex: {result.error_message}")

        # 回退到正则提取
        self.logger.info("[Regex] using regex fallback extraction")
        result = self._extract_with_regex(markdown_text, parse_result)
        result.processing_time = time.time() - start_time
        result.extraction_method = "regex"

        return result

    # ── LLM 提取 ─────────────────────────────────────────────────

    def _extract_with_llm(
        self,
        text: str,
        parse_result: Optional[ParseResult],
    ) -> ExtractionResult:
        """使用 LLM 提取"""
        try:
            prepared_text = self._prepare_llm_input(text)

            # 构建 Prompt
            prompt = format_extraction_prompt_v3(prepared_text)

            # 调用 LLM
            self.logger.info(f"[LLM] sending request with text length {len(prepared_text)} chars")
            llm_kwargs: Dict[str, Any] = {}
            if self._supports_strict_schema():
                llm_kwargs.update(
                    {
                        "json_schema": PAPER_DATA_JSON_SCHEMA,
                        "schema_name": "paperinsight_paper_data",
                    }
                )
            response = self.llm.generate_json(prompt, temperature=0.2, **llm_kwargs)

            # 解析并校验
            paper_data = self._parse_and_validate(response)

            if paper_data:
                paper_data = self._backfill_paper_info_from_text(paper_data, prepared_text, parse_result)
                paper_data = self._merge_inferred_devices(paper_data, prepared_text)
                paper_data = self._sanitize_devices(paper_data)
                paper_data = self._ensure_bilingual_text_fields(paper_data)
                return ExtractionResult(
                    success=True,
                    data=paper_data,
                    source_file=parse_result.source_file if parse_result else None,
                )
            else:
                return ExtractionResult(
                    success=False,
                    error_message="LLM response validation failed",
                )

        except Exception as e:
            return ExtractionResult(
                success=False,
                error_message=f"LLM extraction failed: {str(e)}",
            )

    def _ensure_bilingual_text_fields(self, paper_data: PaperData) -> PaperData:
        """对标题之后的自然语言字段补齐中英对照。"""
        output_config = self.config.get("output", {})
        if not output_config.get("bilingual_text", True):
            return paper_data

        if not self.llm:
            return paper_data

        try:
            self.logger.info("[LLM] running bilingual post-processing")
            prompt = format_bilingual_postprocess_prompt(paper_data.model_dump())
            llm_kwargs: Dict[str, Any] = {}
            if self._supports_strict_schema():
                llm_kwargs.update(
                    {
                        "json_schema": PAPER_DATA_JSON_SCHEMA,
                        "schema_name": "paperinsight_bilingual_paper_data",
                    }
                )
            response = self.llm.generate_json(prompt, temperature=0.1, **llm_kwargs)
            bilingual_data = self._parse_and_validate(response)

            if bilingual_data:
                self.logger.info("[LLM] bilingual post-processing complete")
                return bilingual_data

            self.logger.warning("[LLM] bilingual post-processing validation failed; keeping initial extraction")
            return paper_data

        except Exception as e:
            self.logger.warning(f"[LLM] bilingual post-processing failed; keeping initial extraction: {e}")
            return paper_data

    def _supports_strict_schema(self) -> bool:
        provider = self.llm_config.get("provider", "").lower()
        return provider == "openai"

    def _prepare_llm_input(self, text: str) -> str:
        """准备 LLM 输入，优先相信 cleaner 的预算控制，仅在极端情况下兜底截断。"""
        if not text:
            return ""

        max_chars = (
            self.config.get("cleaner", {}).get("max_input_chars")
            or self.llm_config.get("max_input_chars")
            or 0
        )
        if not max_chars or len(text) <= max_chars:
            return text

        self.logger.warning(
            f"[LLM] cleaned text still exceeds budget; truncating at boundary: {len(text)} -> {max_chars}"
        )
        truncated = text[:max_chars]
        boundary = max(truncated.rfind("\n\n"), truncated.rfind("\n### "), truncated.rfind("\n## "))
        if boundary > max_chars * 0.6:
            return truncated[:boundary].strip()
        return truncated.strip()

    def _parse_and_validate(self, response: Dict[str, Any]) -> Optional[PaperData]:
        """解析并校验 LLM 响应"""
        try:
            # 构建嵌套结构
            paper_info_data = response.get("paper_info", {})
            devices_data = response.get("devices", [])
            data_source_data = response.get("data_source", {})
            optimization_data = response.get("optimization", {})
            raw_journal_title = paper_info_data.get("raw_journal_title")
            matched_journal_title = paper_info_data.get("matched_journal_title")

            # 构建 PaperInfo
            paper_info = PaperInfo(
                title=paper_info_data.get("title"),
                authors=paper_info_data.get("authors"),
                journal_name=paper_info_data.get("journal_name") or matched_journal_title or raw_journal_title,
                raw_journal_title=raw_journal_title,
                raw_issn=paper_info_data.get("raw_issn"),
                raw_eissn=paper_info_data.get("raw_eissn"),
                matched_journal_title=matched_journal_title,
                matched_issn=paper_info_data.get("matched_issn"),
                match_method=paper_info_data.get("match_method"),
                journal_profile_url=paper_info_data.get("journal_profile_url"),
                impact_factor=paper_info_data.get("impact_factor"),
                impact_factor_year=paper_info_data.get("impact_factor_year"),
                impact_factor_source=paper_info_data.get("impact_factor_source"),
                impact_factor_status=paper_info_data.get("impact_factor_status"),
                year=paper_info_data.get("year"),
                optimization_strategy=paper_info_data.get("optimization_strategy"),
                best_eqe=paper_info_data.get("best_eqe"),
                research_type=paper_info_data.get("research_type"),
                emitter_type=paper_info_data.get("emitter_type"),
            )

            # 构建 Devices 列表
            devices = []
            for device_data in devices_data:
                if isinstance(device_data, dict):
                    device = DeviceData(
                        device_label=device_data.get("device_label"),
                        structure=device_data.get("structure"),
                        eqe=device_data.get("eqe"),
                        cie=device_data.get("cie"),
                        lifetime=device_data.get("lifetime"),
                        luminance=device_data.get("luminance"),
                        current_efficiency=device_data.get("current_efficiency"),
                        power_efficiency=device_data.get("power_efficiency"),
                        notes=device_data.get("notes"),
                    )
                    devices.append(device)

            # 构建 DataSourceReference
            data_source = DataSourceReference(
                eqe_source=data_source_data.get("eqe_source"),
                cie_source=data_source_data.get("cie_source"),
                lifetime_source=data_source_data.get("lifetime_source"),
                structure_source=data_source_data.get("structure_source"),
            )

            # 构建 OptimizationInfo
            optimization = None
            if optimization_data:
                optimization = OptimizationInfo(
                    level=optimization_data.get("level"),
                    strategy=optimization_data.get("strategy"),
                    key_findings=optimization_data.get("key_findings"),
                )

            # 构建完整的 PaperData
            paper_data = PaperData(
                paper_info=paper_info,
                devices=devices,
                data_source=data_source,
                optimization=optimization,
            )
            paper_data = sanitize_devices(paper_data)

            return paper_data

        except ValidationError as e:
            self.logger.warning(f"[ValidationFailed] {e}")
            return None
        except Exception as e:
            self.logger.warning(f"[ParseFailed] {e}")
            return None

    # ── 正则提取（兜底） ─────────────────────────────────────────

    def _extract_with_regex(
        self,
        text: str,
        parse_result: Optional[ParseResult],
    ) -> ExtractionResult:
        """使用正则表达式提取（兜底方案）"""
        try:
            # 提取基本信息
            raw_journal_title, raw_issn, raw_eissn = self._extract_raw_journal_metadata(text, parse_result)
            paper_info = PaperInfo(
                title=self._extract_title(text, parse_result),
                authors=self._extract_authors(text, parse_result),
                journal_name=raw_journal_title,
                raw_journal_title=raw_journal_title,
                raw_issn=raw_issn,
                raw_eissn=raw_eissn,
                impact_factor=self._extract_impact_factor(text),
                year=self._extract_year(text),
                research_type=self._detect_research_type(text),
                emitter_type=self._detect_emitter_type(text),
            )

            # 提取器件数据
            devices = self._extract_devices(text)

            # 提取数据溯源
            data_source = DataSourceReference(
                eqe_source=self._extract_metric_source(text, "eqe"),
                cie_source=self._extract_metric_source(text, "cie"),
                lifetime_source=self._extract_metric_source(text, "lifetime"),
                structure_source=self._extract_metric_source(text, "structure"),
            )

            # 提取优化信息
            optimization = OptimizationInfo(
                level=self._extract_optimization_level(text),
                strategy=self._extract_optimization_strategy(text),
            )

            # 构建 PaperData
            paper_data = PaperData(
                paper_info=paper_info,
                devices=devices,
                data_source=data_source,
                optimization=optimization,
            )
            paper_data = self._backfill_paper_info_from_text(paper_data, text, parse_result)
            paper_data = self._merge_inferred_devices(paper_data, text)
            paper_data = self._sanitize_devices(paper_data)

            return ExtractionResult(
                success=True,
                data=paper_data,
                source_file=parse_result.source_file if parse_result else None,
            )

        except Exception as e:
            return ExtractionResult(
                success=False,
                error_message=f"Regex extraction failed: {str(e)}",
            )

    # ── 元数据回填 ───────────────────────────────────────────────

    def _backfill_paper_info_from_text(
        self,
        paper_data: PaperData,
        text: str,
        parse_result: Optional[ParseResult],
    ) -> PaperData:
        paper_info = paper_data.paper_info
        raw_journal_title, raw_issn, raw_eissn = self._extract_raw_journal_metadata(text, parse_result)
        extracted_title = self._extract_title(text, parse_result)

        normalized_existing_title = normalize_title_candidate(paper_info.title)
        if extracted_title and (
            not normalized_existing_title or is_bad_title_candidate(normalized_existing_title)
        ):
            paper_info.title = extracted_title
        elif normalized_existing_title and normalized_existing_title != paper_info.title:
            paper_info.title = normalized_existing_title

        if raw_journal_title and not paper_info.raw_journal_title:
            paper_info.raw_journal_title = raw_journal_title
        if raw_journal_title and not paper_info.journal_name:
            paper_info.journal_name = raw_journal_title
        if raw_issn and not paper_info.raw_issn:
            paper_info.raw_issn = raw_issn
        if raw_eissn and not paper_info.raw_eissn:
            paper_info.raw_eissn = raw_eissn
        if paper_info.impact_factor in (None, 0):
            extracted_if = self._extract_impact_factor(text)
            if extracted_if:
                paper_info.impact_factor = extracted_if
        return paper_data

    # ── Lite backfill（LLM 补填） ────────────────────────────────

    def lite_backfill_paper_info(
        self,
        paper_data: PaperData,
        text: str,
        parse_result: Optional[ParseResult],
    ) -> PaperData:
        if not self.lite_backfill_llm:
            return paper_data

        if not self._needs_lite_backfill(paper_data):
            return paper_data

        try:
            snippet = self._prepare_lite_backfill_input(text)
            prompt = format_lite_paper_info_backfill_prompt(
                paper_text=snippet,
                source_file=parse_result.source_file if parse_result else None,
                metadata=parse_result.metadata if parse_result else {},
            )
            response = self.lite_backfill_llm.generate_json(prompt, temperature=0.1)
            self.logger.info(
                "[LLM] lite backfill response: "
                f"title={bool(response.get('title'))}, "
                f"authors={bool(response.get('authors'))}, "
                f"journal_name={bool(response.get('journal_name'))}, "
                f"raw_journal_title={bool(response.get('raw_journal_title'))}, "
                f"year={response.get('year')!r}"
            )
            self._merge_lite_backfill_result(paper_data, response)
            return self._backfill_paper_info_from_text(paper_data, text, parse_result)
        except Exception as e:
            self.logger.warning(f"[LLM] lite backfill failed: {e}")
            return paper_data

    def _needs_lite_backfill(self, paper_data: PaperData) -> bool:
        paper_info = paper_data.paper_info
        return not all(
            [
                paper_info.title,
                paper_info.journal_name or paper_info.raw_journal_title,
                paper_info.year,
            ]
        )

    def _prepare_lite_backfill_input(self, text: str) -> str:
        if not text:
            return ""
        max_chars = 6000
        snippet = text[:max_chars].strip()
        boundary = max(snippet.rfind("\n\n"), snippet.rfind(". "), snippet.rfind("\n"))
        if boundary > max_chars * 0.6:
            return snippet[:boundary].strip()
        return snippet

    def _merge_lite_backfill_result(self, paper_data: PaperData, response: Dict[str, Any]) -> None:
        paper_info = paper_data.paper_info
        title = coerce_metadata_value(response.get("title"))
        authors = coerce_metadata_value(response.get("authors"))
        journal_name = normalize_journal_title_candidate(
            coerce_metadata_value(response.get("journal_name"))
        )
        raw_journal_title = normalize_journal_title_candidate(
            coerce_metadata_value(response.get("raw_journal_title"))
        )
        year_value = response.get("year")

        if title and not paper_info.title:
            paper_info.title = title
        if authors and not paper_info.authors:
            paper_info.authors = authors
        if raw_journal_title and not paper_info.raw_journal_title:
            paper_info.raw_journal_title = raw_journal_title
        if journal_name and not paper_info.journal_name:
            paper_info.journal_name = journal_name
        if year_value not in (None, "") and not paper_info.year:
            try:
                year = int(year_value)
            except (TypeError, ValueError):
                year = None
            if year and 1900 <= year <= 2100:
                paper_info.year = year

        self.logger.info(
            "[LLM] lite backfill merged: "
            f"title={bool(paper_info.title)}, "
            f"authors={bool(paper_info.authors)}, "
            f"journal={paper_info.journal_name or paper_info.raw_journal_title!r}, "
            f"year={paper_info.year!r}"
        )

    # ============== 委托方法（正则提取） ==============
    # 以下方法保持原始签名，实现委托到子模块纯函数。
    # 这确保了测试代码和外部调用者无需修改。

    # ── 标题 / 作者 ──────────────────────────────────────────────

    def _extract_title(self, text: str, parse_result: Optional[ParseResult]) -> Optional[str]:
        return extract_title(text, parse_result)

    def _extract_authors(self, text: str, parse_result: Optional[ParseResult]) -> Optional[str]:
        return extract_authors(text, parse_result)

    # ── 期刊元数据 ────────────────────────────────────────────────

    def _extract_raw_journal_metadata(
        self,
        text: str,
        parse_result: Optional[ParseResult],
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        return extract_raw_journal_metadata(text, parse_result)

    def _extract_journal_name(self, text: str) -> Optional[str]:
        return extract_journal_name(text)

    def _extract_journal_name_from_subject(self, metadata: Dict[str, Any]) -> Optional[str]:
        return extract_journal_name_from_subject(metadata)

    def _extract_journal_name_from_filename(
        self,
        parse_result: Optional[ParseResult],
    ) -> Optional[str]:
        return extract_journal_name_from_filename(parse_result)

    def _normalize_journal_title_candidate(self, value: Optional[str]) -> Optional[str]:
        return normalize_journal_title_candidate(value)

    def _extract_issn_from_text(self, text: str) -> tuple[Optional[str], Optional[str]]:
        return extract_issn_from_text(text)

    def _extract_pdf_metadata_from_source(self, parse_result: Optional[ParseResult]) -> Dict[str, Any]:
        return extract_pdf_metadata_from_source(parse_result)

    @staticmethod
    def _coerce_metadata_value(value: Any) -> Optional[str]:
        return coerce_metadata_value(value)

    @staticmethod
    def _first_non_empty(*values: Optional[str]) -> Optional[str]:
        return first_non_empty(*values)

    # ── 论文属性 ─────────────────────────────────────────────────

    def _extract_impact_factor(self, text: str) -> Optional[float]:
        return extract_impact_factor(text)

    def _extract_year(self, text: str) -> Optional[int]:
        return extract_year(text)

    def _detect_research_type(self, text: str) -> Optional[str]:
        return detect_research_type(text)

    def _detect_emitter_type(self, text: str) -> Optional[str]:
        return detect_emitter_type(text)

    def _extract_optimization_level(self, text: str) -> Optional[str]:
        return extract_optimization_level(text)

    def _extract_optimization_strategy(self, text: str) -> Optional[str]:
        return extract_optimization_strategy(text)

    def _extract_metric_source(self, text: str, metric: str) -> Optional[str]:
        return extract_metric_source(text, metric)

    # ── 器件提取 ─────────────────────────────────────────────────

    def _extract_devices(self, text: str) -> List[DeviceData]:
        return extract_devices(text)

    def _extract_candidate_devices(self, text: str) -> List[DeviceData]:
        return extract_candidate_devices(text)

    def _extract_all_structures(self, text: str) -> List[str]:
        return extract_all_structures(text)

    def _extract_all_eqe(self, text: str) -> List[str]:
        return extract_all_eqe(text)

    def _extract_all_cie(self, text: str) -> List[str]:
        return extract_all_cie(text)

    def _extract_all_lifetime(self, text: str) -> List[str]:
        return extract_all_lifetime(text)

    def _merge_inferred_devices(self, paper_data: PaperData, text: str) -> PaperData:
        return merge_inferred_devices(paper_data, text)

    def _sanitize_devices(self, paper_data: PaperData) -> PaperData:
        return sanitize_devices(paper_data)

    def _sanitize_device(self, device: DeviceData) -> Optional[DeviceData]:
        return sanitize_device(device)

    def _device_signal_score(self, device: DeviceData) -> int:
        return device_signal_score(device)

    def _device_signature(self, device: DeviceData) -> tuple:
        return device_signature(device)

    def _refresh_best_eqe(self, paper_data: PaperData) -> None:
        refresh_best_eqe(paper_data)

    # ── 标题辅助 ─────────────────────────────────────────────────

    def _extract_title_candidates_from_lines(
        self,
        parse_result: Optional[ParseResult],
        text: str,
    ) -> List[str]:
        return extract_title_candidates_from_lines(parse_result, text)

    def _build_title_blocks(self, lines: List[str]) -> List[str]:
        return build_title_blocks(lines)

    def _normalize_title_candidate(self, value: Optional[str]) -> Optional[str]:
        return normalize_title_candidate(value)

    def _is_bad_title_candidate(self, candidate: str) -> bool:
        return is_bad_title_candidate(candidate)

    def _score_title_candidate(self, candidate: str, *, index: int, heading_hint: bool) -> int:
        return score_title_candidate(candidate, index=index, heading_hint=heading_hint)
