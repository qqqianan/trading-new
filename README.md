# A 股量化研究台

一个面向个人投资者的本地优先量化研究项目。当前版本提供确定性演示行情、双均线策略、带 A 股交易约束的日频回测，以及可操作的中文 Web 研究台。

> 本项目仅用于研究和软件验证，不构成投资建议。演示行情不是真实市场数据，回测收益不代表未来表现。

## 快速开始

```bash
uv sync --all-groups
uv run uvicorn ashare_lab.main:app --reload --port 8000
```

打开 <http://127.0.0.1:8000>。API 文档位于 <http://127.0.0.1:8000/docs>。

## Tushare 数据接入

真实数据只写入隔离数据库 `ashare_quant`。密钥保存在被 Git 忽略的本机 `.env`，初始化和
日频 Raw 同步使用：

```bash
uv run ashare-data init-db
uv run ashare-data daily --trade-date YYYYMMDD
uv run ashare-data daily-latest
uv run ashare-data backfill-market --start-date YYYYMMDD --end-date YYYYMMDD --max-days 20
uv run ashare-data sync-universe --start-date 19900101 --end-date YYYYMMDD
uv run ashare-data sync-dividends --start-date YYYYMMDD --end-date YYYYMMDD --max-days 31
uv run ashare-data backfill-income --start-date YYYYMMDD --end-date YYYYMMDD --max-securities 100
```

历史回填只选择尚未形成完整治理证据链的交易日。默认单日失败后安全停止；需要在记录失败后
继续本批其他日期时，显式增加 `--continue-on-error`。供应商请求在同步服务层统一限速，默认
间隔为 1.2 秒，可通过 `TUSHARE_MIN_REQUEST_INTERVAL_SECONDS` 调整。

小范围验收命令：

```bash
uv run ashare-data pilot \
  --trade-date YYYYMMDD \
  --calendar-start YYYYMMDD \
  --calendar-end YYYYMMDD
```

命令只拉取 schema 白名单接口，所有响应依次经过字段契约、内容哈希、MongoDB validator、
canonical 转换、质量报告和字段级 lineage。重复响应不会覆盖 Raw。PIT 查询只允许读取
`quality_status=ACCEPTED` 且 `available_at <= decision_time` 的记录。历史股票池由 `LISTED`、
`FIRST_TRADED`、`DELISTED` 和 `NAME_STATUS` 事件回放；未知 ST 状态必须排除，不能默认成正常股。

macOS 本机已通过 `com.ashare-lab.daily-data` LaunchAgent 在每天 `18:30` 和 `21:30` 执行
`nightly-maintenance`，仓库模板位于 `ops/launchd/`，日志写入被 Git 忽略的 `logs/`。每天同步
交易日历、五类股票日频、六个基准日线并回看最近 7 个自然日的分红公告；周一至周四分别以
14 天固定窗口刷新利润表、资产负债表、现金流和财务指标，周五刷新股票池与名称，周六回看
最近三个月基准权重并同步行业。所有阶段继续通过 TushareSyncService 限速、Raw 门禁、
canonical、PIT、质量和 lineage 链路。正式模型训练仍保持关闭。
`21:30` 轮次用于补拉晚发布数据；已具备完整范围证据的财务证券会直接跳过。

## 质量检查

```bash
make check
```

量化研究的最高约束见 [docs/QUANT_RESEARCH_RULEBOOK.md](docs/QUANT_RESEARCH_RULEBOOK.md)。其中明确了点时可得性、数据准确性、回测方法、模型训练红线与风险控制要求，并由数据门禁、模型治理守卫和风控引擎在代码中执行。

开发前先阅读根目录 [AGENTS.md](AGENTS.md)。工程约束见 [docs/ENGINEERING_STANDARDS.md](docs/ENGINEERING_STANDARDS.md)，机器学习目标架构见 [docs/ML_SYSTEM_ARCHITECTURE.md](docs/ML_SYSTEM_ARCHITECTURE.md)。需求边界见 [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)，系统分层见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
