# 工程规范

## 1. 技术栈

- Python `>=3.12`，本地与 CI 当前使用 Python 3.13。
- 包管理与运行统一使用 `uv`，禁止新增 requirements.txt、Poetry 或 Conda 环境。
- Web API 使用 FastAPI + Pydantic v2。
- 数据计算使用 Polars、NumPy 与 DuckDB，禁止在核心管线引入 Pandas。
- 格式化和静态检查使用 Ruff，类型检查使用 BasedPyright strict。
- 测试使用 Pytest，覆盖率门禁为 90%。

## 2. 模块化单体

```text
src/ashare_lab/
├── domain/                 # 不依赖外层的领域值对象
├── governance/             # 数据与模型治理的稳定入口
├── data/                   # 数据适配器
├── research/
│   ├── datasets/           # 内容寻址的数据集定义
│   ├── features/           # 点时特征定义
│   ├── labels/             # 独立的未来标签定义
│   ├── splits/             # Walk-forward / purge / embargo
│   └── experiments/        # 可复现实验清单
├── ml/                     # Trainer 协议、模型产物与注册表
├── portfolio/              # 预测到组合目标的边界
├── strategies/             # 非 ML 基线策略
├── backtest/               # A 股成交和风险执行
├── services/               # 应用用例编排
├── api/                    # HTTP 信任边界
└── web/                    # 本地研究台
```

依赖始终由外向内：`api -> services -> research/backtest/ml/portfolio -> domain`。`domain` 不得导入其他业务包。跨模块通信使用不可变类型或 Protocol，不共享可变全局状态。

## 3. 类型与数据建模

- API、配置、文件和外部数据边界使用冻结 Pydantic 模型。
- 内部值对象使用 `@dataclass(frozen=True, slots=True)`。
- ID、版本和不同单位优先使用 `NewType` 或明确值对象。
- 闭集使用 `StrEnum`；分支必须显式处理所有变体。
- 公共函数不得接收或返回无类型字典、`Any` 或 `object`。
- 资源通过上下文管理器管理；禁止静默捕获宽泛异常。

## 4. 文件与职责

- 生产 Python 文件上限 250 行，由架构测试强制。
- 一个文件只承担一个主要职责。
- 只有消除真实复杂度时才增加抽象。
- 不允许在 API 路由、页面代码或训练脚本中复制成交与风控规则。
- 规则版本、数据版本、特征版本和标签版本是公共契约，不得无声修改。

## 5. 研究产物

所有可比较的研究输出必须由不可变清单描述：

- 数据集通过 `DatasetSpec.snapshot_id` 内容寻址。
- 特征和标签分别定义、分别版本化、物理隔离。
- 实验通过 `ExperimentManifest` 绑定数据、代码、随机种子和 split 协议。
- 模型通过 `ModelRecord` 关联数据集与训练运行。
- `DRAFT` 模型只有获得 `TrainingApproval` 后才能变为 `VALIDATED`。
- 模型分数先进入组合构建器，再进入风控，不得直接变成订单。

## 6. 测试策略

- 单元测试覆盖数据校验、标签、切分、成交、费用和风险规则。
- 集成测试覆盖真实 FastAPI 边界和未来的 DuckDB/Parquet 适配器。
- E2E 覆盖用户可见研究闭环。
- 每个测试只有一个 When，使用 Given / When / Then 组织。
- 不以 Mock 替代可快速创建的真实值对象。
- 时间、随机数、数据快照和模型种子必须显式固定。

## 7. 数据和机器学习

完整硬规则以 `QUANT_RESEARCH_RULEBOOK.md` 为准。工程实现必须确保：

- 策略读取数据前先通过 `DataQualityGuard`。
- `available_at` 晚于决策时间的数据无法进入特征。
- 训练预处理器只能在训练折拟合。
- 最终测试集最多运行一次。
- 多次模型选择必须记录试验次数并使用多重检验控制。
- 演示或合成数据训练的模型不得晋级为投资决策模型。

## 8. 安全与运维

- 密钥通过环境变量或本机密钥管理器注入，不写入仓库和日志。
- 原始供应商响应只追加，不原地修改。
- 日志不得包含 Token、交易密码或完整账户信息。
- 模型文件、市场数据和研究产物默认不提交 Git。
- 未来实盘功能必须与研究环境隔离，并增加人工审批与紧急停止机制。

## 9. 质量门禁

```bash
make check
```

该命令依次检查格式、Lint、严格类型和带 90% 覆盖率门禁的测试。CI 使用完全相同的命令集合。

