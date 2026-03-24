"""
持久化影响因子缓存系统

使用SQLite存储查询结果，支持缓存过期和批量操作
"""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List
from contextlib import contextmanager

from paperinsight.utils.journal_metadata import canonicalize_journal_title


@dataclass
class CachedImpactFactor:
    journal_name: str
    impact_factor: float
    year: Optional[int]
    source_name: str
    source_url: str
    cached_at: float
    expires_at: float


class ImpactFactorCache:
    """影响因子持久化缓存"""
    
    DEFAULT_CACHE_DIR = Path.home() / ".paperinsight"
    DEFAULT_CACHE_FILE = DEFAULT_CACHE_DIR / "impact_factor_cache.db"
    DEFAULT_EXPIRY_DAYS = 30
    
    def __init__(
        self,
        cache_file: Optional[Path] = None,
        expiry_days: int = DEFAULT_EXPIRY_DAYS,
    ):
        self.cache_file = cache_file or self.DEFAULT_CACHE_FILE
        self.expiry_days = expiry_days
        self._ensure_cache_dir()
        self._init_db()
    
    def _ensure_cache_dir(self):
        """确保缓存目录存在"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.cache_file))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_db(self):
        """初始化数据库表"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS impact_factors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_name TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    impact_factor REAL NOT NULL,
                    year INTEGER,
                    source_name TEXT NOT NULL,
                    source_url TEXT,
                    cached_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    UNIQUE(canonical_name)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_name 
                ON impact_factors(canonical_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at 
                ON impact_factors(expires_at)
            """)
            conn.commit()
    
    def get(self, journal_name: str) -> Optional[CachedImpactFactor]:
        """获取缓存的影响因子"""
        if not journal_name:
            return None
        
        canonical_name = canonicalize_journal_title(journal_name)
        if not canonical_name:
            return None
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT journal_name, impact_factor, year, source_name, 
                       source_url, cached_at, expires_at
                FROM impact_factors
                WHERE canonical_name = ? AND expires_at > ?
                LIMIT 1
                """,
                (canonical_name, time.time())
            )
            row = cursor.fetchone()
            
            if row:
                return CachedImpactFactor(
                    journal_name=row["journal_name"],
                    impact_factor=row["impact_factor"],
                    year=row["year"],
                    source_name=row["source_name"],
                    source_url=row["source_url"],
                    cached_at=row["cached_at"],
                    expires_at=row["expires_at"],
                )
        
        return None
    
    def set(
        self,
        journal_name: str,
        impact_factor: float,
        source_name: str,
        source_url: str = "",
        year: Optional[int] = None,
        expiry_days: Optional[int] = None,
    ):
        """设置缓存"""
        if not journal_name or not impact_factor:
            return
        
        canonical_name = canonicalize_journal_title(journal_name)
        if not canonical_name:
            return
        
        now = time.time()
        expiry = expiry_days or self.expiry_days
        expires_at = now + (expiry * 24 * 60 * 60)
        
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO impact_factors
                (journal_name, canonical_name, impact_factor, year, 
                 source_name, source_url, cached_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    journal_name,
                    canonical_name,
                    impact_factor,
                    year,
                    source_name,
                    source_url,
                    now,
                    expires_at,
                )
            )
            conn.commit()
    
    def get_many(self, journal_names: List[str]) -> dict[str, Optional[CachedImpactFactor]]:
        """批量获取缓存"""
        result = {}
        for journal_name in journal_names:
            result[journal_name] = self.get(journal_name)
        return result
    
    def set_many(
        self,
        entries: List[tuple[str, float, str, str, Optional[int]]],
    ):
        """批量设置缓存"""
        now = time.time()
        expires_at = now + (self.expiry_days * 24 * 60 * 60)
        
        with self._get_connection() as conn:
            for journal_name, impact_factor, source_name, source_url, year in entries:
                canonical_name = canonicalize_journal_title(journal_name)
                if not canonical_name:
                    continue
                
                conn.execute(
                    """
                    INSERT OR REPLACE INTO impact_factors
                    (journal_name, canonical_name, impact_factor, year, 
                     source_name, source_url, cached_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        journal_name,
                        canonical_name,
                        impact_factor,
                        year,
                        source_name,
                        source_url,
                        now,
                        expires_at,
                    )
                )
            conn.commit()
    
    def clear_expired(self) -> int:
        """清除过期缓存"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM impact_factors WHERE expires_at <= ?",
                (time.time(),)
            )
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
    
    def clear_all(self) -> int:
        """清除所有缓存"""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM impact_factors")
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
    
    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END) as valid,
                    SUM(CASE WHEN expires_at <= ? THEN 1 ELSE 0 END) as expired
                FROM impact_factors
                """,
                (time.time(), time.time())
            )
            row = cursor.fetchone()
            
            return {
                "total": row["total"] or 0,
                "valid": row["valid"] or 0,
                "expired": row["expired"] or 0,
                "cache_file": str(self.cache_file),
                "expiry_days": self.expiry_days,
            }
    
    def preload_from_dict(self, cache_dict: dict[str, float]):
        """从字典预加载缓存"""
        entries = [
            (name, value, "PRELOADED", "", None)
            for name, value in cache_dict.items()
            if value is not None  # 跳过None值
        ]
        self.set_many(entries)
