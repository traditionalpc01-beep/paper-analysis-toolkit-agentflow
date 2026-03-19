from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from paperinsight.agentflow.identity import (
    IdentityResultRecord,
    build_identity_job,
    build_paper_data_payload,
    extract_identity_hints,
)
from paperinsight.cleaner.section_filter import SectionFilter
from paperinsight.core.cache import CacheManager
from paperinsight.core.extractor import DataExtractor
from paperinsight.core.reporter import ReportGenerator
from paperinsight.models.schemas import PaperData
from paperinsight.parser.base import ParseResult
from paperinsight.parser.mineru import MinerUParser
from paperinsight.utils.hash_utils import calculate_md5
from paperinsight.utils.logger import setup_logger


IDENTITY_PROMPT = """# Identity Match Tasks

Use `identity_jobs.jsonl` as the work queue. Process one paper at a time in a fresh chat/thread.

For each job:
1. Prefer DOI for exact matching. If DOI is missing, use title plus year.
2. Confirm the matched paper before extracting the journal name.
3. Return the latest available impact factor with the actual report year.
4. Keep evidence URLs for both the paper match and the impact-factor source.
5. Write one JSON object per line to `identity_results.jsonl`.

Expected output schema:
```json
{
  "paper_key": "string",
  "matched": true,
  "paper_identifier": "string|null",
  "matched_title": "string|null",
  "journal_name": "string|null",
  "impact_factor": 0.0,
  "impact_factor_year": 2025,
  "impact_factor_source": "string|null",
  "impact_factor_status": "OK",
  "evidence_urls": ["https://example.com"],
  "notes": "string|null"
}
```
"""


class AgentPreparePipeline:
    def __init__(
        self,
        output_dir: Path | str,
        config: Optional[dict[str, Any]] = None,
        cache_dir: Path | str = ".cache",
    ) -> None:
        self.config = config or {}
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.cache_dir = Path(cache_dir)
        self.enable_cache = bool(self.config.get("cache", {}).get("enabled", True))
        self.cache_manager = CacheManager(self.cache_dir) if self.enable_cache else None

        self.logger = setup_logger("paperinsight.agentflow")
        self.parser = self._init_parser()

    def prepare(
        self,
        pdf_dir: Path | str,
        *,
        recursive: bool = False,
        pdf_files: Optional[list[Path]] = None,
        use_cache: bool = True,
        run_name: Optional[str] = None,
    ) -> dict[str, Any]:
        pdf_dir = Path(pdf_dir)
        pdf_files = pdf_files or self._collect_pdf_files(pdf_dir, recursive=recursive)
        pdf_files = [Path(path) for path in pdf_files if Path(path).is_file()]

        if not pdf_files:
            return {"status": "no_files", "pdf_count": 0}

        if not self.parser:
            raise RuntimeError("MinerU parser is not available. Configure MinerU API or CLI before running prepare.")

        run_dir = self._build_run_dir(run_name)
        papers_dir = run_dir / "papers"
        jobs_dir = run_dir / "jobs"
        papers_dir.mkdir(parents=True, exist_ok=True)
        jobs_dir.mkdir(parents=True, exist_ok=True)

        manifest: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_dir.name,
            "created_at": datetime.now().isoformat(),
            "input_dir": str(pdf_dir.resolve()),
            "run_dir": str(run_dir.resolve()),
            "jobs_file": str((jobs_dir / "identity_jobs.jsonl").resolve()),
            "papers": [],
        }

        jobs_path = jobs_dir / "identity_jobs.jsonl"
        results_path = jobs_dir / "identity_results.jsonl"
        prompt_path = jobs_dir / "identity_prompt.md"
        results_path.touch()
        prompt_path.write_text(IDENTITY_PROMPT, encoding="utf-8")

        success_count = 0
        error_count = 0

        with jobs_path.open("w", encoding="utf-8") as job_stream:
            for index, pdf_path in enumerate(pdf_files, start=1):
                md5 = calculate_md5(pdf_path) if self.enable_cache else ""
                paper_key = self._build_paper_key(index, pdf_path, md5)
                paper_dir = papers_dir / paper_key
                paper_dir.mkdir(parents=True, exist_ok=True)

                parse_result, from_cache = self._parse_pdf(pdf_path, md5=md5, use_cache=use_cache)
                parse_meta_path = paper_dir / "01_parse_meta.json"

                if parse_result.success and parse_result.markdown:
                    markdown_path = paper_dir / "01_parse.md"
                    markdown_path.write_text(parse_result.markdown, encoding="utf-8")

                    identity_hints = extract_identity_hints(
                        parse_result.markdown,
                        parse_result.metadata,
                        pdf_path,
                    )
                    job = build_identity_job(
                        paper_key=paper_key,
                        source_pdf=pdf_path,
                        markdown_path=markdown_path,
                        identity_hints=identity_hints,
                    )

                    identity_job_path = paper_dir / "02_identity_job.json"
                    identity_job_path.write_text(
                        json.dumps(job, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    job_stream.write(json.dumps(job, ensure_ascii=False) + "\n")

                    parse_meta_path.write_text(
                        json.dumps(
                            self._build_parse_metadata(pdf_path, parse_result, md5=md5, from_cache=from_cache),
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )

                    manifest["papers"].append(
                        {
                            "paper_key": paper_key,
                            "status": "prepared",
                            "source_pdf": str(pdf_path.resolve()),
                            "markdown_path": str(markdown_path.resolve()),
                            "parse_meta_path": str(parse_meta_path.resolve()),
                            "identity_job_path": str(identity_job_path.resolve()),
                            "title_hint": identity_hints.get("title"),
                            "doi_hint": identity_hints.get("doi"),
                            "year_hint": identity_hints.get("year"),
                        }
                    )
                    success_count += 1
                    continue

                parse_meta_path.write_text(
                    json.dumps(
                        self._build_parse_metadata(pdf_path, parse_result, md5=md5, from_cache=from_cache),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                manifest["papers"].append(
                    {
                        "paper_key": paper_key,
                        "status": "parse_failed",
                        "source_pdf": str(pdf_path.resolve()),
                        "parse_meta_path": str(parse_meta_path.resolve()),
                        "error_message": parse_result.error_message or "MinerU parse failed",
                    }
                )
                error_count += 1

        manifest["pdf_count"] = len(pdf_files)
        manifest["success_count"] = success_count
        manifest["error_count"] = error_count

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "status": "completed",
            "pdf_count": len(pdf_files),
            "success_count": success_count,
            "error_count": error_count,
            "run_dir": str(run_dir.resolve()),
            "manifest_path": str(manifest_path.resolve()),
            "identity_jobs_path": str(jobs_path.resolve()),
            "identity_results_path": str(results_path.resolve()),
            "identity_prompt_path": str(prompt_path.resolve()),
        }

    def import_identity_results(
        self,
        run_dir: Path | str,
        *,
        results_path: Optional[Path | str] = None,
    ) -> dict[str, Any]:
        run_dir = Path(run_dir)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        results_file = Path(results_path) if results_path else run_dir / "jobs" / "identity_results.jsonl"
        if not results_file.exists():
            raise FileNotFoundError(f"Identity results file not found: {results_file}")

        papers_by_key = {paper["paper_key"]: paper for paper in manifest.get("papers", [])}
        imported_count = 0
        invalid_count = 0
        unmatched_count = 0
        invalid_records: list[dict[str, Any]] = []

        for line_number, raw_line in enumerate(results_file.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                payload = json.loads(line)
                identity_result = IdentityResultRecord.model_validate(payload)
            except (json.JSONDecodeError, ValidationError) as exc:
                invalid_count += 1
                invalid_records.append({"line": line_number, "error": str(exc)})
                continue

            paper_entry = papers_by_key.get(identity_result.paper_key)
            if not paper_entry:
                invalid_count += 1
                invalid_records.append(
                    {"line": line_number, "paper_key": identity_result.paper_key, "error": "unknown paper_key"}
                )
                continue

            paper_dir = run_dir / "papers" / identity_result.paper_key
            identity_job_path = Path(paper_entry["identity_job_path"])
            identity_job = json.loads(identity_job_path.read_text(encoding="utf-8"))

            identity_result_path = paper_dir / "03_identity_result.json"
            identity_result_path.write_text(
                json.dumps(identity_result.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            paper_data_payload = build_paper_data_payload(
                identity_job=identity_job,
                identity_result=identity_result,
            )
            paper_data_path = paper_dir / "03_paper_data.json"
            paper_data_path.write_text(
                json.dumps(paper_data_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            paper_entry["status"] = "identity_imported"
            paper_entry["identity_result_path"] = str(identity_result_path.resolve())
            paper_entry["paper_data_path"] = str(paper_data_path.resolve())
            paper_entry["matched"] = identity_result.matched
            paper_entry["journal_name"] = identity_result.journal_name
            paper_entry["impact_factor"] = identity_result.impact_factor
            paper_entry["impact_factor_year"] = identity_result.impact_factor_year
            paper_entry["impact_factor_source"] = identity_result.impact_factor_source
            paper_entry["impact_factor_status"] = identity_result.impact_factor_status
            paper_entry["evidence_urls"] = identity_result.evidence_urls

            if not identity_result.matched:
                unmatched_count += 1
            imported_count += 1

        manifest["identity_import"] = {
            "imported_count": imported_count,
            "invalid_count": invalid_count,
            "unmatched_count": unmatched_count,
            "results_path": str(results_file.resolve()),
            "imported_at": datetime.now().isoformat(),
        }
        if invalid_records:
            manifest["identity_import"]["invalid_records"] = invalid_records

        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        summary_path = run_dir / "jobs" / "identity_import_summary.json"
        summary_payload = {
            "status": "completed",
            "run_dir": str(run_dir.resolve()),
            "manifest_path": str(manifest_path.resolve()),
            "results_path": str(results_file.resolve()),
            "imported_count": imported_count,
            "invalid_count": invalid_count,
            "unmatched_count": unmatched_count,
            "invalid_records": invalid_records,
        }
        summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_payload["summary_path"] = str(summary_path.resolve())
        return summary_payload

    def extract_metrics(
        self,
        run_dir: Path | str,
        *,
        paper_keys: Optional[list[str]] = None,
        force: bool = False,
    ) -> dict[str, Any]:
        run_dir = Path(run_dir)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        selected_keys = set(paper_keys or [])
        cleaner = SectionFilter(self.config.get("cleaner", {}))
        extractor = DataExtractor(config=self.config)

        processed_count = 0
        failed_count = 0
        skipped_count = 0

        for paper_entry in manifest.get("papers", []):
            paper_key = paper_entry.get("paper_key")
            if selected_keys and paper_key not in selected_keys:
                continue

            paper_dir = run_dir / "papers" / paper_key
            markdown_path = paper_dir / "01_parse.md"
            if not markdown_path.exists():
                skipped_count += 1
                continue

            metrics_result_path = paper_dir / "04_metrics_result.json"
            metrics_meta_path = paper_dir / "04_metrics_meta.json"
            if metrics_result_path.exists() and not force:
                skipped_count += 1
                continue

            markdown = markdown_path.read_text(encoding="utf-8")
            parse_meta_path = paper_dir / "01_parse_meta.json"
            parse_meta = json.loads(parse_meta_path.read_text(encoding="utf-8")) if parse_meta_path.exists() else {}
            parse_result = ParseResult(
                markdown=markdown,
                raw_text=markdown,
                success=True,
                parser_name=str(parse_meta.get("parser_name") or "agentflow"),
                metadata=parse_meta.get("metadata") or {},
                source_file=paper_entry.get("source_pdf"),
            )

            cleaned_content = cleaner.clean(markdown)
            extraction_text = cleaned_content.get_text_for_extraction()
            extraction_result = extractor.extract(
                markdown_text=markdown,
                cleaned_text=extraction_text,
                parse_result=parse_result,
            )

            if not extraction_result.success or not extraction_result.data:
                metrics_meta = {
                    "paper_key": paper_key,
                    "success": False,
                    "error_message": extraction_result.error_message,
                    "extraction_method": extraction_result.extraction_method,
                    "llm_model": extraction_result.llm_model,
                }
                metrics_meta_path.write_text(
                    json.dumps(metrics_meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                paper_entry["status"] = "metrics_failed"
                paper_entry["metrics_meta_path"] = str(metrics_meta_path.resolve())
                paper_entry["metrics_error"] = extraction_result.error_message
                failed_count += 1
                continue

            merged_paper_data = self._merge_imported_paper_data(
                extracted=extraction_result.data,
                imported_payload=self._load_imported_paper_data(paper_entry),
            )
            metrics_result_path.write_text(
                json.dumps(merged_paper_data.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            metrics_meta = {
                "paper_key": paper_key,
                "success": True,
                "extraction_method": extraction_result.extraction_method,
                "llm_model": extraction_result.llm_model,
                "processing_time": extraction_result.processing_time,
                "used_imported_identity": bool(paper_entry.get("paper_data_path")),
            }
            metrics_meta_path.write_text(
                json.dumps(metrics_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            best_device = merged_paper_data.get_best_device()
            paper_entry["status"] = "metrics_extracted"
            paper_entry["metrics_result_path"] = str(metrics_result_path.resolve())
            paper_entry["metrics_meta_path"] = str(metrics_meta_path.resolve())
            paper_entry["title"] = merged_paper_data.paper_info.title
            paper_entry["journal_name"] = merged_paper_data.paper_info.journal_name
            paper_entry["impact_factor"] = merged_paper_data.paper_info.impact_factor
            paper_entry["impact_factor_year"] = merged_paper_data.paper_info.impact_factor_year
            paper_entry["impact_factor_source"] = merged_paper_data.paper_info.impact_factor_source
            paper_entry["impact_factor_status"] = merged_paper_data.paper_info.impact_factor_status
            paper_entry["best_eqe"] = (
                merged_paper_data.paper_info.best_eqe
                or (best_device.eqe if best_device else None)
            )
            processed_count += 1

        manifest["metrics_extraction"] = {
            "processed_count": processed_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "completed_at": datetime.now().isoformat(),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        summary_path = run_dir / "jobs" / "metrics_summary.json"
        summary_payload = {
            "status": "completed",
            "run_dir": str(run_dir.resolve()),
            "manifest_path": str(manifest_path.resolve()),
            "processed_count": processed_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
        }
        summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_payload["summary_path"] = str(summary_path.resolve())
        return summary_payload

    def finalize(
        self,
        run_dir: Path | str,
        *,
        output_dir: Optional[Path | str] = None,
        sort_by_if: bool = True,
        export_json: bool = False,
    ) -> dict[str, Any]:
        run_dir = Path(run_dir)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report_dir = Path(output_dir) if output_dir else run_dir / "reports"
        reporter = ReportGenerator(report_dir)

        dict_results: list[dict[str, Any]] = []
        json_results: list[dict[str, Any]] = []
        finalized_count = 0
        incomplete_count = 0

        for paper_entry in manifest.get("papers", []):
            source_pdf = Path(paper_entry["source_pdf"]) if paper_entry.get("source_pdf") else None
            final_paper_data = self._load_final_paper_data(paper_entry)
            if final_paper_data is None:
                incomplete_count += 1
                dict_results.append(
                    self._build_incomplete_report_row(
                        paper_entry=paper_entry,
                        source_pdf=source_pdf,
                    )
                )
                continue

            paper_dir = run_dir / "papers" / paper_entry["paper_key"]
            final_data_path = paper_dir / "05_final_paper_data.json"
            final_data_path.write_text(
                json.dumps(final_paper_data.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            row = final_paper_data.to_excel_row()
            row["file"] = source_pdf.name if source_pdf else paper_entry.get("paper_key", "")
            row["url"] = source_pdf.resolve().as_uri() if source_pdf and source_pdf.exists() else ""
            row["processing_status"] = self._build_finalize_processing_status(paper_entry, final_paper_data)
            dict_results.append(row)

            dumped = final_paper_data.model_dump()
            dumped["file"] = row["file"]
            dumped["url"] = row["url"]
            dumped["processing_status"] = row["processing_status"]
            json_results.append(dumped)

            best_device = final_paper_data.get_best_device()
            paper_entry["status"] = "finalized"
            paper_entry["final_paper_data_path"] = str(final_data_path.resolve())
            paper_entry["title"] = final_paper_data.paper_info.title
            paper_entry["journal_name"] = final_paper_data.paper_info.journal_name
            paper_entry["impact_factor"] = final_paper_data.paper_info.impact_factor
            paper_entry["impact_factor_year"] = final_paper_data.paper_info.impact_factor_year
            paper_entry["impact_factor_source"] = final_paper_data.paper_info.impact_factor_source
            paper_entry["impact_factor_status"] = final_paper_data.paper_info.impact_factor_status
            paper_entry["best_eqe"] = (
                final_paper_data.paper_info.best_eqe or (best_device.eqe if best_device else None)
            )
            finalized_count += 1

        report_files: dict[str, str] = {}
        excel_path = reporter.generate_excel_report(dict_results, sort_by_if=sort_by_if)
        report_files["excel"] = str(excel_path)
        if export_json:
            json_path = reporter.generate_json_report(json_results, sort_by_if=sort_by_if)
            report_files["json"] = str(json_path)

        manifest["finalize"] = {
            "finalized_count": finalized_count,
            "incomplete_count": incomplete_count,
            "report_files": report_files,
            "completed_at": datetime.now().isoformat(),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        summary_path = run_dir / "jobs" / "finalize_summary.json"
        summary_payload = {
            "status": "completed",
            "run_dir": str(run_dir.resolve()),
            "manifest_path": str(manifest_path.resolve()),
            "finalized_count": finalized_count,
            "incomplete_count": incomplete_count,
            "report_files": report_files,
        }
        summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_payload["summary_path"] = str(summary_path.resolve())
        return summary_payload

    def _init_parser(self) -> Optional[MinerUParser]:
        mineru_config = self.config.get("mineru", {})
        if not mineru_config.get("enabled", True):
            return None

        try:
            parser = MinerUParser(config=mineru_config)
        except Exception as exc:
            self.logger.warning(f"[AgentPrepare] MinerU init failed: {exc}")
            return None

        if not parser.is_available():
            return None
        return parser

    def _parse_pdf(self, pdf_path: Path, *, md5: str, use_cache: bool) -> tuple[ParseResult, bool]:
        if self.enable_cache and use_cache and self.cache_manager and self.cache_manager.has_markdown_cache(md5):
            cached_markdown = self.cache_manager.load_markdown_cache(md5) or ""
            return (
                ParseResult(
                    markdown=cached_markdown,
                    raw_text=cached_markdown,
                    success=bool(cached_markdown),
                    parser_name="cache",
                ),
                True,
            )

        assert self.parser is not None
        try:
            parse_result = self.parser.parse(pdf_path)
        except Exception as exc:
            parse_result = ParseResult(
                success=False,
                error_message=str(exc),
                parser_name=getattr(self.parser, "name", "MinerU"),
                source_file=str(pdf_path),
            )
        if parse_result.success and parse_result.markdown and self.enable_cache and use_cache and self.cache_manager:
            self.cache_manager.save_markdown_cache(md5, parse_result.markdown)
        return parse_result, False

    @staticmethod
    def _collect_pdf_files(pdf_dir: Path, *, recursive: bool) -> list[Path]:
        iterator = pdf_dir.rglob("*.pdf") if recursive else pdf_dir.glob("*.pdf")
        return [path for path in iterator if path.is_file()]

    def _build_run_dir(self, run_name: Optional[str]) -> Path:
        base_name = run_name or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir = self.output_dir / self._slugify(base_name)
        if not run_dir.exists():
            run_dir.mkdir(parents=True, exist_ok=True)
            return run_dir

        counter = 1
        while True:
            candidate = self.output_dir / f"{self._slugify(base_name)}_{counter}"
            if not candidate.exists():
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            counter += 1

    @staticmethod
    def _build_paper_key(index: int, pdf_path: Path, md5: str) -> str:
        slug = AgentPreparePipeline._slugify(pdf_path.stem) or "paper"
        suffix = (md5[:8] if md5 else "nocache").lower()
        return f"{index:04d}_{slug[:48]}_{suffix}"

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^0-9A-Za-z_-]+", "-", value.strip())
        slug = re.sub(r"-{2,}", "-", slug).strip("-_")
        return slug or "run"

    @staticmethod
    def _build_parse_metadata(
        pdf_path: Path,
        parse_result: ParseResult,
        *,
        md5: str,
        from_cache: bool,
    ) -> dict[str, Any]:
        return {
            "source_pdf": str(pdf_path.resolve()),
            "source_filename": pdf_path.name,
            "parser_name": parse_result.parser_name,
            "success": parse_result.success,
            "error_message": parse_result.error_message,
            "processing_time": parse_result.processing_time,
            "page_count": parse_result.page_count,
            "word_count": parse_result.word_count,
            "markdown_chars": len(parse_result.markdown or ""),
            "metadata": parse_result.metadata or {},
            "cache_md5": md5 or None,
            "from_cache": from_cache,
        }

    @staticmethod
    def _load_imported_paper_data(paper_entry: dict[str, Any]) -> Optional[dict[str, Any]]:
        paper_data_path = paper_entry.get("paper_data_path")
        if not paper_data_path:
            return None
        path = Path(paper_data_path)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _merge_imported_paper_data(
        *,
        extracted: PaperData,
        imported_payload: Optional[dict[str, Any]],
    ) -> PaperData:
        if not imported_payload:
            return extracted

        imported = PaperData.model_validate(imported_payload)
        merged = extracted.model_copy(deep=True)
        imported_info = imported.paper_info
        merged_info = merged.paper_info

        for field_name in (
            "title",
            "authors",
            "year",
            "journal_name",
            "raw_journal_title",
            "matched_journal_title",
            "match_method",
            "journal_profile_url",
            "impact_factor",
            "impact_factor_year",
            "impact_factor_source",
            "impact_factor_status",
        ):
            imported_value = getattr(imported_info, field_name)
            if imported_value not in (None, ""):
                setattr(merged_info, field_name, imported_value)

        if not merged.devices and imported.devices:
            merged.devices = imported.devices
        return merged

    def _load_final_paper_data(self, paper_entry: dict[str, Any]) -> Optional[PaperData]:
        metrics_path = paper_entry.get("metrics_result_path")
        imported_payload = self._load_imported_paper_data(paper_entry)

        if metrics_path:
            path = Path(metrics_path)
            if path.exists():
                metrics_payload = json.loads(path.read_text(encoding="utf-8"))
                metrics_paper_data = PaperData.model_validate(metrics_payload)
                return self._merge_imported_paper_data(
                    extracted=metrics_paper_data,
                    imported_payload=imported_payload,
                )

        if imported_payload:
            return PaperData.model_validate(imported_payload)
        return None

    @staticmethod
    def _build_finalize_processing_status(paper_entry: dict[str, Any], paper_data: PaperData) -> str:
        segments = [f"agent-finalize: {paper_entry.get('status', 'unknown')}"]
        if paper_data.paper_info.impact_factor not in (None, 0):
            year = paper_data.paper_info.impact_factor_year
            if year:
                segments.append(f"IF={paper_data.paper_info.impact_factor} ({year})")
            else:
                segments.append(f"IF={paper_data.paper_info.impact_factor}")
        elif paper_data.paper_info.impact_factor_status:
            segments.append(f"IF status={paper_data.paper_info.impact_factor_status}")

        best_device = paper_data.get_best_device()
        if best_device and best_device.eqe:
            segments.append(f"best EQE={best_device.eqe}")
        elif paper_data.paper_info.best_eqe:
            segments.append(f"best EQE={paper_data.paper_info.best_eqe}")
        return " | ".join(segments)

    @staticmethod
    def _build_incomplete_report_row(
        *,
        paper_entry: dict[str, Any],
        source_pdf: Optional[Path],
    ) -> dict[str, Any]:
        return {
            "file": source_pdf.name if source_pdf else paper_entry.get("paper_key", ""),
            "url": source_pdf.resolve().as_uri() if source_pdf and source_pdf.exists() else "",
            "processing_status": f"incomplete: {paper_entry.get('status', 'missing_data')}",
            "title": paper_entry.get("title") or paper_entry.get("title_hint") or "",
            "journal": paper_entry.get("journal_name") or "",
            "impact_factor": paper_entry.get("impact_factor") or "",
            "impact_factor_year": paper_entry.get("impact_factor_year") or "",
            "impact_factor_source": paper_entry.get("impact_factor_source") or "",
            "impact_factor_status": paper_entry.get("impact_factor_status") or "",
            "authors": "",
            "structure": "",
            "eqe": "",
            "cie": "",
            "lifetime": "",
            "best_eqe": "",
            "optimization_level": "",
            "optimization_strategy": "",
            "optimization_details": "",
            "key_findings": "",
            "eqe_source": "",
            "cie_source": "",
            "lifetime_source": "",
            "structure_source": "",
        }
