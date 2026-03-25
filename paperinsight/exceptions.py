"""
PaperInsight 异常体系

提供项目级统一异常基类和分类异常，替代宽泛的 except Exception。
所有业务异常均继承自 PaperInsightError 基类。
"""

from __future__ import annotations


class PaperInsightError(Exception):
    """PaperInsight 项目所有业务异常的基类。"""

    def __init__(self, message: str = "", *, recoverable: bool = False):
        super().__init__(message)
        self.message = message
        self.recoverable = recoverable


# ── 解析相关 ──────────────────────────────────────────────────────────

class ParseError(PaperInsightError):
    """PDF / 文档解析失败。"""

    def __init__(self, message: str = "PDF parsing failed", *, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable)


class MinerUParserError(ParseError):
    """MinerU 解析器调用失败。"""

    def __init__(self, message: str = "MinerU parser error", *, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable)


# ── 数据提取相关 ──────────────────────────────────────────────────────

class ExtractionError(PaperInsightError):
    """LLM / Regex 数据提取失败。"""

    def __init__(self, message: str = "Data extraction failed", *, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable)


class LLMExtractionError(ExtractionError):
    """LLM 提取调用失败（网络、超时、限流等）。"""

    def __init__(self, message: str = "LLM extraction error", *, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable)


class ValidationError(PaperInsightError):
    """Pydantic 模型校验失败或数据质量不达标。"""

    def __init__(self, message: str = "Validation failed", *, recoverable: bool = False):
        super().__init__(message, recoverable=recoverable)


# ── 影响因子相关 ──────────────────────────────────────────────────────

class IFLookupError(PaperInsightError):
    """影响因子查找失败（可恢复——通常可回退到次级来源）。"""

    def __init__(self, message: str = "IF lookup failed", *, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable)


class IFSourceError(IFLookupError):
    """特定 IF 来源调用失败。"""

    def __init__(self, source_name: str = "", message: str = "", *, recoverable: bool = True):
        full_msg = f"[{source_name}] {message}" if source_name else message
        super().__init__(full_msg, recoverable=recoverable)
        self.source_name = source_name


# ── 网络相关 ──────────────────────────────────────────────────────────

class NetworkError(PaperInsightError):
    """网络请求失败（超时、连接错误、DNS 等），通常可重试。"""

    def __init__(self, message: str = "Network request failed", *, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable)


class RateLimitError(NetworkError):
    """API 限流（429），建议等待后重试。"""

    def __init__(self, message: str = "Rate limit exceeded", *, retry_after: float = 0):
        super().__init__(message, recoverable=True)
        self.retry_after = retry_after


# ── 缓存相关 ──────────────────────────────────────────────────────────

class CacheError(PaperInsightError):
    """缓存读写失败。"""

    def __init__(self, message: str = "Cache error", *, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable)


class CacheVersionError(CacheError):
    """缓存版本不兼容，需要重新生成。"""

    def __init__(self, message: str = "Cache version mismatch", *, expected: int = 0, actual: int = 0):
        super().__init__(message, recoverable=True)
        self.expected_version = expected
        self.actual_version = actual


# ── 配置相关 ──────────────────────────────────────────────────────────

class ConfigError(PaperInsightError):
    """配置读取或校验失败。"""

    def __init__(self, message: str = "Configuration error", *, recoverable: bool = False):
        super().__init__(message, recoverable=recoverable)


# ── 报告生成相关 ──────────────────────────────────────────────────────

class ReportError(PaperInsightError):
    """报告（Excel/JSON）生成失败。"""

    def __init__(self, message: str = "Report generation failed", *, recoverable: bool = False):
        super().__init__(message, recoverable=recoverable)


# ── 工具函数 ──────────────────────────────────────────────────────────

def is_recoverable(exc: BaseException) -> bool:
    """判断异常是否可恢复（可重试或跳过继续处理）。"""
    if isinstance(exc, PaperInsightError):
        return exc.recoverable
    # 非 PaperInsightError 的标准异常默认不可恢复
    return False
