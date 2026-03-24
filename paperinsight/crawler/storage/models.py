"""
数据存储模型

定义期刊和影响因子的数据模型，使用 Pydantic 进行数据验证。
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict
from enum import Enum


class DataSourceType(str, Enum):
    """数据源类型"""
    LETPUB = "letpub"
    MJL = "mjl"
    WOS = "wos"
    CROSSREF = "crossref"
    PUBMED = "pubmed"
    AI_MODEL = "ai_model"
    LOCAL = "local"
    MANUAL = "manual"


class DataQuality(str, Enum):
    """数据质量等级"""
    VERIFIED = "verified"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNVERIFIED = "unverified"


class JournalRecord(BaseModel):
    """期刊记录模型"""
    
    model_config = ConfigDict(extra='forbid')
    
    id: Optional[int] = Field(default=None, description="数据库主键")
    canonical_name: str = Field(..., description="期刊标准名称")
    issn: Optional[str] = Field(default=None, description="印刷版 ISSN")
    eissn: Optional[str] = Field(default=None, description="电子版 ISSN")
    publisher: Optional[str] = Field(default=None, description="出版社")
    country: Optional[str] = Field(default=None, description="出版国家")
    language: Optional[str] = Field(default=None, description="出版语言")
    homepage: Optional[str] = Field(default=None, description="期刊主页")
    
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    updated_at: Optional[datetime] = Field(default=None, description="更新时间")
    
    @field_validator('issn', 'eissn')
    @classmethod
    def validate_issn(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        if len(v) == 8:
            v = f"{v[:4]}-{v[4:]}"
        if len(v) == 9 and v[4] == '-':
            return v
        return None


class ImpactFactorRecord(BaseModel):
    """影响因子记录模型"""
    
    model_config = ConfigDict(extra='forbid')
    
    id: Optional[int] = Field(default=None, description="数据库主键")
    journal_id: int = Field(..., description="期刊 ID")
    if_value: float = Field(..., ge=0, le=500, description="影响因子数值")
    if_year: int = Field(..., ge=1900, le=2100, description="影响因子年份")
    
    source: DataSourceType = Field(..., description="数据来源")
    source_url: Optional[str] = Field(default=None, description="来源 URL")
    confidence_score: float = Field(default=1.0, ge=0, le=1, description="置信度评分")
    quality: DataQuality = Field(default=DataQuality.UNVERIFIED, description="数据质量等级")
    
    jcr_quartile: Optional[str] = Field(default=None, description="JCR 分区")
    jcr_category: Optional[str] = Field(default=None, description="JCR 学科分类")
    category_rank: Optional[int] = Field(default=None, description="学科排名")
    
    verified: bool = Field(default=False, description="是否已验证")
    verified_at: Optional[datetime] = Field(default=None, description="验证时间")
    verified_by: Optional[str] = Field(default=None, description="验证者")
    
    fetched_at: datetime = Field(default_factory=datetime.now, description="抓取时间")
    
    @field_validator('if_value')
    @classmethod
    def validate_if_value(cls, v: float) -> float:
        return round(v, 3)


class JournalAlias(BaseModel):
    """期刊别名模型"""
    
    model_config = ConfigDict(extra='forbid')
    
    id: Optional[int] = Field(default=None)
    journal_id: int = Field(..., description="期刊 ID")
    alias_name: str = Field(..., description="别名")
    alias_type: str = Field(default="alternate", description="别名类型")
    
    created_at: Optional[datetime] = Field(default=None)


class JournalCategory(BaseModel):
    """期刊学科分类模型"""
    
    model_config = ConfigDict(extra='forbid')
    
    id: Optional[int] = Field(default=None)
    journal_id: int = Field(..., description="期刊 ID")
    category_name: str = Field(..., description="学科分类名称")
    category_rank: Optional[int] = Field(default=None, description="学科排名")
    quartile: Optional[str] = Field(default=None, description="分区")
    
    created_at: Optional[datetime] = Field(default=None)


class CrawlTask(BaseModel):
    """爬取任务模型"""
    
    model_config = ConfigDict(extra='forbid')
    
    id: Optional[int] = Field(default=None)
    task_type: str = Field(..., description="任务类型")
    target_url: Optional[str] = Field(default=None, description="目标 URL")
    target_journal: Optional[str] = Field(default=None, description="目标期刊")
    
    status: str = Field(default="pending", description="任务状态")
    priority: int = Field(default=5, description="优先级 (1-10)")
    
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    
    records_processed: int = Field(default=0)
    records_success: int = Field(default=0)
    records_failed: int = Field(default=0)
    
    error_message: Optional[str] = Field(default=None)
    retry_count: int = Field(default=0)
    
    created_at: Optional[datetime] = Field(default=None)
    created_by: Optional[str] = Field(default=None)


class CrawlResult(BaseModel):
    """爬取结果模型"""
    
    model_config = ConfigDict(extra='forbid')
    
    success: bool = Field(..., description="是否成功")
    journal_name: str = Field(..., description="期刊名称")
    impact_factor: Optional[float] = Field(default=None, description="影响因子")
    if_year: Optional[int] = Field(default=None, description="影响因子年份")
    
    source: DataSourceType = Field(..., description="数据来源")
    source_url: Optional[str] = Field(default=None)
    confidence_score: float = Field(default=1.0)
    
    issn: Optional[str] = Field(default=None)
    eissn: Optional[str] = Field(default=None)
    publisher: Optional[str] = Field(default=None)
    
    error_message: Optional[str] = Field(default=None)
    processing_time: Optional[float] = Field(default=None)
    
    def to_if_record(self, journal_id: int) -> Optional[ImpactFactorRecord]:
        """转换为影响因子记录"""
        if not self.success or self.impact_factor is None:
            return None
        
        return ImpactFactorRecord(
            journal_id=journal_id,
            if_value=self.impact_factor,
            if_year=self.if_year or datetime.now().year - 1,
            source=self.source,
            source_url=self.source_url,
            confidence_score=self.confidence_score,
        )


class BatchCrawlResult(BaseModel):
    """批量爬取结果模型"""
    
    model_config = ConfigDict(extra='forbid')
    
    total: int = Field(default=0, description="总数量")
    success: int = Field(default=0, description="成功数量")
    failed: int = Field(default=0, description="失败数量")
    cached: int = Field(default=0, description="缓存命中数量")
    
    results: List[CrawlResult] = Field(default_factory=list)
    
    start_time: Optional[datetime] = Field(default=None)
    end_time: Optional[datetime] = Field(default=None)
    total_time: Optional[float] = Field(default=None, description="总耗时（秒）")
    
    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.success / self.total
    
    @property
    def cache_hit_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.cached / self.total
