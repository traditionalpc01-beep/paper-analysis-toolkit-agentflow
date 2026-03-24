"""
数据解析器模块

实现多数据源的解析器，支持 LetPub、MJL、Crossref 等数据源。
"""

import re
import json
import html
import logging
from abc import abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlencode

from paperinsight.crawler.engine import BaseParser, BaseFetcher, RequestEngine
from paperinsight.crawler.storage.models import CrawlResult, DataSourceType
from paperinsight.utils.journal_metadata import canonicalize_journal_title, normalize_issn

logger = logging.getLogger(__name__)


class HTMLParser(BaseParser):
    """HTML 解析器基类"""
    
    def can_parse(self, url: str) -> bool:
        return True
    
    def _clean_text(self, text: str) -> str:
        """清理文本"""
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
    
    def _extract_number(self, text: str, pattern: str = r"[\d.]+") -> Optional[float]:
        """从文本中提取数字"""
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
        return None


class LetPubParser(HTMLParser):
    """LetPub 解析器"""
    
    IF_PATTERN = re.compile(r"\bIF\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
    
    async def parse(self, content: str, url: str) -> Dict[str, Any]:
        """解析 LetPub 搜索结果页面"""
        results = []
        
        for row_html in re.finditer(r"<tr\b.*?</tr>", content, flags=re.IGNORECASE | re.DOTALL):
            row_text = self._clean_text(row_html.group())
            
            if_match = self.IF_PATTERN.search(row_text)
            if not if_match:
                continue
            
            if_value = float(if_match.group(1))
            if not 0.1 <= if_value <= 500:
                continue
            
            title_match = re.search(
                r'<a[^>]+href="([^"]*page=journalapp&view=detail[^"]*)"[^>]*>(.*?)</a>',
                row_html.group(),
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not title_match:
                continue
            
            journal_name = self._clean_text(title_match.group(2))
            detail_url = urljoin("https://www.letpub.com.cn/", title_match.group(1))
            
            issn_match = re.search(r"\b(\d{4}[-–]\d{3}[0-9X])\b", row_text)
            issn = normalize_issn(issn_match.group(1)) if issn_match else None
            
            results.append({
                "journal_name": journal_name,
                "impact_factor": if_value,
                "issn": issn,
                "source_url": detail_url,
            })
        
        return {"results": results}


class LetPubFetcher(BaseFetcher):
    """LetPub 数据获取器"""
    
    source_type = DataSourceType.LETPUB
    BASE_URL = "https://www.letpub.com.cn/"
    
    def __init__(self, engine: RequestEngine):
        super().__init__(engine)
        self.parser = LetPubParser()
    
    async def fetch(self, journal_name: str, **kwargs) -> CrawlResult:
        """获取单个期刊的影响因子"""
        params = {
            "currentsearchpage": 1,
            "page": "journalapp",
            "view": "search",
            "searchname": journal_name,
        }
        search_url = f"{self.BASE_URL}index.php?{urlencode(params)}"
        
        start_time = datetime.now()
        
        try:
            result = await self.engine.fetch(search_url)
            
            if not result.success:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message=result.error_message or f"HTTP {result.status_code}",
                )
            
            parsed = await self.parser.parse(result.content, search_url)
            results = parsed.get("results", [])
            
            if not results:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message="No results found",
                )
            
            best_match = self._find_best_match(journal_name, results)
            
            if not best_match:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message="No matching journal found",
                )
            
            elapsed = (datetime.now() - start_time).total_seconds()
            
            return CrawlResult(
                success=True,
                journal_name=best_match["journal_name"],
                impact_factor=best_match["impact_factor"],
                source=self.source_type,
                source_url=best_match["source_url"],
                issn=best_match.get("issn"),
                confidence_score=0.9,
                processing_time=elapsed,
            )
            
        except Exception as e:
            logger.error(f"LetPub fetch error for {journal_name}: {e}")
            return CrawlResult(
                success=False,
                journal_name=journal_name,
                source=self.source_type,
                error_message=str(e),
            )
    
    def _find_best_match(
        self,
        query: str,
        results: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """找到最佳匹配结果"""
        if not results:
            return None
        
        canonical_query = canonicalize_journal_title(query)
        
        best_result = None
        best_score = 0
        
        for result in results:
            score = 0
            canonical_result = canonicalize_journal_title(result["journal_name"])
            
            if canonical_query == canonical_result:
                score += 10
            elif canonical_query and canonical_result:
                if canonical_query in canonical_result:
                    score += 7
                elif canonical_result in canonical_query:
                    score += 5
            
            if result.get("issn"):
                score += 2
            
            if score > best_score:
                best_score = score
                best_result = result
        
        return best_result or results[0]
    
    async def fetch_batch(self, journals: List[str], **kwargs) -> List[CrawlResult]:
        """批量获取"""
        import asyncio
        return await asyncio.gather(*[self.fetch(j) for j in journals])


class JSONParser(BaseParser):
    """JSON 解析器基类"""
    
    def can_parse(self, url: str) -> bool:
        return "api" in url.lower() or url.endswith(".json")
    
    async def parse(self, content: str, url: str) -> Dict[str, Any]:
        """解析 JSON 响应"""
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return {}


class CrossrefFetcher(BaseFetcher):
    """Crossref API 数据获取器"""
    
    source_type = DataSourceType.CROSSREF
    BASE_URL = "https://api.crossref.org/"
    
    def __init__(self, engine: RequestEngine):
        super().__init__(engine)
        self.parser = JSONParser()
    
    async def fetch(self, journal_name: str, **kwargs) -> CrawlResult:
        """获取期刊信息（Crossref 不直接提供 IF，但可获取 ISSN）"""
        params = {"query": journal_name, "rows": 5}
        url = f"{self.BASE_URL}journals?{urlencode(params)}"
        
        try:
            result = await self.engine.fetch(url)
            
            if not result.success:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message=result.error_message,
                )
            
            parsed = await self.parser.parse(result.content, url)
            items = parsed.get("message", {}).get("items", [])
            
            if not items:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message="No results found",
                )
            
            best_match = items[0]
            
            return CrawlResult(
                success=True,
                journal_name=best_match.get("title", journal_name),
                source=self.source_type,
                source_url=url,
                issn=best_match.get("ISSN", [None])[0] if best_match.get("ISSN") else None,
                confidence_score=0.7,
            )
            
        except Exception as e:
            logger.error(f"Crossref fetch error: {e}")
            return CrawlResult(
                success=False,
                journal_name=journal_name,
                source=self.source_type,
                error_message=str(e),
            )
    
    async def fetch_batch(self, journals: List[str], **kwargs) -> List[CrawlResult]:
        """批量获取"""
        import asyncio
        return await asyncio.gather(*[self.fetch(j) for j in journals])


class MJLFetcher(BaseFetcher):
    """MJL Profile 数据获取器"""
    
    source_type = DataSourceType.MJL
    BASE_URL = "https://mjl.clarivate.com/api/mjl/"
    
    def __init__(self, engine: RequestEngine, bearer_token: Optional[str] = None):
        super().__init__(engine)
        self.bearer_token = bearer_token
        self.parser = JSONParser()
    
    async def fetch(self, journal_name: str, **kwargs) -> CrawlResult:
        """获取期刊影响因子"""
        if not self.bearer_token:
            return CrawlResult(
                success=False,
                journal_name=journal_name,
                source=self.source_type,
                error_message="No bearer token configured",
            )
        
        search_url = f"{self.BASE_URL}search"
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        
        try:
            params = {"query": journal_name, "limit": 5}
            result = await self.engine.fetch(
                f"{search_url}?{urlencode(params)}",
                headers=headers,
            )
            
            if not result.success:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message=result.error_message,
                )
            
            parsed = await self.parser.parse(result.content, search_url)
            journals = parsed.get("journals", [])
            
            if not journals:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message="No results found",
                )
            
            best_match = self._find_best_match(journal_name, journals)
            
            if not best_match:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message="No matching journal",
                )
            
            if_value = best_match.get("impactFactor")
            
            return CrawlResult(
                success=if_value is not None,
                journal_name=best_match.get("journalName", journal_name),
                impact_factor=if_value,
                if_year=best_match.get("impactFactorYear"),
                source=self.source_type,
                issn=best_match.get("issn"),
                eissn=best_match.get("eissn"),
                publisher=best_match.get("publisher"),
                confidence_score=0.95,
            )
            
        except Exception as e:
            logger.error(f"MJL fetch error: {e}")
            return CrawlResult(
                success=False,
                journal_name=journal_name,
                source=self.source_type,
                error_message=str(e),
            )
    
    def _find_best_match(self, query: str, journals: List[Dict]) -> Optional[Dict]:
        """找到最佳匹配"""
        canonical_query = canonicalize_journal_title(query)
        
        for journal in journals:
            name = journal.get("journalName", "")
            if canonicalize_journal_title(name) == canonical_query:
                return journal
        
        for journal in journals:
            name = journal.get("journalName", "")
            if canonical_query and canonical_query in canonicalize_journal_title(name):
                return journal
        
        return journals[0] if journals else None
    
    async def fetch_batch(self, journals: List[str], **kwargs) -> List[CrawlResult]:
        """批量获取"""
        import asyncio
        return await asyncio.gather(*[self.fetch(j) for j in journals])


class WoSFetcher(BaseFetcher):
    """Web of Science API 数据获取器"""
    
    source_type = DataSourceType.WOS
    BASE_URL = "https://api.clarivate.com/apis/wos-journals/v1/"
    
    def __init__(self, engine: RequestEngine, api_key: Optional[str] = None):
        super().__init__(engine)
        self.api_key = api_key
        self.parser = JSONParser()
    
    async def fetch(self, journal_name: str, **kwargs) -> CrawlResult:
        """获取期刊影响因子"""
        if not self.api_key:
            return CrawlResult(
                success=False,
                journal_name=journal_name,
                source=self.source_type,
                error_message="No API key configured",
            )
        
        headers = {"X-API-Key": self.api_key}
        
        try:
            params = {"q": f"journal_name={journal_name}", "limit": 5}
            url = f"{self.BASE_URL}journals?{urlencode(params)}"
            
            result = await self.engine.fetch(url, headers=headers)
            
            if not result.success:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message=result.error_message,
                )
            
            parsed = await self.parser.parse(result.content, url)
            journals = parsed.get("journals", [])
            
            if not journals:
                return CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=self.source_type,
                    error_message="No results found",
                )
            
            journal = journals[0]
            metrics = journal.get("metrics", {})
            
            return CrawlResult(
                success=True,
                journal_name=journal.get("journalName", journal_name),
                impact_factor=metrics.get("impactFactor"),
                if_year=metrics.get("impactFactorYear"),
                source=self.source_type,
                issn=journal.get("issn"),
                eissn=journal.get("eissn"),
                publisher=journal.get("publisher"),
                confidence_score=0.98,
            )
            
        except Exception as e:
            logger.error(f"WoS fetch error: {e}")
            return CrawlResult(
                success=False,
                journal_name=journal_name,
                source=self.source_type,
                error_message=str(e),
            )
    
    async def fetch_batch(self, journals: List[str], **kwargs) -> List[CrawlResult]:
        """批量获取"""
        import asyncio
        return await asyncio.gather(*[self.fetch(j) for j in journals])
