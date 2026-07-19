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

每份契约固定列顺序、Polars 物理类型、空值语义、单位、时间角色和允许用途。研究产物写入
前必须匹配对应文件的内容哈希 `schema_manifest_id`；不允许调用方临时声明列结构。
预处理清单是内容寻址 JSON，不是市场数据 Parquet；它必须绑定 `DatasetSpec`、fold、训练日期范围、
训练行内容哈希和有序特征，验证或测试数据不得出现在其拟合字段中。
