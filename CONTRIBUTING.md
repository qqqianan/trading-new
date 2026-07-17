# Contributing

## 开始之前

1. 阅读根目录 `AGENTS.md`。
2. 阅读 `docs/QUANT_RESEARCH_RULEBOOK.md` 和 `docs/ENGINEERING_STANDARDS.md`。
3. 确认改动属于哪个模块，禁止从底层模块反向依赖 API 或基础设施。
4. 涉及数据、标签、回测、训练或风控时，先写出时间语义和失败条件。

## 本地开发

```bash
make install
make check
make run
```

测试遵循 Given / When / Then。任何生产行为变更必须先有失败测试，随后实现最小修复，再重构。

## 提交要求

- 一次提交只表达一个可解释的行为变化。
- 不提交真实市场数据、Token、模型大文件、DuckDB 或 Parquet。
- 数据 schema、特征、标签、规则和配置变化必须升级各自版本。
- 新的训练结果必须关联数据集快照、训练清单、代码提交和规则版本。
- UI 变化除自动测试外，还需完成桌面和移动端真实浏览器检查。

## 完成标准

- `make check` 全部通过。
- 没有未来函数、测试集泄漏或新的生存者偏差。
- 风险约束没有被策略、模型或 API 绕过。
- 文档和 `AGENTS.md` 与代码行为一致。

