# AGENTS.md

本文件适用于整个仓库，是开发者和编码代理的根级执行规范。

## 1. 项目定位

这是面向个人投资者的本地 A 股量化研究系统。当前状态为研究与软件验证阶段，不连接券商实盘，不承诺收益。

演示数据只用于验证软件流程。禁止基于演示或合成数据声称策略、因子或模型有效，也禁止将其训练出的模型用于投资决策。

## 2. 规范优先级

发生冲突时按以下顺序执行：

1. 本文件中的工程与工作流要求。
2. `docs/QUANT_RESEARCH_RULEBOOK.md` 中的量化研究硬规则。
3. `docs/ENGINEERING_STANDARDS.md` 中的实现规范。
4. `docs/ML_SYSTEM_ARCHITECTURE.md` 和 `docs/ARCHITECTURE.md` 中的模块边界。
5. 邻近代码已经建立的局部模式。

完整量化宪法位于 `docs/QUANT_RESEARCH_RULEBOOK.md`。修改数据、特征、标签、回测、训练、组合或风控前必须阅读该文件。

真实数据接入还必须同时阅读：

- `docs/TUSHARE_DATA_PLAN.md`：新库、同步接口白名单、时间语义与调度。
- `docs/DATA_CONTRACT_AND_LINEAGE.md`：字段级 schema 与端到端血缘标准。

## 3. 常用命令

```bash
make install       # uv sync --all-groups
make format        # Ruff 格式化
make check         # 格式、Lint、严格类型、测试与覆盖率
make run           # 启动 http://127.0.0.1:8000
```

禁止使用 pip、Poetry、Conda 或 requirements.txt 管理本项目依赖。

## 4. 架构边界

本项目是模块化单体，依赖方向为：

```text
api -> services -> research / ml / portfolio / backtest -> domain
                    data adapters -----------------------> domain
```

- `domain/`：领域值对象，不得导入任何外层业务包。
- `governance/`：数据与模型治理的稳定入口。
- `data/`：外部数据适配器，不包含策略逻辑。
- `research/datasets/`：内容寻址的数据集规范。
- `research/features/`：点时特征定义。
- `research/labels/`：与特征物理隔离的未来标签。
- `research/splits/`：Walk-forward、purge 和 embargo。
- `research/experiments/`：可复现实验清单。
- `ml/`：训练器协议、模型产物和模型注册。
- `ml/trainers/`：具体模型适配器；Ridge 与未来 LightGBM 平行实现，不得包含数据清洗、组合、风控或成交逻辑。
- `research/preprocessing/`：所有模型共用的训练折内预处理，具体 trainer 不得复制。
- `research/training/targets.py`：训练目标变换的唯一实现；rank 模型不得在 trainer 内复制或修改标签语义。
- `research/training/`：真实训练帧、完整字段 schema、字段级 lineage 和训练证据装配，不得拟合模型。
- `portfolio/`：预测分数到目标权重，不能创建成交。
- `backtest/`：A 股成交、费用、持仓与风险执行的唯一事实来源。
- `services/`：编排用例，不复制领域规则。
- `api/`：Pydantic 信任边界和 HTTP 映射。
- `web/`：研究台，不在浏览器重新实现回测或风控。

生产 Python 文件不得超过 250 行。`tests/test_architecture.py` 会强制检查目录、依赖方向和文件大小。

## 5. 时间与数据硬规则

每条外部数据必须区分：

- `event_time`：事件发生时间。
- `available_at`：当时最早可获得时间。
- `ingested_at`：本系统写入时间。

任何策略或特征只能读取 `available_at <= decision_time` 的数据。日线收盘信号最早在下一交易日开盘成交。

所有策略读取行情前必须通过 `DataQualityGuard`。回测引擎内部保留第二道门禁，禁止为了性能删除。

数据硬门禁至少包括：

- 标的和交易日唯一，时间严格递增。
- 单一序列的标的和价格口径一致。
- 价格有限且大于零，OHLC 关系成立。
- 成交量非负，涨停价高于跌停价。
- 数据在下一执行时间之前已经可得。
- 原始数据只追加，不允许原地覆盖。
- 空响应也必须生成质量与 lineage 证据；不得使用 `all(empty)` 将预定隔离的数据误判为通过。
- 历史回填只有在 accepted Raw、当前 schema 的 canonical lineage 和已通过 canonical 质量报告
  三者齐全时才可跳过日期，不得用独立游标或“请求成功”代替数据完成事实。
- 历史股票池只能由当前 universe schema 下 `ACCEPTED` 的
  `LISTED/FIRST_TRADED/DELISTED/NAME_STATUS` 事件按 `effective_at` 和 `available_at`
  双时钟回放；不得直接读取当前
  `stock_basic` 快照重建历史状态。
- 同一内容寻址 Raw 快照、Raw 行、事件类型和转换版本只能生成一个稳定事件 ID。重复观察时间
  不得制造第二条事实；物质性事件语义变化必须升级 schema/转换版本，旧 manifest 只留审计。
- 历史名称或 ST 状态未知时必须 fail closed，不得把 `is_st=null` 当作非 ST。日线中缺少
  `stock_basic` 生命周期的代码，只能用首个 accepted 日线生成保守 `FIRST_TRADED` 证据，不得
  伪造上市日、退市日或历史名称。
- `dividend` canonical 行同时包含不同公告阶段，必须保持 `QUARANTINED`。研究只能读取当前
  corporate-action schema 下 accepted 的 `PLAN_ANNOUNCED/IMPLEMENTATION_ANNOUNCED` PIT
  事件；方案事件的登记日、除权日、派息日和红股上市日必须物理为空。
- 分红回填按 `ann_date` 自然日逐日请求。只有 accepted Raw、canonical lineage、PIT 批次
  lineage 和通过的 PIT 批次质量报告齐全时才可跳过；零行响应同样必须生成 PIT 批次证据。
- 财务 canonical 行必须保持 `QUARANTINED`，研究只能读取按实际公告日事件化的 accepted PIT
  版本。`f_ann_date` 优先于 `ann_date`，两者缺失时只能从首次观察时间起可用；`update_flag`
  只能标识版本，禁止覆盖旧版或只保留最新修订。
- 当前观察到的 `index_member.in_date/out_date` 只表示供应商声明的有效区间，不证明历史当时
  已经可得。成员 canonical 必须保持 `QUARANTINED`；PIT `available_at` 只能使用本系统首次
  观察时间，禁止把有效日期倒填为历史可得时间或用于观察时点之前的行业暴露。

## 6. 回测硬规则

- 当前日线策略在收盘后形成信号，下一可成交开盘执行。
- 仅做多，买入数量为 100 股整数倍。
- 遵守 T+1、停牌、涨停不可买和跌停不可卖。
- 买卖佣金、最低佣金、卖出印花税和双边滑点必须计入。
- 不得假设订单必然成交，不得忽略成交量参与率。
- 回测输出必须包含数据质量证据、方法论、风险参数、风险事件和成交明细。
- 禁止只报告最好参数、最好年份或最好股票。
- 真实组合回测只能读取所选 `portfolio_targets_*` 绑定的 DatasetSpec 白名单 Raw 快照；股票行情与
  中证 500 基准都不得自动采用同日期后来重跑的 accepted 快照。
- 成交价必须使用未复权日线；Tushare `daily.vol` 的“手”必须在进入风控和成交容量前乘以 100
  转换为“股”。稀疏停牌事件不得通过伪造 OHLC 补齐，必须作为独立 session 证据阻断成交。
- 历史 PIT 行业证据缺失时，组合回测状态只能是 `DRAFT`，不得因其他风控通过而晋级。

## 7. 机器学习禁止事项

以下行为属于 `FORBIDDEN`，不得通过配置开关或人工确认绕过：

- 随机打乱金融时间序列后切分训练集和测试集。
- 在全样本拟合标准化、缺失值填充、PCA、特征选择或中性化。
- 使用决策时点之后发布、修订或回填的数据作为特征。
- 把标签或标签窗口中的未来信息放入特征。
- 使用今天的指数成分、ST 状态或退市结局重建历史股票池。
- 测试集参与超参数、阈值、特征或早停选择。
- 看过最终测试结果后修改模型并继续称其为样本外。
- 根据 post-hoc 模型诊断结果修改当前实验的特征、标签、超参数、阈值或组合规则，并继续把同一
  internal-test 区间称为未见数据；任何此类修改必须登记为新实验和新 trial，不得覆盖原报告。
- 删除亏损、退市、停牌或数据表现不好的样本。
- 从大量试验挑选最高收益结果而不记录试验次数和多重检验控制。
- 使用不可复现的数据快照、代码、特征或环境训练可晋级模型。
- 使用演示或合成行情训练投资决策模型。

模型训练必须通过 `ModelTrainingGuard`。最终测试集最多运行一次。模型默认状态为 `DRAFT`，获得 `TrainingApproval` 后才可晋级为 `VALIDATED`。

final holdout 授权前必须读取已持久化且内容寻址的 `model_promotion_*`。七项预注册开发期门槛必须全部
通过；`BLOCKED`、缺失裁决或 PIT 行业不完整均不可由人工确认、配置开关或新入口绕过。promotion
evaluation 本身始终保持 `DRAFT`、`final_test_runs=0` 和 `final_holdout_authorized=false`。

## 8. 研究产物和版本

- 数据集由 `DatasetSpec.snapshot_id` 内容寻址。
- `DatasetSpec` 只能由已持久化且 `QUALIFIED` 的跨表 coverage report、对应 input manifest、
  已物化特征 artifact 和物理隔离标签 artifact 装配；禁止直接手工拼装训练数据集绕过覆盖门禁。
- 数据集必须固定内容寻址的 `schema_manifest_id` 和 `lineage_manifest_id`。
- 数据集必须同时保留原始 input schema ID、Raw 快照 ID、输入 lineage、特征 lineage 和标签
  lineage；输入 coverage 合格不能替代特征或标签的端到端 lineage。
- 特征、标签、股票池、规则和数据 schema 分别版本化。
- 任何物质变化必须产生新版本或新快照 ID。
- 每次训练保存 `ExperimentManifest`：数据集 ID、规则版本、Git commit、模型族、特征、标签、split、随机种子和最终测试次数。
- 每个模型通过 `ModelRecord` 关联数据集与训练运行。
- 模型诊断只能读取已持久化的 keyed development predictions、逐 fold 模型证据及完整风控回测；
  禁止在诊断代码中重新拟合模型、访问 final holdout 或产生训练审批。
- 任何由 post-hoc 诊断引出的新模型、标签、特征、阈值或组合假设，必须先写入内容寻址且追加式的
  `model_protocol_*`；协议固定父诊断、数据/字段 schema 与 lineage、带时区登记时间、开发期晋级门槛和
  单次人工授权的 final holdout 条件。协议状态为 `PREREGISTERED_NOT_IMPLEMENTED` 时，禁止训练或访问
  final holdout。
- 模型预测进入组合层前必须持久化并逐批验证精确的 `(decision_time, symbol)` 有序键；仅保存键哈希的
  旧预测只允许审计，禁止从其他 artifact 或当前数据顺序猜测、回填或重建预测键。
- 组合层只能接收 `decision_time`、`symbol` 和模型分数，不得携带 label；重复键、跨 fold 重叠键或
  键哈希不一致必须 fail closed。
- 模型输出只能进入组合构建器，不能直接创建订单。
- `ridge_rank` 只能读取已验证的 `model_protocol_*`；其拟合目标按每个 `decision_time` 独立计算
  `[0,1]` 横截面平均秩（并列取平均秩，单样本固定 `0.5`）。预测 artifact 必须继续保存原始未来收益
  label 供 Rank IC 诊断，禁止把训练 rank 值伪装成收益。
- 没有覆盖全部训练字段的结构文档，或无法从训练列追溯到 Raw 快照时，训练必须停止。

## 9. 风控不可绕过

策略和模型只表达目标，风控拥有最终决定权。

事前风险至少覆盖：单票仓位、现金缓冲、成交量参与率、手数、资金、停牌与涨跌停。

事中风险至少覆盖：持仓止损、单日亏损、组合最大回撤。熔断后停止新增风险，并在下一可成交开盘退出。退出因停牌或跌停受阻时保留订单并记录风险事件。

未来多标的系统还必须覆盖持仓数量、行业暴露、风格暴露、换手率、相关性、集中度、组合波动率和容量。

禁止在 API、页面、策略或训练代码中绕过或复制风控实现。

## 10. Python 工程规范

- Python `>=3.12`，使用 `uv`。
- Ruff 负责格式化和 Lint；BasedPyright 使用 strict。
- 数据计算使用 Polars、NumPy 和 DuckDB，禁止 Pandas。
- 外部边界使用冻结 Pydantic v2 模型。
- 内部结构使用 `@dataclass(frozen=True, slots=True)`。
- 接口使用 Protocol，闭集使用 StrEnum，ID 和单位优先使用 NewType。
- 禁止 `Any`、`object`、无类型字典、`cast()`、`type: ignore` 和宽泛异常吞噬。
- 文件、数据库和网络连接必须由上下文管理器持有。
- 不共享可变模块全局状态。
- 注释解释原因和约束，不复述代码。

## 11. 测试规范

行为变化遵循红、绿、重构：

1. 先写失败测试并确认失败原因正确。
2. 写最小实现使测试通过。
3. 在绿灯保护下整理结构。

每个测试使用 Given / When / Then，只有一个 When。优先真实值对象和内存实现，只有外部服务无法替代时才 Mock。

必须重点测试：

- 时间穿越和点时可得性。
- 重复、乱序、异常 OHLC 和价格口径。
- 标签窗口与成交时钟。
- purge、embargo 和训练折预处理。
- 佣金、印花税、滑点、T+1、涨跌停和停牌。
- 风控缩量、拒单、熔断和退出受阻。
- 数据集指纹、实验清单和模型状态晋级。

UI 改动必须使用真实浏览器检查桌面与移动端，并确认控制台无错误、中文不截断、控件不重叠。

## 12. 数据与安全

- 不提交真实市场数据、Parquet、DuckDB、模型二进制、Token、交易密码或账户信息。
- 新数据库固定为 `ashare_quant`；`tradingagentscn` 只允许人工参考，禁止用于同步回填、训练、验证和回测。
- 历史与增量市场数据只允许从本项目登记的 Tushare 白名单接口进入 Raw 层。
- 所有 Tushare 请求必须经过 `TushareSyncService` 的限速器，CLI、调度器和未来服务不得直连
  `TushareClient.fetch()` 绕过限速与 Raw 门禁。
- 密钥只通过环境变量或本机密钥管理器注入。
- 日志不得输出密钥和完整账户信息。
- 删除或覆盖原始数据、模型与研究产物前必须明确获得用户批准。
- 当前没有实盘权限；新增实盘能力必须单独设计隔离、人工审批、审计和紧急停止。

## 13. 完成标准

任务只有同时满足以下条件才算完成：

- 目标行为已经实现，不是只有接口或 TODO。
- `make check` 全部通过，覆盖率不低于 90%。
- 没有违反架构依赖或 250 行文件上限。
- 没有新增未来函数、泄漏、生存者偏差或风险绕过路径。
- 相关规则、schema、特征、标签和产物版本已更新。
- 文档、API 输出和界面与实际行为一致。
