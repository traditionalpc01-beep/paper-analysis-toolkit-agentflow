"""Web Fetcher 工厂模块。

将 AnalysisPipeline 中分散的 6 个 fetcher 初始化逻辑
集中到工厂类，实现构造函数解耦与依赖注入。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class WebFetchers:
    """所有 web fetcher 实例的容器。"""

    journal_resolver: Any = None
    if_fetcher: Any = None
    letpub_if_fetcher: Any = None
    search_crawler_fetcher: Any = None
    wos_if_fetcher: Any = None
    ai_model_if_fetcher: Any = None


class WebFetcherFactory:
    """根据配置创建并组装所有 web fetcher。

    Usage::

        web_config = config.get("web_search", {})
        fetchers = WebFetcherFactory.build(web_config)
        pipeline = AnalysisPipeline(output_dir, config=config, fetchers=fetchers)
    """

    @staticmethod
    def build(web_config: Optional[Dict[str, Any]] = None) -> WebFetchers:
        """从配置字典创建所有 web fetcher。

        Args:
            web_config: ``config["web_search"]`` 子字典。
                如果为 None，所有 fetcher 均为 None。

        Returns:
            包含所有 fetcher 实例的 ``WebFetchers`` 容器。
        """
        web_config = web_config or {}
        timeout = int(web_config.get("timeout", 30))
        web_enabled = bool(web_config.get("enabled", True))

        journal_resolver = WebFetcherFactory._build_journal_resolver(web_config, timeout)
        if_fetcher = WebFetcherFactory._build_if_fetcher(web_config, timeout)
        letpub_if_fetcher = WebFetcherFactory._build_letpub_fetcher(web_config, timeout)
        search_crawler_fetcher = WebFetcherFactory._build_search_crawler(web_config, timeout)
        wos_if_fetcher = WebFetcherFactory._build_wos_fetcher(web_config, timeout)
        ai_model_if_fetcher = (
            WebFetcherFactory._build_ai_model_fetcher(web_config, timeout)
            if web_enabled
            else None
        )

        return WebFetchers(
            journal_resolver=journal_resolver,
            if_fetcher=if_fetcher,
            letpub_if_fetcher=letpub_if_fetcher,
            search_crawler_fetcher=search_crawler_fetcher,
            wos_if_fetcher=wos_if_fetcher,
            ai_model_if_fetcher=ai_model_if_fetcher,
        )

    @staticmethod
    def _build_journal_resolver(
        web_config: Dict[str, Any], timeout: int
    ) -> Any:
        from paperinsight.web.journal_resolver import MJLJournalResolver

        if not web_config.get("resolve_journal_metadata", True):
            return None
        return MJLJournalResolver(timeout=timeout)

    @staticmethod
    def _build_if_fetcher(
        web_config: Dict[str, Any], timeout: int
    ) -> Any:
        from paperinsight.web.impact_factor_fetcher import MJLImpactFactorFetcher

        if not web_config.get("fetch_official_impact_factor", True):
            return None
        return MJLImpactFactorFetcher(timeout=timeout)

    @staticmethod
    def _build_letpub_fetcher(
        web_config: Dict[str, Any], timeout: int
    ) -> Any:
        from paperinsight.web.letpub_fetcher import LetPubImpactFactorFetcher

        letpub_config = web_config.get("letpub", {})
        if not letpub_config.get("enabled", True):
            return None
        return LetPubImpactFactorFetcher(
            timeout=int(letpub_config.get("timeout", timeout))
        )

    @staticmethod
    def _build_search_crawler(
        web_config: Dict[str, Any], timeout: int
    ) -> Any:
        from paperinsight.web.search_crawler_fetcher import SearchCrawlerFetcher

        crawler_config = web_config.get("search_crawler", {})
        if not crawler_config.get("enabled", True):
            return None
        return SearchCrawlerFetcher(
            timeout=timeout,
            market=str(crawler_config.get("market", "en-US")),
        )

    @staticmethod
    def _build_wos_fetcher(
        web_config: Dict[str, Any], timeout: int
    ) -> Any:
        from paperinsight.web.wos_journal_fetcher import WOSJournalFetcher

        wos_config = web_config.get("web_of_science", {})
        wos_api_key = str(wos_config.get("api_key", "")).strip()
        if not (wos_config.get("enabled") and wos_api_key):
            return None
        return WOSJournalFetcher(
            api_key=wos_api_key,
            timeout=timeout,
            base_url=wos_config.get("journals_api_url"),
        )

    @staticmethod
    def _build_ai_model_fetcher(
        web_config: Dict[str, Any], timeout: int
    ) -> Any:
        ai_model_config = web_config.get("ai_model_if", {})
        if not ai_model_config.get("enabled", False):
            return None
        try:
            from paperinsight.web.optimized_if_fetcher import OptimizedImpactFactorFetcher

            fetcher = OptimizedImpactFactorFetcher(
                timeout=int(ai_model_config.get("timeout", 30)),
                max_workers=int(ai_model_config.get("max_workers", 3)),
                max_retries=int(ai_model_config.get("max_retries", 3)),
                cache_expiry_days=int(ai_model_config.get("cache_expiry_days", 30)),
                qianwen_api_key=ai_model_config.get("qianwen_api_key"),
                kimi_api_key=ai_model_config.get("kimi_api_key"),
                enable_cache=bool(ai_model_config.get("enable_cache", True)),
            )
            logger.info("[AI-IF] Initialized OptimizedImpactFactorFetcher with cache")
            return fetcher
        except Exception as e:
            logger.error(f"[AI-IF] initializer failed: {e}", exc_info=True)
            return None
