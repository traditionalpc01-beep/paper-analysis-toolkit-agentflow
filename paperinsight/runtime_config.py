"""运行时配置构建器。

CLI 和 Desktop Bridge 共享的配置拼装逻辑。
"""

from __future__ import annotations

import copy
from typing import Any, List, Optional


def build_runtime_config(
    base_config: dict[str, Any],
    *,
    mode: str = "auto",
    export_json: bool = False,
    no_json: bool = False,
    no_cache: bool = False,
    rename_pdfs: Optional[bool] = None,
    bilingual: Optional[bool] = None,
    pdf_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> tuple[dict[str, Any], str]:
    """根据基础配置和选项构建运行时配置。

    Args:
        base_config: 标准化后的基础配置（已通过 normalize_config）
        mode: 运行模式，"auto" / "api" / "regex"
        export_json: 是否追加 JSON 输出格式
        no_json: 是否移除 JSON 输出格式
        no_cache: 是否禁用缓存
        rename_pdfs: 是否重命名 PDF（None 表示使用配置默认值）
        bilingual: 是否启用双语输出（None 表示使用配置默认值）
        pdf_dir: PDF 目录路径（用于 UI 状态记录）
        output_dir: 输出目录路径（用于 UI 状态记录）

    Returns:
        (runtime_config, selected_mode)
    """
    config = copy.deepcopy(base_config)

    # 模式选择
    requested_mode = str(mode).lower()
    selected_mode = requested_mode
    if selected_mode == "auto":
        from paperinsight.desktop_bridge import _has_online_capability
        selected_mode = "api" if _has_online_capability(config) else "regex"

    if selected_mode == "regex":
        config.setdefault("llm", {})["enabled"] = False
        config.setdefault("paddlex", {})["enabled"] = False

    # 输出格式合并
    output_config = config.setdefault("output", {})
    formats: List[str] = list(output_config.get("format", ["excel"]))
    if "excel" not in formats:
        formats.insert(0, "excel")
    if export_json and "json" not in formats:
        formats.append("json")
    if no_json:
        formats = [item for item in formats if item != "json"] or ["excel"]
    output_config["format"] = formats

    # rename_pdfs
    if rename_pdfs is not None:
        output_config["rename_pdfs"] = bool(rename_pdfs)

    # bilingual
    if bilingual is not None:
        output_config["bilingual_text"] = bool(bilingual)

    # cache
    cache_config = config.setdefault("cache", {})
    cache_config["enabled"] = bool(cache_config.get("enabled", True)) and not no_cache

    # UI 状态记录（Desktop Bridge 需要）
    if pdf_dir or output_dir:
        desktop_config = config.setdefault("desktop", {})
        ui_config = desktop_config.setdefault("ui", {})
        if pdf_dir:
            ui_config["last_pdf_dir"] = str(pdf_dir)
        if output_dir:
            ui_config["last_output_dir"] = str(output_dir)

    return config, selected_mode
