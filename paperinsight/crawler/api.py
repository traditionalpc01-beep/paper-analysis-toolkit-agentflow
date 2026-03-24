"""
用户查询接口

提供 CLI 命令和程序化 API 接口，支持多维度查询影响因子数据。
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pathlib import Path
from dataclasses import asdict

from paperinsight.crawler.config import CrawlerConfig
from paperinsight.crawler.storage.database import ImpactFactorDatabase
from paperinsight.crawler.storage.models import (
    JournalRecord,
    ImpactFactorRecord,
    CrawlResult,
    BatchCrawlResult,
    DataSourceType,
    DataQuality,
)
from paperinsight.crawler.engine import CrawlerEngine
from paperinsight.crawler.parsers import LetPubFetcher, CrossrefFetcher, MJLFetcher, WoSFetcher
from paperinsight.crawler.validation import DataValidator, CrossValidator
from paperinsight.crawler.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class ImpactFactorQueryAPI:
    """影响因子查询 API"""
    
    def __init__(
        self,
        config: Optional[CrawlerConfig] = None,
        database: Optional[ImpactFactorDatabase] = None,
    ):
        self.config = config or CrawlerConfig()
        self.database = database or ImpactFactorDatabase(self.config.storage)
        self._crawler: Optional[CrawlerEngine] = None
        self._scheduler: Optional[TaskScheduler] = None
    
    async def _get_crawler(self) -> CrawlerEngine:
        """获取爬虫引擎实例"""
        if self._crawler is None:
            self._crawler = CrawlerEngine(self.config)
            await self._crawler.start()
            
            self._crawler.register_fetcher("letpub", LetPubFetcher(self._crawler.request_engine))
            self._crawler.register_fetcher("crossref", CrossrefFetcher(self._crawler.request_engine))
            
            mjl_token = self.config.data_sources.get("mjl", {}).get("api_key")
            if mjl_token:
                self._crawler.register_fetcher(
                    "mjl", MJLFetcher(self._crawler.request_engine, mjl_token)
                )
            
            wos_key = self.config.data_sources.get("wos", {}).get("api_key")
            if wos_key:
                self._crawler.register_fetcher(
                    "wos", WoSFetcher(self._crawler.request_engine, wos_key)
                )
        
        return self._crawler
    
    async def query(
        self,
        journal_name: str,
        if_year: Optional[int] = None,
        force_refresh: bool = False,
        sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        查询单个期刊的影响因子
        
        Args:
            journal_name: 期刊名称
            if_year: 影响因子年份（默认最新）
            force_refresh: 是否强制刷新缓存
            sources: 指定数据源列表
            
        Returns:
            查询结果字典
        """
        journal = self.database.get_journal_by_name(journal_name)
        
        if not journal:
            journal = self.database.get_journal_by_alias(journal_name)
        
        if not journal:
            issn = self._extract_issn(journal_name)
            if issn:
                journal = self.database.get_journal_by_issn(issn)
        
        if journal and not force_refresh:
            if_record = self.database.get_impact_factor(journal.id, if_year)
            
            if if_record:
                return self._format_result(journal, if_record)
        
        crawler = await self._get_crawler()
        
        try:
            result = await crawler.fetch_impact_factor(journal_name, sources)
            
            if result.success:
                cleaned_result, validation = DataValidator.validate_and_clean(result)
                
                if not journal:
                    journal = JournalRecord(
                        canonical_name=cleaned_result.journal_name,
                        issn=cleaned_result.issn,
                        eissn=cleaned_result.eissn,
                        publisher=cleaned_result.publisher,
                    )
                    journal.id = self.database.upsert_journal(journal)
                
                if_record = cleaned_result.to_if_record(journal.id)
                if if_record:
                    if_record.quality = validation.quality
                    self.database.upsert_impact_factor(if_record)
                
                return self._format_result(journal, if_record, validation)
            else:
                return {
                    "success": False,
                    "journal_name": journal_name,
                    "error": result.error_message,
                    "source": result.source.value if result.source else None,
                }
                
        except Exception as e:
            logger.error(f"Query failed for {journal_name}: {e}")
            return {
                "success": False,
                "journal_name": journal_name,
                "error": str(e),
            }
    
    async def query_batch(
        self,
        journals: List[str],
        concurrency: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        批量查询期刊影响因子
        
        Args:
            journals: 期刊名称列表
            concurrency: 并发数
            
        Returns:
            查询结果列表
        """
        crawler = await self._get_crawler()
        
        results = await crawler.fetch_impact_factors_batch(journals, concurrency=concurrency)
        
        formatted_results = []
        for result in results:
            if result.success:
                cleaned_result, validation = DataValidator.validate_and_clean(result)
                
                journal = self.database.get_journal_by_name(cleaned_result.journal_name)
                if not journal:
                    journal = JournalRecord(
                        canonical_name=cleaned_result.journal_name,
                        issn=cleaned_result.issn,
                        eissn=cleaned_result.eissn,
                        publisher=cleaned_result.publisher,
                    )
                    journal.id = self.database.upsert_journal(journal)
                
                if_record = cleaned_result.to_if_record(journal.id)
                if if_record:
                    if_record.quality = validation.quality
                    self.database.upsert_impact_factor(if_record)
                
                formatted_results.append(self._format_result(journal, if_record, validation))
            else:
                formatted_results.append({
                    "success": False,
                    "journal_name": result.journal_name,
                    "error": result.error_message,
                })
        
        return formatted_results
    
    def query_by_issn(
        self,
        issn: str,
        if_year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        根据 ISSN 查询影响因子
        
        Args:
            issn: ISSN 号
            if_year: 影响因子年份
            
        Returns:
            查询结果
        """
        journal = self.database.get_journal_by_issn(issn)
        
        if not journal:
            return {
                "success": False,
                "issn": issn,
                "error": "Journal not found",
            }
        
        if_record = self.database.get_impact_factor(journal.id, if_year)
        
        return self._format_result(journal, if_record)
    
    def search_journals(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        搜索期刊
        
        Args:
            query: 搜索关键词
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            期刊列表
        """
        journals = self.database.search_journals(query, limit, offset)
        
        results = []
        for journal in journals:
            if_record = self.database.get_impact_factor(journal.id)
            results.append(self._format_result(journal, if_record))
        
        return results
    
    def query_by_category(
        self,
        category: str,
        limit: int = 100,
        min_if: Optional[float] = None,
        max_if: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        按学科分类查询期刊
        
        Args:
            category: 学科分类名称
            limit: 返回数量限制
            min_if: 最小影响因子
            max_if: 最大影响因子
            
        Returns:
            期刊列表
        """
        results = self.database.get_journals_by_category(category, limit)
        
        formatted = []
        for journal, if_record in results:
            if if_record:
                if min_if and if_record.if_value < min_if:
                    continue
                if max_if and if_record.if_value > max_if:
                    continue
            
            formatted.append(self._format_result(journal, if_record))
        
        return formatted
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取数据库统计信息
        
        Returns:
            统计信息字典
        """
        return self.database.get_stats()
    
    def export_to_json(
        self,
        output_path: Union[str, Path],
        if_year: Optional[int] = None,
        min_quality: Optional[str] = None,
    ) -> int:
        """
        导出数据到 JSON 文件
        
        Args:
            output_path: 输出文件路径
            if_year: 指定年份
            min_quality: 最低质量等级
            
        Returns:
            导出记录数
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        records = []
        
        with self.database._get_connection() as conn:
            query = """
                SELECT j.canonical_name, j.issn, j.eissn, j.publisher,
                       i.if_value, i.if_year, i.source, i.confidence_score, i.quality
                FROM journals j
                JOIN impact_factors i ON j.id = i.journal_id
            """
            conditions = []
            params = []
            
            if if_year:
                conditions.append("i.if_year = ?")
                params.append(if_year)
            
            if min_quality:
                quality_order = ["unverified", "low", "medium", "high", "verified"]
                min_idx = quality_order.index(min_quality) if min_quality in quality_order else 0
                allowed = quality_order[min_idx:]
                conditions.append(f"i.quality IN ({','.join(['?']*len(allowed))})")
                params.extend(allowed)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            cursor = conn.execute(query, params)
            
            for row in cursor.fetchall():
                records.append({
                    "journal_name": row["canonical_name"],
                    "issn": row["issn"],
                    "eissn": row["eissn"],
                    "publisher": row["publisher"],
                    "impact_factor": row["if_value"],
                    "year": row["if_year"],
                    "source": row["source"],
                    "confidence": row["confidence_score"],
                    "quality": row["quality"],
                })
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Exported {len(records)} records to {output_path}")
        return len(records)
    
    async def close(self):
        """关闭资源"""
        if self._crawler:
            await self._crawler.stop()
            self._crawler = None
    
    def _format_result(
        self,
        journal: JournalRecord,
        if_record: Optional[ImpactFactorRecord],
        validation: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """格式化查询结果"""
        result = {
            "success": True,
            "journal_name": journal.canonical_name,
            "issn": journal.issn,
            "eissn": journal.eissn,
            "publisher": journal.publisher,
        }
        
        if if_record:
            result.update({
                "impact_factor": if_record.if_value,
                "year": if_record.if_year,
                "source": if_record.source.value,
                "confidence": if_record.confidence_score,
                "quality": if_record.quality.value,
                "jcr_quartile": if_record.jcr_quartile,
                "jcr_category": if_record.jcr_category,
            })
        else:
            result.update({
                "impact_factor": None,
                "year": None,
                "source": None,
            })
        
        if validation:
            result["validation"] = {
                "quality": validation.quality.value,
                "confidence": validation.confidence_score,
                "issues": validation.issues,
            }
        
        return result
    
    def _extract_issn(self, text: str) -> Optional[str]:
        """从文本中提取 ISSN"""
        import re
        match = re.search(r"\b(\d{4}[-–]\d{3}[0-9X])\b", text)
        return match.group(1).replace("–", "-") if match else None


async def main_cli():
    """CLI 入口函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Impact Factor Crawler CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    query_parser = subparsers.add_parser("query", help="Query impact factor for a journal")
    query_parser.add_argument("journal", help="Journal name or ISSN")
    query_parser.add_argument("--year", type=int, help="Impact factor year")
    query_parser.add_argument("--refresh", action="store_true", help="Force refresh")
    query_parser.add_argument("--sources", nargs="+", help="Data sources to use")
    
    batch_parser = subparsers.add_parser("batch", help="Batch query journals")
    batch_parser.add_argument("file", help="File containing journal names (one per line)")
    batch_parser.add_argument("--concurrency", type=int, default=5, help="Concurrency")
    
    search_parser = subparsers.add_parser("search", help="Search journals")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=20, help="Result limit")
    
    stats_parser = subparsers.add_parser("stats", help="Show database statistics")
    
    export_parser = subparsers.add_parser("export", help="Export data to JSON")
    export_parser.add_argument("output", help="Output file path")
    export_parser.add_argument("--year", type=int, help="Filter by year")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    api = ImpactFactorQueryAPI()
    
    try:
        if args.command == "query":
            result = await api.query(
                args.journal,
                if_year=args.year,
                force_refresh=args.refresh,
                sources=args.sources,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
        
        elif args.command == "batch":
            with open(args.file, "r", encoding="utf-8") as f:
                journals = [line.strip() for line in f if line.strip()]
            
            results = await api.query_batch(journals, args.concurrency)
            print(json.dumps(results, indent=2, ensure_ascii=False))
        
        elif args.command == "search":
            results = api.search_journals(args.query, args.limit)
            print(json.dumps(results, indent=2, ensure_ascii=False))
        
        elif args.command == "stats":
            stats = api.get_stats()
            print(json.dumps(stats, indent=2, ensure_ascii=False))
        
        elif args.command == "export":
            count = api.export_to_json(args.output, args.year)
            print(f"Exported {count} records to {args.output}")
    
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main_cli())
