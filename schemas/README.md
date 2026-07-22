# Schema registry

这里保存可提交 Git 的机器可读数据结构清单，不保存任何市场数据。

每个清单必须覆盖实际集合的全部字段，并按照
`docs/DATA_CONTRACT_AND_LINEAGE.md` 记录类型、单位、空值语义、时间角色、来源字段和允许用途。
清单规范化后计算 SHA-256，并以 `schema_<sha256>` 登记到数据集和实验清单。

在对应 schema 清单完成并通过测试之前，不得向 `ashare_quant` 回填该接口的数据，也不得
将该接口用于训练。

研究 Parquet 使用独立的精确列契约：

- `research_feature_row_v1.json`：PIT 特征长表，只允许作为模型输入。
- `research_label_row_v1.json`：未来标签长表，只允许作为训练目标。
- `research_universe_row_v1.json`：双时钟股票池准入与持续盯市状态。
- `research_dataset_row_v1.json`：特征、标签和股票池产物的装配引用。
- `fold_preprocessor_artifact_v1.json`：训练折拟合范围、输入哈希、去极值、缺失兜底和规模中性化参数。
- `factor_trial_batch_v1.json`：计算前登记的完整因子假设、方向、family、artifact、规则与代码身份。
- `factor_research_report_v1.json`：全 trial 诊断、分段、缺失样本、BH-FDR 和候选/拒绝决定。
- `portfolio_risk_decision_v1.json`：周频目标权重、现金、组合限制、研究状态和全部风险事件；不含订单或成交字段。
- `portfolio_target_batch_v1.json`：真实开发期候选因子的逐周 Top 30 风控前目标；绑定 factor report、DatasetSpec 和 trial batch，不含标签、订单、成交或假定持仓。
- `portfolio_backtest_report_v1.json`：绑定目标、DatasetSpec、股票/基准 schema 与实际 Raw 快照的组合账户报告；包含冻结成本/风险假设、数据质量、订单、成交、净值、基准、分段指标和 final holdout 封存计数。
- `model_training_input_v1.json`：训练前必须验证的 DatasetSpec、字段 schema/lineage、fold 预处理、开发帧哈希、封存账本、模型族、标签变换与实验协议引用。
- `ridge_experiment_artifact_v1.json`：固定 alpha 全候选结果、等权基线、内部 test、系数、预测血缘、模型哈希和 DRAFT 状态；新增字段向后兼容旧 Ridge，并为 rank Ridge 绑定 protocol、目标变换和原始收益标签语义。
- `model_experiment_protocol_v1.json`：由 post-hoc 诊断引出的新实验预注册；冻结父证据、数据/字段血缘、假设、晋级门槛与单次 final holdout 条件，不含训练或评估结果。
- `research_audit_report_v1.json`：一键研究阶段、冻结身份、全部因子/试验、成本风控、最差区间、失败、模型与 final holdout 状态。

每份契约固定列顺序、Polars 物理类型、空值语义、单位、时间角色和允许用途。研究产物写入
前必须匹配对应文件的内容哈希 `schema_manifest_id`；不允许调用方临时声明列结构。
预处理清单是内容寻址 JSON，不是市场数据 Parquet；它必须绑定 `DatasetSpec`、fold、训练日期范围、
训练行内容哈希和有序特征，验证或测试数据不得出现在其拟合字段中。
训练输入 schema 描述的是 `TrainingService` 的受治理边界；实际字段文档和 lineage 文档仍以各自
SHA-256 描述符读取并逐字节验证。Ridge 产物只保存 JSON，不允许 pickle；内部 test 不是 final holdout。
