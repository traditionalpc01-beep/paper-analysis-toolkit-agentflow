from __future__ import annotations

from typing import Optional

from paperinsight.llm.base import BaseLLM
from paperinsight.llm.longcat_client import LongcatClient
from paperinsight.llm.prompt_templates import (
    format_bilingual_postprocess_prompt,
    format_extraction_prompt,
    format_extraction_prompt_v3,
    format_journal_prompt,
    format_lite_paper_info_backfill_prompt,
    format_optimization_prompt,
)

__all__ = [
    "BaseLLM",
    "LongcatClient",
    "create_llm_client",
    "format_bilingual_postprocess_prompt",
    "format_extraction_prompt",
    "format_extraction_prompt_v3",
    "format_journal_prompt",
    "format_lite_paper_info_backfill_prompt",
    "format_optimization_prompt",
]


def create_llm_client(config: dict) -> Optional[BaseLLM]:
    if not config.get("enabled", True):
        return None

    provider = str(config.get("provider", "longcat")).lower()
    if provider != "longcat":
        raise ValueError(f"Unsupported LLM provider in the cleaned project: {provider}")

    longcat_config = config.get("longcat", {})
    return LongcatClient(
        api_key=config.get("api_key", ""),
        model=longcat_config.get("model", config.get("model", "LongCat-Flash-Chat")),
        base_url=longcat_config.get(
            "base_url",
            config.get("base_url", "https://api.longcat.chat/openai"),
        ),
        timeout=config.get("timeout", 120),
    )
