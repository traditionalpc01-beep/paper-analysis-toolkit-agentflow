# PaperInsight AgentFlow

`PaperInsight AgentFlow` is a clean, agent-first PDF paper analysis toolkit.
It keeps the refactored workflow only:

1. Use MinerU API to turn each PDF into Markdown.
2. Use IDE agents or web-enabled tools to match the paper and fill journal + latest impact factor.
3. Use Longcat to extract the remaining metrics from the Markdown, one paper per thread.
4. Merge identity data and metrics data into Excel/JSON reports.
5. Return the final report path after the run finishes.

## What This Repo Contains

- A focused CLI for the new agent-first workflow.
- MinerU parser integration with retry and SSL EOF download fallback.
- Longcat-based metric extraction.
- Incremental finalization that merges `03_paper_data.json` and `04_metrics_result.json`.
- Minimal tests covering the new flow only.

## Project Layout

- `paperinsight/cli.py`: CLI entrypoint.
- `paperinsight/agentflow/`: prepare, identity import, metrics extraction, finalize.
- `paperinsight/parser/mineru.py`: MinerU API adapter.
- `paperinsight/core/extractor.py`: Longcat-driven metric extraction.
- `paperinsight/core/reporter.py`: Excel/JSON export.
- `paperinsight/models/schemas.py`: shared paper schema.
- `docs/AGENTFLOW.md`: stage-by-stage artifact contract.
- `docs/PROJECT_LAYOUT.md`: compact module map.

## Install

```bash
git clone <your-repo-url>
cd paper-analysis-toolkit-agentflow
pip install -r requirements.txt
pip install -e .
```

## Configuration

Runtime config is loaded from `~/.paperinsight/config.yaml`.
The repo only keeps `config/config.example.yaml` as a template.

Required keys for the refactored flow:

- `mineru.token`
- `llm.api_key`
- `llm.provider=longcat`

Copy the example if you need a fresh local config:

```powershell
New-Item -ItemType Directory -Force "$HOME/.paperinsight" | Out-Null
Copy-Item config/config.example.yaml "$HOME/.paperinsight/config.yaml"
```

Sensitive fields are encrypted before saving by `paperinsight.utils.config_crypto`.

## CLI Workflow

### 1) Prepare MinerU outputs

```bash
paperinsight agent prepare ./pdfs
```

Output per paper:

- `01_parse.md`
- `01_parse_meta.json`
- `02_identity_job.json`

Run-level artifacts:

- `manifest.json`
- `jobs/identity_jobs.jsonl`
- `jobs/identity_results.jsonl`
- `jobs/identity_prompt.md`

### 2) Import identity matching results

Fill `jobs/identity_results.jsonl` with one JSON line per paper, then run:

```bash
paperinsight agent import-identity <run_dir>
```

This generates:

- `03_identity_result.json`
- `03_paper_data.json`

### 3) Extract metrics with Longcat

```bash
paperinsight agent extract-metrics <run_dir>
```

This generates:

- `04_metrics_result.json`
- `04_metrics_meta.json`

Recommended usage: one paper per clean thread so the model stays inside context limits.

### 4) Finalize reports

```bash
paperinsight agent finalize <run_dir> --json
```

Finalize behavior:

- prefers `04_metrics_result.json`
- overlays identity fields from `03_paper_data.json`
- falls back to `03_paper_data.json` when metrics are missing
- exports incomplete rows instead of silently dropping papers

Generated outputs:

- `reports/paperinsight_report_<timestamp>.xlsx`
- `reports/paperinsight_report_<timestamp>.json`

The CLI prints the final report path directly.

## Artifact Contract

A typical run looks like this:

```text
agent_runs/
  run_20260319_120000/
    manifest.json
    jobs/
      identity_jobs.jsonl
      identity_results.jsonl
      metrics_summary.json
      finalize_summary.json
    papers/
      0001_sample_abcd1234/
        01_parse.md
        01_parse_meta.json
        02_identity_job.json
        03_identity_result.json
        03_paper_data.json
        04_metrics_result.json
        04_metrics_meta.json
        05_final_paper_data.json
    reports/
      paperinsight_report_20260319_122253.xlsx
      paperinsight_report_20260319_122253.json
```

## Validation

```bash
python -m pytest tests/test_agentflow_prepare.py tests/test_api_integrations.py tests/test_project_layout.py -q
```

## Current Scope

This cleaned project intentionally does not keep the old desktop shell, legacy web crawlers, packaging scripts, PRD archives, or unrelated regression suites.
The repo now starts from the refactored agent-first workflow only.
