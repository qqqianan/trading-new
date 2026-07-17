# Tushare 数据同步与新库规划

状态：`ALL P0 INGESTION ACCEPTED / PIT HISTORY PARTIAL / FORMAL TRAINING STILL BLOCKED`  
目标数据库：`ashare_quant`  
主数据源：`Tushare Pro`  
禁止训练来源：现有数据库 `tradingagentscn` 及其全部派生集合。

## 1. 决策边界

- `ashare_quant` 必须是全新数据库，不复制 `tradingagentscn` 的市场数据。
- 历史数据和每日增量均由本项目直接请求 Tushare。
- 训练、回测和特征计算不得在运行时直接请求 Tushare，只能读取已验收快照。
- Raw 层只追加；供应商返回值变化时新增版本，不更新旧文档。
- 第一版是收盘后日频系统，不把 Tushare 日线接口描述为实时行情。
- 未进入本文件白名单的接口不得静默加入训练数据。

## 2. 数据库分层

| 前缀 | 责任 | 覆写策略 |
|---|---|---|
| `meta_` | 同步运行、快照、schema、血缘和质量报告 | 元数据状态可追加，已签名清单不可改 |
| `raw_` | Tushare 原始响应行和请求上下文 | 只追加 |
| `canonical_` | 类型、代码、单位和时间语义标准化 | 按版本追加，不覆盖历史版本 |
| `pit_` | 按 `available_at` 可回放的点时视图 | 由固定 Raw 快照派生 |
| `feature_` | 版本化特征 | 按特征版本和数据快照物化 |
| `label_` | 与特征物理隔离的未来标签 | 按标签版本物化 |
| `dataset_` | 内容寻址训练集和清单 | 不可变 |
| `model_` | 实验、模型、预测和审批记录 | 产物不可变，状态转换追加审计 |

所有 Raw 行必须关联 `meta_source_snapshots.snapshot_id`。所有 canonical、PIT、特征、标签和
训练集必须能沿 `meta_lineage_edges` 反向追溯到一个或多个 Raw 快照。

## 3. 第一批同步白名单

### 3.1 市场日历与股票池

| 优先级 | Tushare 接口 | Raw 集合 | Canonical 集合 | 用途 | 同步频率 |
|---|---|---|---|---|---|
| P0 | `trade_cal` | `raw_tushare_trade_cal` | `canonical_trade_calendar` | 上交所/深交所交易日与前后交易日 | 每周全量核对未来一年 |
| P0 | `stock_basic` | `raw_tushare_stock_basic` | `canonical_security_master` | 上市、暂停上市、退市股票主数据 | 每日按 `L/P/D` 分别拉取 |
| P0 | `namechange` | `raw_tushare_namechange` | `canonical_security_name_history` | 名称和历史 ST 状态 | 每周增量、每月全量核对 |

`stock_basic` 必须分别请求 `list_status=L`、`P`、`D`。只请求当前上市股票是禁止的，避免生存者偏差。

### 3.2 行情、估值与可交易性

| 优先级 | Tushare 接口 | Raw 集合 | Canonical 集合 | 用途 | 同步频率 |
|---|---|---|---|---|---|
| P0 | `daily` | `raw_tushare_daily` | `canonical_daily_bar` | 原始 OHLC、成交量、成交额 | 每个交易日收盘后 |
| P0 | `adj_factor` | `raw_tushare_adj_factor` | `canonical_adjustment_factor` | 连续收益计算，不用于模拟成交价 | 每个交易日收盘后 |
| P0 | `daily_basic` | `raw_tushare_daily_basic` | `canonical_daily_valuation` | 换手率、市值、PE/PB/PS、股息率 | 每个交易日收盘后 |
| P0 | `stk_limit` | `raw_tushare_stk_limit` | `canonical_daily_price_limit` | 历史涨跌停价格 | 每个交易日收盘后 |
| P0 | `suspend_d` | `raw_tushare_suspend_d` | `canonical_suspension_event` | 停复牌与不可成交状态 | 每个交易日收盘后 |

成交模拟只能读取 `canonical_daily_bar` 的原始价格。复权价格必须由指定版本的原始价格与
`canonical_adjustment_factor` 派生，并显式记录复权方向、基准日和公式版本。

### 3.3 公司行动与财务报表

| 优先级 | Tushare 接口 | Raw 集合 | Canonical 集合 | 用途 | 同步频率 |
|---|---|---|---|---|---|
| P0 | `dividend` | `raw_tushare_dividend` | `canonical_dividend_event` | 分红、送转、登记和除权日 | 每日增量、每周回看一年 |
| P0 | `income` | `raw_tushare_income` | `canonical_income_statement` | 利润表及历史修订 | 每日按公告日增量 |
| P0 | `balancesheet` | `raw_tushare_balancesheet` | `canonical_balance_sheet` | 资产负债表及历史修订 | 每日按公告日增量 |
| P0 | `cashflow` | `raw_tushare_cashflow` | `canonical_cashflow_statement` | 现金流量表及历史修订 | 每日按公告日增量 |
| P0 | `fina_indicator` | `raw_tushare_fina_indicator` | `canonical_financial_indicator` | 财务指标及历史修订 | 每日按公告日增量 |

财务 Raw 行的版本身份至少包含 `ts_code`、`end_date`、`ann_date`、`f_ann_date`、
`report_type`、`comp_type`、`update_flag` 和 `snapshot_id`。同一报告期的后续修订必须追加，
禁止覆盖首次看到的版本。

### 3.4 基准、历史成分与行业

| 优先级 | Tushare 接口 | Raw 集合 | Canonical 集合 | 用途 | 同步频率 |
|---|---|---|---|---|---|
| P0 | `index_basic` | `raw_tushare_index_basic` | `canonical_index_master` | 基准指数主数据 | 每月全量 |
| P0 | `index_daily` | `raw_tushare_index_daily` | `canonical_index_daily_bar` | 基准收益和市场状态 | 每个交易日收盘后 |
| P0 | `index_weight` | `raw_tushare_index_weight` | `canonical_index_membership` | 历史成分与权重 | 每月并回看最近三个月 |
| P0 | `index_classify` | `raw_tushare_index_classify` | `canonical_industry_master` | 申万行业层级定义 | 每月全量 |
| P0 | `index_member` | `raw_tushare_index_member` | `canonical_industry_membership` | 行业纳入、移出历史 | 每月全量并保留版本 |

第一版基准至少包括上证综指、沪深 300、中证 500、中证 1000、深证成指和北证 50。
任何缺少历史生效区间的成分或行业记录只能进入隔离区，不能回填为历史成员。

基准接口使用独立 `schemas/tushare_benchmarks_v1.json`。`index_basic` 必须按上述六个
`ts_code` 精确请求；市场级响应达到 8,000 行供应商上限时在 Raw 写入前拒绝。它是当前观察
快照，`event_time=available_at=ingested_at`，不得用 `base_date` 或 `list_date` 伪造历史可得性。
`index_daily` 的事件时间为交易日 `15:00`，最早可得时间为 `16:00`；北证 50 基日允许
`open/high/low=null`，但 `close` 仍必须存在且不得补值。`index_weight` canonical 固定为
`QUARANTINED`，研究只能读取 accepted `pit_index_weights`。每月批次必须只有一个指数、一个
权重日期，权重和位于 95% 至 105%；除中证 1000 外，达到 1,000 行供应商上限必须拒绝。
上证综指不伪造固定权重成分，空月也必须保留 PIT 批次质量与 lineage。

行业接口固定 `src=SW2021`。`index_classify` 是当前观察分类快照，只有其 accepted L1 代码
可以驱动逐行业精确 `index_member` 请求。成员接口真实字段为
`index_code/con_code/in_date/out_date/is_new`；层级和名称通过分类主表关联，不在成员行中冗余
伪造。成员 canonical 固定 `QUARANTINED`，`in_date/out_date` 只定义有效区间，PIT
`available_at` 固定为首次观察时间。当前回填不得用于观察时间之前的历史行业暴露。

## 4. 暂缓接口

以下接口可以在独立提案和 PIT 审查后进入 P1，第一批不用于训练：

- `forecast`、`express`：业绩预告和快报，需先定义公告时间与修订处理。
- `fina_audit`：审计意见，需先定义可得时间和缺失语义。
- `share_float`：限售股解禁，不等同于每日流通股本。
- 龙虎榜、融资融券、北向资金、股东人数、新闻和概念板块。
- AkShare、Baostock 或其他替代源。

## 5. 历史回填范围

- 每个 P0 接口从 Tushare 当前权限允许的最早日期开始拉取，不使用旧库补洞。
- 日线类按交易日或月份分片，财务类按报告期和公告期分片。
- 任一接口因权限只能获得部分历史时，记录实际覆盖区间并阻止超出覆盖区间的训练。
- 历史回填结束后必须重新拉取最近 60 个交易日进行一致性核对。
- 训练起始日由所有必需输入的共同覆盖区间决定，不由某一张行情表单独决定。

## 6. 每日调度

使用 macOS LaunchAgent 和 Asia/Shanghai 时区，每天 `18:30` 和 `21:30` 执行
`nightly-maintenance`；第二轮用于晚发布与失败恢复：

1. 每天：检查交易日历；开市日同步五类股票日频和六个基准日线；回看最近 7 个自然日分红。
2. 周一：以最近 14 个自然日的固定范围按全部历史生命周期代码刷新利润表。
3. 周二：同范围刷新资产负债表；周三刷新现金流；周四刷新财务指标。
4. 周五：刷新 L/P/D 股票主数据和最近 370 天名称/ST 变化。
5. 周六：同步基准主数据、回看当前月及前两个月权重，并同步 SW2021 行业分类和成员。
6. 财务请求按 100 个证券分块；每块完成即持久化 PIT 及批次证据，失败后由相同范围证据恢复。

调度时间只是抓取时间，不自动等于 `available_at`。日线、财务和公司行动必须使用各自的
可得时间政策。

## 7. 接入完成标准

- 18 个 P0 接口都具有字段级 schema 文档、唯一键、单位、时区和空值语义。
- 每个同步运行都有请求参数、开始/结束时间、原始行数、内容哈希和状态。
- 所有 Raw 快照不可变，重复请求可识别为相同内容或新版本。
- 质量报告覆盖重复、缺口、OHLC、复权跳变、停牌、涨跌停和财务时间穿越。
- 从 canonical 任一字段可以追溯到转换代码版本、Raw 字段和快照。
- 未满足上述条件前，不创建正式训练数据集。

## 8. 实施状态

截至 `2026-07-16`：

- 已创建隔离数据库 `ashare_quant` 的治理、9 个 Raw、9 个 canonical 和 PIT 事件集合。
- 已为首批 9 个接口启用严格 MongoDB validator、唯一索引和内容寻址 Raw 快照。
- 已完成 `2026-07-10` 日频数据、L/P/D 股票主数据和交易日历的受治理试同步。
- 重复日频同步已验证为幂等，不覆盖或重复插入相同快照。
- 试同步发现的两个不完整快照保留审计证据并标记为 `REJECTED`。
- 日频 schema 下首批 7 个接口已启用 canonical 转换、质量报告和 Raw 到 canonical 字段级 lineage；转换
  版本为 `1.1.1`，schema 版本为 `1.1.1`。`daily.pre_close` 允许首个交易日缺少昨收价，
  此类记录仍需通过 OHLC 与其他行情质量检查。
- PIT 门禁只返回 `ACCEPTED` 且 `available_at <= decision_time` 的记录。当前快照型
  `stock_basic` 包括空批次都强制 `QUARANTINED`，不得重建历史股票池。
- 历史回填以数据库治理证据为断点：五个日频接口必须同时具有当前 schema 的 accepted Raw、
  canonical lineage 和已通过质量报告，日期才会被跳过。默认单日失败后停止，可显式选择继续，
  所有失败最终返回非零退出码。
- schema `1.1.1` 已验收 1,581 个连续日频交易日，完整覆盖 `2020-01-02` 至
  `2026-07-14`，待补交易日为 0；`canonical_daily_bar` 包含 7,792,174 条 accepted 文档。
- 独立 universe schema `1.1.1` 的当前 manifest 为
  `schema_49b36e8944a757ca01f221a1f3137e8605dd49ec2ea5d561b7d258ac84a141da`。它已物化
  26,206 条 accepted PIT 事件：5,866 条 `LISTED`、1 条 `FIRST_TRADED`、337 条
  `DELISTED` 和 20,002 条 `NAME_STATUS`；逐事件质量报告与字段级 lineage 均为
  26,206/26,206，且没有 `available_at > ingested_at`。
- 5,756 个 accepted 日线代码全部具有 `LISTED` 或 `FIRST_TRADED` 入口。`300114.SZ`
  因 Tushare `stock_basic` 和 `namechange` 均无记录，只使用首条 accepted 日线生成
  `2020-01-02 15:00` 的保守 `FIRST_TRADED` 事件，不推断其精确上市或退市事实。
- 相同 universe 同步连续执行两次后事件数保持 26,206。事件 ID 绑定内容寻址 Raw 快照、
  Raw 行、事件类型、输出 schema 和转换版本，不再受重试观察时钟影响。旧 manifest 中的历史
  事件继续只追加保留审计，数据集不得跨 manifest 混读。
- 在 `2020-01-02 16:00`、`2023-01-03 16:00`、`2026-07-16 16:00` 回放时，上市状态数
  分别为 3,761、5,068、5,530；名称/ST 已知数分别为 3,760、5,066、5,529。未知状态必须
  fail closed，不能当作非 ST 进入训练股票池。
- corporate-action schema `1.0.0` 的当前 manifest 为
  `schema_cfbfafcd6e186b448f227547c5b92ecdd51258d358bb4df1b0905f07f2251c45`。`dividend`
  已按公告自然日完整覆盖 `2020-01-01` 至 `2026-07-16` 的 2,389 天，无缺口、无 received
  或 rejected 快照；最大单日 1,971 行，未触及 2,000 行接口上限。
- 分红 Raw 共 131,411 行，其中 6 行是供应商同一响应内的完全重复行；Raw 原样保留，内容寻址
  canonical 折叠为 131,405 条且全部 `QUARANTINED`。PIT 层生成 131,405 条
  `PLAN_ANNOUNCED` 和 27,655 条 `IMPLEMENTATION_ANNOUNCED`，共 159,060 条 accepted
  事件；逐事件质量和 lineage 均为 159,060/159,060，批次质量和 lineage 均为
  2,389/2,389。方案事件的实施日期泄漏为 0，`available_at > ingested_at` 为 0。
- financial schema `1.0.0` 的当前 manifest 为
  `schema_ae03b82887c1cd2d24790c3f90d1f96d8650071a3265fd592a80b7a4f33bf49e`。当前 Token
  无 `income_vip` 权限，系统在供应商边界失败且未写 Raw；正式回填改用 `income`，覆盖全部
  5,867 个历史生命周期代码，缺失 0。共 5,867 个 accepted 快照，其中 68 个空响应；Raw、
  quarantined canonical 和 accepted PIT 版本均为 197,571 条，逐事件质量/lineage 均为
  197,571/197,571，批次质量/lineage 均为 5,867/5,867，时间违规为 0。
- 独立 balance-sheet schema `1.0.0` 的当前 manifest 为
  `schema_d2379fe19ab11ac1ec8f65440931d17d7a510927d7c1f5c214c94c8a03e2eed4`。普通
  `balancesheet` 接口已覆盖全部 5,867 个历史生命周期代码，缺失 0；其中 68 个空响应仍具有完整
  批次证据。Raw、quarantined canonical 和 accepted PIT 版本均为 189,004 条，逐事件
  质量/lineage 均为 189,004/189,004，批次质量/lineage 均为 5,867/5,867，时间违规为 0。
- 独立 cash-flow schema `1.0.0` 的当前 manifest 为
  `schema_29eb174cf861d08e8d7ba25101c0989676ccb92f11fc14a7d7436a1490506ebb`。普通
  `cashflow` 接口已覆盖全部 5,867 个历史生命周期代码，缺失 0；其中 70 个空响应仍具有完整
  批次证据。Raw、quarantined canonical 和 accepted PIT 版本均为 214,552 条，逐事件
  质量/lineage 均为 214,552/214,552，批次质量/lineage 均为 5,867/5,867，时间违规为 0。
- 独立 financial-indicator schema `1.0.0` 的当前 manifest 为
  `schema_3ba4da69c3ae11fc76008832f7346f195c3cad7cc31a234c17deeae050486915`。普通
  `fina_indicator` 接口已覆盖全部 5,867 个历史生命周期代码，缺失 0；其中 61 个空响应仍具有
  完整批次证据。Raw、quarantined canonical 和 accepted PIT 版本均为 214,192 条，逐事件
  质量/lineage 均为 214,192/214,192，批次质量/lineage 均为 5,867/5,867，时间违规为 0。
  8 条供应商记录缺少 `ann_date`，严格从首次观察时间起可用，没有回填到报告期末。
- benchmark schema `1.0.2` 的当前 manifest 为
  `schema_cd92111d31e7f5ff60777851a81f3b76c7d749d967ac50cacec7c262d3b6b1d8`。六个精确
  `index_basic` 快照共 6 行；六个 `index_daily` 快照共 8,936 行。前五个指数各覆盖
  `2020-01-02` 至 `2026-07-16` 的 1,583 个交易日，北证 50 从 `2022-04-29` 基日覆盖
  1,021 个交易日；其基日唯一一条 `open/high/low=null` 原样保留，`close=1000`。
- `index_weight` 已执行 395 个“指数×月份”请求，覆盖 `2020-01` 至 `2026-07`，Raw 与
  quarantined canonical 均为 181,600 行，39 个空月仍有完整批次证据。accepted PIT 事件、
  逐事件质量和字段级 lineage 均为 181,600/181,600；批次质量和 lineage 均为 395/395。
  沪深 300、中证 500、中证 1000、深证成指各有 78 个有效权重月，北证 50 从
  `2022-11-30` 起有 44 个有效权重月；所有月度权重和位于 99.976% 至 100.021%。
- industry schema `1.0.1` 的当前 manifest 为
  `schema_00ba78ad478ccfc33108151d518b2f7470bfca25f3947bf7ee142458670d47ae`。
  `index_classify` accepted 快照包含 511 行：L1 31、L2 134、L3 346。31 个 L1 精确
  `index_member` 快照全部 accepted，共 7,727 行；quarantined canonical、accepted
  `pit_industry_memberships`、逐事件质量和字段 lineage 均为 7,727/7,727，批次质量和 lineage
  均为 31/31，时间违规为 0。5,199 条区间当前没有 `out_date`，但所有 7,727 条事实最早只能从
  本次观察时间起用于决策，不能支持 2020 至观察日前的历史行业回测。
- 回填发现 `2020-01-15` 的首日交易记录 `pre_close=null`，旧 schema 正确拒绝但字段契约过严；
  schema `1.1.1` 已将昨收价改为可空并通过原日期真实重放。旧失败快照继续保留审计证据。
- 历史回填已完成。为容纳不可变 Raw、canonical 和索引，Colima Docker 稀疏磁盘上限已从
  100 GiB 无损扩展至 200 GiB。完成后主机可用约 139 GiB，Colima 内部可用约 86 GiB。
- 回填期间每批结束后瘦身新生成的 Time Machine 本地快照，避免 APFS 为虚拟磁盘保留旧块
  造成写放大；当前文件、MongoDB 数据和系统更新快照未被删除。
- Tushare 请求由同步服务统一以默认 1.2 秒最小间隔限速。
- macOS LaunchAgent `com.ashare-lab.daily-data` 已重新加载，每天 `18:30` 和 `21:30` 运行
  `nightly-maintenance`。日频、分红、四类财务、股票池、基准和行业均已纳入上述分频增量计划；
  当前安装参数已核对为新命令，日志继续写入本地 `logs/`。
- 18 个 P0 接口均已接入受治理 Raw/canonical；但跨表数据集质量门禁、历史行业可得性、特征和标签
  lineage 仍未全部完成。baseline 跨表输入覆盖已对 `2020-01-02` 至 `2026-06-16` 的五表
  日频、PIT 股票池和沪深 300 日线生成 qualified coverage report 与 input manifest，交易日历
  1,562 个开市日和五端点完整日一一对应。该 manifest 固定 7,850 个 Raw 快照与 34,017 条
  输入 lineage；行业因首次可得日为 `2026-07-17` 未进入历史 baseline。特征/标签尚未物化，
  `DatasetSpec` 未生成，正式训练门禁继续关闭。
