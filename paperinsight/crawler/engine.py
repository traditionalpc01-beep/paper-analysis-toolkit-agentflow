"""
核心爬虫引擎

基于异步架构的高性能爬虫引擎，支持并发请求、智能反爬策略和代理池管理。
"""

import asyncio
import random
import time
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable, Awaitable
from urllib.parse import urlparse, urljoin
from collections import defaultdict

import aiohttp
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from paperinsight.crawler.config import CrawlerConfig, RequestConfig, AntiCrawlerConfig, ProxyConfig
from paperinsight.crawler.storage.models import CrawlResult, DataSourceType

logger = logging.getLogger(__name__)


class CrawlerException(Exception):
    """爬虫异常基类"""
    pass


class RateLimitException(CrawlerException):
    """速率限制异常"""
    pass


class BlockedException(CrawlerException):
    """被封禁异常"""
    pass


class ParseException(CrawlerException):
    """解析异常"""
    pass


@dataclass
class RequestResult:
    """请求结果"""
    success: bool
    status_code: int = 0
    content: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    url: str = ""
    elapsed: float = 0.0
    error_message: Optional[str] = None
    from_cache: bool = False


class UserAgentRotator:
    """User-Agent 轮换器"""
    
    def __init__(self, user_agents: Optional[List[str]] = None):
        self.user_agents = user_agents or [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]
        self._current_index = 0
    
    def get_random(self) -> str:
        return random.choice(self.user_agents)
    
    def get_next(self) -> str:
        ua = self.user_agents[self._current_index]
        self._current_index = (self._current_index + 1) % len(self.user_agents)
        return ua


class ProxyPool:
    """代理池管理器"""
    
    def __init__(self, config: ProxyConfig):
        self.config = config
        self.proxies: List[str] = []
        self.proxy_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"success": 0, "failure": 0, "banned": False, "banned_until": 0}
        )
        self._current_index = 0
        self._load_proxies()
    
    def _load_proxies(self):
        """加载代理列表"""
        if self.config.proxy_file and self.config.proxy_file.exists():
            with open(self.config.proxy_file, "r") as f:
                self.proxies = [line.strip() for line in f if line.strip()]
        elif self.config.proxies:
            self.proxies = list(self.config.proxies)
        
        logger.info(f"Loaded {len(self.proxies)} proxies")
    
    def get_proxy(self) -> Optional[str]:
        """获取可用代理"""
        if not self.config.enabled or not self.proxies:
            return None
        
        now = time.time()
        available_proxies = [
            p for p in self.proxies
            if not self.proxy_stats[p]["banned"]
            or self.proxy_stats[p]["banned_until"] < now
        ]
        
        if not available_proxies:
            logger.warning("No available proxies")
            return None
        
        if self.config.rotation_strategy == "round_robin":
            proxy = available_proxies[self._current_index % len(available_proxies)]
            self._current_index += 1
        else:
            proxy = random.choice(available_proxies)
        
        return proxy
    
    def report_success(self, proxy: str):
        """报告代理成功"""
        if proxy:
            self.proxy_stats[proxy]["success"] += 1
            self.proxy_stats[proxy]["banned"] = False
    
    def report_failure(self, proxy: str, is_banned: bool = False):
        """报告代理失败"""
        if not proxy:
            return
        
        self.proxy_stats[proxy]["failure"] += 1
        
        if is_banned:
            self.proxy_stats[proxy]["banned"] = True
            self.proxy_stats[proxy]["banned_until"] = time.time() + self.config.ban_duration
            logger.warning(f"Proxy {proxy} banned for {self.config.ban_duration}s")
        elif self.proxy_stats[proxy]["failure"] >= self.config.ban_threshold:
            self.proxy_stats[proxy]["banned"] = True
            self.proxy_stats[proxy]["banned_until"] = time.time() + self.config.ban_duration
            logger.warning(f"Proxy {proxy} temporarily banned due to failures")


class RateLimiter:
    """速率限制器"""
    
    def __init__(
        self,
        requests_per_second: float = 1.0,
        burst_size: int = 5,
    ):
        self.rate = requests_per_second
        self.burst_size = burst_size
        self.tokens = burst_size
        self.last_update = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """获取令牌"""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(
                self.burst_size,
                self.tokens + elapsed * self.rate
            )
            self.last_update = now
            
            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class DomainRateLimiter:
    """域名级别速率限制器"""
    
    def __init__(self, default_rate: float = 1.0, domain_rates: Optional[Dict[str, float]] = None):
        self.default_rate = default_rate
        self.domain_rates = domain_rates or {}
        self._limiters: Dict[str, RateLimiter] = {}
    
    def get_limiter(self, domain: str) -> RateLimiter:
        """获取域名对应的限制器"""
        if domain not in self._limiters:
            rate = self.domain_rates.get(domain, self.default_rate)
            self._limiters[domain] = RateLimiter(rate)
        return self._limiters[domain]
    
    async def acquire(self, url: str):
        """获取指定 URL 的访问令牌"""
        domain = urlparse(url).netloc
        limiter = self.get_limiter(domain)
        await limiter.acquire()


class AntiCrawlerDetector:
    """反爬检测器"""
    
    BLOCK_PATTERNS = [
        r"captcha",
        r"access denied",
        r"rate limit",
        r"too many requests",
        r"blocked",
        r"forbidden",
        r"请输入验证码",
        r"访问频率过高",
        r"请求过于频繁",
    ]
    
    @classmethod
    def check_response(cls, response: RequestResult) -> Optional[str]:
        """检查响应是否被反爬"""
        if response.status_code == 403:
            return "forbidden"
        if response.status_code == 429:
            return "rate_limit"
        if response.status_code == 503:
            return "service_unavailable"
        
        if response.content:
            content_lower = response.content.lower()
            for pattern in cls.BLOCK_PATTERNS:
                if re.search(pattern, content_lower, re.IGNORECASE):
                    return pattern
        
        return None


class RequestEngine:
    """请求引擎"""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.request_config = config.request
        self.anti_crawler_config = config.anti_crawler
        
        self.ua_rotator = UserAgentRotator(self.request_config.user_agents)
        self.proxy_pool = ProxyPool(config.proxy)
        self.rate_limiter = DomainRateLimiter(
            default_rate=1.0 / self.request_config.min_request_delay,
        )
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._sync_session: Optional[requests.Session] = None
        
        self._domain_last_request: Dict[str, float] = defaultdict(float)
        self._domain_request_count: Dict[str, int] = defaultdict(int)
    
    async def __aenter__(self):
        await self._init_async_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def _init_async_session(self):
        """初始化异步会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self.request_config.timeout,
                connect=self.request_config.connect_timeout,
            )
            connector = aiohttp.TCPConnector(
                limit=self.request_config.concurrent_limit,
                limit_per_host=5,
                ttl_dns_cache=300,
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            )
    
    async def close(self):
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()
        if self._sync_session:
            self._sync_session.close()
    
    def _build_headers(self, url: str, referer: Optional[str] = None) -> Dict[str, str]:
        """构建请求头"""
        headers = dict(self.request_config.default_headers)
        
        if self.anti_crawler_config.enable_user_agent_rotation:
            headers["User-Agent"] = self.ua_rotator.get_random()
        
        if self.anti_crawler_config.enable_referer_spoofing and referer:
            headers["Referer"] = referer
        elif url:
            parsed = urlparse(url)
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
        
        return headers
    
    async def _apply_delay(self, url: str):
        """应用请求延迟"""
        domain = urlparse(url).netloc
        
        if self.anti_crawler_config.enable_random_delay:
            delay = random.uniform(
                self.request_config.min_request_delay,
                self.request_config.max_request_delay,
            )
        else:
            delay = self.request_config.min_request_delay
        
        last_request = self._domain_last_request.get(domain, 0)
        elapsed = time.time() - last_request
        
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        
        self._domain_last_request[domain] = time.time()
        self._domain_request_count[domain] += 1
        
        if self._domain_request_count[domain] >= self.anti_crawler_config.max_requests_per_domain:
            logger.warning(f"Domain {domain} reached max requests, cooling down")
            await asyncio.sleep(self.anti_crawler_config.domain_cooldown)
            self._domain_request_count[domain] = 0
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def fetch(
        self,
        url: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        referer: Optional[str] = None,
        use_proxy: bool = True,
    ) -> RequestResult:
        """异步获取页面"""
        await self._init_async_session()
        await self._apply_delay(url)
        
        request_headers = self._build_headers(url, referer)
        if headers:
            request_headers.update(headers)
        
        proxy = None
        if use_proxy and self.config.proxy.enabled:
            proxy = self.proxy_pool.get_proxy()
        
        start_time = time.time()
        
        try:
            proxy_url = f"http://{proxy}" if proxy else None
            
            async with self._session.request(
                method,
                url,
                data=data,
                json=json_data,
                headers=request_headers,
                proxy=proxy_url,
                allow_redirects=True,
                max_redirects=self.request_config.max_redirects,
            ) as response:
                content = await response.text()
                elapsed = time.time() - start_time
                
                result = RequestResult(
                    success=response.status < 400,
                    status_code=response.status,
                    content=content,
                    headers=dict(response.headers),
                    url=str(response.url),
                    elapsed=elapsed,
                )
                
                block_reason = AntiCrawlerDetector.check_response(result)
                if block_reason:
                    if proxy:
                        self.proxy_pool.report_failure(proxy, is_banned=True)
                    raise BlockedException(f"Blocked: {block_reason}")
                
                if proxy:
                    self.proxy_pool.report_success(proxy)
                
                return result
                
        except asyncio.TimeoutError as e:
            elapsed = time.time() - start_time
            if proxy:
                self.proxy_pool.report_failure(proxy)
            return RequestResult(
                success=False,
                url=url,
                elapsed=elapsed,
                error_message=f"Timeout: {e}",
            )
        except aiohttp.ClientError as e:
            elapsed = time.time() - start_time
            if proxy:
                self.proxy_pool.report_failure(proxy)
            return RequestResult(
                success=False,
                url=url,
                elapsed=elapsed,
                error_message=f"Client error: {e}",
            )
    
    def fetch_sync(
        self,
        url: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        referer: Optional[str] = None,
    ) -> RequestResult:
        """同步获取页面（兼容模式）"""
        if self._sync_session is None:
            self._sync_session = requests.Session()
        
        request_headers = self._build_headers(url, referer)
        if headers:
            request_headers.update(request_headers)
        
        start_time = time.time()
        
        try:
            response = self._sync_session.request(
                method,
                url,
                data=data,
                json=json_data,
                headers=request_headers,
                timeout=self.request_config.timeout,
                allow_redirects=True,
            )
            
            elapsed = time.time() - start_time
            
            result = RequestResult(
                success=response.status_code < 400,
                status_code=response.status_code,
                content=response.text,
                headers=dict(response.headers),
                url=response.url,
                elapsed=elapsed,
            )
            
            block_reason = AntiCrawlerDetector.check_response(result)
            if block_reason:
                raise BlockedException(f"Blocked: {block_reason}")
            
            return result
            
        except requests.RequestException as e:
            elapsed = time.time() - start_time
            return RequestResult(
                success=False,
                url=url,
                elapsed=elapsed,
                error_message=str(e),
            )


class BaseParser(ABC):
    """解析器基类"""
    
    @abstractmethod
    async def parse(self, content: str, url: str) -> Dict[str, Any]:
        """解析页面内容"""
        pass
    
    @abstractmethod
    def can_parse(self, url: str) -> bool:
        """判断是否能解析该 URL"""
        pass


class BaseFetcher(ABC):
    """数据获取器基类"""
    
    source_type: DataSourceType
    
    def __init__(self, engine: RequestEngine):
        self.engine = engine
    
    @abstractmethod
    async def fetch(self, journal_name: str, **kwargs) -> CrawlResult:
        """获取期刊数据"""
        pass
    
    @abstractmethod
    async def fetch_batch(self, journals: List[str], **kwargs) -> List[CrawlResult]:
        """批量获取期刊数据"""
        pass


class CrawlerEngine:
    """爬虫引擎主类"""
    
    def __init__(self, config: Optional[CrawlerConfig] = None):
        self.config = config or CrawlerConfig()
        self.request_engine = RequestEngine(self.config)
        self._fetchers: Dict[str, BaseFetcher] = {}
        self._running = False
    
    def register_fetcher(self, name: str, fetcher: BaseFetcher):
        """注册数据获取器"""
        self._fetchers[name] = fetcher
    
    async def fetch_impact_factor(
        self,
        journal_name: str,
        sources: Optional[List[str]] = None,
    ) -> CrawlResult:
        """获取单个期刊的影响因子"""
        sources = sources or list(self._fetchers.keys())
        
        for source in sources:
            if source not in self._fetchers:
                logger.warning(f"Unknown source: {source}")
                continue
            
            fetcher = self._fetchers[source]
            try:
                result = await fetcher.fetch(journal_name)
                if result.success:
                    return result
            except Exception as e:
                logger.error(f"Fetcher {source} failed: {e}")
                continue
        
        return CrawlResult(
            success=False,
            journal_name=journal_name,
            source=DataSourceType.LOCAL,
            error_message="All sources failed",
        )
    
    async def fetch_impact_factors_batch(
        self,
        journals: List[str],
        sources: Optional[List[str]] = None,
        concurrency: int = 5,
    ) -> List[CrawlResult]:
        """批量获取影响因子"""
        semaphore = asyncio.Semaphore(concurrency)
        
        async def fetch_with_semaphore(journal: str) -> CrawlResult:
            async with semaphore:
                return await self.fetch_impact_factor(journal, sources)
        
        tasks = [fetch_with_semaphore(j) for j in journals]
        return await asyncio.gather(*tasks)
    
    async def start(self):
        """启动爬虫引擎"""
        self._running = True
        await self.request_engine._init_async_session()
        logger.info("Crawler engine started")
    
    async def stop(self):
        """停止爬虫引擎"""
        self._running = False
        await self.request_engine.close()
        logger.info("Crawler engine stopped")
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
