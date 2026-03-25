"""
IF 获取策略链模块

将 ImpactFactor 补全逻辑拆分为职责单一的策略对象，
每个 IF 来源封装为独立的 ``IFSourceStrategy`` 实现，
通过 ``IFStrategyChain`` 按优先级编排。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple

from paperinsight.web.impact_factor_fetcher import ImpactFactorLookupResult
from paperinsight.web.journal_resolver import MJLJournalResolution

logger = logging.getLogger("paperinsight.pipeline")


# ── 上下文数据 ────────────────────────────────────────────────────────


@dataclass
class IFRequestContext:
    """传递给每个策略的上下文信息。"""

    paper_info: Any  # PaperInfo model
    journal_name: str
    paper_title: str
    journal_resolution: Optional[MJLJournalResolution] = None
    journal_candidate: Any = None  # MJL journal candidate
    current_if: Optional[float] = None
    should_correct_existing: bool = True
    validation_tolerance: float = 0.6


# ── 策略接口 ──────────────────────────────────────────────────────────


class IFSourceStrategy(ABC):
    """IF 来源策略基类。每个实现封装一个 IF 来源的查找逻辑。"""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """策略对应的来源标识。"""
        ...

    @abstractmethod
    def lookup(self, ctx: IFRequestContext) -> Optional[ImpactFactorLookupResult]:
        """执行 IF 查找。返回 None 表示该策略不适用或未找到。"""
        ...


# ── 官方 IF 策略（MJL Profile API）─────────────────────────────────────


class OfficialIFStrategy(IFSourceStrategy):
    """通过 MJL Profile API 获取官方 IF。"""

    def __init__(self, if_fetcher: Any):
        self.if_fetcher = if_fetcher

    @property
    def source_name(self) -> str:
        return "MJL_PROFILE_API"

    def lookup(self, ctx: IFRequestContext) -> Optional[ImpactFactorLookupResult]:
        if self.if_fetcher is None or ctx.journal_candidate is None:
            return None
        try:
            return self.if_fetcher.lookup(ctx.journal_candidate)
        except Exception as e:
            logger.error(f"[IFLookup] {self.source_name} lookup failed: {e}", exc_info=True)
            return ImpactFactorLookupResult(
                status="ERROR",
                source_name=self.source_name,
                source_url=ctx.paper_info.journal_profile_url or "",
                error_message=str(e),
            )


# ── LetPub IF 策略 ───────────────────────────────────────────────────


class LetPubIFStrategy(IFSourceStrategy):
    """通过 LetPub 获取 IF。"""

    def __init__(self, fetcher: Any):
        self.fetcher = fetcher

    @property
    def source_name(self) -> str:
        return "LETPUB"

    def lookup(self, ctx: IFRequestContext) -> Optional[ImpactFactorLookupResult]:
        if self.fetcher is None:
            return None
        letpub_journal_name = (
            ctx.journal_candidate.display_title
            if ctx.journal_candidate and ctx.journal_candidate.display_title
            else None
        ) or ctx.journal_name
        if not any((letpub_journal_name, ctx.paper_info.raw_issn, ctx.paper_info.raw_eissn)):
            return None
        return self.fetcher.lookup(
            journal_title=letpub_journal_name,
            issn=ctx.paper_info.matched_issn or ctx.paper_info.raw_issn,
            eissn=ctx.paper_info.raw_eissn,
        )


# ── Curated Fallback 策略 ────────────────────────────────────────────


class CuratedFallbackStrategy(IFSourceStrategy):
    """MJL curated fallback（按标题查找）。"""

    def __init__(self, if_fetcher: Any):
        self.if_fetcher = if_fetcher

    @property
    def source_name(self) -> str:
        return "CURATED_FALLBACK"

    def lookup(self, ctx: IFRequestContext) -> Optional[ImpactFactorLookupResult]:
        if self.if_fetcher is None:
            return None
        journal = ctx.paper_info.journal_name or ctx.paper_info.raw_journal_title
        if not journal:
            return None
        try:
            return self.if_fetcher.lookup_by_title(journal)
        except Exception as e:
            logger.error(f"[IFLookup] {self.source_name} lookup failed: {e}", exc_info=True)
            return None


# ── Search Crawler 策略 ──────────────────────────────────────────────


class SearchCrawlerStrategy(IFSourceStrategy):
    """通过搜索引擎爬取 IF。"""

    def __init__(self, fetcher: Any):
        self.fetcher = fetcher

    @property
    def source_name(self) -> str:
        return "SEARCH_CRAWLER"

    def lookup(self, ctx: IFRequestContext) -> Optional[ImpactFactorLookupResult]:
        if self.fetcher is None:
            return None
        journal = ctx.paper_info.journal_name or ctx.paper_info.raw_journal_title
        if not journal:
            return None
        try:
            return self.fetcher.lookup(
                journal_title=journal,
                issn=ctx.paper_info.matched_issn or ctx.paper_info.raw_issn,
                eissn=ctx.paper_info.raw_eissn,
            )
        except Exception as e:
            logger.error(f"[IFLookup] {self.source_name} lookup failed: {e}", exc_info=True)
            return None


# ── WOS Journals API 策略 ───────────────────────────────────────────


class WOSIFStrategy(IFSourceStrategy):
    """通过 Web of Science Journals API 获取 IF。"""

    def __init__(self, fetcher: Any):
        self.fetcher = fetcher

    @property
    def source_name(self) -> str:
        return "WOS_JOURNALS_API"

    def lookup(self, ctx: IFRequestContext) -> Optional[ImpactFactorLookupResult]:
        if self.fetcher is None:
            return None
        journal = ctx.paper_info.journal_name or ctx.paper_info.raw_journal_title
        if not journal:
            return None
        try:
            return self.fetcher.lookup(
                journal_title=journal,
                issn=ctx.paper_info.matched_issn or ctx.paper_info.raw_issn,
                eissn=ctx.paper_info.raw_eissn,
            )
        except Exception as e:
            logger.error(f"[IFLookup] {self.source_name} lookup failed: {e}", exc_info=True)
            return None


# ── AI Model IF 策略 ─────────────────────────────────────────────────


class AIModelIFStrategy(IFSourceStrategy):
    """通过 AI 模型推断 IF。"""

    def __init__(self, fetcher: Any):
        self.fetcher = fetcher

    @property
    def source_name(self) -> str:
        return "AI_MODEL"

    def lookup(self, ctx: IFRequestContext) -> Optional[ImpactFactorLookupResult]:
        if self.fetcher is None:
            return None
        logger.info(
            f"[IFLookup] query via AI method: journal={ctx.journal_name}, "
            f"title={ctx.paper_title[:30] if ctx.paper_title else 'N/A'}..."
        )
        try:
            fetch_result = self.fetcher.lookup(
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


# ── IF 来源工厂 ───────────────────────────────────────────────────────


class IFSourceFactory:
    """根据配置创建 IF 策略链。"""

    @staticmethod
    def build_chain(
        *,
        if_fetcher: Any = None,
        letpub_if_fetcher: Any = None,
        search_crawler_fetcher: Any = None,
        wos_if_fetcher: Any = None,
        ai_model_if_fetcher: Any = None,
        web_config: Optional[Dict[str, Any]] = None,
    ) -> List[IFSourceStrategy]:
        """按优先级构建 IF 策略列表。

        优先级: Official > Curated Fallback > Search Crawler > LetPub > WOS > AI Model

        注意: 实际的 IF 选择逻辑（交叉验证、合并等）在
        ``AnalysisPipeline._supplement_impact_factor`` 中编排，
        策略链仅负责封装各来源的 lookup 调用。
        """
        chain: List[IFSourceStrategy] = []

        # 官方来源
        chain.append(OfficialIFStrategy(if_fetcher))
        chain.append(CuratedFallbackStrategy(if_fetcher))

        # 次级来源
        chain.append(SearchCrawlerStrategy(search_crawler_fetcher))
        chain.append(WOSIFStrategy(wos_if_fetcher))
        chain.append(LetPubIFStrategy(letpub_if_fetcher))

        # AI 模型来源（最低优先级）
        chain.append(AIModelIFStrategy(ai_model_if_fetcher))

        # 过滤掉 fetcher 为 None 的策略
        active_chain = []
        for strategy in chain:
            # OfficialIFStrategy 和 CuratedFallbackStrategy 共享 if_fetcher，
            # 需要额外检查是否有有效 fetcher
            if isinstance(strategy, (OfficialIFStrategy, CuratedFallbackStrategy)):
                if strategy.if_fetcher is not None:
                    active_chain.append(strategy)
            elif isinstance(strategy, AIModelIFStrategy):
                if strategy.fetcher is not None:
                    active_chain.append(strategy)
            elif isinstance(strategy, LetPubIFStrategy):
                if strategy.fetcher is not None:
                    active_chain.append(strategy)
            else:
                if strategy.fetcher is not None:
                    active_chain.append(strategy)

        return active_chain

    @staticmethod
    def has_any_fetcher(
        *,
        if_fetcher: Any = None,
        letpub_if_fetcher: Any = None,
        search_crawler_fetcher: Any = None,
        wos_if_fetcher: Any = None,
        ai_model_if_fetcher: Any = None,
    ) -> bool:
        """检查是否有任何 IF 获取器可用。"""
        return any(
            [if_fetcher, letpub_if_fetcher, search_crawler_fetcher, wos_if_fetcher, ai_model_if_fetcher]
        )
