"""
爬虫系统配置模块

定义爬虫系统的所有配置项，包括请求参数、反爬策略、代理池配置等。
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path
from enum import Enum
import json


class DataSourcePriority(Enum):
    """数据源优先级"""
    LEPUB = 1
    MJL = 2
    WOS = 3
    CROSSREF = 4
    PUBMED = 5
    AI_MODEL = 6
    LOCAL = 7


@dataclass
class RequestConfig:
    """请求配置"""
    timeout: int = 30
    connect_timeout: int = 10
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    max_redirects: int = 5
    
    min_request_delay: float = 0.5
    max_request_delay: float = 2.0
    concurrent_limit: int = 10
    
    default_headers: Dict[str, str] = field(default_factory=lambda: {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    
    user_agents: List[str] = field(default_factory=lambda: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ])


@dataclass
class ProxyConfig:
    """代理池配置"""
    enabled: bool = False
    proxy_file: Optional[Path] = None
    proxies: List[str] = field(default_factory=list)
    
    test_url: str = "https://httpbin.org/ip"
    test_timeout: int = 10
    min_success_rate: float = 0.7
    
    rotation_strategy: str = "round_robin"
    ban_threshold: int = 3
    ban_duration: int = 300
    
    def get_proxy(self) -> Optional[str]:
        if not self.enabled or not self.proxies:
            return None
        return self.proxies[0] if self.proxies else None


@dataclass
class AntiCrawlerConfig:
    """反爬策略配置"""
    enable_random_delay: bool = True
    enable_user_agent_rotation: bool = True
    enable_referer_spoofing: bool = True
    enable_cookie_handling: bool = True
    
    respect_robots_txt: bool = True
    robots_txt_cache_ttl: int = 86400
    
    max_requests_per_domain: int = 100
    domain_cooldown: int = 60
    
    detection_patterns: List[str] = field(default_factory=lambda: [
        "captcha",
        "access denied",
        "rate limit",
        "too many requests",
        "blocked",
        "forbidden",
    ])


@dataclass
class DataSourceConfig:
    """数据源配置"""
    name: str
    base_url: str
    enabled: bool = True
    priority: int = 1
    
    requires_auth: bool = False
    auth_type: Optional[str] = None
    api_key: Optional[str] = None
    
    rate_limit: float = 1.0
    max_concurrent: int = 3
    
    timeout: int = 30
    max_retries: int = 3
    
    parser_type: str = "html"
    data_fields: List[str] = field(default_factory=lambda: [
        "journal_name", "impact_factor", "year", "issn", "eissn"
    ])


@dataclass
class StorageConfig:
    """存储配置"""
    database_type: str = "sqlite"
    database_path: Path = field(default_factory=lambda: Path.home() / ".paperinsight" / "impact_factor.db")
    
    cache_enabled: bool = True
    cache_expiry_days: int = 30
    
    enable_fts: bool = True
    
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    backup_max_count: int = 7
    
    journal_table: str = "journals"
    if_table: str = "impact_factors"
    alias_table: str = "journal_aliases"
    category_table: str = "journal_categories"
    task_table: str = "crawl_tasks"


@dataclass
class SchedulerConfig:
    """调度器配置"""
    enabled: bool = False
    update_interval_hours: int = 24
    update_time: str = "02:00"
    
    batch_size: int = 100
    max_workers: int = 5
    
    enable_incremental_update: bool = True
    incremental_threshold_days: int = 7
    
    retry_failed_tasks: bool = True
    max_retry_count: int = 3


@dataclass
class CrawlerConfig:
    """爬虫系统总配置"""
    request: RequestConfig = field(default_factory=RequestConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    anti_crawler: AntiCrawlerConfig = field(default_factory=AntiCrawlerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    
    data_sources: Dict[str, DataSourceConfig] = field(default_factory=lambda: {
        "letpub": DataSourceConfig(
            name="LetPub",
            base_url="https://www.letpub.com.cn/",
            priority=1,
            rate_limit=1.0,
            max_concurrent=3,
            parser_type="html",
        ),
        "mjl": DataSourceConfig(
            name="MJL Profile",
            base_url="https://mjl.clarivate.com/",
            priority=2,
            requires_auth=True,
            auth_type="bearer",
            rate_limit=2.0,
            max_concurrent=5,
            parser_type="json",
        ),
        "wos": DataSourceConfig(
            name="Web of Science",
            base_url="https://api.clarivate.com/apis/wos-journals/v1",
            priority=3,
            requires_auth=True,
            auth_type="api_key",
            rate_limit=10.0,
            max_concurrent=10,
            parser_type="json",
        ),
        "crossref": DataSourceConfig(
            name="Crossref",
            base_url="https://api.crossref.org/",
            priority=4,
            rate_limit=50.0,
            max_concurrent=20,
            parser_type="json",
        ),
    })
    
    log_level: str = "INFO"
    log_file: Optional[Path] = None
    
    @classmethod
    def from_file(cls, config_path: Path) -> "CrawlerConfig":
        """从配置文件加载配置"""
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrawlerConfig":
        """从字典创建配置"""
        config = cls()
        
        if "request" in data:
            config.request = RequestConfig(**data["request"])
        if "proxy" in data:
            config.proxy = ProxyConfig(**data["proxy"])
        if "anti_crawler" in data:
            config.anti_crawler = AntiCrawlerConfig(**data["anti_crawler"])
        if "storage" in data:
            storage_data = data["storage"]
            if "database_path" in storage_data:
                storage_data["database_path"] = Path(storage_data["database_path"])
            config.storage = StorageConfig(**storage_data)
        if "scheduler" in data:
            config.scheduler = SchedulerConfig(**data["scheduler"])
        if "data_sources" in data:
            config.data_sources = {
                k: DataSourceConfig(**v) for k, v in data["data_sources"].items()
            }
        
        return config
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "request": self.request.__dict__,
            "proxy": {
                **self.proxy.__dict__,
                "proxy_file": str(self.proxy.proxy_file) if self.proxy.proxy_file else None,
            },
            "anti_crawler": self.anti_crawler.__dict__,
            "storage": {
                **self.storage.__dict__,
                "database_path": str(self.storage.database_path),
            },
            "scheduler": self.scheduler.__dict__,
            "data_sources": {k: v.__dict__ for k, v in self.data_sources.items()},
            "log_level": self.log_level,
            "log_file": str(self.log_file) if self.log_file else None,
        }
    
    def save_to_file(self, config_path: Path):
        """保存配置到文件"""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
