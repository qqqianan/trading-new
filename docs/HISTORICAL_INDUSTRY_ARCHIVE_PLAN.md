# 历史行业档案获取与准入方案

状态：`PHASE 2 OFFICIAL SUCCESSOR FOUND / IPO BRIDGE REQUIRED / RESEARCH USE BLOCKED`

目标：为 `2020-01-01` 至 `2024-12-31` 的 A 股研究建立可回放、可审计的历史行业归属，补齐
当前 Tushare 行业成员只能从本系统首次观察时间起证明可得的缺口。

## 1. 问题定义

本项目需要的不是一张今天下载的历史成员表，而是能够同时回答以下问题的行业档案：

1. 股票在什么时间区间属于哪个行业？
2. 当时最早何时能够知道这项归属？
3. 结论来自哪个原始页面、附件和供应商版本？
4. 修订、分类体系切换和退市股票是否完整保留？

因此，`effective_at` 和 `available_at` 必须分别取证。只有 `in_date/out_date`、没有历史发布证据的
数据仍保持隔离，不能用于历史行业中性化、行业暴露或模型晋级。

## 2. 来源优先级

### 2.1 A 级：官方历史发布档案

首选中国证监会“上市公司行业分类结果”季度页面及原始附件。每份档案保存：

- 内容页 URL、标题和官方发布日期；
- PDF 附件 URL、原始字节数和 SHA-256；
- 页面原始字节 SHA-256；
- 分类体系、季度、解析器版本和抓取时间；
- 发现失败、附件缺失和内容冲突等显式质量状态。

证监会行业粒度较粗，但适合行业集中度、行业暴露和基础行业中性化。完整且可证明的粗分类优先于
缺少历史发布时钟的细分类。

### 2.2 B 级：具备 PIT 字段的授权商业档案

免费官方档案无法覆盖的季度，依次评估 Choice、iFinD、Wind、CSMAR、RESSET 或聚源的一次性历史
导出。采购前先验收样本，不因供应商品牌直接准入。样本必须包含：

| 项目 | 硬要求 |
|---|---|
| 股票范围 | 全部 A 股并包含退市、暂停上市和历史代码 |
| 分类身份 | taxonomy、版本、层级、行业代码和名称 |
| 有效时间 | 纳入和移出日期，空值语义明确 |
| 知识时间 | 历史公告、发布、快照或供应商 as-of 时间 |
| 版本 | 修订记录追加保留，不能只给当前最新结果 |
| 许可 | 允许个人本地研究、原始文件留存和派生结果使用 |

缺少知识时间、只提供当前回溯表的商业数据不得进入 PIT 层。

### 2.3 C 级：交叉验证来源

Tushare `index_classify/index_member`、交易所公司资料、上市公司年报和公开研究数据只能用于代码映射、
异常复核和覆盖率比较。它们不能替代原始发布日期证据，也不能被静默拼接为完整历史。

## 3. 时间与分类规则

- `effective_at`：档案声明的行业生效时间；没有明确声明时记录为未知，不从季度名称猜测具体日期。
- `available_at`：官方发布时刻。只有日期没有时刻时，保守设为下一交易日开盘。
- `ingested_at`：本系统实际获取原始页面或文件的时间。
- 决策只能读取 `available_at <= decision_time` 的最新已知版本。
- `CSRC_2012`、`SW2014`、`SW2021` 分别版本化，禁止把不同体系的代码直接拼接或当作同一行业。
- 分类体系切换属于物质变化，必须生成新 schema、DatasetSpec 和模型/组合协议。

## 4. 第一阶段覆盖审计

审计区间固定为 `2020Q1–2024Q4`。每个季度只有以下状态：

- `FOUND`：列表入口、内容页发布日期、PDF 附件及两项 SHA-256 全部存在。
- `MISSING`：任一必需证据缺失。

审计报告是内容寻址 JSON，写入忽略版本控制的 `artifacts/source_audits/`，不会写入 MongoDB，也不
授予 canonical、PIT、特征、回测或训练读取权限。报告至少包含 20 个季度单元、发现证据、缺失原因、
抓取时间、来源和审计版本。

## 5. 后续准入链路

只有覆盖审计完成后，才按以下顺序实施数据接入：

1. 在数据源白名单登记 `csrc_industry_archive` 或验收通过的商业源。
2. 建立机器可读 schema，固定字段类型、单位、空值、分类版本和三时钟。
3. 原始 HTML/PDF/导出文件只追加保存，创建 Raw snapshot 和文件哈希。
4. 解析股票代码、行业代码及分类版本，生成 canonical，但默认保持 `QUARANTINED`。
5. 以发布证据生成 PIT 事件，并建立逐字段 Raw 到 PIT lineage。
6. 运行代码唯一性、行业唯一性、版本连续性、股票池覆盖和跨来源抽样校验。
7. 生成新的跨表 coverage report；只有 `QUALIFIED` 才能生成 input manifest 和 DatasetSpec。
8. 重新物化需要行业中性化的预处理、因子报告和正式风险回测，不覆盖旧产物。

## 6. 分阶段计划与退出条件

### Phase 1：官方档案审计

- 实现只读 CSRC 列表/内容页/PDF 审计器和 CLI。
- 运行 `2020Q1–2024Q4` 真实审计并生成覆盖矩阵。
- 退出条件：每个季度都有确定状态，所有 `FOUND` 项具有完整哈希证据。

### Phase 2：缺口来源评估

- 对缺失季度搜索官方继任渠道，并向商业源索取小样。
- 使用统一验收表检查 PIT 时钟、退市覆盖、修订历史和许可。
- 退出条件：选定一个能覆盖全部缺口的来源，或明确记录无法获得的季度。

### Phase 3：受治理接入

- 新增 schema、Raw 存储、canonical 转换、PIT 事件、质量报告和字段级 lineage。
- 退出条件：目标区间无静默空洞、无重复归属、无倒填 `available_at`。

### Phase 4：研究系统集成

- 生成新的 coverage/input manifest/DatasetSpec，重新物化行业相关产物。
- 退出条件：历史行业 gate 自动通过；原有 `UNAVAILABLE` 产物仍可审计但不得改写。

## 7. 决策与限制

第一阶段只执行来源审计，不解析 PDF 表格、不写市场数据库、不改变当前模型状态。若 2022--2024
缺少官方档案，任务进入外部来源采购/授权阻塞，而不是用 Tushare 有效日期或当前快照伪造覆盖。

## 8. Phase 1 实际结果

执行时间：`2026-07-23`。正式审计 artifact：

```text
industry_archive_audit_bca2af925851286e7367b86d7201684e1c5ca8c77c16889d3a24cd67af8be250
```

| 季度 | 官方发布日期 | 状态 |
|---|---|---|
| 2020Q1 | 2020-04-14 | FOUND |
| 2020Q2 | 2020-07-14 | FOUND |
| 2020Q3 | 2020-11-05 | FOUND |
| 2020Q4 | 2021-01-25 | FOUND |
| 2021Q1 | 2021-04-14 | FOUND |
| 2021Q2 | 2021-07-19 | FOUND |
| 2021Q3 | 2021-11-10 | FOUND |
| 2021Q4--2024Q4 | - | MISSING（官方栏目无对应入口） |

7 个 `FOUND` 季度的内容页和 PDF 均已实际下载并计算 SHA-256；13 个缺失季度没有被空值、当前
Tushare 成员或推测日期替代。报告固定 `research_use_authorized=false`，因此当前历史行业 gate 状态
不变。Phase 2 的明确缺口是 `2021Q4--2024Q4`，采购或继任官方源验收必须覆盖这 13 个季度。

## 9. Phase 2 官方继任来源

中国上市公司协会于 `2023-05-21` 发布《中国上市公司协会上市公司行业统计分类指引》。指引自
`2023-05-01` 施行，规定每年 6 月 10 日和 12 月 20 日启动分类工作，并由协会网站每半年公布结果。

官方结果栏目：

```text
https://www.capco.org.cn/xhgg/hyfl/hyfljg/index.html
```

正式 CAPCO 来源审计 artifact：

```text
capco_industry_archive_audit_188f3655cb59714dba3349deabf4ee687b3311abe4cb9a185889858d703690e6
```

| 结果期 | 官方发布日期 | PDF 唯一股票代码数 | 状态 |
|---|---|---:|---|
| 2023H1 | 2024-02-08 | 5,178 | FOUND |
| 2023H2 | 2024-04-03 | 5,332 | FOUND |
| 2024H1 | 2024-09-30 | 5,334 | FOUND |
| 2024H2 | 2025-04-18 | 5,384 | FOUND |

每期均有“按股票代码排序”和“按行业排序”两份 PDF；审计器只接受前者作为映射证据。抽取检查未发现
重复股票代码。当前附件被协会迁移至带 `202603` 路径的文件服务器，因此页面发布日期、附件当前
URL、当前文件哈希和本系统抓取时间必须分开保存，禁止从迁移路径推断历史发布时间。

CAPCO 结果不能倒填：`2023H1` 只能从 `2024-02-08` 后使用，`2024H2` 在 2024 年任何决策时点均
不可用。只有页面日期时，`available_at` 保守设为下一交易日开盘；未来若使用 CMS 精确发布时间，
必须把官方搜索响应作为独立 Raw 证据保存。

## 10. 2021Q4--2024-02-08 免费补桥方案

在 `2021-11-10` 至 `2024-02-08` 之间，本地 accepted 生命周期数据包含 842 只新增股票：

| 上市年份 | 新增股票数 |
|---|---:|
| 2021（11 月 10 日后） | 84 |
| 2022 | 428 |
| 2023 | 313 |
| 2024（2 月 8 日前） | 17 |

因此不能只把 2021Q3 快照向后延续并声称行业完整。免费且符合 PIT 的桥接方法为：

1. 对 2021Q3 已存在的股票，沿用“最后已知官方分类”，直到后续官方结果实际发布；保持 taxonomy 和
   stale age，不假装期间没有经营变化。
2. 对上述 842 只新增股票，从巨潮资讯、上交所、深交所或北交所的法定 IPO 上市公告/招股说明书获取
   首次行业披露。
3. 只接受正文明确出现的行业体系、代码和名称，例如 301149 上市前一日公告中的
   `C26 化学原料和化学制品制造业`；不得由公司简称、主营描述或今天的行业字段推断。
4. `available_at` 使用法定披露时间；只有日期时使用下一交易日开盘。原始 PDF、公告详情页和查询响应
   均作为独立不可变 Raw 证据。
5. 到 CAPCO 新体系结果实际发布时切换 taxonomy，旧分类保留历史，不覆盖。

该路径的下一阶段验收标准是 842/842 股票均存在可解析的官方行业披露、公告时间和文件哈希。任何无法
自动确认或出现多个冲突分类的股票进入人工复核清单并保持缺失。若免费路径最终不能达到 100%，才触发
商业源采购；商业样本仍必须提供历史公告/as-of 时间，不能只给有效区间。

## 11. Phase 3 巨潮桥接试点

试点日期：`2026-07-24`。所有身份、公告和 PDF 请求均经过 `CninfoArchiveClient` 与 1 秒
`RequestPacer`，产物仍固定 `research_use_authorized=false`。

| 市场 | 股票 | 上市日 | 最终公告 ID | 行业 | 时间精度 | taxonomy |
|---|---|---|---|---|---|---|
| 深市 | 301149.SZ | 2021-11-10 | 1211541225 | C26 化学原料和化学制品制造业 | EXACT_MILLISECOND | CSRC_UNVERSIONED |
| 沪市 | 688162.SH | 2021-11-10 | 1211530538 | C35 专用设备制造业 | DATE_ONLY | CSRC_2012 |
| 北交所 | 920260.BJ | 2021-11-15 | 1211553255 | C40 仪器仪表制造业 | DATE_ONLY | CSRC_UNVERSIONED |

正式试点 audit ID：

```text
cninfo_industry_bridge_audit_c44250e1d67eade1d6f89f11f3355b2c2ad1f03c410f4025d1ae94351f2fe733
cninfo_industry_bridge_audit_2163835fbeb674730d5b2745b02788e87f8c48dfd7e239342560e0e035d22684
cninfo_industry_bridge_audit_9fe83ed07f00d809ded50c1fa2f938e888053c21098732c6b909ffb4a02f4292
```

试点证明三市免费发现和文本解析可行，但同时暴露两个必须先解决的批量门禁：

1. `DATE_ONLY` 必须结合 accepted 交易日历投影到下一可用交易时点，不能直接采用本地午夜。
2. `CSRC_UNVERSIONED` 必须绑定当时生效的官方分类指引 Raw 证据后才能晋级；不能根据 `C26/C40`
   的形式猜测版本。

842 只全量任务采用分批、可恢复的两阶段执行：先只做身份与公告发现并登记最终 PDF 清单，再以小批量
下载和解析 PDF。首批固定按深市、沪市、北交所及上市年份分层抽取 30 只；只有公告选择、taxonomy、
文本解析和失败分类全部稳定后，才扩大到全量。source audit 合格仍不等于 PIT 准入。

## 12. 30 只确定性分层试点结果

候选区间固定为 `[2021-11-10, 2024-02-08)`，只读取当前 universe manifest
`schema_49b36e8944a757ca01f221a1f3137e8605dd49ec2ea5d561b7d258ac84a141da` 下 accepted 的
`LISTED/FIRST_TRADED`。同一股票优先 `LISTED`；相同上市日的内容寻址重放折叠为一只候选并保留全部
事件 ID，不同上市日则 fail closed。实际复现 842 只，不混读两个旧 universe manifest。

选择协议 `cninfo_bridge_pilot_v1` 按 `上市年份 × SZ/SH/BJ` 形成 12 个非空层，每层先分配 1 只，
其余名额按 population 比例和最大余数法分配；层内按
`sha256("cninfo_bridge_pilot_v1|symbol|listing_date")` 排序。选择在网络请求前持久化，失败后不补抽：

```text
cninfo_bridge_selection_3b432f19e8beb3768897b8351e967fd345e7931530d49af6768fa515be71195e
```

最终 `v4` 批次 artifact：

```text
cninfo_bridge_batch_audit_ee8a426a3abe186a95b6834da53f3bcacde94c77eb5ae315e56fdbdc98e248ef
```

| 结果 | 数量 |
|---|---:|
| FOUND | 22 |
| MISSING | 8 |
| DATE_ONLY（占全部 FOUND） | 22 |
| CSRC_2012 | 10 |
| CSRC_UNVERSIONED | 10 |
| CAPCO_2023 | 2 |

7 个失败是所选上市公告书没有显式行业代码和名称：`688190.SH`、`001230.SZ`、`001299.SZ`、
`301326.SZ`、`920926.BJ`、`601061.SH`、`920403.BJ`。`688475.SH` 在同一官方字段同时列出
`C39` 与 `I65`，保持冲突隔离，禁止自动挑选。

当前自动覆盖率为 `22/30 = 73.3%`，尚未达到扩至 842 只的退出条件。下一阶段固定保留这 30 只，
对 7 个缺失样本增加法定招股说明书候选选择与公告版本规则；`688475.SH` 进入人工语义复核清单。
只有补源选择规则、失败分类和 taxonomy 证据再次稳定后，才实施全量两阶段发现与下载。

## 13. 招股说明书 supplemental 试点

补源固定读取上一节 `v4` 父 batch，只选择 7 个
`explicit_industry_disclosure_missing`；`688475.SH` 的 `C39/I65` 冲突没有进入自动补源。查询仍经
`CninfoArchiveClient + RequestPacer`，窗口为上市日前 730 天，排除摘要、更正、申报稿、预披露稿和
提示性公告。失败 audit 同样保存查询响应及已选 PDF 的哈希 trace。

当前带完整 trace 的正式 supplemental batch：

```text
cninfo_prospectus_bridge_batch_5cac507e1d103804f1904f50394f47cb3188fa22863c30671fa7bc27f0ce6aba
```

| 股票 | supplemental 结果 | 行业 | taxonomy |
|---|---|---|---|
| 001230.SZ | FOUND | N78 公共设施管理业 | CSRC_2012 |
| 920926.BJ | FOUND | C38 电气机械和器材制造业 | CSRC_UNVERSIONED |
| 601061.SH | FOUND | F51 批发业 | CSRC_UNVERSIONED |
| 920403.BJ | FOUND | A01 农业 | CSRC_2012 |
| 001299.SZ | MISSING | 同时披露两级名称和 D45/D4500，层级语义不可自动截断 | - |
| 301326.SZ | MISSING | 只有业务细分描述，没有一一对应的显式三级代码 | - |
| 688190.SH | MISSING/不稳定 | 相同查询出现过正式招股说明书和零响应 | - |

`688190.SH` 的一次观察选择公告 `1211660704`，announcement response SHA-256 为
`6e254cc96aa19088c7ab967213c8f0dfe8519526b5f052f9e651c25ed1840c13`；带 trace 的后续零响应 SHA-256
为 `c2a890bbf3a6a53ab02ddc6c1794bf1c72ba45799fe9f59dcc5ba2cc18467114`。两者均保留，禁止只采用成功
观察。按稳定证据保守合并，30 只中为 `26/30`：原上市公告书 22 只，加稳定招股说明书补源 4 只。

因此仍不扩至 842 只。下一退出条件是：为巨潮查询建立重复观察一致性协议，或从交易所官方公告入口
独立确认 `688190.SH`；同时对 `001299.SZ/301326.SZ/688475.SH` 保持人工复核或缺失，不推断行业。

## 14. 巨潮重复观察一致性协议

协议版本为 `cninfo_prospectus_consistency_audit_v1`，查询规范版本为
`cninfo_prospectus_query_v1`。操作入口必须逐个显式指定 immutable prospectus audit manifest，不允许
扫描目录后只采用可解析或成功的文件。报告保留 exact 查询参数和全部观察的 source audit ID、版本、
时间、响应哈希、规范化结果、公告 ID 与 PDF 哈希。

判定门槛固定如下：少于 3 次一致观察为 `INSUFFICIENT`；空/非空变化为 `query_outcome_changed`；公告
或 PDF 变化为 `selected_document_changed`；稳定空响应的原始哈希变化为 `empty_response_changed`。
后三种均为 `UNSTABLE`，禁止多数票、重试覆盖或挑选成功观察。即使达到 `STABLE_FOUND`，产物仍固定
`research_use_authorized=false`，不能进入 MongoDB、canonical/PIT、训练、验证或回测。

只有显式登记为相同查询语义的 source audit 版本可参与比较；未知未来版本直接拒绝，不能推断兼容。
`688190.SH` 的正式一致性报告为：

```text
cninfo_prospectus_consistency_audit_e03eae8d4ca51e91281b4297591324413e8de70d680759a0a6c77c6d3204b29d
```

它绑定 v2 的 `FOUND/1211660704` 与 v4 的空响应，结论为
`UNSTABLE / query_outcome_changed`。因此重复观察协议已落地，但该股票的来源矛盾尚未解除，30 只稳定
覆盖仍为 `26/30`，842 只扩量继续阻塞。

## 15. 上交所独立确认

`SseArchiveClient + RequestPacer` 通过上交所公司公告查询接口定位 `688190.SH` 的唯一正式招股说明书。
静态附件首次返回已登记的 `acw_sc__v2` challenge；客户端只对该固定结构计算 cookie 并限速重试一次，
未知挑战或非 PDF 保持失败。v1 探索 audit 保留但不具备交叉哈希门禁，正式采用的 v2 audit 为：

```text
sse_prospectus_industry_audit_7628904b28f75baa36981edda35f6f8d84d2fbb492b09348886c86c2645046ff
```

该报告绑定上一节 exact CNInfo 一致性 ID、成功公告 `1211660704` 和预期 PDF SHA-256。上交所结果为：

- 标题：`云路股份首次公开发行股票并在科创板上市招股说明书`
- 上交所记录时间：`2021-11-21T15:30:12+08:00`，披露日期：`2021-11-22`
- PDF：10,237,689 字节，SHA-256
  `c73028df868af703a87d39564d42ef7f26efb15f2dc9d78a253fc3e8d5af8fca`
- 与 CNInfo 成功观察的 PDF SHA-256 完全一致
- 显式披露：`C31 黑色金属冶炼和压延加工业`，taxonomy 为 `CSRC_UNVERSIONED`

因此 `688190.SH` 的文档存在性与内容得到独立官方来源确认，但 CNInfo 查询本身仍标记不稳定。试点可
确认来源覆盖从 `26/30` 更新为 `27/30`；`001299.SZ`、`301326.SZ` 和 `688475.SH` 仍保持人工复核或
缺失。所有 source audit 继续固定 `research_use_authorized=false`，在独立 schema、Raw、质量和字段级
lineage 实施前不写 MongoDB、canonical/PIT、训练、验证或回测，842 只扩量继续阻塞。

## 16. Ordered-taxonomy 补源

`001299.SZ` 的正式招股说明书依次具名《上市公司行业分类指引（2012年修订）》和
《国民经济行业分类（GB/T4754-2011）》，并声明同一“燃气生产和供应业”的行业代码“分别为 D45 和
D4500”。解析器 v5 只接受这种完整的双标准顺序映射：选择 `D45/CSRC_2012`，不截断 `D4500`。
深交所官方 PDF 为 8,963,179 字节，SHA-256
`108bf1efd142d07df6ac24857cfe993fc05e64e208a90e17c95c661c7983fecc`，与 CNInfo 文件完全一致。

固定 7 只 supplemental 新批次为：

```text
cninfo_prospectus_bridge_batch_fa9df02bf6814a82e62094dbd0fe365158daee57c7c9d4d86de6ad4fef4b9c42
```

批次版本 `cninfo_prospectus_bridge_batch_v2`，结果为 5 FOUND / 2 MISSING；`001299.SZ` 新增为 FOUND，
`688190.SH` 的 CNInfo 查询仍为空但由上一节 SSE v2 独立确认，`301326.SZ` 仍缺显式行业代码。结合原
上市公告书 22 只、supplemental 5 只和 SSE 交叉确认 1 只，试点可确认来源覆盖为 `28/30`。剩余
`688475.SH` 是正文明确的 C39/I65 双业务分类，`301326.SZ` 仍需独立核查；842 只扩量继续阻塞。

## 17. Issuer-scope 主体行业

`301326.SZ` 的招股说明书明确声明：根据中国证监会《上市公司行业分类指引（2012年修订）》，公司所处
行业为“计算机、通信和其他电子设备制造业（分类代码：C39）”。同文后续 `C26` 仅限定碳纳米管产品，
不能提升为发行人主体行业。深交所官方 PDF 为 10,316,489 字节，SHA-256
`cc847fe6cc67c7d0b98b7a7bd752be61f9b5967175748cf9e2a672968853b109`，与 CNInfo 文件完全一致。

正式 supplemental 批次更新为：

```text
cninfo_prospectus_bridge_batch_a0e161a71f52340848a2a3ce05d12cc75833a552f1934a35a524e73847bed799
```

批次版本 `cninfo_prospectus_bridge_batch_v3`，7 只本次均返回 FOUND；其中 `688190.SH` 仍不能据此视为
CNInfo 稳定，因为跨运行已有空响应。纳入新 v6 成功观察后的最新一致性报告为
`cninfo_prospectus_consistency_audit_83a7c94e08402f0b27b200b30094de905809cb3cf312cd5f5ede97f6d83cca52`，
三次观察结论仍为 `UNSTABLE/query_outcome_changed`。重新绑定该父报告的 SSE v2 audit 为
`sse_prospectus_industry_audit_c17a7144ca81919aa228d20856374f0ce7ad4014331021d69508e49a999768fa`。

结合原上市公告书 22 只、稳定/可解释 supplemental 6 只和 SSE 交叉确认 1 只，试点可确认来源覆盖为
`29/30`。最后的 `688475.SH` 不是解析缺陷：招股书明确对两个业务分别披露 C39/I65。其上市后首个可
观察的单一公司分类必须来自正式行业档案；在该档案发布前保持未知，不能回填到上市日。

## 18. CAPCO 单股行级时间解析

`688475.SH` 只能由上一节的 exact 巨潮冲突 audit 与第 9 节 exact CAPCO archive audit 共同装配。
正式产物为：

```text
capco_membership_audit_51c4f8e1570f2e0c3b38944fb61fa59e9ff5bb9bff8ba8957ef60216c9eed3d4
```

审计器经 `CapcoArchiveClient + RequestPacer` 重新下载 2023H1 按代码排序 PDF，并与父 evidence 的
SHA-256 `8202be2cb68ff2668d9efeb9f57ea3f98486e9ef50bb64870931715c0ca759ca` 精确复核。layout 第
110 页恰好一个 `688475` 行，结果为 `C39 计算机、通信和其他电子设备制造业`。重复股票行、附件替换、
缺行或无法重建跨行名称均 fail closed。

时间语义固定为：

```text
[2022-12-28, 2024-02-08 经交易日历投影后的下一可用开盘): UNKNOWN
[交易日历投影后的下一可用开盘, ...): C39 来源证据候选
```

source audit 只保存 `provider_publication_date=2024-02-08` 和
`availability_status=PENDING_NEXT_TRADING_SESSION_OPEN`，不能自行生成 `available_at`。因此固定试点
的“可确认来源”达到 `30/30`，但这不等于 2020--2024 历史 PIT 覆盖达到 30/30，也不解除 842 只扩量、
独立 schema/Raw/质量/字段级 lineage 或模型晋级门禁。产物继续固定
`research_use_authorized=false`，禁止写入 MongoDB、canonical/PIT、训练、验证或回测。

## 19. 独立 schema、连续日历与 source admission

CAPCO 行级 source audit 之后新增独立 `historical_industry_source_v1`，不复用 Tushare 当前观察型行业
schema。准入链固定为：

```text
exact CAPCO membership audit
  + current-schema accepted SSE trade_cal rows
  -> source-only Raw observation
  -> QUALIFIED_SOURCE_ONLY quality report
  -> field-level lineage
  -> source-only PIT candidate
```

date-only 日期不能直接加一天或查询孤立开放日。日历证据必须覆盖 `2024-02-08` 至首个后续开放日之间
每个自然日，逐行绑定 Raw snapshot 和 row SHA-256。当前正式日历 artifact 为：

```text
historical_industry_calendar_6351be334a33953b61ce97a1b96d35e545e596b515160e5a1cb82a8526188f0b
```

该证据确认 2 月 9--18 日均闭市，首个后续 open 为 2 月 19 日。正式 admission v2 为：

```text
historical_industry_admission_1fc25bcb0a4d9ba658042456ade8454c8851268bda52d90e1fc83a6db1472788
```

因此 `688475.SH` 的时间状态现为：

```text
[2022-12-28, 2024-02-19 09:30 Asia/Shanghai): UNKNOWN
[2024-02-19 09:30 Asia/Shanghai, ...): C39 source-only PIT candidate
```

这一步已经具备独立 schema、Raw observation、六项质量检查、八字段 lineage 和交易日历投影，但尚未
授权研究使用。artifact 固定 `research_use_authorized=false`，没有写 MongoDB；下一阶段需为其余 29 只
建立统一 admission adapter，并完成全量 coverage/冲突/未知区间报告，之后才能单独评审是否开放研究
数据层准入。

## 20. 30 只多来源裁决与统一 admission

固定试点不按目录中“最新成功文件”选择来源。正式 resolver 显式绑定 base/supplemental batch、
`688190.SH` consistency/SSE 和 `688475.SH` CAPCO，优先级为：

```text
原上市公告 FOUND
  -> 原公告缺失且来源稳定：prospectus
  -> CNInfo 查询不稳定：exact SSE PDF 哈希确认
  -> 原公告显式冲突：exact CAPCO 后续分类
```

正式 resolution 为：

```text
historical_industry_resolution_a82a557838ae6f0c8aa7750f0b8051318eccc67e0fd6b86ab8b9d1fce562eef1
```

30/30 均得到唯一来源，计数为 `CNINFO_LISTING=22`、`CNINFO_PROSPECTUS=6`、
`SSE_PROSPECTUS=1`、`CAPCO_MEMBERSHIP=1`。每行保留 selection lifecycle event、base audit、所有实际
评估的 supplemental/consistency/SSE/CAPCO ID 和选择原因。

统一 admission 使用独立 v2 schema，并明确三个时钟：

```text
source_available_at = 官方精确时间，或 date-only 经连续日历投影后的下一开盘
eligible_from       = 上市日 09:30
usable_from         = max(source_available_at, eligible_from)
```

正式 batch 为：

```text
historical_industry_admission_batch_e271d2fad37707e6a53b21162990e6da1b02300f3cb2c90e8f674daee34d5fdd
```

batch 含 30 个逐股 admission、30 个唯一日期的连续日历证据，`unknown_interval_count=1`。上市前已公开的
29 只只需等待 `eligible_from`，不标记 UNKNOWN；`688475.SH` 继续保留
`[2022-12-28 09:30, 2024-02-19 09:30)` 未知区间。所有产物仍为
`QUALIFIED_SOURCE_ONLY/research_use_authorized=false`，没有写入 MongoDB。下一阶段是实现独立的全量
coverage/冲突/未知区间验收报告，并据此决定是否允许 source-only candidate 进入研究数据层。

## 21. 全量 coverage、冲突与 UNKNOWN 验收

验收入口不扫描目录选择最新产物，必须显式提供 exact selection、resolution、admission batch 和半开
研究区间。报告同时检查：目标 population 是否全量 admitted、试点键集合是否一致、是否存在重复或冲突
分类、source observation lineage 是否匹配、UNKNOWN 区间是否与研究窗口重叠。即使全部通过也只能进入
独立的 research admission review，不能由 coverage 入口直接授权或写 MongoDB。

针对 `[2020-01-01, 2025-01-01)` 的正式报告为：

```text
historical_industry_coverage_f8b715cc0c93daa82fc568f43708be01bfb746647ac5c25aa564542868e9745c
```

结果固定为 `BLOCKED`。30 只试点均存在 exact admission 且分类冲突数为 0，但完整候选 population 为
842，只覆盖 30，缺失 812；`688475.SH` 的 UNKNOWN 区间仍与研究窗口重叠。因此当前 source-only
candidate 不能进入研究数据层，`research_use_authorized=false`，MongoDB、canonical/PIT、训练、验证和
回测保持关闭。下一实施阶段是按冻结的 842 只 candidate universe 扩展确定性发现与下载批次，不得在
失败后补抽或替换候选。

## 22. 842 只全量发现计划与首个恢复分片

后续周度 universe replay 为每只股票追加了 lifecycle event ID，使当前完整 lineage 哈希变化，但 30/30
试点股票的上市日和事件类型均未变化。全量计划不接受更新常量放行，而是按原试点父 batch 的
`audited_at=2026-07-24T09:05:22.696495Z` 重放本地 `ingested_at` 截面，精确恢复原 candidate universe
哈希 `5cb0161923ef3abcf9f13b478a15ff55c584b20570721b7426df6db1dff6ed62`。

正式全量 selection 与 pre-network plan 为：

```text
cninfo_bridge_selection_a5b6bea46e2d3a5e18eca41077206868c44b94d5f2ecc20e661c58a126c93dee
cninfo_full_discovery_plan_0fe443507053ead1363e9de9b3919e63878b16393e1c703a49d9eec2c54d45bc
```

plan 包含 842 只、17 个固定 offset shard，每个 50 只，最后一个 42 只。第一阶段每只仅执行身份查询和
上市公告查询，登记最终 PDF descriptor，不下载或解析 PDF。HTTP/transport 失败作为逐股 observation
记录失败阶段、状态码及可得响应哈希，不让整个 shard 丢失，也不把供应商失败伪装成行业缺失。

首个完成 shard 为：

```text
cninfo_full_discovery_shard_c624230c4de78e270a15343327ee74ca6b4f4088823800683aa7ccb585fc56fa
```

结果为 `48 SELECTED / 2 MISSING`。`001230.SZ` 遇到身份查询 HTTP 502；`001267.SZ` 没有唯一最终上市
公告。两者均原位保留，没有补抽。所有结果继续固定 `research_use_authorized=false`，未写 MongoDB。
下一步按同一 exact plan 执行 shard 1--16，然后由显式列出的全部 shard manifest 装配 discovery
coverage；只有 complete coverage 后才进入第二阶段 PDF 下载与解析。
