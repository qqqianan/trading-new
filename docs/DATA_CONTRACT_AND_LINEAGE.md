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

研究表使用 `schemas/research_feature_row_v1.json`、`research_label_row_v1.json`、
`research_universe_row_v1.json` 和 `research_dataset_row_v1.json` 四个机器可读精确列契约。
`ResearchSchemaCatalog` 以文件字节计算 schema ID；`ParquetArtifactStore` 只接受 catalog 中登记的
kind/schema 组合，并在原子发布前校验列顺序、物理类型、非空约束、row count 和 SHA-256。
每个输出列必须通过结构化 `ArtifactFieldMapping` 指向已声明的上游 artifact/snapshot 字段和转换，
部分字段映射不算完整 lineage。feature 与 label 使用独立物理目录，读取 descriptor 不能跨 kind
重标记；截断 payload、manifest 不一致或 schema 漂移均 fail closed。

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

18 个 P0 接口已具有字段清单；观察日前历史行业可得性仍未完成。
当前输入覆盖报告
`coverage_b25d100af1004281b57e8b38abc6198e491b0fb02b955328727456af9923c273`
已对 `2020-01-02` 至 `2026-07-16` 的日频 bundle、PIT 股票池、财务指标 PIT 和中证 500 日线
完成资格审查；对应 input manifest 为
`inputs_6749e8d049d37b0051bb6988101edd034cfebb70d5f485fb33fee89575646371`，固定
13,829 个 Raw 快照和 285,828 条输入 lineage。身份集合使用最多 1,000 个 ID 的内容寻址块保存，
主文档同时固定完整集合的数量与 SHA-256；重复资格审查不会追加重复证据。行业组件最早可得日为
`2026-07-17`，要求其覆盖历史区间时报告为 `BLOCKED` 且不生成 input manifest。全部 21 个基础特征、
独立标签和逻辑 `DatasetSpec` 已经物化。训练仍不得直接读取 Raw、canonical 或孤立 artifact；下一阶段
还必须完成最终测试封存、purged walk-forward 与训练折内预处理，正式模型训练门禁保持关闭。

周频 PIT 股票池已物化为
`universe_artifact_a5e618d3b4273bc97b8720bc8a31808fed91d00446cfb5e60a6f9cac6040de1b`，
绑定 input manifest `inputs_6749e8d049d37b0051bb6988101edd034cfebb70d5f485fb33fee89575646371`、
lineage manifest `lineage_01f090433e379b2ac0077894f87ffe495c6fadcf913181f9fc45739c133f9b2e`、
代码提交 `831bb3cb6a790b9ffcc7cd74f9bad2ab594dfe90` 和规则版本
`universe_rules_d13c287805d7ae8cb6b13ea90d4ee37f815e1fa27334096cb30ffc0aa09a6d6b`。
产物覆盖 334 个完整周决策、5,866 个历史代码和 1,712,992 行；首末决策分别为
`2020-01-03 18:00 +08:00` 与 `2026-07-10 18:00 +08:00`，不把截止于周四的
`2026-07-16` 误当成完整周。自然键重复和 `available_at > decision_time` 均为 0。
现有 accepted 交易日历从 2020 年开始，因此此前上市标的在累计到 120 个有证据交易日之前仍
保守标记为 `INSUFFICIENT_LISTING_AGE`；不使用自然日猜测或当前状态放宽该门禁。

15 个行情、风险、流动性、规模与估值因子已使用代码提交
`ed164be79870b37f33da8b1447ba4b453594b3e2` 物化。每个因子独立保存 1,712,992 行，绑定同一
input manifest、universe artifact 和各自字段映射/lineage edge；feature row schema 为
`schema_90618062b54a7d5b45d543dcd3b3da5dcdf2aab4952aadb3d6826afd5e7ce922`。

| Feature | Artifact ID |
|---|---|
| `mom_20` | `feature_artifact_caabbff8de5c733df39f35f5404761bed004d3288451f75d820882c83dbc3fd6` |
| `mom_60` | `feature_artifact_95da0f68b63e71675eb7604640351501d07ce111e2dc5d8978306b5c80b1b57c` |
| `mom_120` | `feature_artifact_2dad0a3fc639f46fdb4bec53be4da329857cbace7aaa05325dcbc472b661307b` |
| `reversal_5` | `feature_artifact_9fefdc76972748084a4ea43941568fa230e2fffe5d9ff5f8e069130e1b28c9ef` |
| `vol_20` | `feature_artifact_9ee479f7fabec8cb4e007ca629c9f3a6865226c7c4924ce4a4b974d7d41b349a` |
| `vol_60` | `feature_artifact_b01b0f8092fe141c05c823c080b500b654f19a62e797423c4ea7cfa8d9eff614` |
| `max_drawdown_60` | `feature_artifact_e5cea4b1191cc88b971ed67e9705f94b0426b97072c59b086341a27e68c0d4ab` |
| `turnover_mean_20` | `feature_artifact_20ce7b9420137c53c9e4579648d3eeb93c90ed54d0f0aa05a516886f70360b16` |
| `amount_median_20` | `feature_artifact_933eacb3bded0208d822979db3dfa4dd495c9eb810956f35c9fe310ab09f475d` |
| `amihud_20` | `feature_artifact_27dc65a0e691d615cc7cca8139baf1841c27e30b3f5ecbc426c07d1d4fdbdaf4` |
| `log_total_mv` | `feature_artifact_92b4fd47dfe095080814a5a11edbc883d66d51873aa0b8b0e1260c042fe2bc62` |
| `earnings_yield_ttm` | `feature_artifact_e72c64147d7829c7a90e7104025c6a9c628a6efe4e588446a8ccfe0b8be69fb9` |
| `book_yield` | `feature_artifact_d3a123ae52913ec7c4c49b9bb793d1fbfc73d88097f43c962328ec95b650b315` |
| `sales_yield_ttm` | `feature_artifact_3c0317ac3d3ea47100ee09dbac0e2aa243b57fa8b013cb31d8eee69ff4e79a9f` |
| `dividend_yield_ttm` | `feature_artifact_545346fce4bcafc379e2ec559b74fb47efb502465423a3991406845f1f4bf6f8` |

全量审计覆盖 25,694,880 行：重复 `(symbol, decision_time, feature_id)`、PIT 越界、质量状态
语义错误、股票池缺键/多键和每键非 15 因子均为 0。读取期发现的相同自然键重放只有物质字段一致
时才折叠；冲突会停止整批。`MISSING_DECISION_BAR` 75,750 行和
`MISSING_REQUIRED_BUNDLE` 3,283 行全部来自当时 `eligible_for_new_risk=false` 的股票池键，仍保留
在产物中。因子阶段不执行填充、去极值、标准化或中性化，也不删除停牌、退市、低流动性或缺失样本。

6 个财务质量与成长因子已使用代码提交
`734d49c430794605e25a12175c54baa1bc72f306` 物化。读取层只访问当前
financial-indicator schema
`schema_3ba4da69c3ae11fc76008832f7346f195c3cad7cc31a234c17deeae050486915`
下 `ACCEPTED` 的 `pit_financial_indicators`；feature row schema 为
`schema_2188f37341fed23c1b341582583c4eddbd4a0ea54c32eb1c393480f60d208510`。
每行保留所选版本的 event ID、报告期、公告时钟、update flag、Raw snapshot ID 和 Raw row
SHA-256。每个因子独立保存 1,712,992 行：

| Feature | Artifact ID |
|---|---|
| `roe` | `feature_artifact_86f2b99591d19d9a2684bbf9a4783354d353c47cf737ec756f236eee6ce463d5` |
| `grossprofit_margin` | `feature_artifact_ac866e63cff57d6184441e1a41edeeb64de88d085ff6d8665dbad6249c7d51ed` |
| `ocf_to_debt` | `feature_artifact_4d21cbbf44b5092bf2aea11d44c49e97db64ea30ff0e9d98434552a88a154b92` |
| `debt_to_assets` | `feature_artifact_7d9de2fbdc3591ce537082bce4792d0a68c08c1cbd1149f7455197a507677cc7` |
| `q_sales_yoy` | `feature_artifact_6540a20c8457f70d8cb4bccda18f455cf1ccceab8ed04b49309c7fff7069d99c` |
| `q_netprofit_yoy` | `feature_artifact_fb959366e4ceab00ce239c2b5e54774ab6f1313a0edc1b2dc834061a2f58cc5c` |

全量审计覆盖 10,277,952 行，区间为 `2020-01-03 18:00 +08:00` 至
`2026-07-10 18:00 +08:00`。重复键、PIT 越界、质量语义错误、血缘字段不一致、股票池缺键/多键、
每键非 6 因子及同键跨因子来源不一致均为 0。截止时点可见的 214,181 个 PIT 版本全部参与选择；
库内另外 11 个 accepted 版本在截止时点之后发布，因此不得提前进入产物。9,662,721 行存在真实值，
492,810 行因当时尚无已发布财务版本而标记 `NO_PUBLISHED_FINANCIAL`，122,421 行因所选版本的源字段
为空而标记 `SOURCE_VALUE_MISSING`；两类缺失均未填充或删除。

真实修订样本 `301589.SZ` 的 2023 年报 `roe` 在 `2024-04-18 18:00 +08:00` 前保持
`33.0389` 和原 event ID；`2024-04-19` 决策才读取修订值 `33.0093` 及新 event ID。随后
`2024-04-25` 发布 2024 一季报后，选择器才切换到较新报告期。该序列证明修订不会回写旧决策，
且较新报告期优先于旧报告的后续版本。

独立标签 `relative_open_return_20d_csi500` 使用代码提交
`043c36071e57df8a6fff028510c4974632cb35df` 物化为
`label_artifact_783a1f0794afc9533e855757fa638dd9eaec570d7563ba3ca3ff3399c46f474f`，
其 lineage edge 为
`lineage_fdb33ef11b401ab412986cfb9a78232d735a3806ba253c2315c5731372605854`。
label row schema `1.1.0` 的 manifest 为
`schema_3b53abe6babc6fe4efc9320a897922fe2aea9a2342fc02b653e0eeda467c3d2f`，
21 个字段分别记录键、固定未来窗口、标签值/空值原因，以及个股入场/退出价格、交易约束和中证 500
入场/退出价格的 Raw snapshot 与 Raw row SHA-256。

标签覆盖全部 1,712,992 个宇宙键和 334 个决策周，重复键、股票池缺键/多键、定义漂移、值/空值语义、
未来可得时钟和完整值来源缺失均为 0。1,598,017 行具有有效相对收益；其余行不删除，按固定窗口记录：
`ENTRY_LIMIT_UP` 6,947、`ENTRY_SUSPENDED` 4,193、`EXIT_LIMIT_DOWN` 3,238、
`EXIT_SUSPENDED` 3,087、`MISSING_ENTRY_BAR` 70,371、`MISSING_ENTRY_LIMIT` 3,214、
`MISSING_EXIT_BAR` 483、`NO_EXIT_SESSION` 23,442。停牌或涨跌停不会把 t+1/t+21 顺延。
330 组具有完整未来窗口的交易日偏移审计全部满足 entry-decision=1、exit-decision=21；1,449 个实际
引用的标签 Raw snapshot 全部属于 qualified input manifest。`000001.SZ` 在 `2020-01-03` 决策的
四个 Raw 开盘价独立重算与保存值完全一致，绝对误差为 0。

首个完整逻辑数据集已发布为 `ds_862d155145b89879b679`，固定 13,829 个 Raw snapshot、4 个输入
schema、21 个 feature artifact/lineage、上述独立 label artifact/lineage、宇宙 artifact、覆盖报告和
input manifest。合成 lineage manifest 为
`lineage_e331b1619c729de4b721e3a0e10dc2fd6ca647b8053caa7ffbaa8ba5c8f1127c`，feature 与 label
lineage 交集为 0。DatasetSpec 区间为 `2020-01-03` 至 `2026-07-10`；逻辑清单不复制特征或标签列，
同一输入重复发布得到同一 `ds_*`，已有清单字节变化时 fail closed。

## 11. Split、final holdout 与折内预处理血缘

`ds_862d155145b89879b679` 的开发边界固定为 `2024-12-31`，`2025-01-01` 起只属于 final
holdout。默认开发读取器会物理过滤后者；正式访问必须同时匹配 DatasetSpec、
`FinalHoldoutSpec`、冻结协议、全 PASS promotion artifact 和单次授权，并先写追加式
`HoldoutAccessRecord`。记录固定 exact `model_promotion_* -> model_protocol_* -> ridge_model_* ->
DatasetSpec -> holdout_spec`，任一身份错配均不得创建账本。机器结构为
`schemas/final_holdout_access_v1.json`。截至本节记录时，真实 final holdout 未被打开，开发期
validation/test 不能冒充 final test。

中期 split 使用 504/126/63/63 个交易日的初始训练、验证、内部 test 和滚动步长，标签窗口
purge=20、embargo=5。每个训练折产生独立 `FoldPreprocessingArtifact`，其血缘锚点为
`dataset_snapshot_id + fold_id + training_start/end + training_data_sha256 + feature order`；产物保存
训练折 winsor/fallback 与规模中性化系数，transform 不得改写这些字段。验证/内部 test 仅在各自
决策日做同日横截面填充和 z-score，不进入拟合参数或训练输入哈希。机器结构文档为
`schemas/fold_preprocessor_artifact_v1.json`，transform version 为 `1.0.0`。

研究样本是周频，但 split 的计数单位仍是日交易 session。真实运行必须从 DatasetSpec 的
`input_schema_manifest_ids` 和 `source_snapshot_ids` 读取绑定的 accepted SSE 日交易日历，先在日历上
生成 504/126/63、purge 20、embargo 5 的边界，再把周频 `decision_time` 映射进 fold。禁止直接把
周频 artifact 的 300 余个决策日当成日交易日计数，也禁止读取未被 DatasetSpec 固定的最新日历补足。
每个周频决策日必须存在于绑定日历，否则诊断和训练 fail closed。

历史行业 PIT 证据未覆盖 2020-2025，因此每个预处理 artifact 必须记录
`industry_neutralization_status=UNAVAILABLE`；不得以当前行业快照补历史，也不得据此把研究状态晋级为
完整 `VALIDATED`。真实折预处理 artifact 将在后续研究运行时按内容生成，不在 Git 中提交市场数据
派生产物。

## 12. 因子 trial 与诊断报告血缘

因子试验账本 schema 为 `schemas/factor_trial_batch_v1.json`。每个 `FactorTrial` 绑定
`dataset_snapshot_id -> feature_artifact_id -> feature/version -> family/direction/simplicity_rank ->
diagnostic_version`，trial ID 由上述字段内容寻址。`TrialBatch` 再绑定规则版本、真实 Git commit、
登记人/时间和全部有序 trial ID；store 在任何指标计算前原子发布并在每次读取时重算身份。

因子报告中的浮点诊断、分段、相关性及 p/q 值在 Pydantic 信任边界统一量化为 14 位十进制有效数字，
再参与门禁和内容寻址。该规则用于消除 Polars 并行归约顺序造成的约 `1e-16` 非物质末位抖动；禁止只在
哈希时忽略原始字段，也禁止用低精度掩盖接近门禁阈值的实质变化。

诊断输入只允许来自 `2024-12-31` 及以前的 development partition，并以
`(decision_time, symbol)` 连接训练折预处理后的 feature、独立 label、PIT `log_total_mv`、可得行业和
预先定义的市场状态。诊断不得读取 final holdout，也不得把 label 写回 feature/preprocessor artifact。

完整报告 schema 为 `schemas/factor_research_report_v1.json`。每个 trial 的报告保留总样本、有效 pair、
feature/label 缺失计数、coverage、原始/方向化 Rank IC、ICIR、方向一致率、p/q 值、五分组、毛/净
Top-Bottom、换手、自相关、规模暴露、全部年度/状态/行业分段和最差年度/行业。batch report 中
diagnostics 与 decisions 必须和 ledger trial ID 完全同序，失败因子只能标记 `REJECTED`，不能缺行。

BH-FDR 版本为 `1.0.0`，阈值 `q<=0.10`；相关性证据只比较同一预定义 family 的开发期逐日秩相关，
绝对相关达到 `0.80` 时按预登记简洁度去冗余。trial ledger 与 factor report 分别写入
`trial_ledger/<trial_batch_id>/manifest.json` 和 `factor_report/<factor_report_id>/report.json`，均只追加、
内容寻址并验证 SHA-256。

首个真实 DatasetSpec 的 21 个 feature artifact 已在代码提交
`46bf4fd749c80d695d715925a9bd265db2620a3e` 后预登记为
`trial_batch_898124e44b83fa1cc67fc01ec1fb7405dd43670518eae9237160f5fbb5802e6c`，manifest
SHA-256 为 `4b5b7eef217fdbdadf40229ac78c6a5d7b0e580fa574cd3ff551c7f3c62dba57`。
该账本只有假设和可复现身份，没有诊断结果，也没有读取 label 或 final holdout。固定合成小数据的软件
QA 报告 ID 为 `factor_report_d65b1509e2b5ac832edaa0c07100173bba9e9eb2903741e8905b176bdbaa122a`，
仅证明报告、方向、FDR 和去冗余代码行为，禁止据此声称真实因子有效。

## 13. 组合目标与风险决定契约

周频组合输入只能是训练折预处理后的候选因子标准化值；组合构建不读取标签、最终测试区或成交对象。
复合分数为候选因子等权平均，按分数降序和 `symbol` 升序稳定选择 Top 30，初始股票总权重 95%。

`portfolio_target_batch_v1` 固定 `factor_report_id -> candidate trial -> feature artifact -> fold-local
score -> oriented equal-factor composite -> Top 30 target` 血缘。候选 key 集合必须逐字一致，禁止 inner
join 后静默删除缺因子证券。目标 artifact 只保存 decision date、symbol、score、target weight 和 cash；
不保存 label、订单、成交或臆造的当前持仓。市场容量、行业、换手和现金风控在回测读取实际账户状态后
重新执行。

模型目标额外固定
`ridge_model -> prediction SHA-256 -> keyed internal-test batch -> factor report -> source baseline backtest
-> DatasetSpec -> Top 30 target`。预测批次必须同时保存精确的 `(decision_time, symbol)` 有序键和键哈希；
组合边界逐批重算哈希并拒绝缺键、错位、重复或跨 fold 重叠。仅保存键哈希的旧模型可以审计，但禁止
从当前数据集行序或其他 artifact 推断键。组合可见 frame 只能包含键和 `model_score`，label 必须物理
隔离。模型目标保存 `model_id`，后续仍由同一回测与风险链生成订单、成交和风险证据。

`PortfolioRiskDecision` 固定目标日期、信号来源、标的目标权重、现金权重、换手率、HHI 集中度、
研究状态和全部 `RiskEvent`，机器结构见 `schemas/portfolio_risk_decision_v1.json`。风险事件记录规则、
动作、观测、限制、说明及可选标的；目标中保留当前持仓的零权重行以表达退出意图，因此它不是订单或
成交明细。行业证据必须来自决策时点可得的 PIT 分类；缺失时状态只能是 `DRAFT`。

固定合成风险情景记录在 `.omo/evidence/task-10-risk-decisions.json`，只用于验证缩量、拒绝、现金守恒、
退出意图和阻断晋级的软件行为。该证据不使用真实行情，不打开 final holdout，也不证明组合有效。

## 14. 多标的回测账本与报告契约

`PortfolioBacktestResult` 同时固定初始/结束现金、费用与滑点假设、组合事前风控参数、收盘熔断参数、
逐标的数据质量报告、组合风险决定、风险事件、订单尝试、成交、每日净值和最终 tax-lot 持仓。订单
状态闭集为 `FILLED/PARTIAL/PENDING`，原因稳定记录停牌、涨跌停、T+1、成交量容量、现金不足和缺行情；
每次尝试保存 requested/filled quantity、是否风险退出及实际成交量参与率。

成交只使用下一交易日原始开盘价并加入方向性滑点；买卖双边佣金、最低佣金和卖出印花税逐笔进入
现金与持仓成本。卖出按可卖 acquisition lot FIFO 释放成本，未到 T+1 的 lot 不与旧 lot 混为不可卖。
缺行情的持仓使用最后可得价格继续盯市，不删除标的；退出被跌停、停牌或缺行情阻断时保留目标。

`PortfolioPerformanceMetrics` 使用费用后净值，披露绝对/中证 500 基准/超额收益、年化波动、Sharpe、
最大回撤、成交额换手、总费用、最大参与率、pending 订单、风险事件和年度分段。完整机器结构为
`schemas/portfolio_backtest_report_v1.json`。五票固定合成账本见
`.omo/evidence/task-11-trade-ledger.csv`，只证明软件记账和现金守恒，不证明真实策略有效；final holdout
未打开。

真实 `portfolio_backtest_report_v1` 额外固定
`portfolio_targets_* -> factor_report -> DatasetSpec -> exact market/benchmark schema -> exact used Raw snapshots
-> raw sessions/risk snapshots -> PortfolioRiskEngine -> orders/trades/equity -> metrics` 血缘。Mongo 查询同时
下推 DatasetSpec 的 `source_snapshot_ids` 和目标股票并集，accepted 但不在白名单中的同日重跑不能替换
冻结证据。股票执行 bar 明确为 `PriceBasis.RAW`；Tushare `daily.vol` 从手乘 100 转换为股后才进入容量
风控和成交账本。没有日线的停牌日保留独立 `suspended_symbols` 证据，不伪造价格。中证 500 比较基准
口径显式记录为 `raw_open`，必须与每日净值日期逐日完全对齐。当前行业字段为 `null`，因此报告状态
稳定为 `DRAFT`，`final_test_runs=0`。

## 15. 受治理训练与 Ridge 产物血缘

训练输入的机器契约为 `schemas/model_training_input_v1.json`。`DevelopmentTrainingEvidence` 不接受
`complete_schema_documentation` 或 `complete_data_lineage` 等调用方布尔声明，而是持有 DatasetSpec、
训练字段 schema、字段级 lineage、每 fold 预处理 manifest 的路径和 SHA-256，以及完整 development
frame SHA-256。`ModelTrainingGuard` 在拟合前重新读取文件并校验内容哈希。

字段 schema 的 feature 顺序、规模字段和 label 必须与 `ExperimentManifest` 完全一致。lineage 字段顺序
固定为 `features -> size_feature -> label`，每个字段必须至少关联一个 source artifact 和 Raw snapshot。
DatasetSpec snapshot/lineage、实验 schema/lineage、preprocessor fold/日期/feature order 任一不一致都停止
训练。development frame 最大决策日不得晚于 `2024-12-31`，final holdout ledger 计数必须为 0。

Ridge 模型 manifest 的机器契约为 `schemas/ridge_experiment_artifact_v1.json`。模型 identity 由训练运行、
DatasetSpec、schema/lineage、ExperimentManifest SHA-256、全部 alpha validation 结果、fold 结果、系数、
训练字段、预处理 ID、因子报告、trial batch、来源基线回测、预测 SHA-256、组合/成本规则和随机种子
共同内容寻址。预测 lineage 绑定 DatasetSpec、全部 preprocessor artifact 和内部 test prediction
SHA-256；预测批次同时保存精确的 `(decision_time, symbol)` 有序键及其哈希。组合发布必须验证模型与
预测的 DatasetSpec、研究身份和来源基线回测一致，并保持 `DRAFT`、`final_test_runs=0`。

每个 `RidgeFoldResult` 还必须保存与 `model_feature_names` 顺序完全一致的系数和截距。逐 fold 系数只能
在 `TrainingService -> ModelTrainingGuard -> RidgeTrainer` 已授权的拟合调用中记录；诊断阶段禁止为了
补证据重新拟合。缺少逐 fold 系数的旧模型仍可审计和读取，但不能生成系数稳定性报告。

`model_diagnostic_report_v1` 固定
`ridge_model -> keyed predictions/labels -> fold coefficients -> baseline targets/backtest -> model targets/backtest
-> Rank IC/coefficient stability/Top30 overlap/risk halt`。两个目标的决策日集合必须完全相同，禁止 inner
intersection 后静默丢期；两套回测必须固定相同 DatasetSpec、factor report、成本和风险版本。报告是
post-hoc development evidence，只能解释既有结果，不能授权调参、模型晋级或 final holdout 访问。

`model_experiment_protocol_v1` 是诊断引出新实验的先验冻结契约。它内容寻址父诊断、父模型、
DatasetSpec、schema/lineage、代码提交、带时区登记时间、候选模型与标签变换、特征顺序、split 与
预处理版本、组合/成本/风控版本、开发期晋级门槛和 final holdout 单次人工授权条件。协议 append-only；
同一 ID 只允许逐字节相同内容重读，身份或路径跨界均 fail closed。协议本身不包含训练结果、预测、
标签读取或 holdout 访问，状态只能从 `PREREGISTERED_NOT_IMPLEMENTED` 由后续独立审批流程推进。

`model_performance_attribution_v1` 固定
`model_diagnostic -> ridge_model -> keyed predictions -> model portfolio targets -> baseline/model backtests`
完整身份链。父诊断是唯一调用参数，其余 artifact ID 必须自动解析；模型目标键与预测键必须全量匹配，
日期集合必须相等。报告保存整体及逐年选中尾部 label 收益、Bottom 尾部差、逐年组合净收益差、pending
orders 和按 `(portfolio, risk rule, action)` 聚合的执行约束。该 lineage 只属于开发期 post-hoc 证据，
不得连接训练写入口、final holdout reader、`TrainingApproval` 或模型晋级状态转换。

`portfolio_experiment_protocol_v1` 固定
`model_attribution -> model_diagnostic -> ridge_model/keyed predictions -> DatasetSpec -> baseline/model targets
-> baseline/model backtests` 完整身份链。协议内容寻址全部父 artifact、schema/lineage、代码提交、成本、
风控以及固定候选规则。当前规则只允许原因子 composite 主排序并否决逐日 Ridge 最低 20%；否决数按
`ceil(N*20%)`，同分按 `(model_score asc, symbol asc)` 稳定处理，随后按稳定键取 Top30。任何常量变化
必须产生新 protocol ID。协议同时保存 `REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE`
分类和从 2026-07-24 起 26 个周度决策点、20 日标签成熟的 fresh-forward 时钟，并固定禁止访问既有
final holdout。`PREREGISTERED_NOT_IMPLEMENTED` 产物本身不包含新目标、订单、回测或模型状态变更。

协议实现产生的 `portfolio_targets_*` 在原有 factor report、DatasetSpec、trial batch 与可选 model ID
之外，必须保存 exact `portfolio_protocol_id` 和 `evidence_classification`。因子分数 lineage 为
`trial batch -> accepted factor decisions -> feature artifacts -> fold-local preprocessing -> factor composite`；
否决分数 lineage 为 `portfolio protocol -> ridge_model -> keyed predictions`。两条分数流只能在完全相同的
有序 `(decision_time, symbol)` 键上合并。当前 `portfolio_rule_version=3.0.0` targets 固定属于
`REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE`，不允许被 fresh-forward 评估器或晋级入口误读为新证据。

`ridge_rank` 训练不新增或覆盖物理 label 列。训练包仍以原始未来收益字段及其 Raw/label artifact lineage
通过 `ModelTrainingGuard`；随后由版本化 `cross_sectional_percentile_rank` 在每个 `decision_time` 内生成
临时 fitting target。模型 manifest 固定 protocol ID、变换名和预测标签语义。prediction artifact 保存
精确 `(decision_time, symbol)`、模型分数和原始未来收益；rank target 不写入 prediction artifact，防止
后续 Rank IC、组合诊断或收益报告混淆目标尺度。

`model_promotion_evaluation_v1` 固定
`model_protocol -> ridge_rank model -> keyed prediction SHA-256 -> model diagnostic -> seven frozen gates`。
每项 gate 保存稳定名称、实际观测、协议要求和布尔结果；总裁决只能由完整有序 gate 集推导，不能由
CLI 或人工传入。artifact 始终保存 `model_status=DRAFT`、`final_test_runs=0` 和
`final_holdout_authorized=false`；全部通过只产生后续人工授权资格，不产生 holdout 访问记录。

固定合成 QA 的实验 manifest 见 `.omo/evidence/task-12-experiment-manifest.json`。它的
`data_classification=SYNTHETIC_SOFTWARE_QA_ONLY`、`final_test_runs=0`、`model_status=DRAFT`，仅证明
validation-only alpha 选择、等权基线保存、哈希验证和门禁调用顺序；不构成真实模型、因子、回测或
投资有效性证据。

## 16. 一键研究审计报告

工作流报告 schema 为 `schemas/research_audit_report_v1.json`。report ID 对除自身 ID 外的完整规范 JSON
计算 SHA-256，输入包括 Git commit、uv lock SHA-256、DatasetSpec/schema/lineage、数据库、股票池规则、
因子公式、全部 trial ID、成本/风控版本、最差区间、失败、模型状态、final test 次数和有序阶段记录。

阶段顺序只能是 qualify、materialize、diagnose、portfolio、backtest、train。完成运行可包含前缀，
但首个 `BLOCKED` 后不得出现后续阶段。dry-run 必须包含全部六阶段且均为 `PLANNED`，只读取 manifest
身份，不读取市场 payload 或 label，不产生训练产物。JSON 与 `report.zh-CN.md` 同目录原子发布，读取时
必须由机器报告重新渲染并逐字比对。
