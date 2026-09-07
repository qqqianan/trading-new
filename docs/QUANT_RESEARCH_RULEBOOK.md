# A 股量化研究宪法

版本：`1.1.0`  
适用范围：数据接入、策略研究、因子分析、机器学习、回测、模拟交易与未来实盘。

本文件不是建议清单，而是项目的最高研究约束。任何收益结果只要违反一条 `MUST` 或
`FORBIDDEN`，即判定为无效，不得进入参数比较、策略报告或交易决策。

## 1. 规则等级

- **MUST**：系统必须自动验证；不满足时停止运行。
- **SHOULD**：暂时无法自动验证时，研究报告必须披露原因、影响和补救方式。
- **FORBIDDEN**：禁止以参数开关、人工确认或“仅用于探索”为由绕过。

## 2. 时间与点时可得性

### 2.1 三个时间必须分开

每条数据必须能够表达：

1. `event_time`：经济事件或市场事件实际发生时间。
2. `available_at`：研究者在当时最早可以获得该信息的时间。
3. `ingested_at`：本系统实际抓取或写入数据的时间。

策略只能读取 `available_at <= decision_time` 的数据。回测数据库中的行顺序、文件修改时间、
今天下载到的历史数据，都不能代替 `available_at`。

### 2.2 日线决策时钟

- 日线收盘数据在交易日收盘并完成发布后才可用。
- 当前基准策略的 `decision_time` 是当日收盘后。
- 信号最早在下一交易日开盘尝试成交。
- 当日收盘价产生的信号不得按当日收盘价成交。
- 财务报告按实际公告时间生效，不能按报告期末日期生效。
- 宏观数据按首次发布日期生效；使用修订值必须保留版本并声明。

### 2.3 时间相关禁止事项

- **FORBIDDEN**：使用未来价格、未来成分股、未来 ST/退市状态或未来复权因子。
- **FORBIDDEN**：用全样本均值、方差、分位数或缺失值统计量处理训练期数据。
- **FORBIDDEN**：把公告日期缺失的数据回填到报告期末。
- **FORBIDDEN**：随机打乱时间序列后划分训练集与测试集。
- **FORBIDDEN**：同一交易日收盘计算信号并用该收盘价成交。
- **FORBIDDEN**：把今天观察到的行业成员 `in_date/out_date` 当作历史发布日期，或用于首次观察
  时间之前的行业暴露、行业中性化和历史股票池筛选。

## 3. 数据准确性与血缘

### 3.1 每个数据集必须具备

- 来源名称、接口、请求参数、原始快照 ID、抓取时间和覆盖区间。
- 原始数据不可覆写；清洗、复权、派生数据分层保存。
- 唯一键、字段类型、单位、时区和空值语义。
- 价格口径：原始价、前复权或后复权必须显式标注。
- 公司行动、停复牌、涨跌停、ST、上市和退市状态。
- 数据校验报告和校验规则版本。
- 内容寻址的 schema 清单 ID 和端到端血缘清单 ID。

### 3.2 自动硬门禁

- 交易日和标的唯一，时间严格递增。
- 同一序列只允许一个标的和一种价格口径。
- 所有价格有限且大于零；`low <= open/close <= high`。
- 成交量不得为负；涨停价必须高于跌停价。
- `available_at` 不得晚于该数据参与的下一次决策或成交时点。
- 原始价用于成交模拟；复权价仅用于连续收益和信号计算。

### 3.3 必须披露的数据偏差

- 生存者偏差：股票池必须使用历史时点成分，包含退市和长期停牌标的。
- 复权偏差：复权因子必须按当时已知公司行动计算。
- 修订偏差：财务和宏观数据需要 point-in-time 版本库。
- 缺失偏差：不得默认把缺失解释为零或“无事件”。
- 数据源差异：价格、成交量和公司行动应进行抽样交叉验证。

演示数据只能验证软件流程，**FORBIDDEN** 用于判断策略或模型有效性。

### 3.4 数据结构文档与血缘硬门禁

任何参与训练的数据在训练开始前必须具备完整、版本化且可机器核验的数据结构文档。文档必须
覆盖实际使用的全部字段，并记录类型、单位、精度、时区、空值语义、时间角色、来源字段、
价格口径、质量规则和允许用途。

数据血缘必须能够从训练集的每个特征和标签，沿转换版本、代码提交和参数，反向追溯至 Raw
字段、Tushare 接口、请求参数和不可变原始快照。特征与标签必须是可证明分离的血缘分支。

- **MUST**：`DatasetSpec` 固定 schema 清单 ID 和 lineage 清单 ID，两者参与 dataset ID 计算。
- **MUST**：`ExperimentManifest` 固定 dataset、schema 和 lineage ID。
- **MUST**：schema、血缘、转换或来源快照任一物质变化都生成新的 dataset ID。
- **FORBIDDEN**：训练使用未写入 schema 文档的字段或动态列。
- **FORBIDDEN**：用表级描述代替字段级血缘。
- **FORBIDDEN**：训练开始后补写、替换或修改该次训练引用的 schema 与血缘清单。
- **FORBIDDEN**：无法追溯至不可变 Raw 快照的数据进入训练、验证、回测比较或模型晋级。

完整标准由 `docs/DATA_CONTRACT_AND_LINEAGE.md` 定义。`ModelTrainingGuard` 必须自动拒绝缺少
任一证据的训练请求。

### 3.5 本项目数据源隔离

新数据库固定为 `ashare_quant`，历史和增量市场数据均由本项目直接从 Tushare 获取。
数据库 `tradingagentscn` 未通过本宪法规定的接入校验，只能用于人工参考：

- **FORBIDDEN**：复制、拼接或回填 `tradingagentscn` 的数据到 `ashare_quant`。
- **FORBIDDEN**：任何训练、验证、回测或正式选股读取 `tradingagentscn` 及其派生表。
- **MUST**：同步接口白名单、时间语义和频率遵守 `docs/TUSHARE_DATA_PLAN.md`。

证监会、中上协和巨潮资讯的历史行业材料当前只允许进入本地、内容寻址的 source-audit artifact：

- **MUST**：source audit 固定 `research_use_authorized=false`，且不写 MongoDB。
- **MUST**：巨潮身份查询、公告查询和 PDF 下载统一经过受限速的 `CninfoArchiveClient`。
- **MUST**：批量审计在首个巨潮请求前持久化内容寻址的确定性候选选择，绑定当前 universe schema、
  全部候选哈希和上游生命周期事件；下载或解析失败不得触发补抽、换样本或丢样本。
- **MUST**：全量发现计划必须从原试点父 batch 的 `audited_at` 本地证据截面重放 842 只候选，并匹配已
  冻结的 candidate universe 哈希。计划按固定 offset 分片；第一阶段只登记身份响应、公告响应和最终
  PDF descriptor，不下载 PDF。HTTP/transport 失败必须保留失败阶段、状态码和可得响应哈希，旧观察
  只追加不覆盖。
- **MUST**：招股说明书 supplemental audit 只能绑定 exact 父 batch 中显式披露缺失的逐股 audit；父
  audit 为冲突状态时禁止自动补源。无公告、PDF 错误和正文缺失同样保存响应/PDF 哈希 trace。
- **FORBIDDEN**：同一巨潮查询跨运行出现空/非空或不同公告选择时，只保留成功观察。此类来源不稳定必须
  显式阻塞扩量和准入，直到重复观察协议或另一官方来源能解释差异。
- **MUST**：重复观察报告固定 exact 查询规范、按观察时间排序的全部显式 source audit 和原始响应哈希；
  少于 3 次只能为 `INSUFFICIENT`。空/非空、公告 ID、PDF 哈希或稳定空响应哈希不一致时必须为
  `UNSTABLE`，不能用后续多数票或成功结果覆盖。
- **MUST**：上交所公告与附件请求统一经过 `SseArchiveClient + RequestPacer`。独立确认候选只能由
  exact `UNSTABLE/query_outcome_changed` 巨潮报告装配；SSE PDF SHA-256 必须与父报告唯一成功观察
  完全相同，不同则 fail closed。提供商记录时间只保存原值，不直接解释为 PIT `available_at`。
- **MUST**：CAPCO 单股 membership 候选同时绑定 exact archive audit 与 exact 上游冲突 audit；附件只能
  由 `CapcoArchiveClient + RequestPacer` 下载，下载 SHA-256 必须与 archive evidence 完全一致。
- **MUST**：CAPCO 页面只有发布日期时，source audit 固定
  `PENDING_NEXT_TRADING_SESSION_OPEN`；正式 `available_at` 必须由后续交易日历门禁投影产生。
- **MUST**：date-only 日期投影必须固定当前 market schema 下 accepted SSE `trade_cal` 的连续自然日区间，
  每行保留 Raw snapshot ID 和 row SHA-256。只有字节级完全相同的重复物理记录可以折叠；同一日期出现
  不同 snapshot、row hash 或开闭状态必须阻塞。
- **MUST**：历史行业 source admission 使用独立 schema，并同时持久化 Raw observation、质量裁决、字段
  lineage 和 PIT candidate；未获得另行研究准入前固定 `QUALIFIED_SOURCE_ONLY`。
- **MUST**：多来源 resolver 固定优先级为原上市公告、稳定 prospectus、SSE 对不稳定 CNInfo 的 exact
  哈希确认、CAPCO 对显式冲突的后续解决。每个分支必须绑定完整父链和所有被评估 audit ID。
- **MUST**：统一 PIT candidate 分别保存来源可得、上市资格和最终可用三个时钟；最终可用时间只能是
  `max(source_available_at, eligible_from)`。只有来源在上市后才确定时才记录 UNKNOWN 区间。
- **FORBIDDEN**：把 source-audit 的 `FOUND` 直接解释为 canonical/PIT `ACCEPTED` 或历史行业完整。
- **FORBIDDEN**：把 CAPCO 统计期、分类有效期或后来发布的单一分类倒填到上市日。此前冲突样本必须显式
  记录 `UNKNOWN_UNTIL`，不能用“最终分类已知”消除未知区间。
- **MUST**：历史行业 coverage 必须绑定 exact selection、resolution、admission batch、候选全集哈希和
  研究时间窗。目标 population 不完整、候选键差异、重复/冲突分类、source lineage 不一致或 UNKNOWN
  与研究窗口重叠时必须 `BLOCKED`。`READY_FOR_RESEARCH_ADMISSION_REVIEW` 仅允许单独评审，不能直接
  改写 `research_use_authorized=false`、写 MongoDB 或进入训练/回测。
- **FORBIDDEN**：仅凭周末/节假日常识、手工日期或孤立的下一个开放日构造 `available_at`；日历中间任一
  自然日缺少 accepted 证据时必须停止。
- **FORBIDDEN**：把上市前已公开但股票尚未上市的分类伪装成上市后数据缺失，或把来源可得时间直接当作
  可投资起点；同样禁止用上市日覆盖真实较晚的来源可得时间。
- **FORBIDDEN**：把巨潮日期占位的本地午夜当成精确发布时间；只能标记 `DATE_ONLY`，后续使用交易日历
  投影到下一可用交易时点。
- **FORBIDDEN**：公告只披露行业代码/名称但未披露分类体系版本时，根据代码形式猜测 taxonomy；必须
  绑定当时生效的官方分类规则证据，否则保持 `CSRC_UNVERSIONED`。
- **FORBIDDEN**：把四位国民经济行业代码截断为证监会三级代码。仅当正文依次具名两个分类标准并用
  “代码分别为”建立一一对应关系时，才允许选择明确对应的证监会代码；顺序或 taxonomy 不明确仍隔离。
- **FORBIDDEN**：把产品、材料或业务线的行业代码当作发行人主体行业。公司级证据必须由具名 taxonomy
  与“公司所处行业为/分类代码”共同限定；主体明确时，次要产品分类不能覆盖或伪造公司级冲突。

## 4. 回测方法

### 4.1 事件顺序

每个交易日严格按照以下顺序：

1. 读取截至当前决策时点可得的数据。
2. 计算信号和目标仓位。
3. 运行事前风控，缩减或拒绝订单。
4. 在下一可成交时点按市场约束模拟成交。
5. 扣除佣金、印花税和滑点。
6. 盯市并运行事中风控。
7. 记录净值、订单、成交、拒单和风险事件。

### 4.2 A 股成交假设

- 仅做多；100 股一手；买入遵守资金和现金缓冲。
- T+1；停牌不可成交；涨停不可买；跌停不可卖。
- 日频订单默认下一交易日开盘成交，不保证成交。
- 买卖均收佣金并执行最低收费；卖出收印花税；双边计入滑点。
- 订单不得超过当日成交量参与率；需评估策略容量。

### 4.3 结果报告必须同时包含

- 绝对收益与相对基准收益。
- 年化收益、波动率、最大回撤、夏普、换手率和费用。
- 按年份、市场状态和行业的分段表现。
- 成交、未成交、拒单、缩量和风控事件。
- 参数敏感性、样本外结果和最差区间。
- 数据版本、策略版本、规则版本和全部配置。

只报告最优参数或最好区间是 **FORBIDDEN**。

### 4.4 因子诊断与试验披露

- 每个因子尝试必须在读取标签和计算结果前登记到 immutable trial batch；登记固定 DatasetSpec、
  feature artifact、经济方向、family、简洁度优先级、规则版本和 Git commit。
- 第一批 21 个因子必须全部进入同一个试验账本和最终报告，失败、缺失、不显著或被去冗余者不得删除。
- 每个因子至少报告 coverage、Rank IC/ICIR、方向一致率、五分组单调性、Top-Bottom 毛/净收益、
  换手、自相关、规模暴露，以及年份、市场状态和可得行业分段。
- 报告必须显式列出缺失 feature/label 样本、最差年份和 PIT 行业可得时的最差行业。
- 经济方向在试验登记时冻结；反转、低波、低 Amihud 等 lower-is-better 因子只按预登记方向翻转。
- 同一研究批次统一执行 Benjamini-Hochberg FDR，候选阈值固定 `q<=0.10`；新增任何试验都必须重算全批次 q 值。
- 相关性去冗余只在预定义同 family 内执行，优先保留更低 `simplicity_rank`，并为被拒因子记录稳定原因。
- Top-Bottom 收益、最好年份或最好市场状态不得单独决定 `CANDIDATE`。

## 5. 样本划分与模型训练红线

### 5.1 允许的流程

- 按时间划分训练集、验证集和最终测试集。
- 超参数只在训练集和验证集确定。
- 最终测试集只允许在冻结特征、标签、参数和交易规则后运行一次。
- 多资产标签有重叠时采用 purged walk-forward，并在边界设置 embargo。
- 标准化、降维、特征选择、缺失值处理全部只在训练折拟合。
- 每次训练记录数据快照、代码提交、随机种子、特征清单和参数。
- 任何从 post-hoc 诊断产生的新假设必须先预注册为内容寻址、追加式 `model_protocol_*`：固定父诊断、
  数据集、schema、lineage、带时区登记时间、候选模型/标签变换、特征、预处理、组合、成本、风控、开发期
  晋级门槛与 final holdout 条件。`PREREGISTERED_NOT_IMPLEMENTED` 协议只登记，不得训练或访问 holdout。
- 开发期组合绩效归因必须以一个已持久化且内容寻址的 `model_diagnostic_*` 为唯一入口，沿父诊断自动
  解析 exact 模型、keyed predictions、模型目标、因子基线回测和模型回测。原始未来收益 tail 只能在
  有限标签 prediction universe 内按模型分数重建同样的 TopN 数量，固定标记
  `LABEL_COMPLETE_PREDICTION_UNIVERSE_TOP_N`，不能冒充完整组合成交收益或授权调参。
- 由组合绩效归因产生的组合假设必须先登记追加式、内容寻址的 `portfolio_protocol_*`。当前
  `factor_anchor_ridge_bottom_quintile_veto_v1` 固定原因子 composite 主排序、逐决策日 Ridge 分数底部
  20% 否决、Top30、95% 总仓位和 5% 现金。否决数量固定为 `ceil(N*20%)`，按
  `(model_score asc, symbol asc)` 稳定选取；这些常量禁止通过开发期收益寻优。
- 上述组合协议把 2022--2024 明确标记为 `REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE`。任何晋级证据必须从
  2026-07-24 起新产生，至少覆盖 26 个周度决策点，并等待 20 个交易日标签成熟；既有 final holdout
  对该协议固定为不可访问，不能通过人工授权改变。
- 因子锚定 targets 只能由 exact `portfolio_protocol_*` 读取已登记 trial/factor report 的折内预处理
  无标签 composite 与协议绑定的 keyed Ridge predictions。两条分数流的 `(decision_time, symbol)` 必须
  完全相同；输出必须保留 protocol ID、`REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE` 和规则版本，且仍然只是
  风控前目标，不具有订单或成交能力。
- 横截面预处理必须先在每个决策时点的完整可投资股票池上执行，再按 label 有限性形成拟合和诊断矩阵。
  label 是否可评估不得改变缺失值填充、去极值、标准化或中性化的横截面总体。组合评分必须复用各折
  已持久化 preprocessor 与系数，并在已存 keyed predictions 的重叠行上复算一致后才能覆盖无标签股票。
- 实际 targets 中无标签但当时可投资的股票必须保留并由正式风控回测评价；不得为了生成 tail/IC
  诊断删除这些股票，或把有限标签诊断总体称为实际组合股票池。
- rank-label Ridge 的目标变换固定为逐 `decision_time` 横截面 `[0,1]` 平均秩；并列值取平均秩，横截面
  只有一条有效样本时固定为 `0.5`。该变换不能跨日期、跨 fold 或使用测试期分布拟合参数。
- rank-label 只用于拟合和 MSE 选 alpha；开发期预测证据必须保留同键的原始未来收益，Rank IC 和组合
  诊断不得读取变换后的 rank 充当收益。
- 中期选股开发期固定截止 `2024-12-31`，`2025-01-01` 起属于独立 final holdout。
- final holdout 只能由绑定冻结协议的强类型授权打开；首次访问必须先原子追加账本，第二次 fail closed。
- final holdout 人工授权前必须存在内容寻址的 `model_promotion_*`，其 protocol、模型、diagnostic 与
  DatasetSpec lineage 完全一致，七项预注册开发期门槛全部为 PASS；裁决本身不得授权或读取 holdout。
- final holdout 授权请求和 append-only 访问记录必须同时绑定 exact promotion evaluation、model
  protocol、model、DatasetSpec 与 holdout spec；禁止只凭人工身份或通用 protocol 打开。
- 中期协议固定初始训练 504、验证 126、滚动 63 个交易日，标签 purge 20、embargo 5。
- 折内预处理顺序固定为训练折 1%/99% winsor、逐决策日横截面中位数填充并保留缺失指示、
  横截面 z-score、使用训练折系数对 `log(total_mv)` 中性化。`log_total_mv` 自身只标准化，不对自身回归。
- 历史 PIT 行业证据不可用时不得伪造行业中性化，产物必须记录 `UNAVAILABLE`，研究不得晋级完整验证状态。

### 5.2 绝对禁止

- **FORBIDDEN**：测试集参与特征选择、阈值选择、早停或超参数优化。
- **FORBIDDEN**：看过测试结果后修改模型，再把同一测试集称为样本外。
- **FORBIDDEN**：随机 K 折用于有时间依赖或标签重叠的金融数据。
- **FORBIDDEN**：在全样本上拟合 scaler、PCA、行业中性化或缺失值填充器。
- **FORBIDDEN**：标签或标签计算窗口内的信息进入特征。
- **FORBIDDEN**：使用今天看到的历史成分、最新财务修订值或完整退市结局。
- **FORBIDDEN**：删除亏损严重、退市、停牌或数据“不好看”的样本。
- **FORBIDDEN**：以回测收益最大化作为唯一训练目标。
- **FORBIDDEN**：未做多重检验控制就从大量试验中挑选最高收益模型。
- **FORBIDDEN**：无法复现数据快照和特征生成过程的模型进入模拟或实盘。
- **FORBIDDEN**：演示/合成行情训练可用于投资决策的模型。
- **FORBIDDEN**：通过 `allow_final_test`、直接读取路径或删除访问账本重复打开 final holdout。
- **FORBIDDEN**：缺少 promotion evaluation、裁决为 `BLOCKED`、任一 gate 失败或行业 PIT 不完整时，
  申请、构造或执行 final holdout 授权。
- **FORBIDDEN**：以 post-hoc 诊断为由修改当前实验，或不先冻结新的 `model_protocol_*` 就实现、训练或
  评估由诊断引出的候选模型。
- **FORBIDDEN**：由组合绩效归因入口重新拟合模型、改变目标组合、读取 final holdout，或把归因报告
  直接用作 `TrainingApproval`、模型晋级及 final holdout 授权。
- **FORBIDDEN**：在 `portfolio_protocol_*` 登记前实现或回测归因派生的组合规则；或在登记后修改
  否决比例、排序、持仓数、仓位、成本、风控和 fresh-forward 起点而沿用同一 protocol ID。
- **FORBIDDEN**：把已看过的 2022--2024 归因/回测结果重新称为样本外，或使用 2026-07-24 之前的数据
  充当因子锚定组合的 fresh-forward 晋级证据。
- **FORBIDDEN**：从基线 Top30 结果反推或补猜完整因子排序、在因子与模型分数间做有利 inner join，或
  生成缺少 exact protocol ID 和证据分类的因子锚定 targets。
- **FORBIDDEN**：在横截面预处理前根据未来 label 是否存在删样本，或把仅有有限 label 的 prediction
  键当作历史可投资股票池；此类旧模型不得通过键交集、默认分数或静默删样本进入组合层。
- **FORBIDDEN**：对全部日期一起计算 label rank，或覆盖原始 label 后导致诊断无法还原真实收益语义。
- **FORBIDDEN**：把开发期 walk-forward 的 validation/test 称为 final test。
- **FORBIDDEN**：计算结果后补登记 trial、隐藏失败试验，或把额外噪声试验排除在 FDR 分母之外。
- **FORBIDDEN**：看过标签后修改因子方向、family 或简洁度优先级并沿用原 trial ID。

## 6. 风控引擎

### 6.1 事前风控

- 单标的最大仓位权重。
- 最低现金缓冲。
- 单笔订单最大成交量参与率。
- 价格、停牌、涨跌停、手数、资金和 T+1 检查。
- 风控只能缩量或拒绝订单，策略不得绕过。

### 6.2 事中风控

- 单持仓最大亏损。
- 单日最大亏损。
- 组合最大回撤。
- 任一熔断触发后停止新增风险，并在下一可成交开盘强制退出。
- 因跌停或停牌无法退出时，风险订单持续保留并逐日记录状态。

### 6.3 风险事件审计

每个事件必须记录：规则代码、触发日期、观测值、限制值、动作和说明。风险事件不能只写日志，
必须进入回测结果和研究报告。

## 7. 研究发布门禁

策略进入下一阶段前必须同时满足：

- [ ] 数据质量硬门禁通过，数据血缘可追溯。
- [ ] 全部训练字段具有完整 schema 文档，schema 和 lineage 清单已内容寻址并冻结。
- [ ] 无时间穿越，所有特征具有 `available_at`。
- [ ] 训练/验证/测试按时间隔离，最终测试集未被反复使用。
- [ ] 成交规则、交易成本、流动性和容量已建模。
- [ ] 风控引擎已启用，风险事件已披露。
- [ ] 与合理基准比较，并报告最差区间和参数敏感性。
- [ ] 研究结果可从固定数据快照和配置完全复现。

任一项缺失，研究状态只能是 `DRAFT`，不得标记为 `VALIDATED`。

## 8. 当前代码对应关系

| 规则 | 强制位置 |
|---|---|
| 时间递增、OHLC、可得时间和价格口径 | `DataQualityGuard` |
| 点时特征、schema、血缘、样本隔离、测试集单次使用和多重检验 | `ModelTrainingGuard` |
| 收盘信号、次日开盘成交 | `BacktestEngine` |
| 手数、T+1、涨跌停、停牌和费用 | `BacktestEngine` |
| 限仓、现金缓冲和成交量参与率 | `RiskEngine.size_buy` |
| 止损、单日亏损和回撤熔断 | `RiskEngine.assess_close` |
| 风险与数据质量披露 | `/api/v1/backtests` 响应和研究台 |
