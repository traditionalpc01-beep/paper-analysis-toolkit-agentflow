# Schema / Pydantic Context

## 主要位置

- 核心数据模型：`paperinsight/models/schemas.py`
- 爬虫存储模型：`paperinsight/crawler/storage/models.py`
- 提取阶段校验入口：`paperinsight/core/extractor.py`
- 流水线使用入口：`paperinsight/core/pipeline.py`

## Agent 应该先看什么

- 想确认字段名、字段类型、是否允许为空：先看 `PaperInfo`、`DeviceData`、`PaperData`、`ExtractionResult`
- 想确认输出给 LLM 的 JSON Schema：看 `PAPER_DATA_JSON_SCHEMA`
- 想确认校验失败会在哪里暴露：看 `paperinsight/core/extractor.py` 中的 `ValidationError` 处理
- 想确认字段最终如何落到报表：看 `PaperData.to_excel_row()` 与 `paperinsight/core/reporter.py`

## 相关测试

- 结构化输出与字段回归：`tests/test_prd_regression.py`
- v3.1 行为回归：`tests/test_v31_features.py`
- 报表输出字段：`tests/test_reporting_outputs.py`

