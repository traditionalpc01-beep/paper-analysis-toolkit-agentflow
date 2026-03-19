from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Optional

import yaml

from paperinsight.utils.config_crypto import decrypt_sensitive_fields, encrypt_sensitive_fields

SENSITIVE_FIELDS = ["token", "api_key", "client_id", "client_secret", "secret_key"]

DEFAULT_CONFIG: dict[str, Any] = {
    "mineru": {
        "enabled": True,
        "mode": "api",
        "token": "",
        "api_url": "https://mineru.net/api/v4",
        "timeout": 600,
        "model_version": "vlm",
        "output_format": "markdown",
        "extract_tables": True,
        "method": "auto",
        "download_retries": 3,
        "download_backoff": 1.5,
        "allow_insecure_result_download": True,
    },
    "llm": {
        "enabled": True,
        "provider": "longcat",
        "api_key": "",
        "timeout": 120,
        "longcat": {
            "model": "LongCat-Flash-Chat",
            "base_url": "https://api.longcat.chat/openai",
            "backfill_model": "LongCat-Flash-Lite",
            "enable_lite_backfill": True,
        },
    },
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
    "cache": {
        "enabled": True,
        "directory": ".cache",
        "max_age_days": 30,
    },
    "output": {
        "format": ["excel"],
        "sort_by_if": True,
        "bilingual_text": False,
    },
}


def get_config_path() -> Path:
    config_dir = Path.home() / ".paperinsight"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.yaml"


def normalize_config(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    normalized = copy.deepcopy(DEFAULT_CONFIG)
    if not config:
        return normalized

    decrypted = decrypt_sensitive_fields(copy.deepcopy(config))
    _deep_merge(normalized, decrypted)
    normalized["output"]["format"] = _normalize_output_formats(normalized["output"].get("format"))
    return normalized


def load_config() -> dict[str, Any]:
    config_path = get_config_path()
    if not config_path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return normalize_config(raw)


def save_config(config: dict[str, Any]) -> Path:
    config_path = get_config_path()
    normalized = normalize_config(config)
    encrypted = encrypt_sensitive_fields(normalized, SENSITIVE_FIELDS)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(encrypted, handle, sort_keys=False, allow_unicode=True)
    try:
        os.chmod(config_path, 0o600)
    except PermissionError:
        pass
    return config_path


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    _deep_merge(config, updates)
    save_config(config)
    return config


def get_nested_value(config: dict[str, Any], path: str, default: Any = None) -> Any:
    value: Any = config
    for part in path.split('.'):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default
    return value


def set_nested_value(config: dict[str, Any], path: str, value: Any) -> None:
    target = config
    parts = path.split('.')
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def is_config_complete(config: dict[str, Any], required_keys: Optional[list[str]] = None) -> tuple[bool, list[str]]:
    missing = []
    for key_path in required_keys or []:
        value = get_nested_value(config, key_path)
        if value in (None, ""):
            missing.append(key_path)
    return not missing, missing


def mask_sensitive_value(value: str, visible_chars: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible_chars * 2:
        return "*" * len(value)
    hidden = "*" * (len(value) - visible_chars * 2)
    return f"{value[:visible_chars]}{hidden}{value[-visible_chars:]}"


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _normalize_output_formats(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    formats: list[str] = []
    for item in value or []:
        text = str(item).strip().lower()
        if text and text not in formats:
            formats.append(text)
    return formats or ["excel"]
