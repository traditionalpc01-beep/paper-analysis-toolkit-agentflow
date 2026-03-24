"""
定时任务调度系统

基于 APScheduler 实现的定时任务调度器，支持周期性数据更新和断点续爬。
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Callable, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from paperinsight.crawler.config import SchedulerConfig, CrawlerConfig
from paperinsight.crawler.storage.database import ImpactFactorDatabase
from paperinsight.crawler.storage.models import CrawlTask, CrawlResult, BatchCrawlResult
from paperinsight.crawler.engine import CrawlerEngine

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class TaskType(str, Enum):
    """任务类型"""
    FULL_UPDATE = "full_update"
    INCREMENTAL_UPDATE = "incremental_update"
    SINGLE_JOURNAL = "single_journal"
    BATCH_JOURNALS = "batch_journals"
    VALIDATION = "validation"
    BACKUP = "backup"


@dataclass
class TaskProgress:
    """任务进度"""
    task_id: int
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    started_at: Optional[datetime] = None
    estimated_completion: Optional[datetime] = None
    
    @property
    def progress_percent(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.processed / self.total) * 100
    
    @property
    def elapsed_seconds(self) -> float:
        if not self.started_at:
            return 0.0
        return (datetime.now() - self.started_at).total_seconds()
    
    @property
    def items_per_second(self) -> float:
        if self.elapsed_seconds == 0:
            return 0.0
        return self.processed / self.elapsed_seconds


class CheckpointManager:
    """断点续爬检查点管理器"""
    
    CHECKPOINT_DIR = Path.home() / ".paperinsight" / "checkpoints"
    
    def __init__(self, task_id: int):
        self.task_id = task_id
        self.checkpoint_file = self.CHECKPOINT_DIR / f"task_{task_id}.json"
        self._ensure_dir()
    
    def _ensure_dir(self):
        """确保检查点目录存在"""
        self.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    
    def save(self, data: Dict[str, Any]):
        """保存检查点"""
        data["saved_at"] = datetime.now().isoformat()
        with open(self.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Checkpoint saved for task {self.task_id}")
    
    def load(self) -> Optional[Dict[str, Any]]:
        """加载检查点"""
        if not self.checkpoint_file.exists():
            return None
        
        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None
    
    def clear(self):
        """清除检查点"""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
            logger.debug(f"Checkpoint cleared for task {self.task_id}")


class TaskScheduler:
    """任务调度器"""
    
    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        database: Optional[ImpactFactorDatabase] = None,
        crawler: Optional[CrawlerEngine] = None,
    ):
        self.config = config or SchedulerConfig()
        self.database = database or ImpactFactorDatabase()
        self.crawler = crawler
        
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running_tasks: Dict[int, TaskProgress] = {}
        self._task_callbacks: Dict[str, Callable] = {}
    
    def _init_scheduler(self):
        """初始化调度器"""
        if self._scheduler is not None:
            return
        
        jobstores = {
            "default": MemoryJobStore(),
        }
        
        executors = {
            "default": ThreadPoolExecutor(max_workers=self.config.max_workers),
        }
        
        self._scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            timezone="Asia/Shanghai",
        )
    
    def start(self):
        """启动调度器"""
        self._init_scheduler()
        
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Task scheduler started")
            
            if self.config.enabled:
                self._schedule_periodic_tasks()
    
    def stop(self):
        """停止调度器"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Task scheduler stopped")
    
    def _schedule_periodic_tasks(self):
        """调度周期性任务"""
        hour, minute = map(int, self.config.update_time.split(":"))
        
        self._scheduler.add_job(
            self.run_full_update,
            CronTrigger(hour=hour, minute=minute),
            id="full_update",
            name="Full IF Data Update",
            replace_existing=True,
        )
        logger.info(f"Scheduled full update at {self.config.update_time}")
        
        if self.config.enable_incremental_update:
            self._scheduler.add_job(
                self.run_incremental_update,
                IntervalTrigger(hours=self.config.update_interval_hours),
                id="incremental_update",
                name="Incremental IF Update",
                replace_existing=True,
            )
            logger.info(f"Scheduled incremental update every {self.config.update_interval_hours} hours")
    
    async def run_full_update(self) -> BatchCrawlResult:
        """运行全量更新"""
        logger.info("Starting full update task")
        
        task = CrawlTask(
            task_type=TaskType.FULL_UPDATE.value,
            status=TaskStatus.RUNNING.value,
            priority=10,
        )
        task_id = self.database.create_crawl_task(task)
        
        progress = TaskProgress(task_id=task_id, started_at=datetime.now())
        self._running_tasks[task_id] = progress
        
        checkpoint = CheckpointManager(task_id)
        checkpoint_data = checkpoint.load()
        
        try:
            journals = self._get_journals_to_update(checkpoint_data)
            progress.total = len(journals)
            
            results = []
            batch_size = self.config.batch_size
            
            for i in range(0, len(journals), batch_size):
                batch = journals[i:i + batch_size]
                
                if self.crawler:
                    batch_results = await self.crawler.fetch_impact_factors_batch(
                        batch,
                        concurrency=self.config.max_workers,
                    )
                else:
                    batch_results = [
                        CrawlResult(
                            success=False,
                            journal_name=j,
                            source=None,
                            error_message="No crawler configured",
                        )
                        for j in batch
                    ]
                
                results.extend(batch_results)
                
                progress.processed += len(batch)
                progress.success += sum(1 for r in batch_results if r.success)
                progress.failed += sum(1 for r in batch_results if not r.success)
                
                checkpoint.save({
                    "processed": progress.processed,
                    "last_batch": batch[-1] if batch else None,
                })
                
                self.database.update_crawl_task(
                    task_id,
                    records_processed=progress.processed,
                    records_success=progress.success,
                    records_failed=progress.failed,
                )
                
                logger.info(
                    f"Full update progress: {progress.progress_percent:.1f}% "
                    f"({progress.processed}/{progress.total})"
                )
            
            checkpoint.clear()
            
            self.database.update_crawl_task(
                task_id,
                status=TaskStatus.COMPLETED.value,
                completed_at=datetime.now(),
            )
            
            logger.info(f"Full update completed: {progress.success} success, {progress.failed} failed")
            
            return BatchCrawlResult(
                total=progress.total,
                success=progress.success,
                failed=progress.failed,
                cached=0,
                results=results,
                start_time=progress.started_at,
                end_time=datetime.now(),
            )
            
        except Exception as e:
            logger.error(f"Full update failed: {e}")
            
            self.database.update_crawl_task(
                task_id,
                status=TaskStatus.FAILED.value,
                error_message=str(e),
            )
            
            return BatchCrawlResult(
                total=progress.total,
                success=progress.success,
                failed=progress.failed,
                results=[],
                start_time=progress.started_at,
                end_time=datetime.now(),
            )
        
        finally:
            if task_id in self._running_tasks:
                del self._running_tasks[task_id]
    
    async def run_incremental_update(self) -> BatchCrawlResult:
        """运行增量更新"""
        logger.info("Starting incremental update task")
        
        task = CrawlTask(
            task_type=TaskType.INCREMENTAL_UPDATE.value,
            status=TaskStatus.RUNNING.value,
            priority=5,
        )
        task_id = self.database.create_crawl_task(task)
        
        try:
            threshold = datetime.now() - timedelta(days=self.config.incremental_threshold_days)
            
            journals = self._get_stale_journals(threshold)
            
            if not journals:
                logger.info("No stale journals to update")
                return BatchCrawlResult()
            
            progress = TaskProgress(
                task_id=task_id,
                total=len(journals),
                started_at=datetime.now(),
            )
            self._running_tasks[task_id] = progress
            
            if self.crawler:
                results = await self.crawler.fetch_impact_factors_batch(
                    journals,
                    concurrency=self.config.max_workers,
                )
            else:
                results = []
            
            progress.success = sum(1 for r in results if r.success)
            progress.failed = sum(1 for r in results if not r.success)
            
            self.database.update_crawl_task(
                task_id,
                status=TaskStatus.COMPLETED.value,
                records_processed=len(journals),
                records_success=progress.success,
                records_failed=progress.failed,
                completed_at=datetime.now(),
            )
            
            logger.info(f"Incremental update completed: {progress.success} success")
            
            return BatchCrawlResult(
                total=len(journals),
                success=progress.success,
                failed=progress.failed,
                results=results,
                start_time=progress.started_at,
                end_time=datetime.now(),
            )
            
        except Exception as e:
            logger.error(f"Incremental update failed: {e}")
            
            self.database.update_crawl_task(
                task_id,
                status=TaskStatus.FAILED.value,
                error_message=str(e),
            )
            
            return BatchCrawlResult()
        
        finally:
            if task_id in self._running_tasks:
                del self._running_tasks[task_id]
    
    async def run_single_journal(self, journal_name: str) -> CrawlResult:
        """运行单期刊更新"""
        task = CrawlTask(
            task_type=TaskType.SINGLE_JOURNAL.value,
            target_journal=journal_name,
            status=TaskStatus.RUNNING.value,
            priority=8,
        )
        task_id = self.database.create_crawl_task(task)
        
        try:
            if self.crawler:
                result = await self.crawler.fetch_impact_factor(journal_name)
            else:
                result = CrawlResult(
                    success=False,
                    journal_name=journal_name,
                    source=None,
                    error_message="No crawler configured",
                )
            
            self.database.update_crawl_task(
                task_id,
                status=TaskStatus.COMPLETED.value,
                records_processed=1,
                records_success=1 if result.success else 0,
                records_failed=0 if result.success else 1,
                completed_at=datetime.now(),
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Single journal update failed: {e}")
            
            self.database.update_crawl_task(
                task_id,
                status=TaskStatus.FAILED.value,
                error_message=str(e),
            )
            
            return CrawlResult(
                success=False,
                journal_name=journal_name,
                source=None,
                error_message=str(e),
            )
    
    def _get_journals_to_update(
        self,
        checkpoint_data: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """获取待更新的期刊列表"""
        stats = self.database.get_stats()
        total_journals = stats.get("total_journals", 0)
        
        if total_journals == 0:
            return self._get_default_journal_list()
        
        journals = []
        
        with self.database._get_connection() as conn:
            cursor = conn.execute(
                "SELECT canonical_name FROM journals ORDER BY id"
            )
            for row in cursor.fetchall():
                journals.append(row["canonical_name"])
        
        if checkpoint_data and checkpoint_data.get("last_batch"):
            last_batch = checkpoint_data["last_batch"]
            try:
                idx = journals.index(last_batch)
                journals = journals[idx + 1:]
            except ValueError:
                pass
        
        return journals
    
    def _get_stale_journals(self, threshold: datetime) -> List[str]:
        """获取过期期刊列表"""
        journals = []
        
        with self.database._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT j.canonical_name
                FROM journals j
                LEFT JOIN impact_factors i ON j.id = i.journal_id
                WHERE i.fetched_at IS NULL OR i.fetched_at < ?
                GROUP BY j.id
                """,
                (threshold.isoformat(),)
            )
            for row in cursor.fetchall():
                journals.append(row["canonical_name"])
        
        return journals
    
    def _get_default_journal_list(self) -> List[str]:
        """获取默认期刊列表"""
        return [
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
        ]
    
    def get_task_progress(self, task_id: int) -> Optional[TaskProgress]:
        """获取任务进度"""
        return self._running_tasks.get(task_id)
    
    def get_pending_tasks(self, limit: int = 10) -> List[CrawlTask]:
        """获取待处理任务"""
        return self.database.get_pending_tasks(limit)
    
    def register_callback(self, event: str, callback: Callable):
        """注册事件回调"""
        self._task_callbacks[event] = callback
    
    async def __aenter__(self):
        self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.stop()
