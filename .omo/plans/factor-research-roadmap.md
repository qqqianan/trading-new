# A股中期选股研究系统整体规划

## TL;DR
> Summary:      在现有受治理 Tushare/PIT 数据层之上，建设一条不可绕过的中期横截面选股研究流水线；先完成可追溯数据集、基础因子、标签、因子诊断和多标的组合回测，再进入 Ridge 训练。
> Deliverables: PIT DatasetBuilder；21 个基础因子；20 日相对收益标签；因子审计；周频 Top 30 组合；组合风控与 A 股回测；Ridge 基线；可复现研究报告
> Effort:       XL
> Risk:         High - 时间穿越、财务修订、生存者偏差、多重检验及单标的回测向组合回测升级均可能让结果失真

## Scope
### Must have

- 研究区间从 `2020-01-02` 开始，只使用 `ashare_quant` 中当前 schema 下 `ACCEPTED` 的 Raw/canonical/PIT 数据。
- 中期横截面选股：每周最后一个开市日收盘后决策，下一开市日开盘执行。
- 标签固定为 `t+1 open -> t+21 open` 的个股收益减 `000905.SH` 同期收益。
- 历史股票池按 `effective_at` 与 `available_at` 双时钟回放；未知 ST/名称状态 fail closed。
- 特征、标签、股票池、schema、转换、参数和代码版本都内容寻址并具备字段级 lineage。
- 原始因子物化与标签物理隔离；去极值、填充、标准化、行业/规模中性化只在训练折内拟合。
- 因子研究必须登记全部试验并执行 Benjamini-Hochberg FDR 控制，禁止只留下表现最好的结果。
- Top 30 等权组合，默认现金 5%、单票上限 5%、单次调仓换手上限 25%、成交量参与率上限 5%；单行业上限 20% 仅在当时已有 PIT 行业证据时强制。
- 回测保留 T+1、100 股一手、停牌、涨跌停、费用、滑点、成交量、未成交和受阻退出。
- 最终测试区独立封存，只有特征、组合、成本、风险和模型参数全部冻结后才允许一次性打开。

### Must NOT have

- 不读取 `tradingagentscn`，不使用演示/合成行情证明因子或模型有效。
- 不接券商、不自动下单、不做空、不加杠杆、不加入分钟/Tick/另类数据。
- 不把当前指数成分、当前 ST 状态、最终退市结局或最新财务修订回填到历史。
- 不在全样本拟合 winsorizer、imputer、scaler、行业中性化或特征选择。
- 不在本计划内实现 LightGBM、神经网络、模型注册 UI；Ridge 未稳定前不升级复杂模型。
- 不将模型分数直接转换成订单；必须经过组合构建器和组合风控。

## Fixed research protocol

- 决策日：每个 ISO 周的最后一个开市日；`decision_time` 为该日收盘数据发布之后。
- 可交易日：决策日后的首个开市日；标签与回测均以该日原始开盘价进入。
- 标签：持有 20 个交易日，于第 21 个开市日原始开盘价退出；减去 `000905.SH` 同期收益。
- 开发区：`2020-01-02` 至 `2024-12-31`；最终测试区：`2025-01-01` 至首个冻结快照确定的截止日。
- 开发 Walk-forward：初始训练 504 个交易日、验证 126 个交易日、滚动步长 63 个交易日、purge 20、embargo 5；最终测试区不属于任何开发 fold。
- 股票准入：历史时点已上市至少 120 个交易日、ST/名称状态已知且非 ST、过去 60 日中至少 50 日有行情、过去 20 日成交额中位数不少于 2,000 万元。
- 停牌、涨跌停属于当日可交易性与成交约束，不得通过删除历史样本消失；持仓标的即使不再允许新买也继续进入盯市和退出流程。
- 因子原值不做跨期拟合。训练折预处理顺序固定为：按训练折估计 1%/99% 边界 -> 截面中位数填充并附缺失指示器 -> 截面 z-score -> `log(total_mv)` 中性化；行业中性化仅能用于首次 PIT 观察后的区间。
- 当前申万成员的最早 `available_at` 是 2026 年，禁止回填到 2020 年。因此 2020-2025 的行业暴露只能标记为 `UNAVAILABLE`，对应研究状态保持 `DRAFT`，不能声称通过完整组合风险门禁。

## First factor catalog

| Family | Feature IDs | Exact definition |
|---|---|---|
| Momentum | `mom_20`, `mom_60`, `mom_120` | 当时可得的 `close * adj_factor` 在对应交易日窗口的简单收益 |
| Reversal | `reversal_5` | `-mom_5`，只使用截至决策日收盘的信息 |
| Risk | `vol_20`, `vol_60`, `max_drawdown_60` | 复权日收益样本标准差及 60 日滚动最大回撤 |
| Liquidity | `turnover_mean_20`, `amount_median_20`, `amihud_20` | 换手率均值、人民币成交额中位数的 `log1p`、`mean(abs(raw_return)/(amount*1000))` |
| Size | `log_total_mv` | `log(total_mv * 10000)`，非正值为空 |
| Valuation | `earnings_yield_ttm`, `book_yield`, `sales_yield_ttm`, `dividend_yield_ttm` | 正数 `pe_ttm/pb/ps_ttm` 的倒数及 `dv_ttm/100`；非正估值分母为空，不取绝对值 |
| Quality | `roe`, `grossprofit_margin`, `ocf_to_debt`, `debt_to_assets` | 最新实际公告且当时可得的财务指标 PIT 版本；杠杆方向在组合打分时取负 |
| Growth | `q_sales_yoy`, `q_netprofit_yoy` | 最新实际公告且当时可得的单季同比 PIT 版本 |

共 21 个原始因子。任何新增、删减或公式变化必须升级 feature version，并作为一次新试验登记。

## Factor admission rules

- 覆盖率、缺失率、极值率、重复率和 PIT 泄漏检查全部通过。
- 开发验证 folds 的平均绝对 Rank IC 至少 `0.02`，方向一致率至少 `55%`。
- 五分组收益方向至少四档单调，且报告税费和滑点后的 Top-Bottom 表现。
- 必须报告年度、行业、规模组、牛熊/震荡区间、换手和容量；不得只看全期均值。
- 同一批因子检验执行 BH-FDR，默认 `q <= 0.10`；未通过只可标为 `REJECTED`，不能静默删除。
- 候选因子间训练期 Spearman 相关性绝对值超过 `0.80` 时，只保留事先定义优先级更高且血缘更简单者。
- 上述阈值只决定是否进入第一版复合因子，不构成收益保证或模型晋级批准。

## Verification strategy
> Zero human intervention - all verification is agent-executed.

- Test decision: TDD，使用 Pytest；先确认失败原因，再最小实现，再运行 `make check`。
- QA policy: 每个 todo 都包含正常、拒绝或泄漏场景，并保存命令输出或结构化审计产物。
- Evidence: `.omo/evidence/task-<N>-<slug>.<ext>`；真实数据库集成测试只读输入并写内容寻址研究产物，不改 Raw。
- 全局完成门禁：`make check` 全绿、覆盖率不低于 90%、生产 Python 文件不超过 250 行、Mongo Raw 数量不减少。

## Execution strategy
### Parallel execution waves

> 每一波内仅表示依赖允许并行；执行时仍需尊重同一工作区的文件所有权。

- Wave 1: Todo 1, 2, 3
- Wave 2: Todo 4, 5, 6
- Wave 3: Todo 7, 8
- Wave 4: Todo 9, 10
- Wave 5: Todo 11, 12
- Wave 6: Todo 13
- Critical path: 1 -> 2 -> 3 -> 4 -> 5/6 -> 7 -> 8 -> 9 -> 10 -> 11 -> 12 -> 13

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
|---|---|---|---|
| 1 | - | 2, 12 | 2, 3 |
| 2 | - | 3, 4, 5, 6 | 1 |
| 3 | 2 | 4, 5, 6 | - |
| 4 | 2, 3 | 5, 6, 7 | - |
| 5 | 4 | 7 | 6 |
| 6 | 4 | 7 | 5 |
| 7 | 5, 6 | 8, 11 | - |
| 8 | 7 | 9, 12 | - |
| 9 | 8 | 10, 11 | 10 contracts only |
| 10 | 8, 9 | 11 | - |
| 11 | 7, 9, 10 | 12 | - |
| 12 | 1, 8, 11 | 13 | - |
| 13 | 12 | Final verification | - |

## Todos

- [x] 1. 建立可复现工程身份与研究预检
  What to do: 确认当前目录没有 Git 元数据后执行非破坏性的 `git init`，建立主分支和首个受治理基线提交；新增 research preflight，读取真实 Git SHA、规则版本、Python/uv lock 哈希、Mongo 数据库名和最终测试访问状态。无 Git、脏工作树用于可晋级训练、数据库不是 `ashare_quant`、lock 不匹配或最终测试已被重复打开时 fail closed。补充 `.gitignore`，确保数据、模型、Token、日志和 `.omo/evidence` 不提交。
  Must NOT do: 不提交 `.env`、Mongo 数据、Parquet、模型二进制或现有日志；不伪造 Git SHA。
  Parallelization: Can parallel Y | Wave 1 | Blocks 2,12
  References: `src/ashare_lab/research/experiments/manifest.py:1`; `docs/ML_SYSTEM_ARCHITECTURE.md:76`; `.gitignore`; `AGENTS.md` sections 8,12
  Acceptance criteria: 无 Git SHA 时预检拒绝；干净提交、正确数据库和 lock 时生成内容寻址 preflight manifest；`git status --short` 仅显示计划内文件；`make check` 通过。
  QA scenarios: `uv run pytest tests/test_research_preflight.py -q` 覆盖正常身份、缺 Git、脏树晋级、错误数据库、重复 final holdout；Evidence `.omo/evidence/task-1-preflight.txt`
  Commit: Y | `chore(research): establish reproducible project identity` | `.gitignore`, `src/ashare_lab/research/preflight.py`, tests

- [x] 2. 从 Mongo 治理证据生成真实 DatasetCoverageReport
  What to do: 实现只读 `MongoCoverageEvidenceReader`，对 market daily bundle、universe PIT、benchmark daily、financial PIT 及可选 industry PIT 分别收集共同日期范围、当前 schema ID、accepted Raw snapshot、canonical/PIT lineage 和通过的 quality report；lineage 的 `code_commit` 必须是真实 Git SHA。现有 `workspace_unversioned` 证据一律阻断，并通过从不可变 Raw 追加新转换版本的受治理重物化解除，禁止修改旧 lineage。将现有纯函数 `qualify_dataset()` 作为唯一裁决器，并通过 service/CLI 持久化 coverage report 与 input manifest。零行批次只有完整证据链时算完成。
  Must NOT do: 不让 CLI 手工声明 `quality_passed=True` 或 `point_in_time=True`；不以最新文档时间代替完整覆盖。
  Parallelization: Can parallel Y | Wave 1 | Blocks 3,4,5,6
  References: `src/ashare_lab/research/datasets/coverage.py:29`; `src/ashare_lab/research/datasets/coverage_models.py:8`; `src/ashare_lab/research/datasets/artifact_store.py:1`; `src/ashare_lab/data/canonical_store.py:94`; `docs/ML_SYSTEM_ARCHITECTURE.md:72`
  Acceptance criteria: 对 `2020-01-02` 至冻结截止日生成可复现报告；未重物化前明确报告 `unversioned_lineage`，重物化后旧证据仍保留而新证据绑定真实 Git SHA；删去任一模拟 quality/lineage/Raw 证据立即变为 `BLOCKED`；重复执行 ID 不变且不重复插入；生产只读 Mongo reader 不访问 legacy database。
  QA scenarios: `uv run pytest tests/test_dataset_evidence_reader.py tests/test_dataset_coverage_service.py -q`；本机只读 dry-run 输出组件矩阵到 `.omo/evidence/task-2-coverage.json`
  Commit: Y | `feat(dataset): derive qualification from governed mongo evidence` | `research/datasets`, `services`, CLI, tests

- [x] 3. 建立不可变研究产物存储、schema 与 lineage 注册
  What to do: 增加 `duckdb` 依赖并实现 Parquet artifact writer/reader；临时文件写完、校验 row count/schema/SHA-256 后原子 rename，路径由 artifact ID 决定。定义 feature row、label row、universe row、dataset row 的机器可读 schema；每个产物登记 transform name/version、参数哈希、代码提交、字段映射、上游 artifact/snapshot IDs。特征与标签写入物理分离目录。
  Must NOT do: 不在 Parquet 内放动态列，不覆盖同 ID 的不同内容，不把 Mongo `ingested_at` 当成市场可得时间。
  Parallelization: Can parallel Y | Wave 1 | Blocks 3,4,5,6
  References: `docs/ML_SYSTEM_ARCHITECTURE.md:3`; `docs/DATA_CONTRACT_AND_LINEAGE.md:170`; `src/ashare_lab/research/datasets/assembly.py:15`; `schemas/research_dataset_v1.json`; `.gitignore`
  Acceptance criteria: 同输入重复物化得到相同 ID/哈希；内容变化得到新 ID；截断文件、schema 漂移、缺 lineage、跨目录标签读取均拒绝；DuckDB 能只读查询产物。
  QA scenarios: `uv run pytest tests/test_research_artifact_store.py tests/test_research_schema_registry.py -q`; Evidence `.omo/evidence/task-3-artifacts.txt`
  Commit: Y | `feat(research): add immutable parquet artifact store` | `pyproject.toml`, `uv.lock`, schemas, `research/artifacts`, tests

- [x] 4. 构造周频决策日与历史 PIT 股票池面板
  What to do: 从 accepted trade calendar 选择每个 ISO 周最后开市日；使用 `UniverseBuilder` 的双时钟事件回放构造每个决策日可见股票池。应用版本化准入规则：上市满 120 个交易日、ST 状态已知且非 ST、60 日至少 50 个行情观测、20 日成交额中位数不低于 2,000 万元。分别输出 `eligible_for_new_risk` 与 `must_continue_marking`，避免退市、停牌或持仓退出受阻样本被删除。
  Must NOT do: 不读当前 `stock_basic` 快照重建历史，不把未知 `is_st` 当非 ST，不因未来退市或亏损删除样本。
  Parallelization: Can parallel N | Wave 2 | Blocks 5,6,7
  References: `src/ashare_lab/data/universe_builder.py`; `src/ashare_lab/data/universe.py`; `docs/QUANT_RESEARCH_RULEBOOK.md:37`; `AGENTS.md` section 5
  Acceptance criteria: 在退市、名称/ST 变化、首次交易和停牌夹具上逐日回放正确；改变准入参数生成新 universe version；所有面板行满足 `available_at <= decision_time`。
  QA scenarios: `uv run pytest tests/test_research_calendar.py tests/test_research_universe_panel.py -q`; 本机抽取 10 个历史变更代码做时间切片审计 `.omo/evidence/task-4-universe.json`
  Commit: Y | `feat(research): materialize weekly pit universe` | `research/universe`, schemas, tests

- [x] 5. 实现行情、风险、流动性、规模与估值因子
  What to do: 建立闭集 feature registry 和 Polars 计算器，物化表中定义的 15 个非财务因子。复权连续收益使用当时可得的 `close * adj_factor`，成交模拟仍只用原始价；单位严格转换为人民币/股。每个输出行包含 symbol、decision_time、feature ID/version、value、available_at、artifact ID 和质量状态；缺历史窗口输出 null 与原因，不删除股票。
  Must NOT do: 不使用未来复权因子，不对非正 PE/PB/PS 取绝对值或强制填零，不在此阶段全样本标准化。
  Parallelization: Can parallel Y | Wave 2 | Blocks 7
  References: `src/ashare_lab/research/features/definition.py:18`; `schemas/tushare_p0_v1.json` daily/adj_factor/daily_basic; `docs/QUANT_RESEARCH_RULEBOOK.md:59`
  Acceptance criteria: 手算夹具精确匹配 15 个公式；窗口不足、零成交额、非正估值、停牌和复权因子变化均有稳定空值/结果语义；任一输入行 `available_at` 越界时整批拒绝。
  QA scenarios: `uv run pytest tests/test_market_factors.py tests/test_feature_pit_guard.py -q`; 对 3 只股票 3 个决策日导出手算比对 `.omo/evidence/task-5-market-factors.csv`
  Commit: Y | `feat(features): add governed market factor family` | `research/features`, schemas, tests
  Completed: 15 个独立 feature artifacts 各 1,712,992 行，共 25,694,880 行；重复键、PIT 违规、
  股票池键差异和质量语义违规均为 0。3 只股票 × 3 个决策日的 `mom_20`、`log_total_mv` 和
  `earnings_yield_ttm` 已从 canonical 字段独立手算并逐值匹配。代码提交为 `f4d69bc`、
  `6909349` 和 `ed164be`；artifact IDs 与空值分布记录在 `docs/DATA_CONTRACT_AND_LINEAGE.md`。

- [x] 6. 实现财务质量与成长因子
  What to do: 基于 accepted PIT financial indicator 版本物化 `roe`, `grossprofit_margin`, `ocf_to_debt`, `debt_to_assets`, `q_sales_yoy`, `q_netprofit_yoy`。对每个决策点只选 `available_at <= decision_time` 的最新已公告版本，保留版本 ID、报告期、公告时钟、update_flag 和字段级 lineage；同日多版本使用稳定的版本排序规则，绝不覆盖旧版。
  Must NOT do: 不从 canonical 财务表直接研究，不按 `end_date` 提前生效，不以后见修订覆盖当时版本，不把缺公告日期回填到报告期末。
  Parallelization: Can parallel Y | Wave 2 | Blocks 7
  References: `src/ashare_lab/data/financial_indicators.py`; `src/ashare_lab/data/financial_indicator_documents.py`; `schemas/tushare_financial_indicator_v1.json`; `AGENTS.md` financial PIT rules
  Acceptance criteria: 公告前为 null、公告后出现、修订发布前仍读旧值、修订后读新值；每个字段可追溯到确切 Raw payload 字段和 snapshot。
  QA scenarios: `uv run pytest tests/test_financial_factors.py tests/test_financial_factor_lineage.py -q`; 选择至少一个真实修订样本输出 as-of 序列 `.omo/evidence/task-6-financial-pit.json`
  Commit: Y | `feat(features): add pit financial factor family` | `research/features`, schemas, tests
  Completed: 6 个独立 financial feature artifacts 各 1,712,992 行，共 10,277,952 行；重复键、
  PIT 越界、股票池键差异、质量语义、血缘形状和跨因子来源差异均为 0。真实修订样本
  `301589.SZ` 证明修订只在发布后生效，随后较新报告期按规则优先。基础层提交为 `dd3c39e`，
  服务与全量物化提交为 `734d49c`；artifact IDs 和缺失分布记录在
  `docs/DATA_CONTRACT_AND_LINEAGE.md`。

- [x] 7. 物化隔离标签并装配 DatasetSpec
  What to do: 单独 label service 计算 `t+1 open -> t+21 open` 个股与 `000905.SH` 同期简单收益差；使用交易日索引而非自然日偏移，无法进入/退出或基准缺失时保留 null 原因。特征服务不得导入 label 包，标签服务不得向 feature artifact 写列。完成 feature、label、universe artifact 后调用 `assemble_dataset_spec()`，固定全部 snapshot/schema/lineage/artifact ID。
  Must NOT do: 不用决策日收盘成交，不用复权价格模拟进入/退出，不允许没有未来 21 日的样本伪造标签。
  Parallelization: Can parallel N | Wave 3 | Blocks 8,11
  References: `src/ashare_lab/research/labels/definition.py:16`; `src/ashare_lab/research/datasets/assembly.py:57`; `docs/ML_SYSTEM_ARCHITECTURE.md:42`; `docs/QUANT_RESEARCH_RULEBOOK.md:28`
  Acceptance criteria: 周末、节假日、停牌、涨跌停不改变标签的交易日索引定义；label lineage 与 feature lineage 无交叉边；任一缺失 evidence 阻止 DatasetSpec；相同输入生成相同 `ds_*`。
  QA scenarios: `uv run pytest tests/test_label_materialization.py tests/test_dataset_end_to_end.py tests/test_architecture.py -q`; Evidence `.omo/evidence/task-7-dataset-manifest.json`
  Commit: Y | `feat(dataset): materialize isolated medium-horizon labels` | `research/labels`, `research/datasets`, services, tests
  Completed: 标签 artifact 保留全部 1,712,992 个宇宙键，其中 1,598,017 行具有完整相对收益；
  重复键、股票池键差异、未来时钟、值语义和完整来源违规均为 0。330 组完整窗口的 t+1/t+21
  交易日偏移全部正确，1,449 个实际来源 snapshot 均属于 qualified closure，Raw 开盘价手算误差为
  0。`ds_862d155145b89879b679` 固定 21 个 feature artifact 与独立 label lineage，二者交集为 0。
  代码提交为 `043c360`，完整身份和分布记录在 `docs/DATA_CONTRACT_AND_LINEAGE.md`。

- [x] 8. 建立最终测试封存、purged walk-forward 与训练折预处理
  What to do: 将最终测试日期单独建 `FinalHoldoutSpec` 和 append-only access ledger；开发代码默认只能读取 `2024-12-31` 及以前。扩展 split 合约，明确开发 fold 与 final holdout 不重叠，标签窗口 purge 20、embargo 5。实现 sklearn/Polars 的 typed fold preprocessor，所有拟合统计与中性化系数只来自当前训练 fold，并作为 artifact 保存。
  Must NOT do: 不允许配置 `allow_final_test=true` 绕过；不缓存全样本统计量；不把开发 fold 的内部 OOS 叫最终测试。
  Parallelization: Can parallel N | Wave 3 | Blocks 9,12
  References: `src/ashare_lab/research/splits/walk_forward.py:8`; `docs/QUANT_RESEARCH_RULEBOOK.md:140`; `src/ashare_lab/research/model_governance.py:69`
  Acceptance criteria: 任何 fold 的 scaler/imputer 参数只等于训练切片手算值；相邻标签窗口无重叠；默认 API/CLI 读取 final holdout 被拒；首次正式打开后 ledger 计数为 1，第二次拒绝。
  QA scenarios: `uv run pytest tests/test_walk_forward.py tests/test_fold_preprocessing.py tests/test_final_holdout.py -q`; Evidence `.omo/evidence/task-8-leakage-audit.json`
  Commit: Y | `feat(research): enforce sealed holdout and fold preprocessing` | `research/splits`, `research/preprocessing`, governance, tests
  Completed: 开发截止固定为 `2024-12-31`，final holdout 从 `2025-01-01` 起由 DatasetSpec-bound
  `FinalHoldoutSpec`、冻结协议授权和原子 append-only ledger 隔离；真实 holdout 未打开。开发切分固定
  504/126/63/63、purge 20、embargo 5；周频样本必须先由 DatasetSpec-bound 日交易日历生成 fold
  边界，禁止把周频观测数误当交易日数。预处理 `1.0.0` 仅从训练折拟合 winsor/fallback 和规模系数，
  同日横截面填充保留 missing indicator，不删除样本；artifact 固定 DatasetSpec、训练日期、输入 SHA-256
  与有序特征并内容寻址保存。历史行业 PIT 不足明确记录 `UNAVAILABLE`。全仓 358 测试通过，覆盖率
  90.20%，审计见 `.omo/evidence/task-8-leakage-audit.json`。

- [x] 9. 建立因子诊断、试验账本和多重检验门禁
  What to do: 对开发 folds 计算 coverage、Rank IC/ICIR/方向一致率、五分组单调性、Top-Bottom 净收益、换手、自相关、行业/规模暴露、年度和市场状态分段。所有尝试先登记 immutable trial，再计算结果；按同一研究批次执行 BH-FDR `q<=0.10`。输出 `CANDIDATE/REJECTED` 及稳定原因代码，相关性去冗余按预定义 family/lineage 简洁度优先级执行。
  Must NOT do: 不隐藏失败因子或失败年份，不读取 final holdout，不用回测总收益作为唯一晋级标准。
  Parallelization: Can parallel N | Wave 4 | Blocks 10,11,12
  References: `docs/QUANT_RESEARCH_RULEBOOK.md:129`; `docs/QUANT_RESEARCH_RULEBOOK.md:151`; `src/ashare_lab/research/experiments/manifest.py`
  Acceptance criteria: 21 个因子均出现在 trial ledger；人为添加额外噪声试验会改变 FDR 结果；反转因子方向翻转被正确记录；报告包含最差年份、最差行业和缺失样本，不只含赢家。
  QA scenarios: `uv run pytest tests/test_factor_diagnostics.py tests/test_multiple_testing.py tests/test_trial_ledger.py -q`; 在固定小数据集生成 `.omo/evidence/task-9-factor-report.json`
  Commit: Y | `feat(research): add audited factor diagnostics` | `research/factors`, `research/experiments`, reports, tests
  Completed: 21 个真实 feature artifact 已在 `46bf4fd` 后完整登记为
  `trial_batch_898124e44b83fa1cc67fc01ec1fb7405dd43670518eae9237160f5fbb5802e6c`；唯一
  `AuditedFactorResearchService` 先验证 ledger 再计算 Rank IC/ICIR、方向、五分组、成本后
  Top-Bottom、换手、自相关、规模及年份/状态/可得行业分段，并统一执行 BH-FDR `q<=0.10` 与同 family
  去冗余。固定合成 QA 覆盖全部 21 个决定，反转方向由 -1 翻为 +1，额外噪声改变 FDR，且报告包含
  缺失样本、最差年份/行业；不声称真实投资有效性。全仓 382 测试通过，覆盖率 90.11%。

- [x] 10. 实现周频 Top 30 组合构建器与组合级事前风控
  What to do: 简单基线先按已准入候选因子的等权 z-score 合成分数，按 symbol 稳定打破并列，选择 Top 30，目标总仓位 95%。组合构建器只产生目标权重；组合 RiskEngine 检查单票 5%、持仓 30、现金 5%、调仓换手 25%、成交量参与率 5%、集中度和容量，并输出 resize/reject 事件；行业 PIT 已知时另强制单行业 20%，未知时记录 `INDUSTRY_EXPOSURE_UNAVAILABLE` 并阻止研究晋级为 `VALIDATED`。无法新买不等于强制卖出，退出意图持续保留。
  Must NOT do: 不在策略、API 或模型中复制风险规则，不让 target weight 直接成为成交。
  Parallelization: Can parallel N | Wave 4 | Blocks 11
  References: `src/ashare_lab/portfolio/contracts.py:1`; `src/ashare_lab/backtest/risk.py:17`; `src/ashare_lab/domain/risk.py`; `docs/ML_SYSTEM_ARCHITECTURE.md:107`
  Acceptance criteria: 权重和现金严格为 1；极端同业集中、低流动性、超换手和不足一手均被缩量/拒绝并记录规则；模型分数对象没有订单创建能力。
  QA scenarios: `uv run pytest tests/test_portfolio_builder.py tests/test_portfolio_risk.py tests/test_architecture.py -q`; Evidence `.omo/evidence/task-10-risk-decisions.json`
  Commit: Y | `feat(portfolio): construct risk-governed weekly targets` | `portfolio`, domain risk, tests
  Completed: 已实现候选因子等权标准化分数、稳定并列排序、Top 30 与 95% 股票目标；组合层只产生
  `PortfolioTarget`。唯一组合风险引擎覆盖持仓数、单票、现金、换手、成交量参与率、一手容量、HHI
  集中度和 PIT 行业，并保留退出意图；未知行业产生 `BLOCK_VALIDATION` 且状态保持 `DRAFT`。架构测试
  禁止 portfolio 导入交易或回测能力，机器契约为 `portfolio_risk_decision_v1.json`，固定合成 QA 见
  `.omo/evidence/task-10-risk-decisions.json`。全仓 399 测试通过，覆盖率 90.26%，final holdout 未打开。

- [x] 11. 将单标的引擎升级为多标的 A 股组合回测
  What to do: 保留现有单标的 API 兼容层，新增组合账户、每票 lot/成本/T+1 状态、挂单和逐日盯市。事件顺序固定为：读取可得信息 -> 目标 -> 事前风控 -> 下一开盘成交 -> 费用 -> 收盘盯市/熔断。涨停买单、跌停卖单、停牌与成交量不足订单保持 pending 并逐日审计；组合熔断停止新增风险并尝试退出。报告绝对/基准/超额收益、波动、回撤、Sharpe、换手、费用、容量、风险事件与分段结果。
  Must NOT do: 不假设全量成交，不净掉受阻退出，不用复权价成交，不删除退市/无行情持仓。
  Parallelization: Can parallel N | Wave 5 | Blocks 12
  References: `src/ashare_lab/backtest/engine.py:41`; `src/ashare_lab/backtest/risk.py:29`; `docs/QUANT_RESEARCH_RULEBOOK.md:107`; `docs/QUANT_RESEARCH_RULEBOOK.md:165`
  Acceptance criteria: 多票现金与持仓逐笔守恒；佣金最低额、印花税、滑点、T+1、lot、涨跌停、停牌和参与率手算一致；风险退出受阻会跨日重试；旧单票测试继续通过。
  QA scenarios: `uv run pytest tests/test_portfolio_backtest.py tests/test_portfolio_accounting.py tests/test_backtest_risk_exits.py tests/test_backtest_engine.py -q`; 固定 5 票情景账本 `.omo/evidence/task-11-trade-ledger.csv`
  Commit: Y | `feat(backtest): add multi-asset ashare execution engine` | `backtest`, domain trading/risk, services, tests
  Completed: 保留旧单标的 API，新增唯一 `PortfolioBacktestEngine`、多票现金/持仓/tax-lot 账户和逐日
  盯市。所有目标强制经过组合风控并在下一开盘先卖后买；T+1、100 股一手、停牌、涨跌停、参与率、
  部分成交、费用、滑点和现金缓冲均逐笔守恒，pending 与风险退出跨日保留。报告覆盖绝对/基准/超额
  收益、波动、Sharpe、回撤、换手、费用、容量、风险事件和年度分段，机器契约为
  `portfolio_backtest_report_v1.json`，五票合成 QA 见 `.omo/evidence/task-11-trade-ledger.csv`；不声称
  投资有效。全仓 412 测试通过，覆盖率 90.35%，final holdout 未打开。

- [x] 12. 建立等权/线性基线与受治理 Ridge 训练
  What to do: 先保存等权因子组合的开发 fold 结果，再增加 scikit-learn Ridge 的 typed trainer；只通过 `TrainingService` 调用。每 fold 单独预处理、拟合与预测，超参数候选固定为 `alpha=(0.1,1,10,100)`，只由开发验证 folds 选择；保存全部候选结果、随机种子、DatasetSpec、ExperimentManifest、模型哈希和预测 lineage。`ModelTrainingGuard` 从实际 artifacts 验证证据，不能由调用者布尔声明。只有 Ridge 在相同快照/组合/成本下稳定优于简单基线且 final test 单次运行后，才可申请 `VALIDATED`。
  Must NOT do: 不在本任务加入 LightGBM，不把最终测试用于 alpha、特征或阈值选择，不让 trainer 绕过 service。
  Parallelization: Can parallel N | Wave 5 | Blocks 13
  References: `src/ashare_lab/services/training.py:23`; `src/ashare_lab/ml/contracts.py`; `src/ashare_lab/research/model_governance.py:69`; `src/ashare_lab/ml/registry.py`; `docs/ML_SYSTEM_ARCHITECTURE.md:98`
  Acceptance criteria: 架构测试证明只有 TrainingService 可导入 Trainer；篡改 dataset/model artifact 哈希或缺 schema/lineage 时训练前拒绝；alpha 选择不访问 final holdout；重复 final test 拒绝；模型默认 `DRAFT`。
  QA scenarios: `uv run pytest tests/test_ridge_trainer.py tests/test_training_service.py tests/test_model_governance.py tests/test_architecture.py -q`; Evidence `.omo/evidence/task-12-experiment-manifest.json`
  Commit: Y | `feat(ml): add governed ridge baseline` | `ml`, services, governance, pyproject/lock, tests
  Completed: `TrainingService` 先校验模型族并调用 artifact-backed `ModelTrainingGuard`，只有审批后才创建
  `TrainerJob`；DatasetSpec、字段 schema/lineage、fold preprocessor、development frame 和 final holdout
  零访问账本均逐字节验证。Ridge 固定四个 alpha，只按 validation mean MSE 选择，随后才查看内部 test；
  保存等权基线、全部候选、fold 指标、系数、预测 SHA/lineage 和内容寻址 JSON，默认注册为 `DRAFT`。
  合成 QA 明确不可用于投资判断，final holdout 未打开。全仓 425 测试通过，覆盖率 90.20%。

- [ ] 13. 提供一键研究命令、审计报告与运行手册
  What to do: 增加 `ashare-research` CLI，按 qualify -> materialize -> diagnose -> portfolio -> backtest -> train 的顺序编排，默认停在 final holdout 之前。生成机器 JSON 和中文 Markdown 报告，明确数据截止、snapshot/schema/lineage、股票池规则、因子公式、全部试验、成本/风险参数、最差区间、失败和 DRAFT/VALIDATED 状态。更新架构、数据字典、lineage、工程规范和 README；每日调度只更新数据，不自动重训或打开最终测试。
  Must NOT do: 不在报告中承诺收益，不在日志输出 Token，不让 UI/CLI 提供绕过 guard 的选项。
  Parallelization: Can parallel N | Wave 6 | Blocks Final verification
  References: `src/ashare_lab/data/cli.py`; `docs/DATA_CONTRACT_AND_LINEAGE.md`; `docs/ENGINEERING_STANDARDS.md`; `README.md`; `AGENTS.md`
  Acceptance criteria: 从固定快照重复运行得到相同 artifact IDs 和指标；被阻断阶段返回非零退出码和稳定原因；报告包含全部宪法要求且不含秘密；nightly maintenance 不触发训练。
  QA scenarios: `uv run pytest tests/test_research_cli.py tests/test_research_report.py tests/test_nightly.py -q`; 执行 dry-run 并保存 `.omo/evidence/task-13-cli.txt` 与 `.omo/evidence/task-13-report.md`
  Commit: Y | `feat(research): orchestrate auditable medium-horizon workflow` | CLI, reports, docs, tests
  Progress: 已落地固定六阶段编排协议、首错即停、确定性双语报告 store、报告机器 schema、nightly 导入
  隔离和 `ashare-research dry-run`。真实仓库 dry-run 披露唯一 DatasetSpec、21 个 trial、成本/风控规则，
  模型状态为 `NOT_TRAINED` 且 final holdout 为 0。开发区间基础 coverage 已 `QUALIFIED`；要求历史行业
  PIT 时按预期 `BLOCKED`，因此只允许继续 DRAFT 研究。真实 `diagnose` composition root 已接入唯一
  DatasetSpec/trial batch、逐 artifact 哈希/schema 校验、按 family 流式诊断和折内 OOS frame；工作树
  不干净时在读取 Parquet 前稳定阻断。下一步需在干净代码身份下生成真实诊断产物，再接入 portfolio、
  backtest 与 train 的真实阶段适配器后才可勾选。

## Final verification wave (after ALL todos)
> 以下检查可并行，但必须全部 APPROVE；在用户明确确认前不得宣称研究系统或模型已验证。

- [ ] F1. Plan compliance audit：逐项映射 13 个 todo 的代码、测试、evidence 和提交，确认 scope 外能力未加入。
- [ ] F2. Code quality review：运行 `make check`，确认 strict typing、Ruff、覆盖率 >=90%、文件 <=250 行、依赖方向和唯一训练入口。
- [ ] F3. Real data QA：只读审计 `ashare_quant` 的固定快照，重跑一个小范围端到端研究，验证 artifact hash、PIT 时钟、trade ledger 和报告一致。
- [ ] F4. Leakage/risk adversarial audit：主动注入未来公告、当前 ST、重复 final holdout、全样本 scaler、风险旁路和缺 lineage，确认全部 fail closed。

## Commit strategy

- Todo 1 建立 Git 基线后，每个 todo 一个小而完整的 Conventional Commit；实现与对应测试同一提交。
- 不提交数据、evidence、模型、Token、日志和本地调度状态。
- 每波结束执行 `make check`；失败不得进入下一波。
- 数据/schema/feature/label/risk 规则的物质变化同时升级版本并产生新内容 ID。

## Success criteria

- 可以从 `ashare_quant` 的固定 accepted 快照生成一个 `QUALIFIED`、字段级可追溯、内容寻址的 2020 年以来中期选股数据集。
- 21 个基础因子和独立标签均有 schema、PIT 证明、quality、lineage 和稳定 artifact ID。
- 因子报告包含全部试验、FDR、分段、最差区间、换手、费用和容量，不挑选性展示。
- Top 30 周频组合只能通过组合风控进入多标的回测，所有缩量、拒绝、未成交和退出受阻均可审计。
- Ridge 只能通过 TrainingService 和实际证据驱动的 ModelTrainingGuard 训练，默认 DRAFT，最终测试最多一次；历史行业 PIT 缺口未解决前不得晋级为完整风险门禁下的 `VALIDATED`。
- `make check` 全部通过且覆盖率不低于 90%；没有未来函数、生存者偏差、财务修订泄漏或风控旁路。
