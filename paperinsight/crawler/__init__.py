"""
影响因子爬虫系统

基于异步架构的高性能影响因子数据获取系统，支持多数据源并发抓取、
智能反爬策略、数据清洗验证和定时更新。

主要组件:
- CrawlerEngine: 核心爬虫引擎
- CrawlerConfig: 配置管理
- ImpactFactorDatabase: 数据存储层
- ImpactFactorQueryAPI: 用户查询接口
- TaskScheduler: 定时任务调度器

使用示例:
    from paperinsight.crawler import ImpactFactorQueryAPI, CrawlerConfig
    
    # 创建 API 实例
    api = ImpactFactorQueryAPI()
    
    # 查询单个期刊
    result = await api.query("Nature")
    
    # 批量查询
    results = await api.query_batch(["Nature", "Science", "Cell"])
    
    # 搜索期刊
    journals = api.search_journals("nano")
    
    # 导出数据
    api.export_to_json("output.json")
"""

from paperinsight.crawler.engine import (
    CrawlerEngine,
    RequestEngine,
    BaseFetcher,
    BaseParser,
    CrawlerException,
    RateLimitException,
    BlockedException,
    ParseException,
)
from paperinsight.crawler.config import (
    CrawlerConfig,
    RequestConfig,
    ProxyConfig,
    AntiCrawlerConfig,
    DataSourceConfig,
    StorageConfig,
    SchedulerConfig,
    DataSourcePriority,
)
from paperinsight.crawler.storage.database import ImpactFactorDatabase
from paperinsight.crawler.storage.models import (
    JournalRecord,
    ImpactFactorRecord,
    JournalAlias,
    JournalCategory,
    CrawlTask,
    CrawlResult,
    BatchCrawlResult,
    DataSourceType,
    DataQuality,
)
from paperinsight.crawler.parsers import (
    LetPubFetcher,
    CrossrefFetcher,
    MJLFetcher,
    WoSFetcher,
    HTMLParser,
    JSONParser,
)
from paperinsight.crawler.validation import (
    DataValidator,
    DataCleaner,
    CrossValidator,
    IFRangeValidator,
    YearValidator,
    SourceReliabilityScorer,
    ValidationResult,
)
from paperinsight.crawler.scheduler import (
    TaskScheduler,
    TaskStatus,
    TaskType,
    TaskProgress,
    CheckpointManager,
)
from paperinsight.crawler.api import ImpactFactorQueryAPI

__all__ = [
    "CrawlerEngine",
    "RequestEngine",
    "BaseFetcher",
    "BaseParser",
    "CrawlerException",
    "RateLimitException",
    "BlockedException",
    "ParseException",
    "CrawlerConfig",
    "RequestConfig",
    "ProxyConfig",
    "AntiCrawlerConfig",
    "DataSourceConfig",
    "StorageConfig",
    "SchedulerConfig",
    "DataSourcePriority",
    "ImpactFactorDatabase",
    "JournalRecord",
    "ImpactFactorRecord",
    "JournalAlias",
    "JournalCategory",
    "CrawlTask",
    "CrawlResult",
    "BatchCrawlResult",
    "DataSourceType",
    "DataQuality",
    "LetPubFetcher",
    "CrossrefFetcher",
    "MJLFetcher",
    "WoSFetcher",
    "HTMLParser",
    "JSONParser",
    "DataValidator",
    "DataCleaner",
    "CrossValidator",
    "IFRangeValidator",
    "YearValidator",
    "SourceReliabilityScorer",
    "ValidationResult",
    "TaskScheduler",
    "TaskStatus",
    "TaskType",
    "TaskProgress",
    "CheckpointManager",
    "ImpactFactorQueryAPI",
]

__version__ = "1.0.0"
