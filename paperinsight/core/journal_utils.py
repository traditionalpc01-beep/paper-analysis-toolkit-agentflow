"""期刊名称提取与规范化工具函数。

从 DataExtractor 中提取的期刊相关逻辑，
提供期刊名称提取、ISSN 提取、别名查找、域名提示等功能。
所有函数均为纯函数，不依赖 DataExtractor 实例。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from paperinsight.parser.base import ParseResult


# ── 期刊别名加载 ─────────────────────────────────────────────────


def load_journal_aliases() -> Tuple[Dict[str, str], Dict[str, str]]:
    """从 config/journal_aliases.yaml 加载期刊别名表。

    Returns:
        (journal_domain_hints, journal_title_aliases) 元组。
    """
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "journal_aliases.yaml"
    domain_hints: Dict[str, str] = {}
    title_aliases: Dict[str, str] = {}
    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            domain_hints = data.get("journal_domain_hints", {})
            title_aliases = data.get("journal_title_aliases", {})
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to load journal aliases from {config_path}: {e}")
    return domain_hints, title_aliases


# 模块级加载
JOURNAL_DOMAIN_HINTS, JOURNAL_TITLE_ALIASES = load_journal_aliases()

JOURNAL_LINE_PATTERNS: List[str] = [
    r"\bNature\s+(?:Communications|Photonics|Materials|Nanotechnology|Energy)\b",
    r"\bAdvanced\s+(?:Materials|Functional\s+Materials|Optical\s+Materials|Energy\s+Materials)\b",
    r"\bAdvanced Functional Materials\b",
    r"\bAdvanced Materials\b",
    r"\bAdvanced Optical Materials\b",
    r"\bLaser\s*(?:&|and)?\s*Photonics\s+Reviews\b",
    r"\bACS\s+(?:Nano|Applied\s+Materials|Energy\s+Letters|Photonics)\b",
    r"\bNano\s+(?:Letters|Today|Research|Energy)\b",
    r"\bJournal\s+of\s+the\s+American\s+Chemical\s+Society\b",
    r"\bScience\s+Advances\b",
    r"\bCell(?:\s+Reports)?\b",
    r"\bAngewandte\s+Chemie\b",
    r"\bChemical\s+Science\b",
    r"\bPhysical\s+Review\s+(?:Letters|Applied)\b",
]


# ── 期刊名称提取 ─────────────────────────────────────────────────


def extract_journal_name(text: str) -> Optional[str]:
    """从正文前 5000 字符提取期刊名称（域名提示 + 模式匹配）。"""
    head_text = text[:5000]
    head_lower = head_text.lower()

    for domain, journal_name in JOURNAL_DOMAIN_HINTS.items():
        if domain in head_lower:
            return journal_name

    candidate_lines = []
    for line in head_text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            candidate_lines.append(cleaned)

    for line in candidate_lines[:40]:
        normalized_line = normalize_journal_title_candidate(line)
        if normalized_line:
            return normalized_line

        for pattern in JOURNAL_LINE_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                normalized_match = normalize_journal_title_candidate(match.group(0))
                if normalized_match:
                    return normalized_match

    return None


def extract_journal_name_from_subject(metadata: Dict[str, Any]) -> Optional[str]:
    """从 PDF metadata 的 subject 字段解析期刊名称。"""
    subject = metadata.get("subject")
    if not subject:
        return None

    normalized_subject = re.sub(r"\s+", " ", str(subject)).strip()
    normalized_subject = re.sub(r"\bdoi\s*:\s*10\.\S+$", "", normalized_subject, flags=re.IGNORECASE).strip(" ,.;")

    subject_candidates = [normalized_subject]
    volume_patterns = [
        r"^(.+?)(?:,\s*\d+\s*\((?:19|20)\d{2}\).*)$",
        r"^(.+?)(?:\s+\d+\s*\((?:19|20)\d{2}\).*)$",
        r"^(.+?)(?:\s+(?:19|20)\d{2}[,.:; ].*)$",
        r"^(.+?)(?:\s+(?:19|20)\d{2}\.\d+.*)$",
    ]
    for pattern in volume_patterns:
        match = re.match(pattern, normalized_subject, re.IGNORECASE)
        if match:
            subject_candidates.insert(0, match.group(1).strip(" ,.;"))

    for candidate_text in subject_candidates:
        candidate = normalize_journal_title_candidate(candidate_text)
        if candidate:
            return candidate

    return None


def extract_journal_name_from_filename(parse_result: Optional[ParseResult]) -> Optional[str]:
    """从文件名推断期刊名称。"""
    if not parse_result or not parse_result.source_file:
        return None

    filename = str(parse_result.source_file).split("/")[-1].split("\\")[-1]
    filename = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)

    candidates = [filename]
    split_candidates = re.split(r"\s+-\s+", filename)
    if split_candidates:
        candidates.append(split_candidates[0])
        if len(split_candidates) >= 2:
            candidates.append(" - ".join(split_candidates[:2]))

    for candidate in candidates:
        normalized = normalize_journal_title_candidate(candidate)
        if normalized:
            return normalized

    return None


def normalize_journal_title_candidate(value: Optional[str]) -> Optional[str]:
    """规范化期刊名称候选（去噪 + 别名查找 + 模式匹配）。"""
    if value in (None, ""):
        return None

    candidate = re.sub(r"\s+", " ", str(value)).strip()
    candidate = re.sub(r"^(?:cite\s+this|available\s+online)\b[:\s-]*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"^(?:review|research article|article)\b[:\s-]*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\bdoi\s*:\s*10\.\S+$", "", candidate, flags=re.IGNORECASE).strip(" -|,;.")
    candidate = re.sub(r"\bwww\.[^\s]+", "", candidate, flags=re.IGNORECASE).strip(" -|,;")
    candidate = re.sub(r"\(\d+\)$", "", candidate).strip()
    candidate = re.sub(r"\b(19|20)\d{2}\b.*$", "", candidate).strip(" -|,;")
    candidate = re.sub(r"^[0-9A-Za-z_.-]+-main(?:\s*\(\d+\))?$", "", candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r"\s*\([^)]*\)$", "", candidate).strip(" -|,;.")

    lower_candidate = candidate.lower()
    if any(token in lower_candidate for token in ("university of science", "school of materials science")):
        return None

    alias = JOURNAL_TITLE_ALIASES.get(lower_candidate)
    if alias:
        return alias

    simplified_candidate = re.sub(r"[^a-z0-9]+", " ", lower_candidate).strip()
    alias = JOURNAL_TITLE_ALIASES.get(simplified_candidate)
    if alias:
        return alias

    for pattern in JOURNAL_LINE_PATTERNS:
        full_match = re.fullmatch(pattern, candidate, re.IGNORECASE)
        if full_match:
            return full_match.group(0)

    return None


# ── ISSN 提取 ────────────────────────────────────────────────────


def extract_issn_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """从文章前部文本提取 ISSN/eISSN。

    Returns:
        (issn, eissn) 元组。
    """
    head_text = text[:5000]
    issn_pattern = r"(\d{4}-?\d{3}[\dXx])"

    eissn_match = re.search(
        rf"\b(?:e-?issn|electronic\s+issn|online\s+issn)\b[^0-9A-Za-z]{{0,10}}{issn_pattern}",
        head_text,
        re.IGNORECASE,
    )
    issn_match = re.search(
        rf"\b(?:p-?issn|print\s+issn|issn\s*\(print\)|issn)\b[^0-9A-Za-z]{{0,10}}{issn_pattern}",
        head_text,
        re.IGNORECASE,
    )

    generic_matches = re.findall(r"\b\d{4}-?\d{3}[\dXx]\b", head_text)
    raw_issn = issn_match.group(1) if issn_match else None
    raw_eissn = eissn_match.group(1) if eissn_match else None

    if not raw_issn and generic_matches:
        raw_issn = generic_matches[0]
    if not raw_eissn and len(generic_matches) > 1:
        for candidate in generic_matches:
            if candidate != raw_issn:
                raw_eissn = candidate
                break

    return raw_issn, raw_eissn


# ── 期刊元数据组合提取 ───────────────────────────────────────────


def extract_raw_journal_metadata(
    text: str,
    parse_result: Optional[ParseResult],
    coerce_fn=None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """提取期刊原始标题、ISSN 和 eISSN。

    Args:
        text: 文章全文。
        parse_result: PDF 解析结果。
        coerce_fn: 元数据值类型转换函数（默认为 coerce_metadata_value）。

    Returns:
        (raw_journal_title, raw_issn, raw_eissn) 元组。
    """
    if coerce_fn is None:
        coerce_fn = coerce_metadata_value

    metadata = dict(parse_result.metadata) if parse_result else {}
    source_metadata = extract_pdf_metadata_from_source(parse_result)
    for key, value in source_metadata.items():
        metadata.setdefault(key, value)

    raw_journal_title = first_non_empty(
        normalize_journal_title_candidate(coerce_fn(metadata.get("journal_name"))),
        normalize_journal_title_candidate(coerce_fn(metadata.get("journal"))),
        normalize_journal_title_candidate(coerce_fn(metadata.get("publication_name"))),
        normalize_journal_title_candidate(coerce_fn(metadata.get("publication_title"))),
        normalize_journal_title_candidate(coerce_fn(metadata.get("container_title"))),
        extract_journal_name_from_subject(metadata),
        extract_journal_name_from_filename(parse_result),
        extract_journal_name(text),
    )

    raw_issn = first_non_empty(
        coerce_fn(metadata.get("issn")),
        coerce_fn(metadata.get("print_issn")),
        coerce_fn(metadata.get("pissn")),
        coerce_fn(metadata.get("issn_print")),
    )
    raw_eissn = first_non_empty(
        coerce_fn(metadata.get("eissn")),
        coerce_fn(metadata.get("electronic_issn")),
        coerce_fn(metadata.get("online_issn")),
        coerce_fn(metadata.get("issn_electronic")),
    )

    text_issn, text_eissn = extract_issn_from_text(text)
    return raw_journal_title, raw_issn or text_issn, raw_eissn or text_eissn


# ── PDF 元数据提取 ───────────────────────────────────────────────


def extract_pdf_metadata_from_source(parse_result: Optional[ParseResult]) -> Dict[str, Any]:
    """从 PDF 源文件提取元数据。"""
    if not parse_result or not parse_result.source_file:
        return {}

    try:
        from paperinsight.utils.pdf_utils import PDFProcessor

        with PDFProcessor(parse_result.source_file) as processor:
            return processor._extract_metadata(processor._open())
    except Exception:
        return {}


# ── 通用工具函数 ─────────────────────────────────────────────────


def coerce_metadata_value(value: Any) -> Optional[str]:
    """将任意元数据值转换为字符串或 None。"""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)):
        for item in value:
            coerced = coerce_metadata_value(item)
            if coerced:
                return coerced
        return None
    return str(value).strip() or None


def first_non_empty(*values: Optional[str]) -> Optional[str]:
    """返回第一个非空值。"""
    for value in values:
        if value not in (None, ""):
            return value
    return None
