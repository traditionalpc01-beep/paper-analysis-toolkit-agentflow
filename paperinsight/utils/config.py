"""
配置读写与兼容处理。

v3.0 重构：
- 添加 MinerU 解析器配置
- 添加文心一言 LLM 配置
- 支持启动时动态配置向导
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Optional
import re

import yaml

from paperinsight.utils.config_crypto import (
    decrypt_sensitive_fields,
    encrypt_sensitive_fields,
)

# 敏感字段列表（需要加密存储）
SENSITIVE_FIELDS = [
    "token",
    "api_key",
    "client_id",
    "client_secret",
    "secret_key",
]

# v3.0 默认配置
DEFAULT_CONFIG: dict[str, Any] = {
    # MinerU PDF 解析器配置（v3.0 新增）
    "mineru": {
        "enabled": True,
        "mode": "api",  # cli | api
        "token": "",  # API 模式需要
        "api_url": "https://mineru.net/api/v4",
        "timeout": 600,
        "model_version": "vlm",  # pipeline | vlm | MinerU-HTML
        "output_format": "markdown",
        "extract_tables": True,
        "method": "auto",  # auto | txt | ocr
    },
    # PaddleX OCR 配置（保留作为备选）
    "paddlex": {
        "enabled": False,
        "token": "",
        "model": "PaddleOCR-VL-1.5",
        "use_doc_orientation": False,
        "use_doc_unwarping": False,
        "use_layout_detection": True,
        "use_chart_recognition": False,
        "timeout": 300,
        "poll_interval": 5,
    },
    # LLM 配置（v3.0 扩展）
    "llm": {
        "enabled": True,
        "provider": "longcat",  # longcat | openai | deepseek | wenxin
        "api_key": "",
        "model": "LongCat-Flash-Chat",
        "base_url": "",
        "timeout": 120,
        "max_retries": 3,
        # 文心一言额外配置
        "wenxin": {
            "client_id": "",
            "client_secret": "",
            "model": "ernie-4.0-8k",  # ernie-4.0-8k | ernie-3.5-8k
        },
        # DeepSeek 配置
        "deepseek": {
            "model": "deepseek-chat",  # deepseek-chat | deepseek-coder
        },
        # OpenAI 配置
        "openai": {
            "model": "gpt-4o",
            "organization": "",
        },
        # Longcat 配置
        "longcat": {
            "model": "LongCat-Flash-Chat",
            "base_url": "https://api.longcat.chat/openai",
            "backfill_model": "LongCat-Flash-Lite",
            "enable_lite_backfill": True,
        },
    },
    # Web 搜索配置
    "web_search": {
        "enabled": True,
        "timeout": 30,
        "resolve_journal_metadata": True,
        "fetch_official_impact_factor": True,
        "correct_existing_impact_factor": True,
        "impact_factor_validation_tolerance": 0.6,
        "letpub": {
            "enabled": True,
            "timeout": 30,
        },
        "use_ai_model_if": False,
        "ai_model_if": {
            "enabled": False,
            "timeout": 60,
            "headless": True,
            "delay": 2.0,
            "qianwen_api_key": "",
            "kimi_api_key": "",
        },
        "search_crawler": {
            "enabled": True,
            "market": "en-US",
        },
        "web_of_science": {
            "enabled": False,
            "api_key": "",
            "journals_api_url": "https://api.clarivate.com/apis/wos-journals/v1",
        },
    },
    # 缓存配置
    "cache": {
        "enabled": True,
        "directory": ".cache",
        "max_age_days": 30,
    },
    # 输出配置
    "output": {
        "format": ["excel"],
        "sort_by_if": True,
        "generate_error_log": True,
        "rename_pdfs": False,
        "rename_template": "[{year}_{impact_factor}_{journal}]_{title}.pdf",
        "include_source": True,  # 是否包含原文引用
        "bilingual_text": False,  # 默认中文处理；每次运行前可交互确认是否启用双语
    },
    # PDF 处理配置
    "pdf": {
        "max_pages": 0,
        "text_ratio_threshold": 0.1,
    },
    # 文本清洗配置（v3.0 新增）
    "cleaner": {
        "enabled": True,
        "block_window": 1,
        "max_input_chars": 24000,
        "max_blocks": 80,
        "min_block_score": 3.0,
        "keep_table_context": True,
        "remove_sections": [
            "references",
            "acknowledgments",
            "author contributions",
            "supplementary material",
            "conflict of interest",
            "data availability",
        ],
        "keep_sections": [
            "abstract",
            "introduction",
            "experimental",
            "results",
            "discussion",
            "conclusion",
        ],
    },
    # 桌面端配置
    "desktop": {
        "engine": {
            "mode": "bundled",  # bundled | system_python
            "python_path": "",
            "backend_path": "",
        },
        "ui": {
            "last_pdf_dir": "",
            "last_output_dir": "",
            "remember_last_paths": True,
            "onboarding_completed": False,
        },
    },
}


def get_config_path() -> Path:
    """返回用户配置文件路径。"""
    config_dir = Path.home() / ".paperinsight"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.yaml"


def normalize_config(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    """将旧版配置统一转换为当前嵌套结构。"""
    normalized = copy.deepcopy(DEFAULT_CONFIG)
    if not config:
        config = {}

    config = decrypt_sensitive_fields(copy.deepcopy(config))

    # 深度合并现有配置
    if any(key in config for key in DEFAULT_CONFIG):
        _deep_merge(normalized, config)

    # 旧版扁平配置兼容（v1.x/v2.x）
    _migrate_legacy_config(config, normalized)

    # 标准化输出格式
    normalized["output"]["format"] = _normalize_output_formats(normalized["output"]["format"])

    # 配置值范围校验
    _validate_config_ranges(normalized)

    return normalized


def _migrate_legacy_config(config: dict[str, Any], normalized: dict[str, Any]) -> None:
    """迁移旧版配置项到新结构。"""
    # PaddleX 迁移
    if "use_paddlex" in config:
        normalized["paddlex"]["enabled"] = bool(config.get("use_paddlex"))
    if "paddlex_token" in config:
        normalized["paddlex"]["token"] = config.get("paddlex_token", "")

    # LLM 迁移
    if "use_llm" in config:
        normalized["llm"]["enabled"] = bool(config.get("use_llm"))
    if "llm_provider" in config:
        normalized["llm"]["provider"] = config.get("llm_provider", "openai")
    if "llm_api_key" in config:
        normalized["llm"]["api_key"] = config.get("llm_api_key", "")
    if "llm_model" in config:
        provider = normalized["llm"]["provider"]
        if provider == "openai":
            normalized["llm"]["openai"]["model"] = config.get("llm_model", "gpt-4o")
        elif provider == "deepseek":
            normalized["llm"]["deepseek"]["model"] = config.get("llm_model", "deepseek-chat")
        elif provider == "longcat":
            normalized["llm"]["longcat"]["model"] = config.get("llm_model", "LongCat-Flash-Chat")
        else:
            normalized["llm"]["model"] = config.get("llm_model", "")
    if "llm_base_url" in config:
        normalized["llm"]["base_url"] = config.get("llm_base_url", "")

    # Web 搜索迁移
    if "use_web_search" in config:
        normalized["web_search"]["enabled"] = bool(config.get("use_web_search"))

    # 缓存迁移
    if "enable_cache" in config:
        normalized["cache"]["enabled"] = bool(config.get("enable_cache"))
    if "cache_dir" in config:
        normalized["cache"]["directory"] = config.get("cache_dir", ".cache")

    # 输出迁移
    if "output_formats" in config and isinstance(config["output_formats"], list):
        normalized["output"]["format"] = config["output_formats"]
    if "sort_by_if" in config:
        normalized["output"]["sort_by_if"] = bool(config.get("sort_by_if"))
    if "rename_pdfs" in config:
        normalized["output"]["rename_pdfs"] = bool(config.get("rename_pdfs"))
    if "rename_template" in config:
        normalized["output"]["rename_template"] = config.get(
            "rename_template",
            normalized["output"]["rename_template"],
        )
    if "bilingual_text" in config:
        normalized["output"]["bilingual_text"] = bool(config.get("bilingual_text"))

    # PDF 迁移
    if "max_pages" in config:
        normalized["pdf"]["max_pages"] = int(config.get("max_pages") or 0)
    if "text_ratio_threshold" in config:
        normalized["pdf"]["text_ratio_threshold"] = float(
            config.get("text_ratio_threshold") or normalized["pdf"]["text_ratio_threshold"]
        )


def load_config() -> dict[str, Any]:
    """加载并标准化配置。"""
    config_path = get_config_path()
    if not config_path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)

    with config_path.open("r", encoding="utf-8") as file:
        raw_config = yaml.safe_load(file) or {}

    return normalize_config(raw_config)


def save_config(config: dict[str, Any]) -> Path:
    """保存配置（敏感字段加密）。"""
    config_path = get_config_path()
    normalized = normalize_config(config)
    encrypted_config = encrypt_sensitive_fields(normalized)

    with config_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(encrypted_config, file, default_flow_style=False, allow_unicode=True)

    # 设置文件权限为仅用户可读写
    os.chmod(config_path, 0o600)
    return config_path


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    """更新配置并保存。"""
    config = load_config()
    _deep_merge(config, updates)
    save_config(config)
    return config


def get_nested_value(config: dict[str, Any], path: str, default: Any = None) -> Any:
    """获取嵌套配置值。路径格式: 'llm.api_key' 或 'llm.wenxin.client_id'"""
    keys = path.split(".")
    value = config
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


def set_nested_value(config: dict[str, Any], path: str, value: Any) -> None:
    """设置嵌套配置值。路径格式: 'llm.api_key'"""
    keys = path.split(".")
    current = config
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    """深度合并两个字典。"""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _normalize_output_formats(value: Any) -> list[str]:
    """标准化输出格式列表。"""
    if isinstance(value, str):
        value = [value]

    formats = []
    for item in value or []:
        text = str(item).strip().lower()
        if text and text not in formats:
            formats.append(text)

    return formats or ["excel"]


def is_config_complete(config: dict[str, Any], required_keys: Optional[list[str]] = None) -> tuple[bool, list[str]]:
    """
    检查配置是否完整。

    返回: (是否完整, 缺失的配置项列表)
    """
    if required_keys is None:
        # 默认检查 LLM 配置
        required_keys = []

    missing = []
    for key_path in required_keys:
        value = get_nested_value(config, key_path)
        if value is None or value == "":
            missing.append(key_path)

    return len(missing) == 0, missing


def validate_api_key(api_key: str, provider: str) -> tuple[bool, str]:
    """
    验证 API Key 格式。

    返回: (是否有效, 错误信息)
    """
    if not api_key or not api_key.strip():
        return False, "API Key 不能为空"

    api_key = api_key.strip()

    if provider == "openai":
        if not api_key.startswith("sk-"):
            return False, "OpenAI API Key 应以 'sk-' 开头"
        if len(api_key) < 20:
            return False, "OpenAI API Key 长度不足"

    elif provider == "deepseek":
        if not api_key.startswith("sk-"):
            return False, "DeepSeek API Key 应以 'sk-' 开头"
        if len(api_key) < 20:
            return False, "DeepSeek API Key 长度不足"

    elif provider == "wenxin":
        # 文心一言使用 client_id 和 client_secret
        pass

    elif provider == "longcat":
        # Longcat API Key 无特定格式要求，只需非空
        pass

    return True, ""


def mask_sensitive_value(value: str, visible_chars: int = 4) -> str:
    """遮蔽敏感值，仅显示部分字符。"""
    if not value:
        return ""
    if len(value) <= visible_chars * 2:
        return "*" * len(value)
    return f"{value[:visible_chars]}{'*' * (len(value) - visible_chars * 2)}{value[-visible_chars:]}"


# 配置向导相关函数
def create_interactive_config() -> dict[str, Any]:
    """
    创建交互式配置（由 CLI 调用）。

    返回初始配置模板，实际交互逻辑在 CLI 中实现。
    """
    return copy.deepcopy(DEFAULT_CONFIG)


def _validate_config_ranges(config: dict[str, Any]) -> None:
    """校验配置值范围，不合法时 warning 并回退到默认值。"""
    _clamp_value(
        config, "web_search", "timeout",
        default=30, min_val=1, max_val=300,
    )
    _clamp_value(
        config, "web_search", "impact_factor_validation_tolerance",
        default=0.6, min_val=0.0, max_val=10.0,
    )
    _clamp_value(
        config, "llm", "timeout",
        default=120, min_val=1, max_val=600,
    )
    _clamp_value(
        config, "llm", "max_retries",
        default=3, min_val=0, max_val=10,
    )
    _clamp_value(
        config, "cleaner", "max_input_chars",
        default=24000, min_val=100, max_val=100000,
    )
    _clamp_value(
        config, "cleaner", "max_blocks",
        default=80, min_val=1, max_val=200,
    )
    _clamp_value(
        config, "cleaner", "min_block_score",
        default=3.0, min_val=0.0, max_val=10.0,
    )
    _clamp_value(
        config, "pdf", "max_pages",
        default=0, min_val=0, max_val=500,
    )
    _clamp_value(
        config, "pdf", "text_ratio_threshold",
        default=0.1, min_val=0.0, max_val=1.0,
    )


def _clamp_value(
    config: dict[str, Any],
    section: str,
    key: str,
    *,
    default: Any,
    min_val: Any,
    max_val: Any,
) -> None:
    """校验并修正配置值到合法范围。"""
    import logging
    logger = logging.getLogger("paperinsight.config")

    section_cfg = config.get(section, {})
    value = section_cfg.get(key, default)

    try:
        num_value = float(value)
    except (TypeError, ValueError):
        logger.warning(
            f"[Config] {section}.{key}={value!r} is not a number, falling back to {default}"
        )
        config.setdefault(section, {})[key] = default
        return

    if num_value < float(min_val) or num_value > float(max_val):
        logger.warning(
            f"[Config] {section}.{key}={num_value} out of range [{min_val}, {max_val}], "
            f"falling back to {default}"
        )
        config.setdefault(section, {})[key] = default
        return

    # 确保整数配置保持整数类型
    if isinstance(default, int) and num_value == int(num_value):
        config.setdefault(section, {})[key] = int(num_value)
