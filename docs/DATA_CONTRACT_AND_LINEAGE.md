# 数据结构文档与血缘规范

本规范定义“完整数据结构文档”和“完整数据血缘”的最低标准。两者都是训练前置条件，
不是训练完成后的补充材料。

## 1. 完整数据结构文档

每个进入 canonical、PIT、特征、标签或训练集的集合都必须有一个内容寻址的 schema 清单。
清单 ID 格式为 `schema_<sha256>`，正文存放于 `schemas/`，并登记到
`meta_schema_manifests`。

每个字段必须记录：

- 字段名和业务中文名。
- 数据类型、是否允许为空以及空值的业务含义。
- 单位、币种、精度、时区和日期格式。
- 来源接口与来源字段。
- `event_time`、`available_at`、`ingested_at` 中承担的时间角色。
- 原始价、前复权、后复权或非价格口径。
- 枚举值、合法范围和质量校验规则。
- 首次引入版本、废弃版本和兼容策略。
- 是否允许进入特征、标签、成交模拟或仅用于审计。

缺少任一实际字段、使用未登记动态字段、字段含义写成“参考上游”或没有空值语义，均视为
文档不完整。

## 2. Raw 快照契约

`meta_source_snapshots` 至少包含：

| 字段 | 类型 | 含义 |
|---|---|---|
| `snapshot_id` | string | 请求与响应内容计算的不可变 ID |
| `source` | string | 固定为 `tushare` |
| `endpoint` | string | Tushare 接口名 |
| `request_params_canonical` | string | 排序并规范化后的请求参数 JSON |
| `requested_at` | datetime | 发起请求时间，Asia/Shanghai |
| `completed_at` | datetime | 完成响应时间 |
| `provider_version` | string/null | 可获得时记录供应商版本 |
| `row_count` | int | 原始响应行数 |
| `payload_sha256` | string | 规范化原始响应哈希 |
| `schema_manifest_id` | string | 本次响应使用的 Raw schema |
| `status` | enum | `RECEIVED/QUARANTINED/ACCEPTED/REJECTED` |

每个 `raw_tushare_*` 文档至少包含：

| 字段 | 类型 | 含义 |
|---|---|---|
| `snapshot_id` | string | 所属原始快照 |
| `row_ordinal` | int | 供应商响应中的稳定行序 |
| `ingested_at` | datetime | 本系统写入时间 |
| `payload` | document | 不改名、不换单位的供应商原始行 |
| `row_sha256` | string | 规范化单行内容哈希 |

Raw 唯一键为 `(snapshot_id, row_ordinal)`，并额外索引 `row_sha256`。Raw 文档不得原地更新。

## 3. Canonical 公共信封

所有 canonical 文档除业务字段外必须包含：

| 字段 | 类型 | 含义 |
|---|---|---|
| `record_id` | string | 规范业务键和版本计算的内容 ID |
| `schema_manifest_id` | string | 当前集合字段结构版本 |
| `source_snapshot_id` | string | 直接来源 Raw 快照 |
| `source_row_sha256` | string | 直接来源 Raw 行 |
| `transform_name` | string | 转换器稳定名称 |
| `transform_version` | string | 转换代码语义版本 |
| `event_time` | datetime/date | 市场或经济事件时间 |
| `available_at` | datetime | 历史当时最早允许使用时间 |
| `ingested_at` | datetime | 实际写入时间 |
| `quality_status` | enum | `QUARANTINED/ACCEPTED/REJECTED` |
| `quality_report_id` | string | 对应质量报告 |

业务自然键、版本键和字段结构由 `docs/TUSHARE_DATA_PLAN.md` 对应接口的 schema 清单定义。

## 4. PIT 股票池事件契约

`pit_security_events` 使用独立的 `schemas/tushare_universe_v1.json`，每条事件至少包含：

| 字段 | 含义 |
|---|---|
| `event_id` | Raw 快照、Raw 行、事件类型、输出 schema 和转换版本计算的稳定 ID |
| `event_type` | `LISTED/FIRST_TRADED/DELISTED/NAME_STATUS` 闭集 |
| `effective_at` | 状态开始生效的市场时间 |
| `available_at` | 该事实最早允许被决策读取的时间 |
| `ingested_at` | 首次持久化的系统观察时间 |
| `input_schema_manifest_id` | 直接输入 schema；日线 fallback 与 universe 输出 schema 可不同 |
| `schema_manifest_id` | PIT 输出 schema，查询和数据集必须精确固定此 ID |
| `quality_report_id` | 与本事件一一对应的质量证据 |

事件查询必须同时满足 `quality_status=ACCEPTED`、`effective_at <= decision_time` 和
`available_at <= decision_time`。`SecurityState` 不携带未来退市日期；名称/ST 未知保留
`null` 并 fail closed。`stock_basic` canonical 快照继续 `QUARANTINED`，其受审生命周期字段
只能经事件转换使用，不能直接作为历史 PIT。

## 5. 血缘图

`meta_lineage_edges` 的每条边表示一个产物如何由上游产物生成，至少包含：

| 字段 | 类型 | 含义 |
|---|---|---|
| `lineage_edge_id` | string | 内容寻址边 ID |
| `upstream_artifact_id` | string | Raw 快照、canonical 快照或数据集 ID |
| `downstream_artifact_id` | string | canonical、PIT、特征、标签或训练集 ID |
| `transform_name` | string | 生成逻辑名称 |
| `transform_version` | string | 生成逻辑版本 |
| `code_commit` | string | Git commit |
| `input_schema_ids` | array[string] | 输入 schema 清单 |
| `output_schema_id` | string | 输出 schema 清单 |
| `parameters_sha256` | string | 规范化参数哈希 |
| `executed_at` | datetime | 执行时间 |

字段级血缘另外记录：

```text
downstream_collection.field
    <- transform expression/version
    <- upstream_collection.field
    <- raw_tushare_endpoint.payload.field
    <- source_snapshot_id
```

只记录“训练集来自行情和财务”不属于完整血缘。

PIT 事件的每条 lineage 必须把 `ts_code`、生效日期、名称和 ST 派生分别映射到对应 Raw 字段。
`FIRST_TRADED` 允许从 accepted `canonical_daily_bar` 跨 schema 派生，但必须保留日线 Raw
快照和 `trade_date` 字段映射，且不能声称它是精确上市日期。

分红使用独立 `schemas/tushare_corporate_actions_v1.json`。`canonical_dividend_event` 必须保持
`QUARANTINED`，因为同一供应商行同时携带方案和实施阶段字段。`PLAN_ANNOUNCED` 只能映射
`ann_date` 与方案字段，实施日期必须为 `null`；只有 `IMPLEMENTATION_ANNOUNCED` 可以映射
`imp_ann_date`、`record_date`、`ex_date`、`pay_date` 和 `div_listdate`。每个公告自然日还必须
具有独立 PIT 批次 artifact、质量报告和 lineage，空响应也不得省略。

利润表使用 `schemas/tushare_financials_v1.json`。每个 `FINANCIAL_VERSION_PUBLISHED` 事件按
`f_ann_date`、`ann_date`、首次观察时间的优先级确定可得时间，并保留 `report_type`、
`comp_type`、`end_type` 和 `update_flag` 版本身份。canonical 不允许直接进入特征；空股票响应
也必须生成范围批次质量和 lineage。

资产负债表使用独立 `schemas/tushare_balance_sheet_v1.json`，不得修改利润表清单来追加字段。
`canonical_balance_sheet` 必须保持 `QUARANTINED`，研究只能读取 `pit_balance_sheets` 中
`ACCEPTED` 且在决策时点已发布的版本。每个版本按实际公告时钟保留负债、资产、权益和版本身份的
字段级映射；空股票响应同样必须生成范围批次质量和 lineage。

现金流量表使用独立 `schemas/tushare_cashflow_v1.json`。`canonical_cashflow_statement` 必须
保持 `QUARANTINED`，经营、投资、筹资现金流及现金等价物字段只能通过实际公告时钟生成的
`pit_cashflow_statements` 版本进入后续数据集。每个版本与空股票响应都必须具备质量和字段级
lineage，不得用利润表或资产负债表的完成证据代替。

财务指标使用独立 `schemas/tushare_financial_indicator_v1.json`。供应商没有 `f_ann_date`，
因此 `ann_date` 18:00 是唯一历史公告时钟；缺失时只能从首次观察时间起可用。指标 canonical
必须保持 `QUARANTINED`，每股、盈利能力、偿债能力、周转率、现金流覆盖和同比增长字段只能从
accepted `pit_financial_indicators` 读取。

基准数据使用独立 `schemas/tushare_benchmarks_v1.json`。`index_basic` 是观察时点主数据，
不能从 `base_date/list_date` 倒推历史可得性；`index_daily` 按交易日收盘后时钟进入 accepted
canonical。`canonical_index_membership` 必须保持 `QUARANTINED`，每条权重只能通过
`INDEX_WEIGHT_PUBLISHED` 事件进入 `pit_index_weights`。事件 lineage 必须逐字段映射
`index_code/con_code/trade_date/weight` 到 Raw，并记录 `effective_at/available_at` 的收盘后
时钟。每个“指数×自然月”请求还必须生成独立 PIT 批次 artifact、质量报告和 lineage；零行
响应不得省略。研究数据集只能固定单一 benchmark manifest，禁止与旧市场级截断快照混读。

行业数据使用独立 `schemas/tushare_industry_v1.json`。`index_classify` 记录当前观察到的 SW2021
层级；`canonical_industry_membership` 必须保持 `QUARANTINED`。`pit_industry_memberships` 的
`effective_from/effective_to` 映射 `in_date/out_date`，但 `available_at` 必须映射 Raw 快照首次
观察时间。字段 lineage 必须保留 `index_code/con_code/in_date/out_date/is_new`，并通过
`index_code` 关联同 manifest 的分类主表。不得把有效区间起点解释为发布日期。

## 6. 训练必须能回答的问题

任何训练运行在开始拟合前必须自动回答：

1. 每个训练列的数据类型、单位、空值语义和特征定义是什么？
2. 每个特征值来自哪些 Raw 快照、接口和字段？
3. 使用了哪个转换版本、代码提交和参数？
4. 当时为什么允许在 `decision_time` 使用这条数据？
5. 标签由哪些未来价格构造，为什么没有进入特征路径？
6. 历史股票池如何包含退市、停牌、ST 和成分变化？
7. 数据发生变化后，为什么会生成新的 dataset ID？

任一问题无法由持久化清单回答时，`complete_schema_documentation` 或
`complete_data_lineage` 必须为 `false`，`ModelTrainingGuard` 必须拒绝训练。

## 7. 训练产物引用

`DatasetSpec` 必须包含：

- `coverage_report_id` 和 `input_manifest_id`
- `source_snapshot_ids`
- `schema_manifest_id`
- `input_schema_manifest_ids`
- `lineage_manifest_id`
- `feature_artifact_ids` 与 `feature_lineage_edge_ids`
- `label_artifact_id` 与 `label_lineage_edge_ids`
- 历史股票池版本
- 特征和标签版本
- 规则版本与覆盖区间

`ExperimentManifest` 再次固定 dataset、schema 和 lineage ID，避免训练完成后替换文档。
schema、血缘、数据或转换任一物质变化都必须生成新的 dataset ID。

跨表覆盖产物使用 `schemas/research_dataset_v1.json`。`dataset_coverage_reports` 保存请求区间、
必需组件和资格结果；`dataset_component_coverage` 分别固定每个组件的日期、schema、Raw 快照、
lineage、质量与 PIT 证据；只有 `QUALIFIED` 报告可以生成 `dataset_input_manifests`。BLOCKED
报告允许保留审计，但不得关联 input manifest。

## 8. 当前状态

首批 9 个接口 `trade_cal`、`stock_basic`、`namechange`、`daily`、`adj_factor`、`daily_basic`、
`stk_limit`、`suspend_d` 和 `dividend` 已具有机器可读 Raw/canonical 字段契约，并启用 canonical 转换、
PIT 时间、canonical 质量报告和字段级 lineage。零行批次也必须记录输入与输出 schema ID，不能因没有
业务行而丢失血缘或改变预定质量状态。

截至 `2026-07-16`，日频 schema `1.1.1` 包含 7,912 条 Raw 到 canonical lineage 边，关联的
7,912 份 canonical 质量报告全部通过；日频数据完整覆盖 1,581 个交易日，区间为
`2020-01-02` 至 `2026-07-14`。不存在 `RECEIVED`、`REJECTED` 或待补日期。
universe schema `1.1.1` 当前 manifest 为
`schema_49b36e8944a757ca01f221a1f3137e8605dd49ec2ea5d561b7d258ac84a141da`，包含 26,206 条
accepted PIT 事件、26,206 份通过的逐事件质量报告和 26,206 条字段级 lineage，缺失均为 0。
所有 accepted 日线代码均有生命周期入口；唯一 fallback `300114.SZ` 保持名称/ST 未知。
corporate-action schema `1.0.0` 包含 159,060 条 accepted 分红 PIT 事件，每条都有通过的质量
报告和字段级 lineage；2,389 个公告自然日均有 PIT 批次质量和 lineage，覆盖
`2020-01-01` 至 `2026-07-16`，缺失为 0。
financial schema `1.0.0` 的利润表覆盖 5,867 个历史生命周期代码，包含 197,571 条 accepted
PIT 版本、同量质量报告和字段级 lineage，以及 5,867 份通过的范围批次证据。
balance-sheet schema `1.0.0` 的资产负债表覆盖同一组 5,867 个代码，包含 189,004 条 accepted
PIT 版本、同量质量报告和字段级 lineage，以及 5,867 份通过的范围批次证据；68 个空响应没有
被省略或误判为无须治理。
cash-flow schema `1.0.0` 覆盖同一组 5,867 个代码，包含 214,552 条 accepted PIT 版本、同量
质量报告和字段级 lineage，以及 5,867 份通过的范围批次证据；70 个空响应保持显式证据。
financial-indicator schema `1.0.0` 覆盖同一组 5,867 个代码，包含 214,192 条 accepted PIT
版本、同量质量报告和字段级 lineage，以及 5,867 份通过的范围批次证据；61 个空响应保持显式
证据，8 条公告日缺失记录只使用首次观察时钟。
benchmark schema `1.0.2` 当前 manifest 为
`schema_cd92111d31e7f5ff60777851a81f3b76c7d749d967ac50cacec7c262d3b6b1d8`。六个基准的
`index_daily` accepted canonical 共 8,936 条；五个加权指数的 `index_weight` Raw、
quarantined canonical、accepted PIT、逐事件质量和字段级 lineage 均为 181,600 条。
395 个“指数×月份”批次均有通过的批次质量与 lineage，其中 39 个是显式零行响应。北证 50
基日缺失 OHLC 不做填补，权重在指数发布前的空月不伪造成历史成员。
industry schema `1.0.1` 当前 manifest 为
`schema_00ba78ad478ccfc33108151d518b2f7470bfca25f3947bf7ee142458670d47ae`。分类主表包含
511 行，31 个一级行业成员批次共 7,727 行；quarantined canonical、accepted PIT、逐事件
质量和 lineage 均为 7,727 条，批次质量和 lineage 均为 31 条。当前事实只有观察时点之后的
知识效力，不能补足观察时点之前的历史行业可得性。
历史回填完成状态必须由 accepted Raw、当前 schema lineage 与通过的 canonical 质量报告联合
证明，不使用独立游标冒充数据事实。

18 个 P0 接口已具有字段清单，但跨表组合质量门禁、观察日前历史行业可得性、特征和标签
lineage 尚未完成。baseline 输入覆盖报告
`coverage_79a6511780bf5ddefe13a0bfedfececde195ac897107649a306a983b9d95b0e5`
已对 `2020-01-02` 至 `2026-06-16` 的五表日频、PIT 股票池和沪深 300 日线完成资格审查；
对应 input manifest 为
`inputs_dfb1ee67335e98b1fb29975c6c552cd4e4054912e50dab04d3403bbe55298a84`，固定
7,850 个 Raw 快照和 34,017 条输入 lineage。行业组件最早可得日为 `2026-07-17`，未进入该
历史 baseline。特征和标签尚未物化，因此没有生成 `DatasetSpec`，正式训练门禁保持关闭，
不得把当前 Raw
或 canonical 快照直接作为训练数据集。
