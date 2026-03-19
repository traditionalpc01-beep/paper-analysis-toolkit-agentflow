from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DataSourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eqe_source: Optional[str] = None
    cie_source: Optional[str] = None
    lifetime_source: Optional[str] = None
    structure_source: Optional[str] = None


class DeviceData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_label: Optional[str] = None
    structure: Optional[str] = None
    eqe: Optional[str] = None
    cie: Optional[str] = None
    lifetime: Optional[str] = None
    luminance: Optional[str] = None
    current_efficiency: Optional[str] = None
    power_efficiency: Optional[str] = None
    notes: Optional[str] = None

    @field_validator(
        "device_label",
        "structure",
        "eqe",
        "cie",
        "lifetime",
        "luminance",
        "current_efficiency",
        "power_efficiency",
        "notes",
        mode="before",
    )
    @classmethod
    def normalize_strings(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        return re.sub(r"\s+", " ", str(value).strip()) or None


class OptimizationInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Optional[str] = None
    strategy: Optional[str] = None
    key_findings: Optional[str] = None


class PaperInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    authors: Optional[str] = None
    journal_name: Optional[str] = None
    raw_journal_title: Optional[str] = None
    raw_issn: Optional[str] = None
    raw_eissn: Optional[str] = None
    matched_journal_title: Optional[str] = None
    matched_issn: Optional[str] = None
    match_method: Optional[str] = None
    journal_profile_url: Optional[str] = None
    impact_factor: Optional[float] = None
    impact_factor_year: Optional[int] = None
    impact_factor_source: Optional[str] = None
    impact_factor_status: Optional[str] = None
    year: Optional[int] = None
    optimization_strategy: Optional[str] = None
    best_eqe: Optional[str] = None
    research_type: Optional[str] = None
    emitter_type: Optional[str] = None

    @field_validator("impact_factor", mode="before")
    @classmethod
    def normalize_impact_factor(cls, value: Optional[Any]) -> Optional[float]:
        if value in (None, ""):
            return None
        return float(value)

    @field_validator("impact_factor_year", "year", mode="before")
    @classmethod
    def normalize_years(cls, value: Optional[Any]) -> Optional[int]:
        if value in (None, ""):
            return None
        return int(value)

    @field_validator("impact_factor_status", mode="before")
    @classmethod
    def normalize_if_status(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        return str(value).strip().upper()


class PaperData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_info: PaperInfo = Field(default_factory=PaperInfo)
    devices: list[DeviceData] = Field(default_factory=list)
    data_source: DataSourceReference = Field(default_factory=DataSourceReference)
    optimization: Optional[OptimizationInfo] = None

    def to_excel_row(self) -> dict[str, Any]:
        structures = []
        eqes = []
        cies = []
        lifetimes = []
        for device in self.devices:
            prefix = f"[{device.device_label}] " if device.device_label else ""
            if device.structure:
                structures.append(f"{prefix}{device.structure}")
            if device.eqe:
                eqes.append(f"{prefix}{device.eqe}")
            if device.cie:
                cies.append(f"{prefix}{device.cie}")
            if device.lifetime:
                lifetimes.append(f"{prefix}{device.lifetime}")

        journal = (
            self.paper_info.journal_name
            or self.paper_info.matched_journal_title
            or self.paper_info.raw_journal_title
        )
        return {
            "title": self.paper_info.title,
            "authors": self.paper_info.authors,
            "journal": journal,
            "impact_factor": self.paper_info.impact_factor,
            "impact_factor_year": self.paper_info.impact_factor_year,
            "impact_factor_source": self.paper_info.impact_factor_source,
            "impact_factor_status": self.paper_info.impact_factor_status,
            "structure": "\n".join(structures) if structures else None,
            "eqe": "\n".join(eqes) if eqes else None,
            "cie": "\n".join(cies) if cies else None,
            "lifetime": "\n".join(lifetimes) if lifetimes else None,
            "best_eqe": self.paper_info.best_eqe,
            "optimization_level": self.optimization.level if self.optimization else None,
            "optimization_strategy": self.paper_info.optimization_strategy,
            "optimization_details": self.optimization.strategy if self.optimization else None,
            "key_findings": self.optimization.key_findings if self.optimization else None,
            "eqe_source": self.data_source.eqe_source,
            "cie_source": self.data_source.cie_source,
            "lifetime_source": self.data_source.lifetime_source,
            "structure_source": self.data_source.structure_source,
        }

    def get_best_device(self) -> Optional[DeviceData]:
        best_device = None
        best_value = -1.0
        for device in self.devices:
            if not device.eqe:
                continue
            match = re.search(r"(\d+(?:\.\d+)?)", device.eqe)
            if not match:
                continue
            value = float(match.group(1))
            if value > best_value:
                best_value = value
                best_device = device
        return best_device or (self.devices[0] if self.devices else None)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool = True
    data: Optional[PaperData] = None
    source_file: Optional[str] = None
    error_message: Optional[str] = None
    processing_time: Optional[float] = None
    extraction_method: Optional[str] = None
    llm_model: Optional[str] = None

    def __getitem__(self, key: str):
        if not self.data:
            raise KeyError(key)
        flattened = self.data.to_excel_row()
        if key in flattened:
            return flattened[key]
        dumped = self.data.model_dump()
        if key in dumped:
            return dumped[key]
        if key == "data_source":
            return self.data.data_source.model_dump()
        raise KeyError(key)


PAPER_DATA_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "paper_info": {
            "type": "object",
            "properties": {
                "title": {"type": ["string", "null"]},
                "authors": {"type": ["string", "null"]},
                "journal_name": {"type": ["string", "null"]},
                "raw_journal_title": {"type": ["string", "null"]},
                "raw_issn": {"type": ["string", "null"]},
                "raw_eissn": {"type": ["string", "null"]},
                "matched_journal_title": {"type": ["string", "null"]},
                "matched_issn": {"type": ["string", "null"]},
                "match_method": {"type": ["string", "null"]},
                "journal_profile_url": {"type": ["string", "null"]},
                "impact_factor": {"type": ["number", "null"]},
                "impact_factor_year": {"type": ["integer", "null"]},
                "impact_factor_source": {"type": ["string", "null"]},
                "impact_factor_status": {"type": ["string", "null"]},
                "year": {"type": ["integer", "null"]},
                "optimization_strategy": {"type": ["string", "null"]},
                "best_eqe": {"type": ["string", "null"]},
                "research_type": {"type": ["string", "null"]},
                "emitter_type": {"type": ["string", "null"]},
            },
        },
        "devices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "device_label": {"type": ["string", "null"]},
                    "structure": {"type": ["string", "null"]},
                    "eqe": {"type": ["string", "null"]},
                    "cie": {"type": ["string", "null"]},
                    "lifetime": {"type": ["string", "null"]},
                    "luminance": {"type": ["string", "null"]},
                    "current_efficiency": {"type": ["string", "null"]},
                    "power_efficiency": {"type": ["string", "null"]},
                    "notes": {"type": ["string", "null"]},
                },
            },
        },
        "data_source": {
            "type": "object",
            "properties": {
                "eqe_source": {"type": ["string", "null"]},
                "cie_source": {"type": ["string", "null"]},
                "lifetime_source": {"type": ["string", "null"]},
                "structure_source": {"type": ["string", "null"]},
            },
        },
        "optimization": {
            "type": ["object", "null"],
            "properties": {
                "level": {"type": ["string", "null"]},
                "strategy": {"type": ["string", "null"]},
                "key_findings": {"type": ["string", "null"]},
            },
        },
    },
    "required": ["paper_info", "devices", "data_source"],
}
