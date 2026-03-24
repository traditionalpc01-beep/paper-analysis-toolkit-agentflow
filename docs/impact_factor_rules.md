# 影响因子规则

## 适用范围

本文只整理当前仓库里可验证的影响因子处理规则，供 Agent 在排查、改动和验收时对齐上下文。规则来源以实现代码和测试为准，主要对应：

- `paperinsight/core/pipeline.py`
- `paperinsight/web/impact_factor_fetcher.py`
- `paperinsight/web/journal_resolver.py`
- `tests/test_impact_factor_fetcher.py`
- `tests/test_v31_features.py`
- `tests/test_reporting_outputs.py`

## 验收口径

### 1. 先补期刊上下文，再补影响因子

- 影响因子补全依赖期刊匹配结果，先走期刊解析，再决定是否抓取影响因子。
- 补全过程中允许使用原始期刊名、ISSN、eISSN 作为检索输入。
- 成功匹配后，期刊标准标题、匹配 ISSN、匹配方式要回填到 `PaperInfo`。

### 2. 官方来源优先

- 能从 MJL 官方资料拿到结果时，优先使用官方来源。
- 当前实现里的官方主来源标记为 `MJL_PROFILE_API`。
- 若已有影响因子与官方结果不一致，且开启纠正逻辑，则应以官方结果覆盖旧值。

### 3. `NO_ACCESS` 不是报错，而是明确状态

- 当 MJL profile 接口返回未授权/无访问权限时，状态应记为 `NO_ACCESS`。
- `NO_ACCESS` 场景下：
  - `impact_factor` 保持为空；
  - `impact_factor_source` 记录为触发该状态的来源，当前验收样例为 `MJL_PROFILE_API`；
  - `impact_factor_status` 必须是 `NO_ACCESS`；
  - 已成功解析出的 `matched_journal_title`、`match_method` 等期刊上下文仍应保留。
- 仅凭 `NO_ACCESS` 不能把该期刊当成未匹配，也不能清空已拿到的期刊标准化信息。

### 4. 无查询值、无匹配、无可见值要区分

- 没有可用于查询的期刊信息：`NO_QUERY`
- 有查询动作但未匹配到期刊或回退来源：`NO_MATCH`
- 查到了 profile，但 payload 中没有可用影响因子：`NOT_VISIBLE`
- 请求异常或非预期失败：`ERROR`

这些状态在排查时不能混用；Agent 需要先确认是哪一层返回的状态，再决定改解析、改回退还是改展示。

### 5. 回退来源只在对应条件下使用

- 官方 profile 成功时，直接使用官方结果。
- 官方 profile 返回 `NO_ACCESS` 时，最终报表优先保留 `NO_ACCESS` 状态，不自动把公开回退值写进最终 IF 单元格。
- 官方 profile 因无匹配、无可见值或异常无法给出可用值时，允许进入回退逻辑。
- 当前实现的回退来源标记为 `CURATED_FALLBACK`。
- 回退成功时结果状态转为 `OK`，但可同时保留原始失败原因到错误信息中，供日志或调试使用。

### 6. 影响因子值与年份的基本约束

- 影响因子提取时只接受合理数值范围内的值；当前 fetcher 验收范围是 `0.1` 到 `200`。
- 年份需要是可识别的报告年份；当前 fetcher 接受的年份范围是 `2000` 到 `2100`。
- 最终 Excel 里的 IF 口径是“该期刊当前可拿到的最新 IF”，而不是论文发表当年的 IF。
- 当同一 payload 中出现多个候选值时，优先选择年份更新、数值也更可信的候选项；当前实现按“年份优先、数值次之”排序。
- 当官方来源不可用，只能在次级来源之间选择时，也应优先保留年份更新的结果，而不是仅按来源优先级选旧年份值。

### 7. 支持多种 JIF 字段形态

当前验收已覆盖的可识别形态包括：

- 显式 `jif`
- `impactfactor`
- `journalimpactfactor`
- 带年份后缀的 `jif2024`、`jif2023`
- 由 `citationReportYear`、`reportYear`、`year`、`jifYear` 提供年份上下文的组合

Agent 若扩展字段识别，需保证不破坏上述既有形态。

### 8. ISSN-only 场景也必须能落状态

- 即使没有原始期刊标题，只要有 `ISSN` / `eISSN` 并成功完成期刊解析，后续影响因子流程仍应继续。
- 在这种场景下，如果官方来源返回 `NO_ACCESS`，也必须正确写回：
  - `matched_journal_title`
  - `match_method`
  - `impact_factor_source`
  - `impact_factor_status`

### 8.1 `MULTI_MATCH` 不能静默挑一个候选继续查 IF

- 当期刊解析结果是 `MULTI_MATCH` 且无法唯一确定候选期刊时，不应默认选列表中的第一个候选继续抓 IF。
- 这种场景下应优先保留 `MULTI_MATCH` 状态，等待更强的期刊上下文（如 ISSN / eISSN / 更精确标题）再继续。
- 不能为了填出 Excel 中的 IF 数值而牺牲期刊匹配准确性。

### 9. 报表输出要保留状态型字段

- 报表层除了影响因子数值，还需要能输出：
  - `impact_factor_year`
  - `impact_factor_source`
  - `impact_factor_status`
- 当数值为空但状态存在时，状态字段仍应可见，不能因为没有数值就丢失来源或状态。
- 最终 Excel 默认导出中也应保留这些 IF 审计字段，避免用户只看到裸数值而无法判断可信度。
- `impact_factor_year` 在 Excel 中应保持为整数类型（`int`），不应被转为字符串。

### 10. `OK_STALE` 结果仍可被接受为有效次级来源

- `OK_STALE` 表示回退来源有值，但年份超过了 `STALE_YEAR_THRESHOLD`（当前为 2 年）。
- 在次级来源筛选（`valid_secondaries`）中，`OK_STALE` 与 `OK` 同等对待，不会被过滤掉。
- 有过期数据总比没有数据好，但必须通过 `OK_STALE` 状态告知用户数据可能过期。
- 当有多个次级来源时，排序逻辑会优先选择年份更新的结果（`_impact_factor_result_sort_key` 中年份为第一优先级）。

### 11. 改动时优先对齐测试

与影响因子规则直接相关的回归测试优先看：

- `tests/test_impact_factor_fetcher.py`
- `tests/test_v31_features.py`
- `tests/test_reporting_outputs.py`

如果实现行为与文档冲突，以这些测试和对应代码路径为准，再更新文档。
