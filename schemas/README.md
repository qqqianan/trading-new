# Schema registry

这里保存可提交 Git 的机器可读数据结构清单，不保存任何市场数据。

每个清单必须覆盖实际集合的全部字段，并按照
`docs/DATA_CONTRACT_AND_LINEAGE.md` 记录类型、单位、空值语义、时间角色、来源字段和允许用途。
清单规范化后计算 SHA-256，并以 `schema_<sha256>` 登记到数据集和实验清单。

在对应 schema 清单完成并通过测试之前，不得向 `ashare_quant` 回填该接口的数据，也不得
将该接口用于训练。
