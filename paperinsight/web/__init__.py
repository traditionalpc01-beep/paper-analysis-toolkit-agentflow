"""Web 搜索模块"""

from paperinsight.web.impact_factor_fetcher import MJLImpactFactorFetcher
from paperinsight.web.journal_resolver import MJLJournalResolver
from paperinsight.web.optimized_if_fetcher import OptimizedImpactFactorFetcher
from paperinsight.web.if_cache import ImpactFactorCache

__all__ = [
    "MJLJournalResolver",
    "MJLImpactFactorFetcher",
    "OptimizedImpactFactorFetcher",
    "ImpactFactorCache",
]
