"""
影响因子爬虫系统性能测试

测试爬虫系统的各项性能指标，包括抓取效率、数据准确性、系统稳定性等。
"""

import asyncio
import time
import json
import logging
import statistics
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass, field, asdict

from paperinsight.crawler import (
    ImpactFactorQueryAPI,
    CrawlerConfig,
    ImpactFactorDatabase,
    CrawlerEngine,
    LetPubFetcher,
    CrossrefFetcher,
)
from paperinsight.crawler.storage.models import DataSourceType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """性能指标"""
    test_name: str
    start_time: str
    end_time: str
    duration_seconds: float
    
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    
    avg_response_time_ms: float = 0.0
    min_response_time_ms: float = 0.0
    max_response_time_ms: float = 0.0
    p50_response_time_ms: float = 0.0
    p95_response_time_ms: float = 0.0
    p99_response_time_ms: float = 0.0
    
    requests_per_second: float = 0.0
    success_rate: float = 0.0
    
    memory_peak_mb: float = 0.0
    cpu_peak_percent: float = 0.0
    
    errors: List[str] = field(default_factory=list)


class PerformanceTestSuite:
    """性能测试套件"""
    
    TEST_JOURNALS = [
        "Nature",
        "Science",
        "Cell",
        "Nature Communications",
        "Advanced Materials",
        "Journal of the American Chemical Society",
        "Angewandte Chemie",
        "Nano Letters",
        "ACS Nano",
        "Small",
        "Chemical Engineering Journal",
        "Applied Catalysis B",
        "Energy & Environmental Science",
        "Nature Nanotechnology",
        "Nature Chemistry",
        "Physical Review Letters",
        "Journal of Physical Chemistry C",
        "Langmuir",
        "Journal of Materials Chemistry A",
        "Crystal Growth & Design",
    ]
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.results: List[PerformanceMetrics] = []
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """运行所有性能测试"""
        logger.info("Starting performance test suite")
        
        results = {}
        
        results["single_query"] = await self.test_single_query()
        results["batch_query_small"] = await self.test_batch_query(5)
        results["batch_query_medium"] = await self.test_batch_query(10)
        results["batch_query_large"] = await self.test_batch_query(20)
        results["concurrent_query"] = await self.test_concurrent_query()
        results["cache_performance"] = await self.test_cache_performance()
        results["database_operations"] = self.test_database_operations()
        
        results["summary"] = self._generate_summary(results)
        
        return results
    
    async def test_single_query(self) -> PerformanceMetrics:
        """测试单个查询性能"""
        logger.info("Testing single query performance")
        
        metrics = PerformanceMetrics(
            test_name="single_query",
            start_time=datetime.now().isoformat(),
            end_time="",
            duration_seconds=0,
        )
        
        api = ImpactFactorQueryAPI(self.config)
        response_times = []
        
        try:
            start = time.time()
            
            for journal in self.TEST_JOURNALS[:5]:
                req_start = time.time()
                try:
                    result = await api.query(journal)
                    metrics.successful_requests += 1
                except Exception as e:
                    metrics.failed_requests += 1
                    metrics.errors.append(f"{journal}: {str(e)}")
                req_time = (time.time() - req_start) * 1000
                response_times.append(req_time)
                metrics.total_requests += 1
            
            end = time.time()
            metrics.duration_seconds = end - start
            metrics.end_time = datetime.now().isoformat()
            
            if response_times:
                metrics.avg_response_time_ms = statistics.mean(response_times)
                metrics.min_response_time_ms = min(response_times)
                metrics.max_response_time_ms = max(response_times)
                metrics.p50_response_time_ms = statistics.median(response_times)
                sorted_times = sorted(response_times)
                metrics.p95_response_time_ms = sorted_times[int(len(sorted_times) * 0.95)]
                metrics.p99_response_time_ms = sorted_times[int(len(sorted_times) * 0.99)]
            
            if metrics.duration_seconds > 0:
                metrics.requests_per_second = metrics.total_requests / metrics.duration_seconds
            
            if metrics.total_requests > 0:
                metrics.success_rate = metrics.successful_requests / metrics.total_requests
            
        finally:
            await api.close()
        
        logger.info(f"Single query test completed: {metrics.successful_requests}/{metrics.total_requests} success")
        return metrics
    
    async def test_batch_query(self, batch_size: int) -> PerformanceMetrics:
        """测试批量查询性能"""
        logger.info(f"Testing batch query performance (batch_size={batch_size})")
        
        metrics = PerformanceMetrics(
            test_name=f"batch_query_{batch_size}",
            start_time=datetime.now().isoformat(),
            end_time="",
            duration_seconds=0,
        )
        
        api = ImpactFactorQueryAPI(self.config)
        
        try:
            journals = self.TEST_JOURNALS[:batch_size]
            
            start = time.time()
            
            results = await api.query_batch(journals, concurrency=5)
            
            end = time.time()
            metrics.duration_seconds = end - start
            metrics.end_time = datetime.now().isoformat()
            
            metrics.total_requests = len(results)
            metrics.successful_requests = sum(1 for r in results if r.get("success"))
            metrics.failed_requests = metrics.total_requests - metrics.successful_requests
            
            if metrics.duration_seconds > 0:
                metrics.requests_per_second = metrics.total_requests / metrics.duration_seconds
            
            if metrics.total_requests > 0:
                metrics.success_rate = metrics.successful_requests / metrics.total_requests
            
            metrics.avg_response_time_ms = (metrics.duration_seconds / metrics.total_requests) * 1000 if metrics.total_requests > 0 else 0
            
        finally:
            await api.close()
        
        logger.info(f"Batch query test completed: {metrics.success_rate:.1%} success rate")
        return metrics
    
    async def test_concurrent_query(self) -> PerformanceMetrics:
        """测试并发查询性能"""
        logger.info("Testing concurrent query performance")
        
        metrics = PerformanceMetrics(
            test_name="concurrent_query",
            start_time=datetime.now().isoformat(),
            end_time="",
            duration_seconds=0,
        )
        
        api = ImpactFactorQueryAPI(self.config)
        
        try:
            start = time.time()
            
            tasks = [api.query(j) for j in self.TEST_JOURNALS]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            end = time.time()
            metrics.duration_seconds = end - start
            metrics.end_time = datetime.now().isoformat()
            
            metrics.total_requests = len(results)
            for r in results:
                if isinstance(r, Exception):
                    metrics.failed_requests += 1
                    metrics.errors.append(str(r))
                elif isinstance(r, dict):
                    if r.get("success"):
                        metrics.successful_requests += 1
                    else:
                        metrics.failed_requests += 1
            
            if metrics.duration_seconds > 0:
                metrics.requests_per_second = metrics.total_requests / metrics.duration_seconds
            
            if metrics.total_requests > 0:
                metrics.success_rate = metrics.successful_requests / metrics.total_requests
            
        finally:
            await api.close()
        
        logger.info(f"Concurrent query test completed: {metrics.requests_per_second:.1f} req/s")
        return metrics
    
    async def test_cache_performance(self) -> PerformanceMetrics:
        """测试缓存性能"""
        logger.info("Testing cache performance")
        
        metrics = PerformanceMetrics(
            test_name="cache_performance",
            start_time=datetime.now().isoformat(),
            end_time="",
            duration_seconds=0,
        )
        
        api = ImpactFactorQueryAPI(self.config)
        
        try:
            journals = self.TEST_JOURNALS[:5]
            
            start = time.time()
            results_first = await api.query_batch(journals)
            first_duration = time.time() - start
            
            start = time.time()
            results_second = await api.query_batch(journals)
            second_duration = time.time() - start
            
            metrics.duration_seconds = first_duration + second_duration
            metrics.end_time = datetime.now().isoformat()
            
            metrics.total_requests = len(journals) * 2
            metrics.successful_requests = sum(1 for r in results_first if r.get("success")) + \
                                          sum(1 for r in results_second if r.get("success"))
            metrics.failed_requests = metrics.total_requests - metrics.successful_requests
            
            cache_speedup = first_duration / second_duration if second_duration > 0 else 0
            
            metrics.errors.append(f"Cache speedup: {cache_speedup:.1f}x")
            metrics.errors.append(f"First pass: {first_duration:.2f}s, Second pass: {second_duration:.2f}s")
            
        finally:
            await api.close()
        
        logger.info(f"Cache performance test completed")
        return metrics
    
    def test_database_operations(self) -> PerformanceMetrics:
        """测试数据库操作性能"""
        logger.info("Testing database operations performance")
        
        metrics = PerformanceMetrics(
            test_name="database_operations",
            start_time=datetime.now().isoformat(),
            end_time="",
            duration_seconds=0,
        )
        
        db = ImpactFactorDatabase(self.config.storage)
        
        try:
            start = time.time()
            
            for i, journal in enumerate(self.TEST_JOURNALS):
                from paperinsight.crawler import JournalRecord, ImpactFactorRecord, DataSourceType
                
                record = JournalRecord(
                    canonical_name=f"Test Journal {i}",
                    issn=f"1234-567{i % 10}",
                )
                record.id = db.upsert_journal(record)
                metrics.total_requests += 1
                
                if record.id:
                    if_record = ImpactFactorRecord(
                        journal_id=record.id,
                        if_value=10.0 + i,
                        if_year=2024,
                        source=DataSourceType.LOCAL,
                    )
                    db.upsert_impact_factor(if_record)
                    metrics.successful_requests += 1
                else:
                    metrics.failed_requests += 1
            
            stats = db.get_stats()
            metrics.errors.append(f"Total journals in DB: {stats['total_journals']}")
            metrics.errors.append(f"Total IF records: {stats['total_if_records']}")
            
            end = time.time()
            metrics.duration_seconds = end - start
            metrics.end_time = datetime.now().isoformat()
            
            if metrics.duration_seconds > 0:
                metrics.requests_per_second = metrics.total_requests / metrics.duration_seconds
            
            if metrics.total_requests > 0:
                metrics.success_rate = metrics.successful_requests / metrics.total_requests
            
        except Exception as e:
            metrics.errors.append(str(e))
        
        logger.info(f"Database operations test completed: {metrics.requests_per_second:.1f} ops/s")
        return metrics
    
    def _generate_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """生成测试摘要"""
        summary = {
            "total_tests": len(results) - 1,
            "overall_success_rate": 0.0,
            "avg_requests_per_second": 0.0,
            "recommendations": [],
        }
        
        success_rates = []
        rps_values = []
        
        for key, value in results.items():
            if key == "summary":
                continue
            if hasattr(value, "success_rate"):
                success_rates.append(value.success_rate)
            if hasattr(value, "requests_per_second"):
                rps_values.append(value.requests_per_second)
        
        if success_rates:
            summary["overall_success_rate"] = statistics.mean(success_rates)
        if rps_values:
            summary["avg_requests_per_second"] = statistics.mean(rps_values)
        
        if summary["overall_success_rate"] < 0.9:
            summary["recommendations"].append("成功率低于 90%，建议检查网络连接或降低请求频率")
        
        if summary["avg_requests_per_second"] < 1.0:
            summary["recommendations"].append("请求速率较低，建议增加并发数或使用代理池")
        
        return summary
    
    def save_report(self, results: Dict[str, Any], output_path: str):
        """保存测试报告"""
        output = {}
        for key, value in results.items():
            if hasattr(value, "__dict__"):
                output[key] = asdict(value)
            else:
                output[key] = value
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Report saved to {output_path}")


async def main():
    """主测试函数"""
    config = CrawlerConfig()
    
    suite = PerformanceTestSuite(config)
    
    results = await suite.run_all_tests()
    
    suite.save_report(results, "performance_test_report.json")
    
    print("\n" + "=" * 60)
    print("性能测试报告摘要")
    print("=" * 60)
    
    summary = results.get("summary", {})
    print(f"总测试数: {summary.get('total_tests', 0)}")
    print(f"整体成功率: {summary.get('overall_success_rate', 0):.1%}")
    print(f"平均请求速率: {summary.get('avg_requests_per_second', 0):.2f} req/s")
    
    if summary.get("recommendations"):
        print("\n优化建议:")
        for rec in summary["recommendations"]:
            print(f"  - {rec}")
    
    print("\n详细测试结果:")
    for key, value in results.items():
        if key == "summary":
            continue
        if hasattr(value, "success_rate"):
            print(f"  {key}: 成功率 {value.success_rate:.1%}, "
                  f"速率 {value.requests_per_second:.2f} req/s")


if __name__ == "__main__":
    asyncio.run(main())
