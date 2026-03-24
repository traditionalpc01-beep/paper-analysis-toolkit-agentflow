"""
优化的影响因子获取器

包含并发查询、智能重试、持久化缓存等功能
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Iterable, Callable

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

import requests
from requests.exceptions import RequestException, Timeout

from paperinsight.web.impact_factor_fetcher import ImpactFactorLookupResult
from paperinsight.web.letpub_fetcher import LetPubImpactFactorFetcher
from paperinsight.web.journal_resolver import MJLJournalCandidate
from paperinsight.web.ai_model_if_fetcher import (
    CrossrefFetcher,
    QianwenAPIFetcher,
    KimiAPIFetcher,
    JournalIFCache,
)
from paperinsight.web.if_cache import ImpactFactorCache
from paperinsight.web.journal_if_database import JOURNAL_IF_DATABASE

logger = logging.getLogger(__name__)


class RetryableError(Exception):
    """可重试的错误"""
    pass


class NonRetryableError(Exception):
    """不可重试的错误"""
    pass


class OptimizedImpactFactorFetcher:
    """
    优化的影响因子获取器
    
    特性：
    1. 持久化缓存（SQLite）
    2. 并发查询支持
    3. 智能重试机制
    4. 详细的日志记录
    """
    
    def __init__(
        self,
        timeout: int = 30,
        max_workers: int = 3,
        max_retries: int = 3,
        cache_expiry_days: int = 30,
        qianwen_api_key: Optional[str] = None,
        kimi_api_key: Optional[str] = None,
        enable_cache: bool = True,
    ):
        self.timeout = timeout
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.enable_cache = enable_cache

        self.cache = ImpactFactorCache(expiry_days=cache_expiry_days) if enable_cache else None

        if self.cache and JOURNAL_IF_DATABASE:
            try:
                preload_dict = {
                    key: record.if_value
                    for key, record in JOURNAL_IF_DATABASE.items()
                }
                self.cache.preload_from_dict(preload_dict)
            except Exception as e:
                logger.warning(f"Failed to preload local database: {e}")

        self.letpub_fetcher = LetPubImpactFactorFetcher(timeout=timeout)
        self.crossref_fetcher = CrossrefFetcher(timeout=timeout)
        self.qianwen_fetcher = QianwenAPIFetcher(
            api_key=qianwen_api_key,
            timeout=timeout,
        )
        self.kimi_fetcher = KimiAPIFetcher(
            api_key=kimi_api_key,
            timeout=timeout,
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RequestException, Timeout)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _fetch_with_retry(
        self,
        fetch_func: Callable[[], ImpactFactorLookupResult],
        source_name: str,
    ) -> ImpactFactorLookupResult:
        """带重试的获取"""
        try:
            return fetch_func()
        except RequestException as e:
            logger.warning(f"{source_name} request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"{source_name} unexpected error: {e}")
            raise NonRetryableError(str(e))
    
    def lookup(
        self,
        paper_title: str,
        journal_name: Optional[str] = None,
    ) -> ImpactFactorLookupResult:
        """
        查询影响因子

        支持两种调用方式：
        1. lookup(paper_title="...", journal_name="...") - 标准的期刊IF查询
        2. lookup(candidate) - 当传入MJLJournalCandidate时，从中提取期刊名称

        优先级：
        1. 外部源缓存（如有）
        2. 外部源查询（LetPub > AI模型）
        3. 本地数据库（作为最终备选）

        Args:
            paper_title: 论文标题
            journal_name: 期刊名称（可选）

        Returns:
            ImpactFactorLookupResult: 查询结果
        """
        if isinstance(paper_title, MJLJournalCandidate):
            candidate = paper_title
            journal_name = candidate.display_title if candidate.display_title else None
            paper_title = ""

        if not journal_name and paper_title:
            journal_name = self._infer_journal_name(paper_title)

        if journal_name and self.cache:
            cached = self.cache.get(journal_name)
            if cached:
                logger.info(f"Cache hit for journal: {journal_name}")
                return ImpactFactorLookupResult(
                    status="OK",
                    source_name=f"CACHE_{cached.source_name}",
                    source_url=cached.source_url,
                    impact_factor=cached.impact_factor,
                    year=cached.year,
                )

        if not journal_name and paper_title:
            try:
                journal_name = self.crossref_fetcher.lookup_journal_by_title(paper_title)
                if journal_name:
                    logger.info(f"Found journal via Crossref: {journal_name}")
            except Exception as e:
                logger.warning(f"Crossref lookup failed: {e}")

        if journal_name:
            try:
                result = self._fetch_with_retry(
                    lambda: self.letpub_fetcher.lookup(journal_title=journal_name),
                    "LETPUB",
                )
                if result.status == "OK" and self.cache:
                    self.cache.set(
                        journal_name=journal_name,
                        impact_factor=result.impact_factor,
                        source_name=result.source_name,
                        source_url=result.source_url,
                        year=result.year,
                    )
                return result
            except NonRetryableError:
                pass
            except Exception as e:
                logger.warning(f"LetPub fetch failed: {e}")

        if self.qianwen_fetcher.api_key:
            try:
                result = self.qianwen_fetcher.lookup(paper_title, journal_name)
                if result.status == "OK" and self.cache and journal_name:
                    self.cache.set(
                        journal_name=journal_name,
                        impact_factor=result.impact_factor,
                        source_name=result.source_name,
                        source_url=result.source_url,
                        year=result.year,
                    )
                if result.status == "OK":
                    return result
            except Exception as e:
                logger.warning(f"Qianwen API failed: {e}")

        if self.kimi_fetcher.api_key:
            try:
                result = self.kimi_fetcher.lookup(paper_title, journal_name)
                if result.status == "OK" and self.cache and journal_name:
                    self.cache.set(
                        journal_name=journal_name,
                        impact_factor=result.impact_factor,
                        source_name=result.source_name,
                        source_url=result.source_url,
                        year=result.year,
                    )
                if result.status == "OK":
                    return result
            except Exception as e:
                logger.warning(f"Kimi API failed: {e}")

        if journal_name:
            local_result = self._get_from_local_database(journal_name)
            if local_result:
                logger.info(f"Falling back to local database for: {journal_name}")
                return local_result

        return ImpactFactorLookupResult(
            status="ERROR",
            source_name="ALL_SOURCES_FAILED",
            source_url="",
            error_message="所有查询源均失败",
        )

    def lookup_by_title(
        self,
        journal_title: str,
    ) -> ImpactFactorLookupResult:
        """
        根据期刊名称查询影响因子

        Args:
            journal_title: 期刊名称

        Returns:
            ImpactFactorLookupResult: 查询结果
        """
        return self.lookup(paper_title="", journal_name=journal_title)

    def _infer_journal_name(self, paper_title: str) -> Optional[str]:
        """从论文标题推断期刊名称"""
        title_lower = paper_title.lower()
        hints = {
            "advanced materials": "Advanced Materials",
            "adv. mater.": "Advanced Materials",
            "advanced functional materials": "Advanced Functional Materials",
            "adv. funct. mater.": "Advanced Functional Materials",
            "nature": "Nature",
            "nat. commun.": "Nature Communications",
            "science advances": "Science Advances",
            "nano letters": "Nano Letters",
            "nano lett.": "Nano Letters",
            "acs nano": "ACS Nano",
            "j. am. chem. soc.": "Journal of the American Chemical Society",
            "angewandte": "Angewandte Chemie",
            "small": "Small",
            "laser photonics reviews": "Laser & Photonics Reviews",
            "light: science": "Light: Science & Applications",
        }
        for hint, journal in hints.items():
            if hint in title_lower:
                return journal
        return None

    def _get_from_local_database(self, journal_name: str) -> Optional[ImpactFactorLookupResult]:
        """从本地数据库获取IF"""
        if not journal_name:
            return None

        from paperinsight.web.journal_if_database import get_journal_if_record
        record = get_journal_if_record(journal_name)
        if record:
            return ImpactFactorLookupResult(
                status="OK",
                source_name="LOCAL_DATABASE",
                source_url="",
                impact_factor=record.if_value,
                year=record.if_year,
            )
        return None
    
    def lookup_many(
        self,
        items: Iterable[tuple[str, Optional[str]]],
        delay: float = 1.0,
    ) -> List[ImpactFactorLookupResult]:
        """
        批量并发查询影响因子
        
        Args:
            items: (paper_title, journal_name) 的迭代器
            delay: 请求之间的延迟（秒）
            
        Returns:
            List[ImpactFactorLookupResult]: 查询结果列表
        """
        results = []
        
        # 先检查缓存
        items_list = list(items)
        if self.cache:
            journal_names = [journal for _, journal in items_list if journal]
            cached_results = self.cache.get_many(journal_names)
            
            # 分离缓存命中和未命中的
            cached_items = []
            uncached_items = []
            
            for paper_title, journal_name in items_list:
                if journal_name and cached_results.get(journal_name):
                    cached = cached_results[journal_name]
                    results.append(ImpactFactorLookupResult(
                        status="OK",
                        source_name=f"CACHE_{cached.source_name}",
                        source_url=cached.source_url,
                        impact_factor=cached.impact_factor,
                        year=cached.year,
                    ))
                    cached_items.append((paper_title, journal_name))
                else:
                    uncached_items.append((paper_title, journal_name))
            
            logger.info(f"Cache hits: {len(cached_items)}, misses: {len(uncached_items)}")
            
            # 只查询未命中的
            items_to_fetch = uncached_items
        else:
            items_to_fetch = items_list
        
        # 并发查询
        if items_to_fetch:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_item = {
                    executor.submit(self.lookup, paper_title, journal_name): (paper_title, journal_name)
                    for paper_title, journal_name in items_to_fetch
                }
                
                for future in as_completed(future_to_item):
                    try:
                        result = future.result()
                        results.append(result)
                        # 添加延迟避免被封禁
                        time.sleep(delay)
                    except Exception as e:
                        logger.error(f"Batch lookup failed: {e}")
                        paper_title, journal_name = future_to_item[future]
                        results.append(ImpactFactorLookupResult(
                            status="ERROR",
                            source_name="BATCH_ERROR",
                            source_url="",
                            error_message=str(e),
                        ))
        
        return results
    
    def clear_cache(self, expired_only: bool = True) -> int:
        """清除缓存"""
        if not self.cache:
            return 0
        
        if expired_only:
            return self.cache.clear_expired()
        else:
            return self.cache.clear_all()
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计信息"""
        if not self.cache:
            return {"enabled": False}
        
        stats = self.cache.get_stats()
        stats["enabled"] = True
        return stats
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        return None
