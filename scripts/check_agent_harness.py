from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from paperinsight.core.reporter import ReportGenerator
from paperinsight.utils.config import DEFAULT_CONFIG, normalize_config


REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DOCS = {
    "docs/ARCHITECTURE.md": ["# Agent-Friendly Architecture", "## 2. 模块分层"],
    "docs/PIPELINE_STAGES.md": ["# Pipeline Stages", "## Stage 4: 结构化提取"],
    "docs/AGENT_WORKFLOW.md": ["# Agent Workflow", "## 2. 每轮改动的推荐闭环"],
    "docs/QUALITY_GATES.md": ["# Quality Gates", "## 6. 最小 harness 入口"],
    "docs/KNOWN_GAPS.md": ["# Known Gaps", "## 3. 下一批最值得继续做的 harness"],
    "docs/CODEX_AGENT_FIRST_PLAYBOOK.md": ["# Codex Agent-First 八步手册", "## Step 8：最后做持续清理"],
    "docs/agent_harness_issues.md": ["# Agent-First Phase 1 Issues", "## AH-004 最小 Harness 与诊断命令"],
}

EXPECTED_REPORT_FIELDS = [
    "file",
    "url",
    "journal",
    "impact_factor",
    "impact_factor_year",
    "impact_factor_source",
    "impact_factor_status",
    "authors",
    "processing_status",
    "title",
    "structure",
    "eqe",
    "cie",
    "lifetime",
    "best_eqe",
    "optimization_level",
    "optimization_strategy",
    "optimization_details",
    "key_findings",
    "eqe_source",
    "cie_source",
    "lifetime_source",
    "structure_source",
]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ok(name: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": "ok", "detail": detail}


def _fail(name: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": "fail", "detail": detail}


def check_required_docs() -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for rel_path, markers in REQUIRED_DOCS.items():
        path = REPO_ROOT / rel_path
        if not path.exists():
            results.append(_fail(rel_path, "missing file"))
            continue
        content = _read_text(path)
        missing_markers = [marker for marker in markers if marker not in content]
        if missing_markers:
            results.append(_fail(rel_path, f"missing markers: {missing_markers}"))
            continue
        results.append(_ok(rel_path, "file and required sections exist"))
    return results


def check_agents_routes() -> dict[str, str]:
    agents_content = _read_text(REPO_ROOT / "AGENTS.md")
    required_routes = [
        "docs/ARCHITECTURE.md",
        "docs/PIPELINE_STAGES.md",
        "docs/AGENT_WORKFLOW.md",
        "docs/QUALITY_GATES.md",
        "docs/KNOWN_GAPS.md",
        "docs/CODEX_AGENT_FIRST_PLAYBOOK.md",
        "docs/agent_harness_issues.md",
    ]
    missing = [route for route in required_routes if route not in agents_content]
    if missing:
        return _fail("AGENTS routes", f"missing route entries: {missing}")
    return _ok("AGENTS routes", "all required route entries exist")


def check_report_contracts() -> dict[str, str]:
    report_fields = [field for _, field in ReportGenerator.REPORT_COLUMNS]
    if report_fields != EXPECTED_REPORT_FIELDS:
        return _fail("report columns", f"unexpected report fields: {report_fields}")
    if len(report_fields) != 23:
        return _fail("report columns", f"expected 23 columns, got {len(report_fields)}")
    return _ok("report columns", "field order and count are stable")


def check_default_config_contracts() -> dict[str, str]:
    config = normalize_config(DEFAULT_CONFIG)
    required_top_keys = {
        "mineru",
        "paddlex",
        "llm",
        "web_search",
        "cache",
        "output",
        "pdf",
        "cleaner",
        "desktop",
    }
    missing_top_keys = sorted(required_top_keys - set(config))
    if missing_top_keys:
        return _fail("default config", f"missing top-level keys: {missing_top_keys}")

    expected = {
        "mineru.mode": config["mineru"]["mode"] == "api",
        "output.format": config["output"]["format"] == ["excel"],
        "llm.provider": config["llm"]["provider"] == "longcat",
        "desktop.engine.mode": config["desktop"]["engine"]["mode"] == "bundled",
    }
    failed = [name for name, passed in expected.items() if not passed]
    if failed:
        return _fail("default config", f"unexpected defaults: {failed}")
    return _ok("default config", "top-level sections and key defaults are stable")


def run_checks() -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    checks.extend(check_required_docs())
    checks.append(check_agents_routes())
    checks.append(check_report_contracts())
    checks.append(check_default_config_contracts())
    return checks


def summarize(results: Iterable[dict[str, str]]) -> tuple[bool, list[dict[str, str]]]:
    materialized = list(results)
    all_ok = all(result["status"] == "ok" for result in materialized)
    return all_ok, materialized


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the agent-first harness baseline.")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    all_ok, results = summarize(run_checks())
    payload = {
        "ok": all_ok,
        "checks": results,
    }

    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for result in results:
            prefix = "[OK]" if result["status"] == "ok" else "[FAIL]"
            print(f"{prefix} {result['name']}: {result['detail']}")
        print(f"\nResult: {'PASS' if all_ok else 'FAIL'}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
