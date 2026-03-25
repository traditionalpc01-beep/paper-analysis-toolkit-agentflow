"""器件数据提取、去重、排序与评分工具函数。

从 DataExtractor 中提取的器件相关逻辑。
所有函数均为纯函数，不依赖 DataExtractor 实例。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from paperinsight.models.schemas import DeviceData, PaperData


# ── 器件提取入口 ─────────────────────────────────────────────────


def extract_devices(text: str) -> List[DeviceData]:
    """提取器件数据（入口，优先候选片段，其次散装提取）。"""
    candidate_devices = extract_candidate_devices(text)
    if candidate_devices:
        return candidate_devices

    structures = extract_all_structures(text)
    eqes = extract_all_eqe(text)
    cies = extract_all_cie(text)
    lifetimes = extract_all_lifetime(text)

    if structures or eqes or cies or lifetimes:
        return [
            DeviceData(
                structure=structures[0] if structures else None,
                eqe=eqes[0] if eqes else None,
                cie=cies[0] if cies else None,
                lifetime=lifetimes[0] if lifetimes else None,
            )
        ]

    return []


def extract_candidate_devices(text: str) -> List[DeviceData]:
    """按段落/候选片段提取多器件信息（含去重、限数）。"""
    segments = build_device_segments(text)
    devices: List[DeviceData] = []
    seen_signatures: set[tuple] = set()

    for segment in segments:
        structure = extract_first_structure(segment)
        eqe = extract_first_eqe(segment)
        cie = extract_first_cie(segment)
        lifetime = extract_first_lifetime(segment)
        label = extract_device_label(segment)

        has_signal = bool(structure or eqe or cie or lifetime)
        if not has_signal:
            continue

        signature = (label or "", structure or "", eqe or "", cie or "", lifetime or "")
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        devices.append(
            DeviceData(
                device_label=label,
                structure=structure,
                eqe=eqe,
                cie=cie,
                lifetime=lifetime,
                notes=build_device_notes(segment),
            )
        )

    return devices[:6]


# ── 段落分割与信号评分 ───────────────────────────────────────────


def build_device_segments(text: str) -> List[str]:
    """将文本拆分为含器件信号的段落/句子窗口。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    segments: List[str] = []

    for paragraph in paragraphs:
        if segment_signal_score(paragraph) >= 2:
            segments.append(paragraph)

    sentence_chunks = re.split(r"(?<=[.!?])\s+", text)
    window: List[str] = []
    for sentence in sentence_chunks:
        sentence = sentence.strip()
        if not sentence:
            continue
        if segment_signal_score(sentence) > 0:
            window.append(sentence)
        else:
            if window:
                segments.append(" ".join(window))
                window = []
    if window:
        segments.append(" ".join(window))

    deduped: List[str] = []
    seen: set[str] = set()
    for segment in segments:
        normalized = re.sub(r"\s+", " ", segment)
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(segment)
    return deduped[:20]


def segment_signal_score(text: str) -> int:
    """评估一段文本是否包含足够的器件信号。"""
    score = 0
    if extract_first_structure(text):
        score += 2
    if extract_first_eqe(text):
        score += 2
    if extract_first_cie(text):
        score += 1
    if extract_first_lifetime(text):
        score += 1
    if extract_device_label(text):
        score += 1
    return score


# ── 单值提取（取第一个匹配）─────────────────────────────────────


def extract_first_structure(text: str) -> Optional[str]:
    structures = extract_all_structures(text)
    return structures[0] if structures else None


def extract_first_eqe(text: str) -> Optional[str]:
    values = extract_all_eqe(text)
    return values[0] if values else None


def extract_first_cie(text: str) -> Optional[str]:
    values = extract_all_cie(text)
    return values[0] if values else None


def extract_first_lifetime(text: str) -> Optional[str]:
    values = extract_all_lifetime(text)
    return values[0] if values else None


def extract_device_label(text: str) -> Optional[str]:
    """提取器件标签（如 "Device A"、"champion device"）。"""
    patterns = [
        r"\b(champion device|best device|optimized device|control device|reference device)\b",
        r"\b(device\s*[A-Z0-9])\b",
        r"\b(sample\s*[A-Z0-9])\b",
        r"\b(QLED[-\s]*[A-Z0-9]+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return " ".join(match.group(1).split())
    return None


def build_device_notes(text: str) -> Optional[str]:
    """从文本片段生成器件备注。"""
    compact = " ".join(text.split())
    if len(compact) <= 220:
        return compact
    return compact[:217].rstrip() + "..."


# ── 批量提取（返回所有匹配值）────────────────────────────────────


def extract_all_structures(text: str) -> List[str]:
    """提取所有器件结构。"""
    patterns = [
        r"((?:ITO|Glass)\s*/\s*[A-Za-z0-9:+()._\-\\s]{1,40}(?:\s*/\s*[A-Za-z0-9:+()._\-\\s]{1,40}){2,8})",
    ]

    structures = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            cleaned = re.sub(r"\s+", " ", m).strip(" .;,)(\"")
            if len(cleaned) > 10 and cleaned not in structures:
                structures.append(cleaned)

    return structures[:3]


def extract_all_eqe(text: str) -> List[str]:
    """提取所有 EQE 值。"""
    patterns = [
        r"EQE[^0-9<≥>]*?([0-9]+\.?[0-9]*)\s*%",
        r"external quantum efficiency[^0-9<≥>]*?([0-9]+\.?[0-9]*)\s*%",
        r"max(?:imum)?\s+EQE[^0-9]*?([0-9]+\.?[0-9]*)\s*%",
    ]

    values = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            try:
                v = float(m)
                if 0.1 < v < 80:
                    formatted = f"{v:.2f}%"
                    if formatted not in values:
                        values.append(formatted)
            except ValueError:
                pass

    return values[:5]


def extract_all_cie(text: str) -> List[str]:
    """提取所有 CIE 坐标。"""
    patterns = [
        r"CIE[^0-9]*?\(([0-9]\.[0-9]+)\s*[,，]\s*([0-9]\.[0-9]+)\)",
        r"\(([0-9]\.[0-9]+)\s*[,，]\s*([0-9]\.[0-9]+)\)[^)]*CIE",
    ]

    values = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            try:
                x, y = float(m[0]), float(m[1])
                if 0 < x < 1 and 0 < y < 1:
                    formatted = f"({x:.4f}, {y:.4f})"
                    if formatted not in values:
                        values.append(formatted)
            except (ValueError, IndexError):
                pass

    return values[:5]


def extract_all_lifetime(text: str) -> List[str]:
    """提取所有寿命值 (T50/LT50/lifetime)。"""
    patterns = [
        r"T[⑤5]0[^0-9]*?([0-9]+\.?[0-9]*)\s*(h|hr|hrs|hour|hours)",
        r"LT[⑤5]0[^0-9]*?([0-9]+\.?[0-9]*)\s*(h|hr|hrs|hour|hours)",
        r"lifetime[^0-9]*?([0-9]+\.?[0-9]*)\s*(h|hour|hours)",
    ]

    values = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            try:
                v = float(m[0])
                if 1 < v < 50000:
                    formatted = f"{v:.1f} h"
                    if formatted not in values:
                        values.append(formatted)
            except (ValueError, IndexError):
                pass

    return values[:5]


# ── 器件合并、去重、排序 ────────────────────────────────────────


def merge_inferred_devices(paper_data: PaperData, text: str) -> PaperData:
    """用本地启发式补强器件列表（去重合并）。"""
    inferred_devices = extract_candidate_devices(text)
    if not inferred_devices:
        return paper_data

    existing_devices = list(paper_data.devices)
    if not existing_devices:
        paper_data.devices = inferred_devices
        refresh_best_eqe(paper_data)
        return paper_data

    if len(existing_devices) == 1 and device_signal_score(existing_devices[0]) <= 1:
        paper_data.devices = inferred_devices
        refresh_best_eqe(paper_data)
        return paper_data

    merged = list(existing_devices)
    seen = {device_signature(device) for device in merged}
    for device in inferred_devices:
        signature = device_signature(device)
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(device)

    paper_data.devices = merged[:6]
    refresh_best_eqe(paper_data)
    return paper_data


def sanitize_devices(paper_data: PaperData) -> PaperData:
    """器件列表清洗：单器件清洗、去重、排序、限数、刷新 best_eqe。"""
    cleaned_devices: List[DeviceData] = []
    seen: set[tuple] = set()

    for device in paper_data.devices:
        normalized = sanitize_device(device)
        if normalized is None:
            continue
        signature = device_signature(normalized)
        if signature in seen:
            continue
        seen.add(signature)
        cleaned_devices.append(normalized)

    cleaned_devices.sort(
        key=lambda item: (
            device_signal_score(item),
            1 if item.eqe else 0,
            1 if item.lifetime else 0,
            1 if item.structure else 0,
        ),
        reverse=True,
    )
    paper_data.devices = cleaned_devices[:6]

    if paper_data.paper_info.best_eqe and not any(
        device.eqe == paper_data.paper_info.best_eqe for device in paper_data.devices
    ):
        paper_data.paper_info.best_eqe = None
    refresh_best_eqe(paper_data)
    return paper_data


def sanitize_device(device: DeviceData) -> Optional[DeviceData]:
    """单器件清洗（结构规范化、备注截断、空信号过滤）。"""
    structure = device.structure
    if structure:
        structure = re.sub(r"\s+", " ", structure).strip(" .;")
        if len(structure) > 220 or structure.count(".") > 1:
            structure = extract_first_structure(structure)

    notes = device.notes
    if notes:
        notes = re.sub(r"\s+", " ", notes).strip()
        if len(notes) > 280:
            notes = notes[:277].rstrip() + "..."

    normalized = DeviceData(
        device_label=device.device_label,
        structure=structure,
        eqe=device.eqe,
        cie=device.cie,
        lifetime=device.lifetime,
        luminance=device.luminance,
        current_efficiency=device.current_efficiency,
        power_efficiency=device.power_efficiency,
        notes=notes,
    )

    score = device_signal_score(normalized)
    has_key_metric = bool(normalized.eqe or normalized.cie or normalized.lifetime)
    if score == 0:
        return None
    if score <= 1 and not has_key_metric:
        return None
    return normalized


def device_signal_score(device: DeviceData) -> int:
    """评估单个器件的非空字段数。"""
    return sum(
        1
        for value in [device.device_label, device.structure, device.eqe, device.cie, device.lifetime]
        if value
    )


def device_signature(device: DeviceData) -> tuple:
    """生成器件签名用于去重。"""
    return (
        (device.device_label or "").lower(),
        (device.structure or "").lower(),
        (device.eqe or "").lower(),
        (device.cie or "").lower(),
        (device.lifetime or "").lower(),
    )


def refresh_best_eqe(paper_data: PaperData) -> None:
    """从器件列表中刷新 best_eqe（取最大值）。"""
    if paper_data.paper_info.best_eqe:
        return

    best_value = -1.0
    best_label = None
    for device in paper_data.devices:
        if not device.eqe:
            continue
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", device.eqe)
        if not match:
            continue
        value = float(match.group(1))
        if value > best_value:
            best_value = value
            best_label = device.eqe

    if best_label:
        paper_data.paper_info.best_eqe = best_label
