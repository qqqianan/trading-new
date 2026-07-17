# Data layout

运行时数据不提交到 Git。每一层只能从左侧相邻层派生，禁止覆盖原始数据。

```text
data/
├── raw/             # 供应商原始响应，只追加
├── normalized/      # 代码、字段、单位和时区标准化
├── point_in_time/   # 保留 event_time / available_at / ingested_at
├── features/        # 带定义版本的特征
├── labels/          # 与特征物理隔离的未来标签
├── datasets/        # 内容寻址的数据集快照
└── artifacts/       # 模型、预测、报告与审计清单
```

目录中的 Parquet、DuckDB、模型文件和供应商响应均由 `.gitignore` 排除。可提交的只有 schema、清单示例和不含市场数据的说明文件。

真实数据唯一数据库为 `ashare_quant`。旧库 `tradingagentscn` 不得进入以上任一目录或数据集。
可提交的机器可读字段定义位于 `schemas/`，血缘要求见
`docs/DATA_CONTRACT_AND_LINEAGE.md`。
