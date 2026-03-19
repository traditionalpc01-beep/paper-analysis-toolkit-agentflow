# AGENTS Route Table

- Project goal, install steps, command overview -> `README.md`
- Clean module map -> `docs/PROJECT_LAYOUT.md`
- Agent stage contract and output files -> `docs/AGENTFLOW.md`
- CLI entry and user-facing commands -> `paperinsight/cli.py`
- Prepare/import/extract/finalize orchestration -> `paperinsight/agentflow/pipeline.py`
- Identity matching payloads and validation -> `paperinsight/agentflow/identity.py`
- Shared paper schema and Excel row mapping -> `paperinsight/models/schemas.py`
- Longcat extraction logic -> `paperinsight/core/extractor.py`, `paperinsight/llm/longcat_client.py`, `paperinsight/llm/prompt_templates.py`
- MinerU API integration and download fallback -> `paperinsight/parser/mineru.py`
- Report export and final path output -> `paperinsight/core/reporter.py`
- Config defaults and secret handling -> `paperinsight/utils/config.py`, `paperinsight/utils/config_crypto.py`
- Regression coverage for the cleaned project -> `tests/`
