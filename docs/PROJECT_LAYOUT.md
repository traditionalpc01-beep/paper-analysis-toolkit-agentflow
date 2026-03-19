# Project Layout

```text
paperinsight/
  agentflow/
    identity.py
    pipeline.py
  cleaner/
    section_filter.py
  core/
    cache.py
    extractor.py
    reporter.py
  llm/
    base.py
    longcat_client.py
    prompt_templates.py
  models/
    schemas.py
  parser/
    base.py
    mineru.py
  utils/
    config.py
    config_crypto.py
    hash_utils.py
    logger.py
    pdf_utils.py
    terminal.py
  cli.py
docs/
  AGENTFLOW.md
  PROJECT_LAYOUT.md
config/
  config.example.yaml
tests/
  test_agentflow_prepare.py
  test_api_integrations.py
  test_project_layout.py
```

## Module Notes

- `agentflow/`: owns filesystem artifacts for each stage.
- `cleaner/`: compresses MinerU Markdown before LLM extraction.
- `core/extractor.py`: calls Longcat and normalizes structured paper data.
- `core/reporter.py`: writes the final Excel/JSON report and returns file paths.
- `parser/mineru.py`: talks to MinerU v4 and handles archive download retry/fallback.
- `utils/config.py`: loads the small runtime config surface for this cleaned project.
