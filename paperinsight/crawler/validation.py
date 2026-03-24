"""
数据清洗与验证模块

实现影响因子数据的清洗、验证和交叉验证机制。
"""

import re
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from paperinsight.crawler.storage.models import (
    CrawlResult,
    ImpactFactorRecord,
    JournalRecord,
    DataSourceType,
    DataQuality,
)
from paperinsight.utils.journal_metadata import canonicalize_journal_title, normalize_issn

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    quality: DataQuality
    confidence_score: float
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


class IFRangeValidator:
    """影响因子范围验证器"""
    
    IF_RANGES: Dict[str, Tuple[float, float]] = {
        "Nature": (40.0, 80.0),
        "Science": (40.0, 70.0),
        "Cell": (40.0, 70.0),
        "Nature Communications": (10.0, 20.0),
        "Advanced Materials": (25.0, 40.0),
        "JACS": (10.0, 20.0),
        "Angewandte Chemie": (10.0, 20.0),
        "Nano Letters": (8.0, 15.0),
        "ACS Nano": (10.0, 20.0),
        "Small": (10.0, 18.0),
    }
    
    DEFAULT_MIN_IF = 0.01
    DEFAULT_MAX_IF = 500.0
    
    @classmethod
    def validate(cls, journal_name: str, if_value: float) -> Tuple[bool, Optional[str]]:
        """验证影响因子是否在合理范围内"""
        if not isinstance(if_value, (int, float)):
            return False, "IF value is not a number"
        
        if if_value < cls.DEFAULT_MIN_IF:
            return False, f"IF value {if_value} is below minimum {cls.DEFAULT_MIN_IF}"
        
        if if_value > cls.DEFAULT_MAX_IF:
            return False, f"IF value {if_value} exceeds maximum {cls.DEFAULT_MAX_IF}"
        
        canonical = canonicalize_journal_title(journal_name)
        
        for known_journal, (min_if, max_if) in cls.IF_RANGES.items():
            if canonical == canonicalize_journal_title(known_journal):
                if min_if <= if_value <= max_if:
                    return True, None
                else:
                    return True, f"IF {if_value} outside expected range [{min_if}, {max_if}] for {known_journal}"
        
        return True, None


class YearValidator:
    """年份验证器"""
    
    @classmethod
    def validate(cls, if_year: int) -> Tuple[bool, Optional[str]]:
        """验证影响因子年份"""
        current_year = datetime.now().year
        
        if if_year < 1990:
            return False, f"IF year {if_year} is too old (before 1990)"
        
        if if_year > current_year:
            return False, f"IF year {if_year} is in the future"
        
        if if_year < current_year - 3:
            return True, f"IF year {if_year} is outdated (more than 3 years old)"
        
        return True, None


class SourceReliabilityScorer:
    """数据源可靠性评分器"""
    
    SOURCE_SCORES: Dict[DataSourceType, float] = {
        DataSourceType.WOS: 0.98,
        DataSourceType.MJL: 0.95,
        DataSourceType.LETPUB: 0.85,
        DataSourceType.CROSSREF: 0.70,
        DataSourceType.PUBMED: 0.75,
        DataSourceType.AI_MODEL: 0.60,
        DataSourceType.LOCAL: 0.90,
        DataSourceType.MANUAL: 1.00,
    }
    
    @classmethod
    def get_score(cls, source: DataSourceType) -> float:
        """获取数据源可靠性评分"""
        return cls.SOURCE_SCORES.get(source, 0.5)


class DataCleaner:
    """数据清洗器"""
    
    JOURNAL_NAME_PATTERNS = [
        (r"\s*[\[\(].*?[\]\)]\s*$", ""),
        (r"\s*[:：]\s*$", ""),
        (r"^\s*The\s+", ""),
        (r"\s+", " "),
    ]
    
    @classmethod
    def clean_journal_name(cls, name: str) -> str:
        """清洗期刊名称"""
        if not name:
            return ""
        
        cleaned = name.strip()
        
        for pattern, replacement in cls.JOURNAL_NAME_PATTERNS:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        
        return cleaned.strip()
    
    @classmethod
    def clean_if_value(cls, value: Any) -> Optional[float]:
        """清洗影响因子值"""
        if value is None:
            return None
        
        if isinstance(value, (int, float)):
            return round(float(value), 3)
        
        if isinstance(value, str):
            match = re.search(r"([\d.]+)", value.replace(",", "."))
            if match:
                try:
                    return round(float(match.group(1)), 3)
                except ValueError:
                    return None
        
        return None
    
    @classmethod
    def clean_issn(cls, issn: str) -> Optional[str]:
        """清洗 ISSN"""
        return normalize_issn(issn)


class CrossValidator:
    """交叉验证器"""
    
    MAX_IF_DIFFERENCE_RATIO = 0.3
    
    @classmethod
    def validate(
        cls,
        results: List[CrawlResult],
        journal_name: str,
    ) -> ValidationResult:
        """交叉验证多个数据源的结果"""
        if not results:
            return ValidationResult(
                is_valid=False,
                quality=DataQuality.UNVERIFIED,
                confidence_score=0.0,
                issues=["No results to validate"],
            )
        
        successful_results = [r for r in results if r.success and r.impact_factor is not None]
        
        if not successful_results:
            return ValidationResult(
                is_valid=False,
                quality=DataQuality.UNVERIFIED,
                confidence_score=0.0,
                issues=["No successful results with IF values"],
            )
        
        if_values = [r.impact_factor for r in successful_results]
        sources = [r.source for r in successful_results]
        
        avg_if = sum(if_values) / len(if_values)
        
        max_diff = max(abs(v - avg_if) / avg_if for v in if_values) if avg_if > 0 else 0
        
        issues = []
        
        if max_diff > cls.MAX_IF_DIFFERENCE_RATIO:
            issues.append(
                f"Large discrepancy between sources: {if_values} "
                f"(max diff: {max_diff:.1%})"
            )
        
        range_valid, range_issue = IFRangeValidator.validate(journal_name, avg_if)
        if range_issue:
            issues.append(range_issue)
        
        source_scores = [SourceReliabilityScorer.get_score(s) for s in sources]
        avg_source_score = sum(source_scores) / len(source_scores)
        
        confidence = avg_source_score * (1 - max_diff) if max_diff < 1 else avg_source_score * 0.5
        
        if len(sources) >= 3 and max_diff < 0.1:
            quality = DataQuality.VERIFIED
        elif len(sources) >= 2 and max_diff < 0.2:
            quality = DataQuality.HIGH
        elif max_diff < 0.3:
            quality = DataQuality.MEDIUM
        else:
            quality = DataQuality.LOW
        
        if issues:
            quality = DataQuality(quality.value)
        
        return ValidationResult(
            is_valid=range_valid,
            quality=quality,
            confidence_score=round(confidence, 3),
            issues=issues,
        )


class DataValidator:
    """数据验证器主类"""
    
    @classmethod
    def validate_result(
        cls,
        result: CrawlResult,
        existing_records: Optional[List[ImpactFactorRecord]] = None,
    ) -> ValidationResult:
        """验证单个爬取结果"""
        issues = []
        suggestions = []
        
        if not result.success:
            return ValidationResult(
                is_valid=False,
                quality=DataQuality.UNVERIFIED,
                confidence_score=0.0,
                issues=[result.error_message or "Unknown error"],
            )
        
        if result.impact_factor is None:
            return ValidationResult(
                is_valid=False,
                quality=DataQuality.UNVERIFIED,
                confidence_score=0.0,
                issues=["No impact factor value"],
            )
        
        range_valid, range_issue = IFRangeValidator.validate(
            result.journal_name, result.impact_factor
        )
        if range_issue:
            issues.append(range_issue)
        
        if result.if_year:
            year_valid, year_issue = YearValidator.validate(result.if_year)
            if year_issue:
                issues.append(year_issue)
        
        source_score = SourceReliabilityScorer.get_score(result.source)
        confidence = result.confidence_score * source_score
        
        if existing_records:
            same_year_records = [
                r for r in existing_records
                if r.if_year == result.if_year
            ]
            if same_year_records:
                existing_if = same_year_records[0].if_value
                diff_ratio = abs(result.impact_factor - existing_if) / existing_if
                if diff_ratio > 0.5:
                    issues.append(
                        f"Large difference from existing record: "
                        f"{result.impact_factor} vs {existing_if} ({diff_ratio:.1%})"
                    )
                    confidence *= 0.7
        
        if not issues:
            quality = DataQuality.HIGH
        elif len(issues) == 1 and range_issue:
            quality = DataQuality.MEDIUM
        else:
            quality = DataQuality.LOW
        
        return ValidationResult(
            is_valid=True,
            quality=quality,
            confidence_score=round(confidence, 3),
            issues=issues,
            suggestions=suggestions,
        )
    
    @classmethod
    def validate_and_clean(
        cls,
        result: CrawlResult,
    ) -> Tuple[CrawlResult, ValidationResult]:
        """验证并清洗结果"""
        cleaned_result = CrawlResult(
            success=result.success,
            journal_name=DataCleaner.clean_journal_name(result.journal_name),
            impact_factor=DataCleaner.clean_if_value(result.impact_factor),
            if_year=result.if_year,
            source=result.source,
            source_url=result.source_url,
            confidence_score=result.confidence_score,
            issn=DataCleaner.clean_issn(result.issn) if result.issn else None,
            eissn=DataCleaner.clean_issn(result.eissn) if result.eissn else None,
            publisher=result.publisher,
            error_message=result.error_message,
            processing_time=result.processing_time,
        )
        
        validation = cls.validate_result(cleaned_result)
        
        cleaned_result.confidence_score = validation.confidence_score
        
        return cleaned_result, validation


class DuplicateDetector:
    """重复数据检测器"""
    
    @classmethod
    def detect(
        cls,
        new_record: ImpactFactorRecord,
        existing_records: List[ImpactFactorRecord],
    ) -> Optional[ImpactFactorRecord]:
        """检测重复记录"""
        for existing in existing_records:
            if (existing.journal_id == new_record.journal_id and
                existing.if_year == new_record.if_year and
                existing.source == new_record.source):
                return existing
        
        return None
    
    @classmethod
    def merge(
        cls,
        new_record: ImpactFactorRecord,
        existing_record: ImpactFactorRecord,
    ) -> ImpactFactorRecord:
        """合并重复记录"""
        if new_record.confidence_score > existing_record.confidence_score:
            base = new_record
            other = existing_record
        else:
            base = existing_record
            other = new_record
        
        return ImpactFactorRecord(
            journal_id=base.journal_id,
            if_value=base.if_value,
            if_year=base.if_year,
            source=base.source,
            source_url=base.source_url or other.source_url,
            confidence_score=max(base.confidence_score, other.confidence_score),
            quality=DataQuality.VERIFIED if base.quality == DataQuality.VERIFIED or other.quality == DataQuality.VERIFIED else base.quality,
            jcr_quartile=base.jcr_quartile or other.jcr_quartile,
            jcr_category=base.jcr_category or other.jcr_category,
            category_rank=base.category_rank or other.category_rank,
            verified=base.verified or other.verified,
            verified_at=base.verified_at or other.verified_at,
            verified_by=base.verified_by or other.verified_by,
            fetched_at=datetime.now(),
        )
