"""标题、作者提取与元数据规范化工具函数。

从 DataExtractor 中提取的标题/作者相关逻辑。
所有函数均为纯函数，不依赖 DataExtractor 实例。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from paperinsight.parser.base import ParseResult


# ── 标题提取 ─────────────────────────────────────────────────────

TITLE_STOP_PATTERNS: List[str] = [
    r"^(?:abstract|a\s*b\s*s\s*t\s*r\s*a\s*c\s*t)\b",
    r"^(?:keywords?|key words?)\b",
    r"^(?:article info|a\s*r\s*t\s*i\s*c\s*l\s*e\s*i\s*n\s*f\s*o)\b",
    r"^(?:introduction|results(?: and discussion)?|experimental(?: section)?|materials?(?: and methods?)?)\b",
    r"^(?:received|accepted|published|available online|copyright)\b",
    r"^(?:doi|https?://|www\.)\b",
    r"^(?:corresponding author|e-?mail)\b",
]


def extract_title(text: str, parse_result: Optional[ParseResult]) -> Optional[str]:
    """提取论文标题。"""
    coerce_fn = _default_coerce_fn()

    metadata_candidates: List[str] = []
    if parse_result:
        metadata_candidates.extend(
            filter(
                None,
                [
                    coerce_fn(parse_result.metadata.get("title")),
                    coerce_fn(parse_result.metadata.get("dc:title")),
                ],
            )
        )
        from paperinsight.core.journal_utils import extract_pdf_metadata_from_source

        source_metadata = extract_pdf_metadata_from_source(parse_result)
        metadata_candidates.extend(
            filter(
                None,
                [
                    coerce_fn(source_metadata.get("title")),
                    coerce_fn(source_metadata.get("subject")),
                ],
            )
        )

    for candidate in metadata_candidates:
        normalized = normalize_title_candidate(candidate)
        if normalized and not is_bad_title_candidate(normalized):
            return normalized

    line_candidates = extract_title_candidates_from_lines(parse_result, text)
    if line_candidates:
        return line_candidates[0]

    return None


def extract_title_candidates_from_lines(
    parse_result: Optional[ParseResult],
    text: str,
) -> List[str]:
    """从文本前 N 行提取并评分排序标题候选。"""
    line_sources: List[str] = []
    if parse_result and parse_result.markdown:
        line_sources.append(parse_result.markdown)
    if parse_result and parse_result.raw_text:
        line_sources.append(parse_result.raw_text)
    if text:
        line_sources.append(text)

    candidates: List[tuple[int, str]] = []
    seen: set[str] = set()

    for source in line_sources:
        lines = source.splitlines()[:40]
        filtered = [normalize_title_candidate(line) for line in lines]
        filtered = [line for line in filtered if line]

        for index, line in enumerate(filtered[:20]):
            if is_bad_title_candidate(line):
                continue
            score = score_title_candidate(
                line,
                index=index,
                heading_hint=lines[index].lstrip().startswith("#") if index < len(lines) else False,
            )
            if score <= 0 or line in seen:
                continue
            seen.add(line)
            candidates.append((score, line))

        for block in build_title_blocks(filtered[:8]):
            if block in seen or is_bad_title_candidate(block):
                continue
            score = score_title_candidate(block, index=0, heading_hint=True) + 2
            if score > 0:
                seen.add(block)
                candidates.append((score, block))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in candidates]


def build_title_blocks(lines: List[str]) -> List[str]:
    """将前几行合并为多行标题块候选。"""
    blocks: List[str] = []
    current: List[str] = []

    for line in lines:
        if is_bad_title_candidate(line):
            if current:
                break
            continue
        if len(current) >= 3:
            break
        current.append(line)
        joined = " ".join(current).strip()
        if 20 <= len(joined) <= 260:
            blocks.append(joined)
    return blocks


def normalize_title_candidate(value: Optional[str]) -> Optional[str]:
    """规范化标题候选（去标记、去后缀）。"""
    if value in (None, ""):
        return None

    candidate = str(value).strip()
    candidate = re.sub(r"^[#*\-\s]+", "", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" \"'`|")
    candidate = re.sub(r"^(?:title|article title)\s*[:\-]\s*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s*\[[^\]]+\]\s*$", "", candidate).strip()
    candidate = re.sub(
        r"\s*\(\s*(?:article|review|communication)\s*\)\s*$", "", candidate, flags=re.IGNORECASE
    ).strip()
    candidate = re.sub(r"\s*doi\s*:\s*10\.\S+$", "", candidate, flags=re.IGNORECASE).strip(" ,.;")
    candidate = re.sub(r"\s*[·]\s*$", "", candidate).strip()
    return candidate or None


def is_bad_title_candidate(candidate: str) -> bool:
    """判断标题候选是否为无效内容。"""
    lowered = candidate.lower().strip()
    if not lowered:
        return True
    if len(candidate) < 20 or len(candidate) > 260:
        return True
    if any(re.match(pattern, lowered, re.IGNORECASE) for pattern in TITLE_STOP_PATTERNS):
        return True
    if "@" in candidate or "http" in lowered or "www." in lowered:
        return True
    if lowered.endswith(".pdf"):
        return True
    if re.fullmatch(r"[a-z]\s*(?:[a-z]\s*){4,}", lowered):
        return True
    if re.search(r"\b(?:university|college|institute|school|laboratory|department)\b", lowered):
        return True
    if re.fullmatch(
        r"(?:[A-Z][a-zA-Z'`-]+(?:\s+[A-Z][a-zA-Z'`-]+){0,2}\s*[,*]?\s*){3,}",
        candidate,
    ):
        return True
    if candidate.count(",") >= 3 and not re.search(r"[:;]", candidate):
        return True
    if re.search(r"\b(?:figure|table)\s+\d+\b", lowered):
        return True
    if re.search(r"\b(?:orcid|supporting information)\b", lowered):
        return True
    if re.search(r"\b(?:j\.\s*[a-z]|adv\.|nano lett\.|chem\.)\b", lowered) and len(candidate.split()) <= 6:
        return True
    if sum(ch.isdigit() for ch in candidate) > max(4, len(candidate) // 8):
        return True
    return False


def score_title_candidate(candidate: str, *, index: int, heading_hint: bool) -> int:
    """对标题候选评分（长度、位置、heading 提示等）。"""
    score = 0
    word_count = len(candidate.split())
    alpha_count = sum(ch.isalpha() for ch in candidate)
    upper_ratio = sum(ch.isupper() for ch in candidate if ch.isalpha()) / max(alpha_count, 1)

    if heading_hint:
        score += 5
    if index == 0:
        score += 4
    elif index <= 2:
        score += 2

    if 6 <= word_count <= 28:
        score += 4
    if 40 <= len(candidate) <= 180:
        score += 4
    if alpha_count >= max(20, len(candidate) * 0.45):
        score += 3
    if upper_ratio < 0.45:
        score += 2
    if ":" in candidate:
        score += 1
    if candidate.endswith("."):
        score -= 2

    return score


# ── 作者提取 ─────────────────────────────────────────────────────


def extract_authors(text: str, parse_result: Optional[ParseResult]) -> Optional[str]:
    """提取作者。"""
    if parse_result and parse_result.metadata.get("author"):
        authors = parse_result.metadata["author"]
        parts = [p.strip() for p in re.split(r"[;,\n]+", authors) if p.strip()]
        return ", ".join(parts[:10])

    # 正则匹配
    name_pattern = r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b"
    matches = re.findall(name_pattern, text[:5000])

    if matches:
        unique_names = list(dict.fromkeys(matches))[:10]
        return ", ".join(unique_names)

    return None


# ── 论文属性提取 ─────────────────────────────────────────────────


def extract_impact_factor(text: str) -> Optional[float]:
    """提取影响因子。"""
    patterns = [
        r"impact\s+factor[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
        r"\bIF[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text[:3000], re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1))
                if 0.1 < value < 200:
                    return value
            except ValueError:
                continue

    return None


def extract_year(text: str) -> Optional[int]:
    """提取发表年份。"""
    patterns = [
        r"(?:published|accepted|received)[^0-9]{0,20}(20[1-2][0-9])",
        r"©?\s*(20[1-2][0-9])\s+(?:The\s+Author|Elsevier|Nature|Science|Wiley)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text[:3000], re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue

    return None


def detect_research_type(text: str) -> Optional[str]:
    """检测研究类型（OLED/PLED/QLED/PeLED/LED）。"""
    types = {
        "OLED": [r"\bOLED\b", r"organic\s+light.emitting\s+diode"],
        "PLED": [r"\bPLED\b", r"polymer\s+light.emitting\s+diode"],
        "QLED": [r"\bQLED\b", r"quantum\s+dot\s+LED"],
        "PeLED": [r"\bPeLED\b", r"perovskite\s+LED"],
        "LED": [r"\bLED\b", r"light.emitting\s+diode"],
    }

    text_lower = text.lower()
    for rtype, patterns in types.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return rtype

    return None


def detect_emitter_type(text: str) -> Optional[str]:
    """检测发光材料类型（TADF/Phosphorescent/Fluorescent/Perovskite）。"""
    types = {
        "TADF": [r"\bTADF\b", r"thermally\s+activated\s+delayed\s+fluorescence"],
        "Phosphorescent": [r"phosphorescen", r"\bIr\([^)]+\)", r"\bPt\([^)]+\)"],
        "Fluorescent": [r"\bfluorescen(?!\\s+delayed)", r"traditional\s+fluorescen"],
        "Perovskite": [r"perovskite", r"\bCsPb[^,]*,", r"\bMAPb"],
    }

    text_lower = text.lower()
    for etype, patterns in types.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return etype

    return None


# ── 优化信息提取 ─────────────────────────────────────────────────


def extract_optimization_level(text: str) -> Optional[str]:
    """提取优化层级。"""
    levels = []
    level_keywords = {
        "材料合成": ["synthesis", "material design", "precursor"],
        "核壳结构": ["core-shell", "core/shell", "shell growth"],
        "表面处理": ["surface treatment", "surface modification", "passivation"],
        "配体工程": ["ligand engineering", "ligand exchange"],
        "器件结构": ["device architecture", "device structure"],
        "工艺优化": ["annealing", "thermal treatment"],
    }

    text_lower = text.lower()
    for level, keywords in level_keywords.items():
        if any(kw in text_lower for kw in keywords):
            levels.append(level)

    return "、".join(levels) if levels else None


def extract_optimization_strategy(text: str) -> Optional[str]:
    """提取优化策略。"""
    strategies = []
    strategy_keywords = {
        "表面钝化": ["passivation", "defect passivation"],
        "配体交换": ["ligand exchange", "ligand replacement"],
        "核壳工程": ["core-shell", "shell growth"],
        "界面工程": ["interface engineering"],
        "退火处理": ["annealing", "thermal treatment"],
    }

    text_lower = text.lower()
    for strategy, keywords in strategy_keywords.items():
        if any(kw in text_lower for kw in keywords):
            strategies.append(strategy)

    if strategies:
        return f"采用{', '.join(strategies)}等方法优化器件性能。"

    return None


def extract_metric_source(text: str, metric: str) -> Optional[str]:
    """提取指标原文（EQE/CIE/lifetime/structure 的原文句子）。"""
    sentence_patterns = {
        "eqe": [
            r"[^.!?\n]*?(?:EQE|external quantum efficiency)[^.!?\n]*?[0-9]+(?:\.[0-9]+)?\s*%[^.!?\n]*[.!?]?",
        ],
        "cie": [
            r"[^.!?\n]*?CIE[^.!?\n]*?\([0-9]\.[0-9]+\s*[,，]\s*[0-9]\.[0-9]+\)[^.!?\n]*[.!?]?",
        ],
        "lifetime": [
            r"[^.!?\n]*?(?:T[⑤5]0|LT[⑤5]0|lifetime)[^.!?\n]*?[0-9]+(?:\.[0-9]+)?\s*(?:h|hr|hrs|hour|hours)[^.!?\n]*[.!?]?",
        ],
        "structure": [
            r"[^.!?\n]*?(?:device\s+structure|architecture)[^.!?\n]*?ITO[^.!?\n]*[.!?]?",
        ],
    }

    for pattern in sentence_patterns.get(metric, []):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return " ".join(match.group(0).split())

    return None


# ── 内部辅助 ─────────────────────────────────────────────────────


def _default_coerce_fn():
    """延迟导入 coerce_metadata_value 避免循环引用。"""
    from paperinsight.core.journal_utils import coerce_metadata_value

    return coerce_metadata_value
