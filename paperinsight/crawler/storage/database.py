"""
影响因子数据库层

基于 SQLite 的高性能数据存储层，支持全文搜索、批量操作和数据迁移。
"""

import sqlite3
import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
from dataclasses import dataclass

from paperinsight.crawler.storage.models import (
    JournalRecord,
    ImpactFactorRecord,
    JournalAlias,
    JournalCategory,
    CrawlTask,
    DataSourceType,
    DataQuality,
)
from paperinsight.crawler.config import StorageConfig
from paperinsight.utils.journal_metadata import canonicalize_journal_title, normalize_issn

logger = logging.getLogger(__name__)


class ImpactFactorDatabase:
    """影响因子数据库管理器"""
    
    SCHEMA_VERSION = 2
    
    def __init__(self, config: Optional[StorageConfig] = None):
        self.config = config or StorageConfig()
        self.db_path = Path(self.config.database_path)
        self._ensure_db_dir()
        self._init_schema()
    
    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_schema(self):
        """初始化数据库模式"""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS journals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL UNIQUE,
                    issn TEXT UNIQUE,
                    eissn TEXT UNIQUE,
                    publisher TEXT,
                    country TEXT,
                    language TEXT,
                    homepage TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS impact_factors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_id INTEGER NOT NULL,
                    if_value REAL NOT NULL,
                    if_year INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    source_url TEXT,
                    confidence_score REAL DEFAULT 1.0,
                    quality TEXT DEFAULT 'unverified',
                    jcr_quartile TEXT,
                    jcr_category TEXT,
                    category_rank INTEGER,
                    verified INTEGER DEFAULT 0,
                    verified_at TIMESTAMP,
                    verified_by TEXT,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (journal_id) REFERENCES journals(id) ON DELETE CASCADE,
                    UNIQUE(journal_id, if_year, source)
                );
                
                CREATE TABLE IF NOT EXISTS journal_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_id INTEGER NOT NULL,
                    alias_name TEXT NOT NULL,
                    alias_type TEXT DEFAULT 'alternate',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (journal_id) REFERENCES journals(id) ON DELETE CASCADE,
                    UNIQUE(journal_id, alias_name)
                );
                
                CREATE TABLE IF NOT EXISTS journal_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_id INTEGER NOT NULL,
                    category_name TEXT NOT NULL,
                    category_rank INTEGER,
                    quartile TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (journal_id) REFERENCES journals(id) ON DELETE CASCADE
                );
                
                CREATE TABLE IF NOT EXISTS crawl_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT NOT NULL,
                    target_url TEXT,
                    target_journal TEXT,
                    status TEXT DEFAULT 'pending',
                    priority INTEGER DEFAULT 5,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    records_processed INTEGER DEFAULT 0,
                    records_success INTEGER DEFAULT 0,
                    records_failed INTEGER DEFAULT 0,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_journals_issn ON journals(issn);
                CREATE INDEX IF NOT EXISTS idx_journals_eissn ON journals(eissn);
                CREATE INDEX IF NOT EXISTS idx_journals_name ON journals(canonical_name);
                
                CREATE INDEX IF NOT EXISTS idx_if_journal_year ON impact_factors(journal_id, if_year);
                CREATE INDEX IF NOT EXISTS idx_if_year ON impact_factors(if_year);
                CREATE INDEX IF NOT EXISTS idx_if_source ON impact_factors(source);
                CREATE INDEX IF NOT EXISTS idx_if_value ON impact_factors(if_value);
                
                CREATE INDEX IF NOT EXISTS idx_aliases_name ON journal_aliases(alias_name);
                CREATE INDEX IF NOT EXISTS idx_aliases_journal ON journal_aliases(journal_id);
                
                CREATE INDEX IF NOT EXISTS idx_categories_name ON journal_categories(category_name);
                CREATE INDEX IF NOT EXISTS idx_categories_journal ON journal_categories(journal_id);
                
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON crawl_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_type ON crawl_tasks(task_type);
            """)
            
            if self.config.enable_fts:
                conn.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS journals_fts USING fts5(
                        canonical_name,
                        publisher,
                        content='journals',
                        content_rowid='id'
                    );
                    
                    CREATE TRIGGER IF NOT EXISTS journals_ai AFTER INSERT ON journals BEGIN
                        INSERT INTO journals_fts(rowid, canonical_name, publisher)
                        VALUES (new.id, new.canonical_name, new.publisher);
                    END;
                    
                    CREATE TRIGGER IF NOT EXISTS journals_ad AFTER DELETE ON journals BEGIN
                        INSERT INTO journals_fts(journals_fts, rowid, canonical_name, publisher)
                        VALUES('delete', old.id, old.canonical_name, old.publisher);
                    END;
                    
                    CREATE TRIGGER IF NOT EXISTS journals_au AFTER UPDATE ON journals BEGIN
                        INSERT INTO journals_fts(journals_fts, rowid, canonical_name, publisher)
                        VALUES('delete', old.id, old.canonical_name, old.publisher);
                        INSERT INTO journals_fts(rowid, canonical_name, publisher)
                        VALUES (new.id, new.canonical_name, new.publisher);
                    END;
                """)
            
            cursor = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            current_version = row["version"] if row else 0
            
            if current_version < self.SCHEMA_VERSION:
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                    (self.SCHEMA_VERSION,)
                )
            
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
    
    def get_journal_by_name(self, name: str) -> Optional[JournalRecord]:
        """根据期刊名称获取期刊记录"""
        canonical = canonicalize_journal_title(name)
        if not canonical:
            return None
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM journals WHERE canonical_name = ?",
                (canonical,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_journal(row)
        return None
    
    def get_journal_by_issn(self, issn: str) -> Optional[JournalRecord]:
        """根据 ISSN 获取期刊记录"""
        normalized = normalize_issn(issn)
        if not normalized:
            return None
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM journals WHERE issn = ? OR eissn = ?",
                (normalized, normalized)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_journal(row)
        return None
    
    def get_journal_by_alias(self, alias: str) -> Optional[JournalRecord]:
        """根据别名获取期刊记录"""
        canonical = canonicalize_journal_title(alias)
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT j.* FROM journals j
                JOIN journal_aliases a ON j.id = a.journal_id
                WHERE a.alias_name = ?
                """,
                (canonical,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_journal(row)
        return None
    
    def upsert_journal(self, journal: JournalRecord) -> int:
        """插入或更新期刊记录"""
        with self._get_connection() as conn:
            now = datetime.now()
            
            cursor = conn.execute(
                """
                INSERT INTO journals (canonical_name, issn, eissn, publisher, country, language, homepage, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_name) DO UPDATE SET
                    issn = COALESCE(excluded.issn, journals.issn),
                    eissn = COALESCE(excluded.eissn, journals.eissn),
                    publisher = COALESCE(excluded.publisher, journals.publisher),
                    country = COALESCE(excluded.country, journals.country),
                    language = COALESCE(excluded.language, journals.language),
                    homepage = COALESCE(excluded.homepage, journals.homepage),
                    updated_at = ?
                RETURNING id
                """,
                (
                    journal.canonical_name,
                    journal.issn,
                    journal.eissn,
                    journal.publisher,
                    journal.country,
                    journal.language,
                    journal.homepage,
                    now,
                    now,
                    now,
                )
            )
            row = cursor.fetchone()
            conn.commit()
            return row["id"]
    
    def get_impact_factor(
        self,
        journal_id: int,
        if_year: Optional[int] = None,
    ) -> Optional[ImpactFactorRecord]:
        """获取期刊的影响因子"""
        with self._get_connection() as conn:
            if if_year:
                cursor = conn.execute(
                    """
                    SELECT * FROM impact_factors
                    WHERE journal_id = ? AND if_year = ?
                    ORDER BY confidence_score DESC, fetched_at DESC
                    LIMIT 1
                    """,
                    (journal_id, if_year)
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM impact_factors
                    WHERE journal_id = ?
                    ORDER BY if_year DESC, confidence_score DESC
                    LIMIT 1
                    """,
                    (journal_id,)
                )
            row = cursor.fetchone()
            if row:
                return self._row_to_if_record(row)
        return None
    
    def get_impact_factors_by_journal(self, journal_id: int) -> List[ImpactFactorRecord]:
        """获取期刊的所有影响因子记录"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM impact_factors
                WHERE journal_id = ?
                ORDER BY if_year DESC, confidence_score DESC
                """,
                (journal_id,)
            )
            return [self._row_to_if_record(row) for row in cursor.fetchall()]
    
    def upsert_impact_factor(self, if_record: ImpactFactorRecord) -> int:
        """插入或更新影响因子记录"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO impact_factors (
                    journal_id, if_value, if_year, source, source_url,
                    confidence_score, quality, jcr_quartile, jcr_category,
                    category_rank, verified, verified_at, verified_by, fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(journal_id, if_year, source) DO UPDATE SET
                    if_value = excluded.if_value,
                    source_url = COALESCE(excluded.source_url, impact_factors.source_url),
                    confidence_score = MAX(excluded.confidence_score, impact_factors.confidence_score),
                    quality = CASE
                        WHEN excluded.quality = 'verified' THEN 'verified'
                        WHEN impact_factors.quality = 'verified' THEN 'verified'
                        ELSE excluded.quality
                    END,
                    jcr_quartile = COALESCE(excluded.jcr_quartile, impact_factors.jcr_quartile),
                    jcr_category = COALESCE(excluded.jcr_category, impact_factors.jcr_category),
                    category_rank = COALESCE(excluded.category_rank, impact_factors.category_rank),
                    fetched_at = excluded.fetched_at
                RETURNING id
                """,
                (
                    if_record.journal_id,
                    if_record.if_value,
                    if_record.if_year,
                    if_record.source.value,
                    if_record.source_url,
                    if_record.confidence_score,
                    if_record.quality.value,
                    if_record.jcr_quartile,
                    if_record.jcr_category,
                    if_record.category_rank,
                    1 if if_record.verified else 0,
                    if_record.verified_at,
                    if_record.verified_by,
                    if_record.fetched_at,
                )
            )
            row = cursor.fetchone()
            conn.commit()
            return row["id"]
    
    def add_journal_alias(self, journal_id: int, alias: str, alias_type: str = "alternate") -> int:
        """添加期刊别名"""
        canonical = canonicalize_journal_title(alias)
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO journal_aliases (journal_id, alias_name, alias_type)
                VALUES (?, ?, ?)
                RETURNING id
                """,
                (journal_id, canonical, alias_type)
            )
            row = cursor.fetchone()
            conn.commit()
            return row["id"] if row else 0
    
    def search_journals(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[JournalRecord]:
        """搜索期刊（支持全文搜索）"""
        with self._get_connection() as conn:
            if self.config.enable_fts:
                cursor = conn.execute(
                    """
                    SELECT j.* FROM journals j
                    JOIN journals_fts fts ON j.id = fts.rowid
                    WHERE journals_fts MATCH ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                    """,
                    (query, limit, offset)
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM journals
                    WHERE canonical_name LIKE ?
                    ORDER BY canonical_name
                    LIMIT ? OFFSET ?
                    """,
                    (f"%{query}%", limit, offset)
                )
            return [self._row_to_journal(row) for row in cursor.fetchall()]
    
    def get_journals_by_category(
        self,
        category: str,
        limit: int = 100,
    ) -> List[Tuple[JournalRecord, Optional[ImpactFactorRecord]]]:
        """根据学科分类获取期刊列表"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT j.*, 
                       i.if_value, i.if_year, i.source, i.confidence_score
                FROM journals j
                JOIN journal_categories c ON j.id = c.journal_id
                LEFT JOIN impact_factors i ON j.id = i.journal_id
                    AND i.if_year = (SELECT MAX(if_year) FROM impact_factors WHERE journal_id = j.id)
                WHERE c.category_name = ?
                ORDER BY i.if_value DESC NULLS LAST
                LIMIT ?
                """,
                (category, limit)
            )
            results = []
            for row in cursor.fetchall():
                journal = self._row_to_journal(row)
                if_record = None
                if row["if_value"]:
                    if_record = ImpactFactorRecord(
                        journal_id=journal.id,
                        if_value=row["if_value"],
                        if_year=row["if_year"],
                        source=DataSourceType(row["source"]),
                        confidence_score=row["confidence_score"],
                    )
                results.append((journal, if_record))
            return results
    
    def create_crawl_task(self, task: CrawlTask) -> int:
        """创建爬取任务"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO crawl_tasks (
                    task_type, target_url, target_journal, status, priority, created_at, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    task.task_type,
                    task.target_url,
                    task.target_journal,
                    task.status,
                    task.priority,
                    datetime.now(),
                    task.created_by,
                )
            )
            row = cursor.fetchone()
            conn.commit()
            return row["id"]
    
    def update_crawl_task(self, task_id: int, **kwargs) -> bool:
        """更新爬取任务状态"""
        allowed_fields = {
            "status", "started_at", "completed_at",
            "records_processed", "records_success", "records_failed",
            "error_message", "retry_count"
        }
        
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not updates:
            return False
        
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [task_id]
        
        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE crawl_tasks SET {set_clause} WHERE id = ?",
                values
            )
            conn.commit()
            return True
    
    def get_pending_tasks(self, limit: int = 100) -> List[CrawlTask]:
        """获取待处理的爬取任务"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM crawl_tasks
                WHERE status = 'pending'
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
                """,
                (limit,)
            )
            return [self._row_to_task(row) for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        with self._get_connection() as conn:
            stats = {}
            
            cursor = conn.execute("SELECT COUNT(*) as count FROM journals")
            stats["total_journals"] = cursor.fetchone()["count"]
            
            cursor = conn.execute("SELECT COUNT(*) as count FROM impact_factors")
            stats["total_if_records"] = cursor.fetchone()["count"]
            
            cursor = conn.execute(
                "SELECT if_year, COUNT(*) as count FROM impact_factors GROUP BY if_year ORDER BY if_year DESC"
            )
            stats["if_by_year"] = {row["if_year"]: row["count"] for row in cursor.fetchall()}
            
            cursor = conn.execute(
                "SELECT source, COUNT(*) as count FROM impact_factors GROUP BY source"
            )
            stats["if_by_source"] = {row["source"]: row["count"] for row in cursor.fetchall()}
            
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM impact_factors WHERE quality = 'verified'"
            )
            stats["verified_records"] = cursor.fetchone()["count"]
            
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM journal_aliases"
            )
            stats["total_aliases"] = cursor.fetchone()["count"]
            
            return stats
    
    def backup(self, backup_path: Optional[Path] = None) -> Path:
        """备份数据库"""
        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.db_path.parent / f"impact_factor_backup_{timestamp}.db"
        
        shutil.copy2(self.db_path, backup_path)
        logger.info(f"Database backed up to {backup_path}")
        return backup_path
    
    def vacuum(self):
        """清理数据库碎片"""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
            conn.commit()
        logger.info("Database vacuumed")
    
    def _row_to_journal(self, row: sqlite3.Row) -> JournalRecord:
        """将数据库行转换为 JournalRecord"""
        return JournalRecord(
            id=row["id"],
            canonical_name=row["canonical_name"],
            issn=row["issn"],
            eissn=row["eissn"],
            publisher=row["publisher"],
            country=row["country"],
            language=row["language"],
            homepage=row["homepage"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )
    
    def _row_to_if_record(self, row: sqlite3.Row) -> ImpactFactorRecord:
        """将数据库行转换为 ImpactFactorRecord"""
        return ImpactFactorRecord(
            id=row["id"],
            journal_id=row["journal_id"],
            if_value=row["if_value"],
            if_year=row["if_year"],
            source=DataSourceType(row["source"]),
            source_url=row["source_url"],
            confidence_score=row["confidence_score"],
            quality=DataQuality(row["quality"]),
            jcr_quartile=row["jcr_quartile"],
            jcr_category=row["jcr_category"],
            category_rank=row["category_rank"],
            verified=bool(row["verified"]),
            verified_at=self._parse_datetime(row["verified_at"]),
            verified_by=row["verified_by"],
            fetched_at=self._parse_datetime(row["fetched_at"]) or datetime.now(),
        )
    
    def _row_to_task(self, row: sqlite3.Row) -> CrawlTask:
        """将数据库行转换为 CrawlTask"""
        return CrawlTask(
            id=row["id"],
            task_type=row["task_type"],
            target_url=row["target_url"],
            target_journal=row["target_journal"],
            status=row["status"],
            priority=row["priority"],
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
            records_processed=row["records_processed"],
            records_success=row["records_success"],
            records_failed=row["records_failed"],
            error_message=row["error_message"],
            retry_count=row["retry_count"],
            created_at=self._parse_datetime(row["created_at"]),
            created_by=row["created_by"],
        )
    
    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        """解析日期时间字符串"""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
