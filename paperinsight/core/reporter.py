from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger("paperinsight.reporter")


class ReportGenerator:
    REPORT_COLUMNS = [
        ("File", "file"),
        ("URL", "url"),
        ("Journal", "journal"),
        ("Impact Factor", "impact_factor"),
        ("Authors", "authors"),
        ("Processing Status", "processing_status"),
        ("Title", "title"),
        ("Device Structure", "structure"),
        ("EQE", "eqe"),
        ("CIE", "cie"),
        ("Lifetime", "lifetime"),
        ("Best EQE", "best_eqe"),
        ("Optimization Level", "optimization_level"),
        ("Strategy Summary", "optimization_strategy"),
        ("Optimization Details", "optimization_details"),
        ("Key Findings", "key_findings"),
        ("EQE Source", "eqe_source"),
        ("CIE Source", "cie_source"),
        ("Lifetime Source", "lifetime_source"),
        ("Structure Source", "structure_source"),
    ]

    def __init__(self, output_dir: Union[str, Path]):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_excel_report(
        self,
        results: list[dict[str, Any]],
        output_filename: Optional[str] = None,
        sort_by_if: bool = True,
    ) -> Path:
        if output_filename is None:
            output_filename = self._build_default_filename("xlsx")
        output_path = self._build_unique_output_path(output_filename)

        if sort_by_if:
            results = sorted(results, key=self._sort_key_by_if, reverse=True)

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "paperinsight"

        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        body_font = Font(size=10)
        border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )

        for col_idx, (header, _) in enumerate(self.REPORT_COLUMNS, start=1):
            cell = sheet.cell(row=1, column=col_idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border

        for row_idx, result in enumerate(results, start=2):
            for col_idx, (_, field_key) in enumerate(self.REPORT_COLUMNS, start=1):
                cell = sheet.cell(row=row_idx, column=col_idx, value=self._format_value(result, field_key))
                cell.font = body_font
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = border

        column_widths = {
            "file": 28,
            "url": 40,
            "journal": 28,
            "impact_factor": 14,
            "authors": 24,
            "processing_status": 28,
            "title": 46,
            "structure": 40,
            "eqe": 18,
            "cie": 18,
            "lifetime": 18,
            "best_eqe": 14,
            "optimization_level": 22,
            "optimization_strategy": 34,
            "optimization_details": 34,
            "key_findings": 34,
            "eqe_source": 40,
            "cie_source": 40,
            "lifetime_source": 40,
            "structure_source": 40,
        }
        for col_idx, (_, field_key) in enumerate(self.REPORT_COLUMNS, start=1):
            sheet.column_dimensions[get_column_letter(col_idx)].width = column_widths.get(field_key, 20)

        sheet.freeze_panes = "A2"
        workbook.save(output_path)
        logger.info("[Report] Excel report saved: %s", output_path)
        return output_path

    def generate_json_report(
        self,
        results: list[dict[str, Any]],
        output_filename: Optional[str] = None,
        sort_by_if: bool = True,
    ) -> Path:
        if output_filename is None:
            output_filename = self._build_default_filename("json")
        output_path = self._build_unique_output_path(output_filename)
        if sort_by_if:
            results = sorted(results, key=self._sort_key_by_if, reverse=True)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
        logger.info("[Report] JSON report saved: %s", output_path)
        return output_path

    def _format_value(self, result: dict[str, Any], field_key: str) -> Any:
        value = self._get_value(result, field_key)
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return value if value not in (None, "") else ""

    def _get_value(self, result: dict[str, Any], field_key: str) -> Any:
        if field_key in result:
            return result[field_key]
        paper_info = result.get("paper_info") if isinstance(result.get("paper_info"), dict) else {}
        data_source = result.get("data_source") if isinstance(result.get("data_source"), dict) else {}
        optimization = result.get("optimization") if isinstance(result.get("optimization"), dict) else {}
        lookup = {
            "journal": paper_info.get("journal_name") or paper_info.get("matched_journal_title") or paper_info.get("raw_journal_title"),
            "impact_factor": paper_info.get("impact_factor"),
            "authors": paper_info.get("authors"),
            "title": paper_info.get("title"),
            "best_eqe": paper_info.get("best_eqe"),
            "optimization_level": optimization.get("level"),
            "optimization_strategy": paper_info.get("optimization_strategy"),
            "optimization_details": optimization.get("strategy"),
            "key_findings": optimization.get("key_findings"),
            "eqe_source": data_source.get("eqe_source"),
            "cie_source": data_source.get("cie_source"),
            "lifetime_source": data_source.get("lifetime_source"),
            "structure_source": data_source.get("structure_source"),
        }
        return lookup.get(field_key, "")

    def _sort_key_by_if(self, result: dict[str, Any]) -> float:
        value = self._get_value(result, "impact_factor")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            import re
            match = re.search(r"(\d+(?:\.\d+)?)", value)
            if match:
                return float(match.group(1))
        return 0.0

    def _build_default_filename(self, extension: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"paperinsight_report_{timestamp}.{extension}"

    def _build_unique_output_path(self, output_filename: str) -> Path:
        output_path = self.output_dir / output_filename
        if not output_path.exists():
            return output_path
        stem = output_path.stem
        suffix = output_path.suffix
        counter = 1
        while True:
            candidate = self.output_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1
