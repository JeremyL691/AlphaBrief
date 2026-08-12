# AlphaBrief 最终版本开发蓝图

版本：2026-08-13.1
状态：Approved for autonomous implementation
产品边界：OANDA v20 practice-only
最终验收：工程门禁全部通过，并完成真实连续 30 个日历日的模拟盘观察

## 0. 如何使用本蓝图

本文件定义最终产品、不可变约束、需求和里程碑。它不是完成报告，也不
记录逐轮流水账。

- 当前真实进度只看 `docs/progress.yaml`。
- 每轮机器可读范围和验收只看 `docs/work_items.yaml`。
- 自动循环状态机和提示词只看 `docs/autonomous_loop.md`。
- 需求到测试/证据的映射只看 `docs/acceptance.md`。
- 运行 OANDA practice 和 30 天观察只看
  `docs/oanda_30_day_runbook.md`。
- 代码架构事实和重大取舍只看 `docs/architecture.md`。

里程碑描述的是完成条件，不是对当前代码的宣称。任何没有测试退出码、
运行证据和账本映射的“已完成”都无效。

## 1. 产品愿景

AlphaBrief 最终版本是一个单用户、本地优先、可恢复、可审计的 AI 金融
研究与 OANDA 模拟交易工作站。每天它应当自主完成：

1. 读取 OANDA practice 账户及该账户实际可交易的完整品种目录；
2. 获取新鲜价格、K 线、点差、交易时段、账户和持仓状态；
3. 抓取金融新闻、宏观事件和市场情绪，并保留来源、时间和可信度；
4. 让多个 AI 角色围绕同一份证据进行自由但结构化的讨论；
5. 输出带证据、反方观点、置信度和失效条件的 `no_trade` 或
   `OrderIntent`；
6. 用完全确定性的 RiskGate 结合账户、敞口、保证金、损失、数据质量、
   新闻风险和交易时段做最终裁决；
7. 只把获批且已持久化 RiskDecision 的订单提交到 OANDA practice；
8. 对订单、成交、交易、持仓、资金和本地记录做持续对账；
9. 在 API、CLI、Dashboard 和日报中解释“看到了什么、讨论了什么、为何
   交易或不交易、风险如何裁决、券商实际发生了什么”；
10. 在崩溃、超时、限流、重启和上下文压缩后不重单、不丢证据，并能继续
    正确运行。

它不是收益承诺、投顾产品、社交平台、多租户 SaaS 或 live-trading
系统。最终版本仍然只允许模拟盘。

## 2. 不可变产品边界

### 2.1 执行边界

- 唯一外部执行场所是 OANDA v20 practice。
- Alpaca、RoutingBrokerAdapter、其他券商和生产路径中的内存成交回退必须
  删除。
- 缺少 OANDA 凭证、网络不可用、账户不匹配、品种不可交易或对账异常时
  必须 fail closed。
- live REST/stream URL、live 开关、通用 `environment=live|practice` 选择器
  和未来 live 占位均禁止出现。
- 测试中的 fake adapter 只用于确定性逻辑，不得在生产工厂可达。

### 2.2 品种边界

“覆盖 OANDA 所有交易类别”定义为：覆盖**配置的 practice 账户通过
`GET /v3/accounts/{accountID}/instruments` 实际返回为可交易的全部品种**，
而不是硬编码某个官网地区的营销清单。

OANDA 账户、法律实体和地区会决定可用类别。系统必须能归类并展示：

- Currency / Forex；
- Metal；
- Index CFD；
- Commodity CFD；
- Bond / Rates CFD；
- Crypto CFD（仅账户返回时）；
- Share CFD（仅账户返回且 API 可交易时）；
- 无法确定的 Other CFD。

分类展示不能改变券商原始 instrument name。无法从 API 元数据可靠区分的
CFD 可由版本化 taxonomy 规则补充，但必须保留 `OTHER_CFD` 回退并显示
分类依据。绝不为了补齐类别而路由到其他券商。

### 2.3 AI 权限边界

AI 可以讨论、提取、归纳、反驳、评分和提出意图，但无权：

- 调用 broker；
- 修改 system prompt、安全策略或风险阈值；
- 选择 live/practice 环境；
- 写入凭证；
- 把网页或新闻中的指令当作系统指令；
- 绕过 schema、RiskGate、幂等、持久化或对账；
- 为了“每天交易”强行生成订单。

### 2.4 数据和证据边界

- 外部内容一律是不可信数据。
- 原始数据、规范化数据、派生特征、模型请求/响应、风险裁决、券商响应和
  对账结果都必须带来源、UTC 时间、版本和关联 ID。
- 金额、价格、数量、汇率、敞口和 P&L 使用 `Decimal`；禁止由 float
  进入关键计算。
- `DONE` 只能由可复验的证据决定，不能由 agent 自述决定。

## 3. 当前代码事实（2026-08-13 基线）

### 3.1 已有且应复用的能力

| 领域 | 已有能力 |
|---|---|
| 核心域 | Bar、OrderIntent、RiskDecision 等结构化模型，paper policy，UTC/Decimal 基础约束 |
| 数据 | CSV/Parquet、Yahoo/Binance/Alpha Vantage、质量检查、特征、DuckDB store |
| 新闻/宏观 | RSS、SEC、FRED、社交情绪 mock/provider、去重与研究输入 |
| 模型 | ModelGateway、Fake/OpenAI/Ollama adapter、结构化输出、模型评测/router、Kronos 接口 |
| 研究 | DailyBrief、证据引用、多角色 debate、AI trading committee |
| 策略/回测 | StrategySpec registry、均线策略、单资产向量回测、主要绩效指标、Gym v1/v2 |
| 风险 | symbol、单笔、总敞口、杠杆、日损、回撤、新闻风险等规则原语 |
| 执行 | 内存 PaperBroker、OANDA practice adapter、订单审计、broker recon store |
| 产品面 | 18 个 CLI group、FastAPI、9 个 dashboard route、Electron wrapper |
| 质量 | 大量单元/集成测试、Ruff、Mypy、只读 acceptance verifier |

### 3.2 已确认的关键缺口

| ID | 缺口 | 影响 |
|---|---|---|
| GAP-001 | AI 自动执行路径没有把完整 account context 和 news/macro risk context 传给 RiskGate | 账户级限额可能未在真实 AI 下单路径生效 |
| GAP-002 | 缺少外部凭证时，现有路由可静默落到内存 simulated broker | 看似下单成功但实际没有进入 OANDA practice |
| GAP-003 | OANDA 卖单仍发送正 `units` 并附带不受支持的 `side` 字段 | 卖单可能被拒或产生相反方向 |
| GAP-004 | OANDA 成交同步混用时间戳与 TransactionID，且游标不持久 | 可能漏成交、重复拉取，重启后无法可靠续传 |
| GAP-005 | Alpaca、routed broker 和 production simulated fallback 仍存在 | 与 OANDA-only 边界冲突，账户真相不可统一 |
| GAP-006 | 缺少账户级 instrument discovery 与完整 metadata catalog | 无法证明覆盖该账户全部交易类别和品种 |
| GAP-007 | 缺少 OANDA-native candles、pricing、liquidity、conversion 和 stream | 多资产决策仍可能依赖不适配的第三方或 stale close |
| GAP-008 | 幂等、broker ledger、account truth 和 reconciliation 不持久或不完整 | 重启/超时可能重复下单，正常远端状态也会被误判 |
| GAP-009 | bars 可覆盖相同 symbol/timestamp，且无正式 migration/restore 证明 | 历史决策、回测和恢复不能绑定不可变数据版本 |
| GAP-010 | 部分 production-facing research 路径默认 FakeProvider，模型调用未统一持久化 | UI 可展示演示输出，失败与 fallback 证据不足 |
| GAP-011 | daily cycle 不是持久分阶段状态机，scheduler 展示与实际任务不同源 | 崩溃续跑、运行状态和审计不可靠 |
| GAP-012 | StrategySpec、真实 IS/OOS、walk-forward、组合成本与过拟合审计不完整 | 研究结果不能达到可复验的最终标准 |
| GAP-013 | 30 天 OANDA practice 观察尚未进行 | 最终稳定性没有时间证据 |

### 3.3 基线质量事实

在受限桌面 sandbox 中：1,389 tests passed；12 个测试因无法绑定
`127.0.0.1` 而失败，未出现业务断言失败；Ruff 和 Mypy 通过；旧静态
acceptance 11/11 通过。这只说明现有本地边界，不等于目标产品验收。

## 4. 最终系统工作流

```text
OANDA instrument/account discovery
        + market prices/candles/account changes
        + news/macro/sentiment ingestion
                         |
                         v
               immutable daily snapshot
                         |
                         v
         AI committee discussion via ModelGateway
                         |
             no_trade or OrderIntent
                         |
                         v
   deterministic RiskGate with full account/risk context
                         |
             persisted RiskDecision
                         |
         rejected ----+---- approved
             |                 |
         audit/report       OANDA practice
                               |
                       orders/trades/fills
                               |
                 cursor-based reconciliation
                               |
                  portfolio/audit/daily report
```

所有箭头都必须可以通过 correlation IDs 从日报追溯回原始证据。

## 5. 功能需求

### 5.1 平台、配置与存储

- **REQ-PLAT-001**：所有运行模式使用同一份经过 schema 校验的配置；未知
  字段失败，不静默忽略。
- **REQ-PLAT-002**：执行端点只能是常量 practice URL，配置文件不能覆盖为
  live URL。
- **REQ-PLAT-003**：凭证只从环境/系统 secret store 读取，输出全面脱敏。
- **REQ-PLAT-004**：数据库 schema 有显式版本和幂等迁移；启动时不兼容
  schema fail closed。
- **REQ-PLAT-005**：关键写入具备事务边界；进程中断不能留下半个 cycle、
  半个 RiskDecision 或无对应订单的“已执行”状态。
- **REQ-PLAT-006**：有单写者或等价协调机制，API、scheduler、CLI 不能并发
  破坏 DuckDB。
- **REQ-PLAT-007**：每日自动备份、保留策略、校验和及实际 restore drill。
- **REQ-PLAT-008**：所有记录使用 UTC，展示层可按用户时区转换。
- **REQ-PLAT-009**：所有关键 ID 可跨数据、研究、模型、风险、订单和对账
  追踪。

### 5.2 OANDA 账户、品种与市场数据

- **REQ-OANDA-001**：启动预检验证 token、account ID、practice host、账户
  状态和账户归属，但日志不暴露完整 ID。
- **REQ-OANDA-002**：从账户 instruments endpoint 动态同步全部 instrument；
  支持新增、停用、属性变化和缓存失效。
- **REQ-OANDA-003**：保存 name、displayName、type、displayPrecision、
  tradeUnitsPrecision、minimumTradeSize、maximumOrderUnits、
  maximumPositionSize、marginRate、pipLocation、stop-distance 等元数据。
- **REQ-OANDA-004**：taxonomy 覆盖 Currency、Metal 和所有 CFD 子类，保留
  原始类型、分类规则版本与 unknown 回退。
- **REQ-OANDA-005**：UI/API/CLI 可以按类别浏览、搜索、筛选账户完整品种，
  并清楚显示当前可交易状态。
- **REQ-OANDA-006**：支持 OANDA candles 的官方 granularity，bid/ask/mid
  component、complete candle 标志、分页和对齐参数。
- **REQ-OANDA-007**：支持批量 current pricing；记录 bid/ask、spread、
  liquidity、tradeable、quote home conversion 和 price timestamp。
- **REQ-OANDA-008**：可选持久价格流采用长连接，不超过官方连接限制；断线
  使用有界退避并检测 stale stream。
- **REQ-OANDA-009**：market data snapshot 必须有 freshness、coverage、gap、
  spread anomaly 和 data quality verdict。
- **REQ-OANDA-010**：资产类别、交易时段、节假日和账户实际 tradeable 状态
  共同决定是否允许提交，不用一个固定周一至周五窗口假装覆盖所有 CFD。
- **REQ-OANDA-011**：同一原始数据版本不可变；修订产生新版本和 lineage，
  不覆盖旧决策证据。

### 5.3 新闻、宏观与市场情绪

- **REQ-NEWS-001**：每日抓取配置的金融新闻源，保存 source、canonical URL、
  published/fetched time、hash、语言、正文摘要和抓取结果。
- **REQ-NEWS-002**：URL canonicalization、内容 hash 和标题相似度联合去重，
  但不合并观点不同的独立报道。
- **REQ-NEWS-003**：支持市场整体、资产类别、货币、国家、公司和具体
  instrument 的实体关联，并保留匹配置信度。
- **REQ-NEWS-004**：宏观日历/数据包含 release time、actual/forecast/previous、
  revision、importance 和受影响货币/市场。
- **REQ-NEWS-005**：情绪输出必须给出方向、强度、分歧度、样本量、来源
  覆盖、新鲜度和不确定性，不能只有一个无解释分数。
- **REQ-NEWS-006**：每条外部文本在进入模型前标记为 untrusted evidence；
  删除/转义提示注入样式指令，并验证它不能改变 system/risk policy。
- **REQ-NEWS-007**：抓取失败、部分源失败和 stale data 有明确降级；关键覆盖
  不足时 RiskGate 可拒绝，而不是捏造摘要。
- **REQ-NEWS-008**：原文许可受限时只存必要元数据和短摘要，不长期复制受
  版权保护全文。
- **REQ-NEWS-009**：每日生成可复验的 market regime/sentiment snapshot，供
  讨论和风险使用同一个 version ID。

### 5.4 ModelGateway 与 AI 研究委员会

- **REQ-AI-001**：所有模型调用经过 ModelGateway，具有 provider/profile、
  timeout、retry classification、fallback policy、cost/latency、schema verdict。
- **REQ-AI-002**：生产 research/brief/trading path 不默认 FakeProvider；缺少
  可用模型时产生明确 blocked/no-trade，不生成演示交易。
- **REQ-AI-003**：每次请求和响应持久化 hash、模板版本、模型参数、结构化
  输出、错误和 token/cost 元数据；敏感内容按策略脱敏。
- **REQ-AI-004**：committee 至少包括 market/technical、news/sentiment、
  macro/fundamental、risk/counterargument 角色，并有主持/汇总角色。
- **REQ-AI-005**：角色可自由讨论和反驳，但每轮输出必须引用 evidence IDs，
  区分事实、推断、未知和观点。
- **REQ-AI-006**：最终 proposal 包含 thesis、anti-thesis、confidence、
  horizon、entry rationale、invalidation、suggested exposure、evidence、
  dissent、data freshness 和 `no_trade` 选项。
- **REQ-AI-007**：模型 JSON 不合法或证据引用不存在时自动修复至有界次数，
  仍失败则 no-trade/blocked，绝不把自由文本直接变成订单。
- **REQ-AI-008**：committee 不能看到 token、完整 account ID 或可修改系统的
  工具；外部内容不能进行 tool call。
- **REQ-AI-009**：重复运行同一 snapshot 使用 deterministic cycle key，不能
  因 scheduler 重试产生多个 order intent。
- **REQ-AI-010**：模型评测包含 schema pass、grounding、citation validity、
  hallucination、prompt injection resistance、latency、cost 和 stability。

### 5.5 策略、回测与决策支持

- **REQ-STRAT-001**：StrategySpec 条件使用安全 DSL/AST 编译，不执行任意
  Python/SQL/模板代码。
- **REQ-STRAT-002**：至少支持 trend、mean reversion、breakout、volatility/
  regime 和 no-trade baseline；每个策略可限定适用类别。
- **REQ-STRAT-003**：支持真实 IS/OOS、rolling/anchored walk-forward、参数
  冻结、benchmark 和可重复 data version。
- **REQ-STRAT-004**：回测是多品种/组合感知并建模 spread、slippage、
  financing、margin、minimum units、market hours 和 rejected orders。
- **REQ-STRAT-005**：报告包含 return、volatility、Sharpe、Sortino、Calmar、
  max drawdown、turnover、exposure、hit rate、profit factor、tail loss、
  category attribution、cost attribution 和 benchmark delta。
- **REQ-STRAT-006**：有 overfitting audit、参数稳定性、multiple-testing 警示、
  data leakage/lookahead tests。
- **REQ-STRAT-007**：Kronos/Gym/其他预测只提供 advisory evidence，不能绕过
  committee 或 RiskGate。
- **REQ-STRAT-008**：回测与实际 OANDA practice 采用相同 instrument metadata
  和关键 risk/execution semantics，差异必须显式记录。

### 5.6 确定性风险

- **REQ-RISK-001**：每个 intent 使用 broker-fresh account snapshot、positions、
  pending orders、trades、prices 和 conversion factors。
- **REQ-RISK-002**：校验 instrument allowlist/active status、units precision、
  min/max size、price precision、market hours 和 data freshness。
- **REQ-RISK-003**：限制单笔 notional、单品种/类别/方向敞口、总 gross/net
  exposure、杠杆、margin utilization 和集中度。
- **REQ-RISK-004**：限制 realized/unrealized daily loss、rolling drawdown、
  consecutive loss、异常 spread/slippage 和流动性。
- **REQ-RISK-005**：新闻/宏观高风险窗口可以降低 size 或拒绝；调整规则是
  确定性配置，不由模型决定。
- **REQ-RISK-006**：同币种和相关资产风险可聚合；所有 exposure 转为账户
  home currency，并保留 conversion evidence。
- **REQ-RISK-007**：kill switch、freeze、stale broker、reconciliation diff、
  backup failure、scheduler health failure 均可阻止新开仓。
- **REQ-RISK-008**：平仓/减仓风险路径与开仓区分，紧急降险不能被不相关的
  开仓规则阻止，但仍需审计。
- **REQ-RISK-009**：RiskDecision 完整持久化 rule-by-rule results、inputs hash、
  max quantity、reason/tags 和 policy version，且不可在提交后修改。
- **REQ-RISK-010**：任何 RiskDecision 缺失、过期、输入已变化或拒绝时，执行
  backend 不能 submit。

### 5.7 OANDA 订单与账户生命周期

- **REQ-EXEC-001**：支持账户实际允许的 Market、Limit、Stop、
  Market-if-Touched，以及适用的 TP、SL、Trailing Stop/GSLO dependent order。
- **REQ-EXEC-002**：支持并正确校验 FOK、IOC、GTC、GTD 和 trigger condition；
  不把 DAY 静默映射为另一语义。
- **REQ-EXEC-003**：OANDA 买卖方向只按官方 units 语义编码；数量、价格、
  distance 先按 instrument metadata 规范化并再过 RiskGate。
- **REQ-EXEC-004**：支持 get/list/cancel/replace order，get/list/close trade，
  get/list/close position，account summary/changes 和 transaction details。
- **REQ-EXEC-005**：client request ID、client extensions、cycle key 和本地
  intent ID 形成持久幂等映射；未知提交结果先查询再决定是否重试。
- **REQ-EXEC-006**：正确处理 immediate fill、pending、partial fill、cancel、
  reject、expire、trade reduce/close 和 dependent order lifecycle。
- **REQ-EXEC-007**：transaction cursor 使用 OANDA transaction ID，不混用
  datetime；每次增量拉取原子推进并可 gap recovery。
- **REQ-EXEC-008**：对账比较本地与远端 orders、fills/transactions、trades、
  positions、balance/NAV/margin 和 financing；正常远端持仓不自动算异常。
- **REQ-EXEC-009**：无法解释的差异产生 freeze 和 alert；恢复需要重新同步、
  证据和显式可审计的 unfreeze 条件。
- **REQ-EXEC-010**：API、CLI、scheduler 共享同一 broker runtime/state authority，
  不各自构造互相冲突的内存账户。
- **REQ-EXEC-011**：重启后恢复 idempotency mappings、cursor、pending cycle、
  risk decisions、orders 和 reconciliation state。
- **REQ-EXEC-012**：所有外部请求记录 method family、endpoint template、状态、
  request ID、latency、retry 和 redacted correlation，不记录 token/完整账户 ID。

### 5.8 每日自动交易编排

- **REQ-CYCLE-001**：每日 cycle 由持久状态机驱动：preflight、ingest、snapshot、
  discuss、propose、risk、execute/no-trade、reconcile、report、complete。
- **REQ-CYCLE-002**：每阶段幂等且可重入；重启从最后持久 gate 恢复，不从头
  重复下单。
- **REQ-CYCLE-003**：research schedule 与 execution enable 分离；即使冻结交易
  也继续数据、研究、风险和报告。
- **REQ-CYCLE-004**：按品种和类别设置分析候选集、流动性/质量过滤、总模型
  预算和最大并发，避免对全部 catalogue 无界调用模型。
- **REQ-CYCLE-005**：候选选择透明，可解释为何分析/跳过某品种；完整品种仍
  可在 UI 浏览，不等于每天全部交易。
- **REQ-CYCLE-006**：同一日/同一 snapshot 的 catch-up 不重复；漏跑有明确
  窗口，过期 cycle 不追单。
- **REQ-CYCLE-007**：`no_trade`、RiskGate rejection、market closed 和 stale data
  都是有原因和证据的正常结果。
- **REQ-CYCLE-008**：cycle 完成后立即对账并生成 daily brief、committee transcript、
  intent/risk/order chain、portfolio snapshot、alerts 和 data quality summary。
- **REQ-CYCLE-009**：scheduler task listing、running status、heartbeat、last/next
  run 和实际执行配置来自同一 runtime truth。
- **REQ-CYCLE-010**：多个进程不能同时成为 scheduler leader；失去 lease 后
  立即停止新 cycle。

### 5.9 API、CLI、Dashboard 与桌面端

- **REQ-UI-001**：API/CLI 对 instruments、prices/candles、news/sentiment、
  committee、risk、orders/trades/positions、cycles、scheduler、alerts、
  observation 提供一致 schema。
- **REQ-UI-002**：所有写操作具备 validation、idempotency、权限边界和清晰
  错误；没有通用任意 broker request 代理。
- **REQ-UI-003**：Dashboard 采用 owner 已选的 Soft (5/5/5)，保留有效品牌，
  提供暗色模式和 320/768/1024/1440 响应式布局。
- **REQ-UI-004**：主导航覆盖 Overview、Markets、News & Sentiment、AI Research、
  Risk、OANDA Account、Orders & Trades、Scheduler、30-Day Observation、Settings。
- **REQ-UI-005**：每页有 loading、empty、stale、partial、error、offline 和
  frozen 状态；不以空白或 fake data 掩盖失败。
- **REQ-UI-006**：订单和风险链可以从 cycle 一键追溯到 evidence、讨论、
  intent、每条 risk rule、OANDA transaction 和 reconciliation。
- **REQ-UI-007**：展示 cash、NAV、margin、P&L、exposure、positions、pending
  orders、fills、financing、category attribution 和时间序列。
- **REQ-UI-008**：满足键盘操作、focus、semantic HTML、对比度、reduced motion、
  screen-reader labels；用图标库，不用 emoji 图标。
- **REQ-UI-009**：Electron 只是受控本地壳，能检测 backend readiness、优雅
  停止、显示端口冲突，不吞掉服务错误。
- **REQ-UI-010**：手工控制仅允许 pause/resume research、freeze/unfreeze paper
  execution、cancel practice order、reduce/close practice exposure；所有动作审计。

### 5.10 运维、可观测性与安全

- **REQ-OPS-001**：结构化日志、metrics、health/readiness、heartbeats 和 alerts
  覆盖 ingestion、models、scheduler、risk、broker、reconciliation、backup。
- **REQ-OPS-002**：日志带 correlation IDs，自动 scrub secret、authorization、
  完整 account ID、model-sensitive content 和未许可新闻全文。
- **REQ-OPS-003**：错误分为 auth、validation、reject、rate-limit、transient、
  protocol、data-quality、safety，并决定重试/冻结/告警。
- **REQ-OPS-004**：alert 有 severity、dedupe、acknowledgement、resolution 和
  escalation；webhook 失败不掩盖本地 alert。
- **REQ-OPS-005**：所有 external request 有 timeout/budget；重试遵循 OANDA
  连接限制并带 jitter，不阻塞整个 scheduler。
- **REQ-OPS-006**：启动、崩溃、SIGTERM、机器重启和数据库恢复有演练；未完成
  cycle 能确定性恢复。
- **REQ-OPS-007**：preflight 在真实外部下单前验证配置、凭证、账户、品种、
  数据、模型、风险、备份、scheduler 单实例和 kill switch。
- **REQ-OPS-008**：依赖和供应链扫描、secret scan、静态安全规则和 prompt
  injection fixtures 进入门禁。

### 5.11 30 天观察与最终验收

- **REQ-OBS-001**：观察期为真实连续 30 个日历日；另记 active market days、
  weekend/holiday、no-trade、failed cycle。
- **REQ-OBS-002**：每天至少有 preflight、数据/新闻/情绪快照、committee 或
  合法 skip、risk/no-trade/order、对账、portfolio、heartbeat 和日报证据。
- **REQ-OBS-003**：不要求每天成交；安全拒绝和无机会是合格行为。
- **REQ-OBS-004**：P0/P1 或影响订单/风险/持久语义的修复会重置 qualified
  observation window；纯展示/日志修复按 runbook 评估是否重置。
- **REQ-OBS-005**：周门禁检查 uptime、cycle success、duplicate orders、
  reconciliation diffs、unresolved alerts、data freshness、model/schema、
  risk rejection 和 backup restore。
- **REQ-OBS-006**：最终报告由数据库、ledger 和 artifact hashes 生成，不靠
  人工拼写通过数。
- **REQ-OBS-007**：最终通过也不解锁 live；产品状态仍为 paper-only。

## 6. 目标非功能指标

这些是验收目标，不是当前事实：

| 指标 | 目标 |
|---|---|
| 重复外部订单 | 0 |
| 无 RiskDecision 的订单 | 0 |
| live endpoint 可达性 | 0 |
| Alpaca/其他 broker 生产引用 | 0 |
| 未解释对账差异 | 0 个跨日未解决 |
| cycle crash recovery | 自动恢复或安全冻结，不重单 |
| 核心本地门禁 | pytest、Ruff、Mypy、acceptance 全绿 |
| 数据快照 lineage | 100% 交易/不交易 cycle 可追溯 |
| 模型 schema validity | 生产 accepted output 100% |
| evidence citation validity | 生产 accepted output 100% 引用存在 |
| critical secret leakage | 0 |
| 备份 | 每日成功并至少完成一次 restore drill |
| 观察期日报 | 30/30 日历日 |
| Dashboard 响应式 | 320/768/1024/1440 全部验证 |

## 7. 重大架构决策摘要

完整 ADR 在 `docs/architecture.md`。

1. **模块化单体而非微服务**：单用户本地系统没有独立扩容收益；用清晰 package
   boundary、单数据库 writer 和后台 scheduler 降低运维复杂度。
2. **OANDA account discovery 而非静态 universe**：地区差异和账户权限决定真实
   能力；硬编码列表会误导且很快漂移。
3. **持久状态机而非 cron 函数串联**：需要跨重启幂等和每阶段证据。
4. **append-only audit + current projections，而非 event sourcing 全量重构**：
   获得审计与恢复能力，同时避免无必要复杂度。
5. **确定性 RiskGate 在 AI 之后**：模型适合生成观点，不适合作为安全裁决器。
6. **真实 30 天和工程完成分离**：工程 gate 可以自动跑完，时间证据不能加速或
   伪造。

### 7.1 零人工运行参数（必须按此实现）

后续 agent 不得为以下值提问或自行选择另一套默认值。所有值都应进入严格、版本化
配置；配置缺失时使用这里的安全默认，未知字段失败。

### 技术栈与运行拓扑

- 保留 Python 3.12+ 模块化单体、FastAPI、Typer、DuckDB 和现有 Electron shell；
  不迁移微服务、不引入第二数据库，也不为 dashboard 引入前端框架；
- dashboard 使用现有 server-rendered/静态资源边界、语义 HTML、原生 CSS/JS 和已有
  图标依赖；只有现有能力无法满足测试过的无障碍需求时才能增加小型依赖；
- API 默认只绑定 `127.0.0.1`；禁止 `0.0.0.0`、公网暴露、通配 CORS 和远程 broker
  代理。所有写操作必须同时经过本地来源、CSRF/同等请求绑定、幂等键、RiskDecision
  或明确的 reduce-only operator policy；
- 一个 scheduler leader 持有可续租 writer lease；API 默认读 current projections，CLI
  写命令转交同一 runtime owner，不创建第二个生产 broker/session；
- DuckDB、artifact、backup 和日志写到显式 runtime data root，不写入源码目录；路径
  缺失时创建具体子目录，绝不对宽泛目录做递归删除；
- 保持本地单用户产品，不设计账号注册、RBAC、云同步、遥测上报、付费或多租户；
- 外部出站 allowlist 只含 OANDA practice、配置并通过健康检查的数据/新闻/模型源；
  未列入目标、重定向到 live/其他 broker 或证书失败全部拒绝；
- 依赖升级采用现有 major version 范围内满足安全门禁的最小变更；若必须跨 major，拆成
  独立 repair item 并以兼容性测试裁决，不询问用户；
- 数据库 schema、配置 schema、API schema、prompt schema、taxonomy 和 risk policy
  都显式版本化。无法自动迁移的未知版本保持只读/冻结，不猜测；
- 产品显示语言默认中文，稳定领域字段、API schema、错误 code 和 evidence ID 使用
  English；时间在存储层统一 UTC，UI 默认展示 `Asia/Shanghai` 并同时保留 UTC；
- 所有自动开发、运行和观察日志采用结构化 JSON；人类可读摘要由同一事实生成，不能
  成为另一份状态源。
- M16 的日历等待由持久 observation supervisor 和宿主 recurring wake 完成；coding
  agent 不用长 sleep 占住 turn。Day 0 前必须验证 next-run 持久化、机器重启恢复和
  Day 30 自动收口；宿主不具备自动唤醒时记录 blocker，绝不要求人工每天继续。

### 调度时刻

统一运营时区 `America/New_York`，数据库仍存 UTC：

| Task | Default schedule |
|---|---|
| account/transaction sync | 每 15 秒；失败后 1/2/4/8/16/30 秒退避，上限 30 秒 |
| quote freshness/watchdog | 流模式持续；poll fallback 每 5 秒；stale > 15 秒阻止新单 |
| candles incremental | 每 5 分钟，同时按所需 granularity 对齐 |
| news ingestion | 每 30 分钟 |
| macro refresh | 每 60 分钟；高影响事件前后每 10 分钟 |
| sentiment snapshot | 每 60 分钟和 daily cycle 前强制一次 |
| instrument catalog sync | 启动时及每天 02:00 |
| daily candidate snapshot | 交易日 07:30 |
| AI discussion/risk cycle | 交易日 08:00；只允许 120 分钟 catch-up |
| reconciliation | 每 5 分钟、每次外部订单结果后、启动/停止时 |
| daily report/review | 每天 17:30；市场关闭日仍生成 observation record |
| backup | 每天 18:00，保留最近 14 日 + 8 个周备份 |
| observation daily gate | 每天 23:30 |

OANDA 各 instrument 实际 tradeable status、报价新鲜度和事件风险仍是 submit 时的
最终 gate；固定时刻从不代表市场一定开放。

### 每日候选和模型预算

- catalog 不限展示数量；每天最多分析 24 个品种；
- 每个非空 asset category 至少尝试 1 个满足质量门的代表，单类最多 6 个；
- 排序依次为：tradeable、quality PASS、spread percentile、liquidity、news relevance、
  regime relevance、instrument name，确保 deterministic；
- 任何一项关键数据 stale/unknown 则跳过，不用模型补猜；
- committee 并发最多 3 个 instrument；
- 单 instrument 固定 4 analyst roles + 1 moderator，最多两轮 analyst rebuttal +
  一轮 moderator synthesis；
- 单 model call timeout 30 秒；schema repair 最多 2 次；provider fallback 最多 1 次；
- 单 instrument 最多 15 个 model calls；单 daily cycle 最多 240 calls；达到预算后其余
  品种记录 `NO_TRADE_MODEL_BUDGET`；
- 默认 production provider 为 `auto`，只在真实 OpenAI/Ollama adapter health PASS 时
  使用；没有可用 provider 时 `NO_TRADE_MODEL_UNAVAILABLE`，绝不 Fake fallback。

### 风险默认值

值均按 broker-fresh NAV 和账户 home currency 计算：

- 单笔初始风险预算：NAV 的 0.25%；
- 单笔最大 notional：NAV 的 2%；
- 单 instrument gross exposure：NAV 的 5%；
- 单 asset category gross exposure：NAV 的 15%；
- 总 gross exposure：NAV 的 30%；总 net absolute exposure：NAV 的 20%；
- margin utilization warning 20%，禁止新开仓 30%，强制 reduce-only 40%；
- 单日 realized + unrealized loss 1% 后冻结新开仓；
- 从观察期 high-water NAV 回撤 3% 后冻结；
- 连续 3 个 closed losing trades 后冻结该 instrument 24 小时；
- 当前 spread 超过过去 20 个可比 session 日的 95th percentile 或报价 stale 时拒绝；
- 高影响宏观事件：受影响货币/资产事件前 30 分钟到后 30 分钟不新开仓；
- 极端 sentiment/新闻分歧或 coverage insufficient：默认 size=0（no-trade）；
- 所有未识别 instrument category 默认禁止下单，直到 taxonomy 和 risk semantics 有
  测试；目录仍展示；
- 每天最多 5 个新开仓 intents；单 instrument 每日最多 1 个新方向 intent；
- 观察前 7 天把上述 notional/exposure/new-intent cap 再乘 0.5；
- risk limit 只能由版本化 owner policy 变更 work item 修改，模型和新闻不能改。

### 订单默认值

- 无显式策略理由时使用 MARKET + FOK，并以 current executable price 做风险评估；
- LIMIT 默认 GTC，但必须显式 expiry review；跨日仍 pending 时 daily cycle 不重复；
- 策略需要 day semantics 时使用 OANDA 官方 GFD，不做 DAY->GTC 近似；
- GTD 必须显式 UTC expiry，默认不超过 24 小时；
- 默认 `positionFill=DEFAULT`，但 reversal/hedging 由账户 mode 和 risk rule 明确处理；
- 保护性 SL/TP 由 deterministic sizing/policy 计算，模型只能建议，RiskGate 最终确定；
- 没有可靠 volatility/price-distance/metadata 时不创建订单；
- 未知 submit outcome 进入 `SUBMIT_UNKNOWN`，先按 client ID/transactions 查询，绝不
  直接重发；
- unfreeze 不依赖人工：修复 gate + controlled E2E + full reconciliation + 连续 3 个
  clean reconcile 周期后由状态机自动恢复；P0/P1 会按 runbook 重置观察窗。

### 新闻/情绪安全默认

- 至少需要 2 个独立成功 source family，且最新关键市场内容 <= 6 小时；否则
  `CONTENT_COVERAGE_INSUFFICIENT`；
- 同 source syndicated 内容按一个 source family 计；
- sentiment sample < 5 或 disagreement > 0.70 时不允许以 sentiment 增加仓位；
- prompt-injection detector 命中不删除原 evidence hash，但隔离文本，不送入模型；
- licensed full text 默认不持久保存，只存 URL/metadata/hash/允许的短摘要；
- provider 报错不由模型生成替代新闻。

### 自动开发控制参数

- 相同 external operation 最多立即重试 2 次；
- 同一 failure signature 最多修复 3 次；单 item 总 repair cycles 最多 5；
- 所有 work item 仍被阻塞时输出 blocker 并结束，不提问；
- 不具备 T7 凭证时 milestone 至多 `CODE_COMPLETE/RUNTIME_VALIDATING`，继续独立项；
- 30 日观察等待下一天时记录 WAITING，不 sleep，不提问；
- 任何未预见选择采用 fail-closed/no-trade/freeze，绝不扩大权限。

## 8. 实施总原则

- M00-M15 是工程准备阶段，不承诺固定日历时长；按 work item 小步自动推进。
- M16 是真实 30 天观察，必须在 engineering readiness gate 之后开始。
- M17 汇总最终证据。没有权限或凭证时可以完成本地代码，但相关里程碑只能是
  `CODE_COMPLETE/RUNTIME_BLOCKED`。
- 每个 work item 一次本地 main commit；每个 milestone 有完整回归 gate。
- 禁止把 observation 当开发测试环境。先通过 sandbox/cassette/small controlled
  practice E2E，再开始计时。
- 观察期间只允许范围明确的缺陷修复；安全/执行语义变化按 runbook 重置窗口。

## 9. 里程碑蓝图

### M00 - 文档权威与基线重置

**目标**：删除历史 Phase/Round 文档，建立单一权威蓝图、机器任务队列、进度、
验收、runbook、loop 协议，并让 scaffold/acceptance 不再依赖旧文档和 Alpaca
预检。

**范围**：仅文档、文档引用、acceptance/scaffold 元测试和非业务注释。

**完成条件**：

- 旧 roadmap、development log、phase plans、duplicated risk/model docs 全部删除；
- 新文档互相无断链，YAML/NDJSON 可解析；
- `progress.yaml` 明确区分当前 multi-broker 代码事实与 OANDA-only 目标；
- acceptance preflight 检查 OANDA practice config/env contract，不再要求 Alpaca；
- 相关测试、Ruff、Mypy、acceptance 通过；
- 未改交易业务逻辑。

### M01 - OANDA-only 硬切换

**目标**：从运行时代码、配置、依赖、API/CLI、测试和 UI 中彻底删除 Alpaca、
multi-broker routing 和 silent simulated fallback。

**关键工作**：删除 Alpaca package/config/env；把执行工厂统一为一个 OANDA
practice runtime；缺凭证 fail closed；静态扫描禁止 `alpaca` 和 live host；更新
policy 为 `provider: oanda_paper`；保留 test-only fake。

**完成条件**：

- production graph 中 Alpaca/RoutingBrokerAdapter/SimulatedBrokerAdapter 不可达；
- tracked source/config/docs 不含 Alpaca credential contract；
- live host 和通用 live switch 有 negative tests；
- API、CLI、scheduler 都获取同一 OANDA runtime；
- 无凭证不会生成本地假成交；
- 全量门禁通过。

### M02 - 自治开发控制器与证据系统

**目标**：让“自动 loop”由确定性工具约束，而不是只依赖 prompt 自律。

**关键工作**：为 work/progress schema 建 validator；实现 preflight、拓扑选项、
非法状态迁移拒绝、allowlist diff gate、命令 exit-code capture、artifact hash、
ledger append、commit trailer 生成和 resume audit；增加 meta-tests。

**完成条件**：控制器不能自行把失败 work item 标 DONE；修改 gate 的工作项不能
用同一次修改后的 gate 单独自证；上下文丢失后能用 Git + checkpoint 恢复；不
拥有的 dirty changes 会停止。

### M03 - 存储版本、迁移与恢复基础

**目标**：建立 30 天连续运行需要的可靠持久层。

**关键工作**：schema version/migrations；single-writer 协调；不可变 market/news/
model/risk/audit facts；current projections；事务 cycle checkpoint；备份、校验和、
restore；原子 failure injection tests。

**完成条件**：从旧 schema 迁移和空库初始化均可重复；崩溃不会留下半状态；
restore drill 复原所有关键对象；并发 writer 被串行化或 fail clearly；旧 bar
version 不再被覆盖。

### M04 - OANDA 账户与完整品种目录

**目标**：以 configured practice account 为权威，发现和展示全部可交易品种及
能力。

**关键工作**：account preflight；instruments client；metadata models/store；
category taxonomy；catalog sync/diff；API/CLI；搜索筛选；账户变化处理；fixtures
覆盖 CURRENCY/METAL/不同 CFD/unknown。

**完成条件**：catalog 数量与 OANDA response 一致；无硬编码 allowlist 丢品种；
每项具备 precision/size/margin 元数据；unknown CFD 可见而非丢弃；practice
contract test 通过。

### M05 - OANDA 市场数据与不可变快照

**目标**：为研究、风险和执行提供同版本、足够新鲜、可解释的数据。

**关键工作**：candles pagination/granularity/components；pricing batch/stream；
spread/liquidity/conversions；session/tradeable；gap/freshness/quality；snapshot
builder；lineage；rate/connection budgets。

**完成条件**：官方 granularity contract 覆盖；incomplete candle 不混入已完成
信号；bid/ask/mid 和 timestamp 保留；断流检测；同一个 cycle 的各模块引用同一
snapshot ID；无覆盖历史版本。

### M06 - OANDA 订单、交易、持仓和 transaction lifecycle

**目标**：实现可靠的 broker port，而不只是一条 market/limit submit demo。

**关键工作**：重定义 broker-neutral/OANDA-specific schemas；订单类型与 TIF；
dependent orders；trade/position close；order replace/cancel；account changes；
transaction cursor；partial fill/reject/expire；错误分类；redacted telemetry。

**完成条件**：所有支持语义按 instrument/account capability 校验；无 DAY 静默
替换；units 方向正确；transaction ID cursor 可断点恢复；unknown submit outcome
先查询；contract fixtures 和受控 practice E2E 通过。

### M07 - 持久幂等、组合事实与对账

**目标**：API、scheduler 和重启看到同一个 OANDA 账户事实，不重复订单。

**关键工作**：client/broker/transaction mapping；local order ledger；remote
projections；账户/订单/成交/trade/position/financing 对账；cursor gap recovery；
freeze/unfreeze；startup sync；crash scenarios。

**完成条件**：相同 cycle 重跑 100 次最多一个外部订单；正常远端持仓不误报；
人为引入每类 diff 都能检测并 freeze；重启恢复 pending order；对账清零后才允许
显式恢复。

### M08 - 完整确定性风险链

**目标**：把现有 risk primitives 接入每一条真实 AI/manual paper 执行路径。

**关键工作**：broker-fresh account context；home-currency conversion；pending
orders；category/correlation/concentration；margin/leverage；daily loss/drawdown；
spread/liquidity；news/macro window；stale/freeze/kill switch；reduce-only；persisted
rule results。

**完成条件**：没有 context 的执行 fail closed；自动 AI 路径和手工路径使用同一
gate；每条 rule 有边界/组合测试；rejected decision 无法被 backend submit；
execution input 与 RiskDecision hash 匹配。

### M09 - 新闻、宏观、情绪生产化

**目标**：每天生成来源清楚、新鲜、去重、抗提示注入的市场内容快照。

**关键工作**：provider reliability；canonical/dedupe；entity mapping；宏观事件；
sentiment ensemble/disagreement；provenance；licensing limits；stale degradation；
injection sanitization；API/CLI。

**完成条件**：固定 fixture 可重放；外部文本无法改变 system/risk instructions；
部分 provider 失败不伪造；关键 coverage 不足触发 no-trade/risk；每个 sentiment
结论可回到样本和 source。

### M10 - ModelGateway 与 AI 委员会闭环

**目标**：让 AI 自由讨论同时保持 schema、证据、成本和安全可控。

**关键工作**：移除生产 Fake 默认；provider health/fallback；durable call record；
prompt/template version；committee roles；multi-turn debate；dissent；citation
validation；JSON repair；budget/concurrency；evaluation suite。

**完成条件**：模型不可用时 no-trade 而非 fake order；所有 accepted claims 引用
存在的 evidence；invalid schema 不进入 intent；prompt injection suite 通过；
同 snapshot/cycle key 不重复产生可执行 intent。

### M11 - 每日自治 cycle 与 scheduler 真相统一

**目标**：形成可恢复、可暂停、研究和执行解耦的每日状态机。

**关键工作**：persistent phases；leader lease；candidate selection；pre-cycle
ingest；committee；risk；execute/no-trade；immediate reconciliation；daily report；
catch-up/expiry；API/CLI scheduler truth；pause/freeze controls。

**完成条件**：每阶段 kill/restart tests；研究在 execution freeze 时继续；API/CLI
显示真实 running/last/next；missed stale cycle 不追单；重复 trigger 不重单；全链
simulation 和 controlled practice smoke 通过。

### M12 - 策略、回测和研究质量闭环

**目标**：把已有策略/回测从 demo 能力提升为可支持 OANDA 决策评估的工具。

**关键工作**：安全条件 DSL；策略族；真实 IS/OOS/walk-forward；multi-instrument
portfolio engine；OANDA spread/financing/margin/session metadata；benchmark；
overfitting/leakage audits；Kronos/Gym advisory boundaries；报告/API/CLI。

**完成条件**：lookahead fixtures 必须失败；同数据版本可复验；费用归因完整；
walk-forward 对 API/CLI 可用；策略不能直接调用 broker；AI 日决策可引用但不盲从
回测证据。

### M13 - API/CLI 合同与手工控制面

**目标**：把内部闭环暴露成一致、受控、可运维的产品接口。

**关键工作**：versioned schemas；统一 error envelope；pagination/filter；instrument
catalog；market/news/research/risk/broker/cycle/observation endpoints；safe operator
actions；OpenAPI/CLI parity；contract tests。

**完成条件**：无假数据默认；写操作有 idempotency/audit；无任意 broker proxy；
API/CLI 对同一对象字段一致；stale/frozen/partial 明确；OpenAPI snapshot 受控。

### M14 - Soft Dashboard 与 Electron 最终体验

**目标**：按 Soft (5/5/5) 完成信息清晰、暗色、响应式、可访问的全功能界面。

**关键工作**：先审计旧 9 页；统一 design tokens/navigation；Markets、News &
Sentiment、AI Research、Risk、OANDA Account、Orders/Trades、Scheduler、30-Day
Observation；trace explorer；loading/error/stale/offline；Electron lifecycle。

**完成条件**：320/768/1024/1440 visual + interaction tests；keyboard/a11y/contrast/
reduced motion；before/after audit；无 emoji icon、无虚构 filler、无 fake runtime
data；暗色模式完整；Electron readiness/port/shutdown 有测试。

### M15 - 运维加固与 Engineering Readiness Gate

**目标**：在开始真实 30 天前完成安全、可观测性、恢复和全仓验收。

**关键工作**：structured logs/metrics/health；alert lifecycle；secret scrub；rate
budgets；dependency/secret/security scans；backup restore；SIGTERM/machine restart；
fault injection；性能/资源 soak；acceptance evidence generator；runbook rehearsal。

**完成条件**：全量 pytest/Ruff/Mypy/acceptance/security 通过；所有 M01-M15
需求有 trace；controlled practice E2E 自动清理且对账为零；duplicate/live/Alpaca/
RiskGate negative gates 全通过；restore drill 成功；运行凭证只从预配置 secret
environment 读取，persistent supervisor 启动后不需要中途人工步骤。

### M16 - 真实 30 日 OANDA practice 观察

**目标**：运行 `docs/oanda_30_day_runbook.md`，积累不可伪造的稳定性证据。

**阶段**：

- Day 0：冻结版本、备份、preflight、最小受控 E2E、建立 observation ID；
- Days 1-7：小风险上限，每日自动只读证据复核，不手工制造订单；
- Days 8-14：验证周末/跨周、financing、新闻风险和首次 restore check；
- Days 15-21：验证连续运行、模型/provider 故障和告警闭环；
- Days 22-29：无高风险变更，只修文档/非语义展示或按规则重置窗口；
- Day 30：最终对账、备份恢复、证据完整性和 observation gate。

**完成条件**：30/30 日历日报；所有 market day cycle 有结论；0 duplicate；0
无 RiskDecision 订单；0 live/Alpaca；0 未解释跨日 diff；所有 P0/P1 已关闭且
qualified window 满足；最终账户与本地投影一致。

### M17 - 最终验收、发行与长期运行移交

**目标**：由证据生成最终报告，确认功能覆盖、已知限制和操作方式。

**关键工作**：自动生成 trace/quality/observation report；fresh-clone setup；
operator recovery drill；package/Electron build；文档 truth audit；版本 tag 候选；
长期 backup/retention/maintenance 日程。

**完成条件**：所有 required work item 和 requirement 为 PASS；没有 TBD/waiver；
fresh install 可按 runbook 到 readiness；最终报告 hash 对应原始 artifacts；仓库
clean；产品明确保持 OANDA practice-only。

## 10. Milestone 依赖与并行规则

```text
M00 -> M01 -> M02 -> M03 -> M04 -> M05 -> M06 -> M07 -> M08
                                      |                    |
                                      +-> M09 -> M10 ------+-> M11
M05 -> M12 -----------------------------------------------> M13
M09 + M10 + M13 -> M14
M01..M14 -> M15 -> M16 -> M17
```

- 同一时刻只能有一个 agent 修改共享执行/数据库 schema；只读调研可并行。
- M09/M10 可在 M06/M07 后段并行，但 M11 必须等待完整风险/幂等链。
- M14 只能在 API contract 稳定后完成，避免 UI 建在临时 schema 上。
- M16 期间不得并行进行会改变执行语义的未来开发。

## 11. 每个里程碑的强制测试层

| 层 | 内容 | 适用规则 |
|---|---|---|
| T0 | 文档/schema、branch、forbidden strings、allowlist | 每轮 |
| T1 | 当前 work item targeted unit/contract tests | 每轮 |
| T2 | 相关 package/API integration tests | 每轮 |
| T3 | 全仓 pytest regression | 执行/风险/模型/调度变更及 milestone gate |
| T4 | Ruff、Mypy、dependency/secret/static safety | 每轮相关项，milestone 全量 |
| T5 | AlphaBrief acceptance、negative invariants、meta-gates | 执行关键项及 milestone |
| T6 | cassette/sandbox fault injection、restart/recovery | 相关 milestone |
| T7 | controlled OANDA practice E2E | 标注 external evidence 的 milestone |
| T8 | real-time observation evidence | M16/M17 |

T7 只能通过正式产品路径、固定最小风险、RiskGate、幂等 ID 和自动清理执行。
Coding agent 不得手工 curl 下单来制造通过证据。

## 12. 完成与重置规则

### 12.1 Work item 完成

必须同时满足：范围、acceptance、测试、safety、文档、commit、ledger、clean
tree。具体由 `docs/autonomous_loop.md` 定义。

### 12.2 Milestone 完成

所有 required work items DONE；全量 milestone gate 通过；需求 trace 无空项；
需要外部证据的已经取得。只有 mock 时最多 `CODE_COMPLETE`。

### 12.3 Observation 窗口重置

以下变化从修复验证后的下一完整日重新计 30 天：

- RiskGate 规则或输入链变化；
- order/transaction/idempotency/reconciliation 语义变化；
- scheduler/cycle recovery 语义变化；
- schema migration 导致历史证据不可连续；
- P0/P1 事故或 duplicate/unapproved order；
- live/other-broker 可达性事件。

文案、非语义布局、仅增加脱敏日志且有回归证明的修复可不重置，但必须在
incident ledger 记录决定和证据。

## 13. 明确不做

- live trading；
- Alpaca 或多券商；
- 多用户、付费、社交、云 SaaS；
- 高频/超低延迟交易；
- AI 自改风险阈值或 prompts；
- 为每天产生交易而强制开仓；
- 用回测收益作为上线条件；
- 复制 `_reference_sources/`；
- 在 30 天之前宣称“最终完成”。

## 14. 官方外部契约

实现 OANDA 相关功能时以账户实际响应和官方 v20 文档为准：

- Account 与 account instruments：
  https://developer.oanda.com/rest-live-v20/account-ep/
- Instrument primitives/types：
  https://developer.oanda.com/rest-live-v20/primitives-df/
- Orders 与 dependent order schemas：
  https://developer.oanda.com/rest-live-v20/order-df/
- Order endpoints：
  https://developer.oanda.com/rest-live-v20/order-ep/
- Trade endpoints：
  https://developer.oanda.com/rest-live-v20/trade-ep/
- Position endpoints：
  https://developer.oanda.com/rest-live-v20/position-ep/
- Transaction endpoints 与 cursor/range：
  https://developer.oanda.com/rest-live-v20/transaction-ep/
- Pricing endpoints：
  https://developer.oanda.com/rest-live-v20/pricing-ep/
- OANDA account-state synchronization best practices：
  https://developer.oanda.com/rest-live-v20/best-practices/
- v20 API 能力、candles/stream/limits：
  https://developer.oanda.com/rest-live-v20/api-comparison/
- Practice endpoint 与连接限制：
  https://developer.oanda.com/rest-live-v20/development-guide/

官网列出的品种类别不保证当前 v20 practice 账户全部可用；账户 instruments
endpoint 始终优先。任何 API 行为假设必须有官方 contract fixture 或真实 practice
evidence，不凭记忆实现。

## 15. 蓝图变更治理

本蓝图已获 owner 整体批准，work item 可在 Autonomous Blueprint Mode 自动推进。
不需要任何逐轮计划审核、确认、优先级选择或重试许可。每轮的计划检查是确定性
机器门禁，不是人工 review。Agent 在整个蓝图执行期间不得向用户提问；未覆盖的
情况一律 fail closed/no-trade/freeze，记录 blocker 后继续独立工作，全部依赖被阻塞
时直接停止并输出 blocker，而不是请求决策。
以下情况不能由 coding agent 静默修改：

- 放宽 OANDA practice-only/live 禁令；
- 加入其他 broker；
- 弱化 RiskGate、幂等、对账、30 天或测试门禁；
- 改变 UI preset；
- 删除 required requirement；
- 让模型拥有执行或配置权限。

发现需求需要拆分时可新增子 work item，但 requirement 和 acceptance 不能减少。
蓝图之外的新产品需求进入 AD_HOC_MODE，需用户明确批准后才实施。
