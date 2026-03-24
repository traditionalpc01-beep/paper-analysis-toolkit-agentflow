# Agent-First Phase 1 Issues

本文档把当前 1-4 步落地过程拆成可关闭的本地 issue，避免后续继续依赖口头约定。

状态说明：
- `OPEN`：已定义，未完成
- `IN_PROGRESS`：正在实现
- `CLOSED`：已实现并落到仓库

## AH-001 仓库架构地图与入口路由

- 状态：`CLOSED`
- 目标：把当前仓库的入口、模块层次、外部依赖和 agent 阅读顺序沉淀为可复用地图
- 拆分任务：
  - [x] 补充 `docs/ARCHITECTURE.md`
  - [x] 补充 `docs/PIPELINE_STAGES.md`
  - [x] 更新 `AGENTS.md` 路由表，让 agent 能快速定位新增文档
- 关闭证据：
  - `docs/ARCHITECTURE.md`
  - `docs/PIPELINE_STAGES.md`
  - `AGENTS.md`

## AH-002 System of Record 文档底座

- 状态：`CLOSED`
- 目标：把 agent 工作方式、知识来源和缺口记录为仓库内文档，而不是散落在对话里
- 拆分任务：
  - [x] 新建 `docs/AGENT_WORKFLOW.md`
  - [x] 新建 `docs/KNOWN_GAPS.md`
  - [x] 在文档中标出“代码里有、文档里还没有完全固化”的区域
- 关闭证据：
  - `docs/AGENT_WORKFLOW.md`
  - `docs/KNOWN_GAPS.md`

## AH-003 机械化约束与质量门禁

- 状态：`CLOSED`
- 目标：先固化边界和验收口径，再继续扩展功能
- 拆分任务：
  - [x] 新建 `docs/QUALITY_GATES.md`
  - [x] 为报表列顺序、配置默认值、agent 路由增加测试
  - [x] 把第一批需要机械检查的约束写清楚
- 关闭证据：
  - `docs/QUALITY_GATES.md`
  - `tests/test_quality_contracts.py`
  - `tests/test_agent_docs.py`

## AH-004 最小 Harness 与诊断命令

- 状态：`CLOSED`
- 目标：提供可以重复执行的检查入口，减少后续每轮都靠人工回忆
- 拆分任务：
  - [x] 新建 `scripts/check_agent_harness.py`
  - [x] 为检查脚本补测试
  - [x] 把检查项映射回 docs / code / tests
- 关闭证据：
  - `scripts/check_agent_harness.py`
  - `tests/test_agent_harness_check.py`

## AH-005 Codex 八步交互手册

- 状态：`CLOSED`
- 目标：把后续使用 Codex 的推荐交互方式沉淀成单独文档，方便重复使用
- 拆分任务：
  - [x] 新建 `docs/CODEX_AGENT_FIRST_PLAYBOOK.md`
  - [x] 给出每一步的目标、提示词模板、预期产物
- 关闭证据：
  - `docs/CODEX_AGENT_FIRST_PLAYBOOK.md`

## AH-006 Reporter 默认文件名契约不一致

- 状态：`CLOSED`
- 来源：执行 `python -m pytest tests/test_reporting_outputs.py tests/test_desktop_bridge.py -q` 时发现
- 现象：
  - `tests/test_reporting_outputs.py` 期望默认文件名前缀为 `论文分析报告_`
  - `paperinsight/core/reporter.py` 当前实际产出前缀为 `paperinsight_report_`
- 处理结果：
  - [x] 以已有 `README.md` 和测试契约为准，统一默认文件名前缀
  - [x] 更新 `paperinsight/core/reporter.py`
  - [x] 将该契约补进 `docs/QUALITY_GATES.md`
- 关闭证据：
  - `paperinsight/core/reporter.py`
  - `docs/QUALITY_GATES.md`
  - `tests/test_reporting_outputs.py`

## AH-007 提升最终 Excel 中 IF（影响因子）字段准确性

- 状态：`IN_PROGRESS`
- 来源：本轮分析请求“提升最终 Excel 中 IF（影响因子）字段准确性”
- 目标：梳理从期刊解析、IF 抓取、来源选择到 Excel 导出的整条链路，降低最终报表中 IF 数值、来源语义和状态语义不一致的风险
- 待分析范围：
  - `docs/impact_factor_rules.md`
  - `paperinsight/core/pipeline.py`
  - `paperinsight/web/journal_resolver.py`
  - `paperinsight/web/impact_factor_fetcher.py`
  - `paperinsight/core/reporter.py`
  - `tests/test_impact_factor_fetcher.py`
  - `tests/test_v31_features.py`
  - `tests/test_reporting_outputs.py`
- 预期产物：
  - 当前 IF 生成链路说明
  - Excel 中 IF 不准确的可能原因清单
  - 可逐步关闭的子任务拆分
- 本阶段已完成：
  - [x] 梳理 IF 生成链路并登记 issue
  - [x] 修正 pipeline 中“官方结果被次级来源抢占”的主路径
  - [x] 修正 `NO_ACCESS` 场景下状态优先落表，而不是自动写入公开回退值
  - [x] 让最终 Excel 默认导出 `impact_factor_year` / `impact_factor_source` / `impact_factor_status`
  - [x] 补 `tests/test_v31_features.py` 与 `tests/test_reporting_outputs.py` 的契约回归
  - [x] 明确“最终 Excel 取期刊当前可拿到的最新 IF，而不是论文发表当年的 IF”口径
  - [x] 调整次级来源选择逻辑，官方缺席时优先保留年份更新的 IF 结果
  - [x] 修正 `MULTI_MATCH` 场景，避免静默挑第一个候选期刊继续抓 IF
  - [x] 补 `tests/test_impact_factor_fetcher.py` 与 `tests/test_v31_features.py` 的 latest IF / `MULTI_MATCH` 回归
  - [x] 为 `NOT_VISIBLE` / `ERROR` 场景补端到端 pipeline 测试（`test_pipeline_falls_back_to_secondary_when_official_not_visible`, `test_pipeline_records_error_status_from_official_lookup`）
  - [x] 为 `NO_MATCH` 场景补端到端 pipeline 测试（`test_pipeline_sets_correct_status_when_journal_no_match`）
  - [x] 修复 `OK_STALE` 次级来源被 `_select_validated_impact_factor_result` 过滤掉的问题
  - [x] 修复 reporter 中 `impact_factor_year` 被错误转为字符串的类型问题
  - [x] 补充 `OK_STALE` 次级来源接受规则到 `docs/impact_factor_rules.md`
- 下一阶段待做：
  - [ ] 增加真实样例批量回归，核查测试 PDF 集中的 IF 来源分布与准确性
  - [ ] 考虑在 `_apply_impact_factor_status` 中让 `NOT_VISIBLE` 和 `ERROR` 也记录状态但保留后续回退路径（当前已实现）
- 当前已知风险：
  - `CURATED_FALLBACK` 仍可能给出旧年份值，用户虽然能在 Excel 中看到年份和 `OK_STALE` 状态，但数值本身仍可能过期
  - `STALE_YEAR_THRESHOLD` 固定为 2 年，未暴露为配置项；未来可考虑让用户通过配置调整
  - pytest + Python 3.13 + Windows 存在 symlink/挂载点兼容性问题（`WinError 448`），需要在 session finish 时忽略
- 关闭条件（预留）：
  - 契约、实现、测试三者对齐
  - 最终 Excel 的 IF 值、来源/状态表达与规则一致
  - 关键回归用例补齐

## 完成本轮后的默认工作方式

- 新问题先登记到这里或同类 issue 文档，再拆任务
- 复杂改动先出 execution plan，再进入代码实现
- 每轮改动结束后，优先补 docs、tests、script，而不是只停留在代码
