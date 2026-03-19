# AgentFlow Stages

This project uses a four-stage, agent-first workflow.

## Stage 1: `paperinsight agent prepare`

Goal:
- parse PDFs with MinerU
- cache Markdown when possible
- create one identity job per paper

Outputs:
- `manifest.json`
- `papers/<paper_key>/01_parse.md`
- `papers/<paper_key>/01_parse_meta.json`
- `papers/<paper_key>/02_identity_job.json`
- `jobs/identity_jobs.jsonl`
- `jobs/identity_results.jsonl`
- `jobs/identity_prompt.md`

## Stage 2: `paperinsight agent import-identity`

Goal:
- import agent or IDE web-search results
- validate the result schema
- persist matched journal and latest impact factor

Outputs:
- `papers/<paper_key>/03_identity_result.json`
- `papers/<paper_key>/03_paper_data.json`
- `jobs/identity_import_summary.json`

Required JSONL fields:
- `paper_key`
- `matched`
- `paper_identifier`
- `matched_title`
- `journal_name`
- `impact_factor`
- `impact_factor_year`
- `impact_factor_source`
- `impact_factor_status`
- `evidence_urls`
- `notes`

## Stage 3: `paperinsight agent extract-metrics`

Goal:
- clean MinerU Markdown
- run Longcat on one paper at a time
- produce metric-rich paper data while preserving imported identity fields

Outputs:
- `papers/<paper_key>/04_metrics_result.json`
- `papers/<paper_key>/04_metrics_meta.json`
- `jobs/metrics_summary.json`

Notes:
- the pipeline merges `03_paper_data.json` into the Longcat result
- `04_metrics_result.json` is the preferred source for finalize

## Stage 4: `paperinsight agent finalize`

Goal:
- merge identity + metrics data
- export Excel and optional JSON
- print final report paths

Outputs:
- `papers/<paper_key>/05_final_paper_data.json`
- `reports/paperinsight_report_<timestamp>.xlsx`
- `reports/paperinsight_report_<timestamp>.json`
- `jobs/finalize_summary.json`

Finalize merge rules:
1. use `04_metrics_result.json` when it exists
2. overlay journal and impact-factor fields from `03_paper_data.json`
3. fall back to `03_paper_data.json` when metrics are missing
4. export incomplete rows instead of dropping failed papers
