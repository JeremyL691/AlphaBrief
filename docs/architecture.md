# AlphaBrief Architecture

版本：2026-08-13.1
用途：记录当前代码事实、最终目标边界和已接受的重大架构决策。
禁止：在本文件追加逐轮开发日志或把目标写成已经实现。

## 1. System Context

AlphaBrief 是单用户、本地优先的模块化单体。最终只有四个进程/边界：

```text
Operator browser / Electron shell
              |
          FastAPI API
              |
  shared application services + stores
              |
  one scheduler leader / background workers
              |
        OANDA v20 practice

External read-only inputs:
market/news/macro feeds + ModelGateway providers
```

API、CLI 和 scheduler 可以是不同入口，但必须依赖同一个持久 runtime authority，
不能各自创建相互独立的券商账户或本地 portfolio truth。

## 2. Current Architecture Truth

### 2.1 Packages

| Package | 当前职责 | 最终方向 |
|---|---|---|
| `alphabrief-core` | domain schemas、settings、paper policy | 保留；policy 收敛为 OANDA practice-only |
| `alphabrief-data` | bar loaders/providers、quality、features | 保留；增加 OANDA native data、immutable lineage |
| `alphabrief-news` | news/sentiment providers | 保留；生产化 provenance/freshness/injection defense |
| `alphabrief-models` | ModelGateway、adapters、evaluation/router | 保留；统一 durable call records/fallback |
| `alphabrief-research` | brief、debate、evidence | 保留；与 daily committee 共享 evidence contract |
| `alphabrief-strategy` | StrategySpec 和 signals | 保留；增加 safe compiler/strategy families |
| `alphabrief-backtest` | vectorized backtest/metrics | 保留；扩展 portfolio/walk-forward/OANDA semantics |
| `alphabrief-risk` | deterministic RiskGate | 保留；所有执行路径必须接入完整 context |
| `alphabrief-execution` | PaperBroker、OANDA、Alpaca、routing、recon、scheduler | 重构为 OANDA-only runtime；test fake 移入测试边界 |
| `alphabrief-trader` | committee、snapshot、daily cycle、execution backend | 保留；改为持久 cycle state machine |
| `alphabrief-gym` | training environments | 保留为 advisory/research，不能直连 execution |
| `alphabrief-review` | post-trade review | 保留并接入 OANDA ledger/observation |
| `alphabrief-acceptance` | read-only local boundary verifier | 扩展为 blueprint/negative/runtime evidence gates |

`apps/api` 提供 FastAPI 和 server-rendered dashboard；`apps/cli` 提供 CLI 与
scheduler entry point；`electron` 只负责本地 backend lifecycle 和窗口。

### 2.2 Current Execution Path

当前代码是多券商路由，而不是最终结构：

```text
API/CLI broker factory
       |
RoutingBrokerAdapter
  | OANDA for underscore symbols
  | Alpaca for equities/crypto
  + SimulatedBrokerAdapter when credentials are absent
```

这带来三个不可接受的事实：

1. 缺凭证时“外部模拟盘”可能在本地内存成交，观察结果并非 OANDA；
2. routing 以 symbol 形态猜 venue，不能以账户真实 instruments 为权威；
3. routing account snapshot 不能正确表达多个 venue 的统一账户事实。

M01 会删除这条生产路径，目标为：

```text
OandaRuntime singleton
  |- OandaHttpClient (practice constant only)
  |- InstrumentCatalog
  |- Pricing/Candle clients
  |- Order/Trade/Position/Transaction client
  |- AccountProjector and durable transaction cursor
  |- RiskContextBuilder
  |- ReconciliationService
  `- BrokerTelemetry
```

### 2.3 Confirmed OANDA Contract Defects

以下是当前代码事实，必须按 M01-M07 修复，不能把 adapter 的存在当完成：

- `broker/oanda/adapter.py` 下单始终发送正 `units` 并额外发送 `side`；OANDA
  v20 方向由 signed units 表达，卖单应为负 units。
- `DAY` 被静默映射为 LIMIT/GTC 或 MARKET/FOK，改变用户语义。目标 model
  需要显式支持 OANDA 的 GFD/GTD/GTC/FOK/IOC，不能静默近似。
- broker port 只有 MARKET/LIMIT；遇到 STOP、MARKET_IF_TOUCHED、TP、SL、
  GSLO、TRAILING_STOP_LOSS 等远端订单时解析可能失败。
- `list_fills()` 对 transactions endpoint 使用了错误参数，并把 datetime 与
  TransactionID 混用；目标使用 durable `lastTransactionID`、account changes/
  since-id 和受控 gap recovery。
- 下单响应没有完整处理 fill/cancel/reject/reissue，partial fill 被简化。
- units/price 没有基于 `tradeUnitsPrecision`、`minimumTradeSize`、
  `maximumOrderUnits`、`displayPrecision` 做账户品种级校验。
- fill 固定 fees=0，丢失 commission、financing、guaranteed execution fee 和
  realized P&L。
- idempotency mapping 仅在 adapter 内存；提交超时后的 uncertain outcome 没有
  持久查询恢复。
- health 只列 account，不验证配置的 account、账户可交易状态和 MT4 兼容限制。
- HTTP transport 丢失 response headers/status metadata，分页、RequestID、
  Retry-After 和审计证据不足。
- reconciliation 不读取 fills，所有 remote positions 都被当作差异，cash/fill
  比较近乎占位；API reconcile 还有永远 match 的 offline placeholder。

### 2.4 Current Data and AI Defects

- market bars 主键不含 data version，同一 timestamp 可被覆盖。
- 现有 market provider factory 还不支持 OANDA source；在 M05 完成前，示例配置
  只能明确使用当前可用的 Yahoo provider，不能把它当作最终多资产行情。
- Yahoo symbol mapping 只覆盖少数 FX，不能覆盖 OANDA 多资产目录。
- brief/research 某些 API 默认 FakeProvider。
- ModelGateway 调用记录主要在进程内；provider selection/fallback 不足。
- daily cycle 的 RiskGate 调用没有完整 account/news risk context。
- scheduler task listing 和实际 handler/enable state 不同源。

## 3. Target Module Boundaries

### 3.1 Dependency Direction

```text
apps/api, apps/cli, scheduler
          |
      application services
          |
core <- data/news/models/research/strategy/backtest/risk/execution/trader/review
          |
 infrastructure adapters (DuckDB, HTTP, filesystem)
```

规则：

- domain models 不 import app 或 provider implementation；
- ModelGateway 是模型 provider 的唯一 boundary；
- OandaRuntime 是 broker HTTP 的唯一 production boundary；
- research/risk 不 import OANDA adapter；它们使用结构化 snapshots/ports；
- execution 不解析自由文本；它只接受已校验 schemas；
- UI/CLI 不直接写数据库或调用 broker；只调用 application services。

### 3.2 Runtime Ownership

最终每个 data directory 只有一个 `RuntimeCoordinator`：

```text
RuntimeCoordinator
  |- DatabaseWriter lease
  |- SchedulerLeader lease
  |- OandaRuntime
  |- ModelGateway
  |- IngestionCoordinator
  |- DailyCycleService
  |- ReconciliationService
  |- BackupService
  `- Health/Alert services
```

FastAPI lifespan 创建并关闭 coordinator；CLI 若连接已运行 API，则通过 API；若
以独立 one-shot 模式运行，必须先取得 writer/operation lease，不能与 scheduler
并行写同一事实。

### 3.3 Production vs Test Adapters

生产 dependency injection graph 只允许：

- `OandaHttpClient`；
- approved news/data HTTP clients；
- ModelGateway adapters；
- DuckDB/filesystem stores；
- local alert/webhook sink。

`FakeBrokerAdapter`、clock、transport、model fake 和 fixtures 只在 tests 或显式
test composition root 可达。production settings 没有 `simulated` provider 值。

## 4. Canonical Data Model

### 4.1 Identity and Correlation

所有关键对象包含：

```text
observation_id
cycle_id / cycle_key
snapshot_id
evidence_id
model_call_id
discussion_id
proposal_id
intent_id
risk_decision_id
client_order_id
broker_order_id
trade_id
transaction_id
reconciliation_id
```

`cycle_key` 至少由 account scope、trading date、candidate universe version、
snapshot version 和 strategy/research policy version 确定。相同 key 不允许创建第
二个 active intent/order chain。

### 4.2 Instrument Catalog

建议 canonical instrument fields：

```text
instrument_name             # OANDA 原始 name，主标识
display_name
oanda_type                  # CURRENCY | CFD | METAL
asset_category              # versioned internal taxonomy
taxonomy_version/reason
display_precision
trade_units_precision
minimum_trade_size
maximum_order_units
maximum_position_size
margin_rate
pip_location
min/max trailing stop distance
financing metadata
tags
tradeable/account scope
source_transaction_id
effective_from/effective_to
raw_payload_hash
```

catalog 是 versioned slowly-changing fact。同步不能删除历史；下架品种变为
inactive。RiskGate 永远基于当前 active record，历史报告基于当时版本。

### 4.3 Market Facts

- Candles 使用 `(instrument, granularity, price_component, timestamp,
  source_version)` 的不可变身份。
- Quote 包含 bid/ask buckets、mid、spread、tradeable/status、closeout bid/ask、
  home conversion、quote time 和 received time。
- Snapshot 是一组 fact IDs 的 manifest，不复制并覆盖事实。
- `complete=false` candle 可以展示，但默认不能进入完成周期信号。
- quality verdict 与 raw data 分开，保留 rules/version/results。

### 4.4 Content and Evidence

```text
ContentItem(raw metadata + permitted text/summary)
EntityLink(item -> instrument/currency/category, confidence)
SentimentObservation(direction, strength, disagreement, sample, freshness)
MacroEvent(actual/forecast/previous/revision/importance)
EvidenceRef(source object ID, excerpt/hash, timestamp, trust label)
DailyResearchSnapshot(manifest of accepted evidence)
```

系统 prompt 与 evidence 永不拼接为同一信任层。模板显式告诉模型 evidence 是
引用材料而不是指令；输出 citation validator 只接受 snapshot 中存在的 ID。

### 4.5 AI Discussion

每个 role turn 存储 role、model call、input manifest hash、claims、citations、
uncertainties、counterpoints、proposed action、schema verdict。最终 proposal 不能
只存一段 prose；prose 是结构化字段的 presentation。

### 4.6 Risk and Execution Ledger

- `OrderIntent` append-only；修改意味着新 intent/version。
- `RiskDecision` append-only，包含输入 hash、policy version 和每条 rule result。
- `OrderSubmission` 在外部 call 前持久化为 `SUBMITTING`，保存 idempotency key。
- OANDA response/transaction 更新状态，不覆盖历史 transition。
- Current order/trade/position/account views 是可重建 projection。
- Transaction cursor 与已应用 transaction IDs 同一事务推进。

## 5. Daily Cycle State Machine

```text
CREATED
-> PREFLIGHT
-> INGESTING_MARKET
-> INGESTING_CONTENT
-> SNAPSHOT_READY
-> SELECTING_CANDIDATES
-> DISCUSSING
-> PROPOSAL_READY
-> RISK_EVALUATING
-> REJECTED | NO_TRADE | EXECUTING
-> RECONCILING
-> REPORTING
-> COMPLETED
```

异常状态：`RETRY_WAIT`、`FROZEN`、`BLOCKED_EXTERNAL`、`FAILED_SAFE`、
`EXPIRED`。每次 transition 必须满足 compare-and-set，记录 timestamp、attempt、
input/output IDs 和 error classification。

原则：

- `EXECUTING` 前必须有 persisted approved RiskDecision；
- 进入 `SUBMITTING` 后崩溃，恢复先按 client ID/transaction cursor 查询；
- 当日 cycle 过了允许窗口后 `EXPIRED`，不补下过期订单；
- research freeze 和 execution freeze 是两个状态；
- `NO_TRADE` 是 completed outcome，不是 failure；
- report 和 reconcile 失败不会假装 cycle completed。

## 6. OANDA Integration Architecture

### 6.1 Hosts

Production constants:

```text
REST:   https://api-fxpractice.oanda.com
STREAM: https://stream-fxpractice.oanda.com
```

测试 transport 通过 dependency injection，不通过可配置不安全 URL 混入 production
settings。任何 `api-fxtrade`/`stream-fxtrade` 字符串在 production source/config 中
由 static gate 拒绝。

### 6.2 HTTP Semantics

- 保存 OANDA RequestID、HTTP status、Location/Link、Retry-After 和 latency；
- GET/poll 可以对 classified transient/429 有界重试；
- POST/PUT/DELETE 未知结果不能盲重试，先 broker lookup/reconcile；
- 遵守官方 REST/stream/connection budgets并留安全余量；
- request logs 使用 endpoint template，不输出 account path literal；
- response raw payload 可按 schema/retention 保存，但先做 secret/privacy scrub。

### 6.3 Account Synchronization

启动：

1. fetch account details/summary；
2. fetch instrument catalog；
3. fetch pending orders/open trades/open positions；
4. 读取远端 `lastTransactionID`；
5. 与本地 cursor/projected state 比较；
6. 缺口用 transactions since-id/id-range 分页安全回补；
7. 原子提交 projection 与 cursor；
8. 无未解释 diff 后才 ready for new orders。

运行：持续或定期 account changes/transaction sync，另有周期全量 reconciliation。

### 6.4 Trading Capability

内部 schema 不假设每个 instrument 支持所有 order/dependent order。请求先经过：

```text
instrument active/capability
-> unit/price/distance normalization
-> current quote/tradeable/freshness
-> RiskGate
-> OANDA request builder
```

官方 schema 支持而账户/instrument 不允许时，产品显示 unsupported/rejected，不做
近似转换。

## 7. Risk Architecture

`RiskContextBuilder` 在评估前一次性冻结输入：

- OANDA account/NAV/balance/margin；
- positions/trades/pending orders；
- current quote/liquidity/home conversions；
- catalog constraints；
- daily realized/unrealized P&L/high-water mark；
- category/currency/correlation exposures；
- data quality/freshness；
- news/macro/sentiment risk windows；
- execution freeze/kill/health/backup/recon flags；
- immutable policy version。

RiskGate 纯函数式评估该 snapshot。backend 同时验证 decision/input hash、未过期、
approved 和 quantity cap。任何一个不匹配都拒绝。

Exposure 不再统一用 `abs(qty) * last close` 猜 USD。使用 OANDA quote/home
conversion、NAV/margin 和 instrument semantics，在账户 home currency 下计算 gross、
net、directional、category、currency 和 concentration。

## 8. Scheduler and Operations

### 8.1 Task Families

最终 scheduler 至少有：

- account/transaction sync；
- quote freshness/optional stream watchdog；
- market candle ingestion；
- news/macro/sentiment ingestion；
- daily research/trading cycle；
- reconciliation；
- daily report/review；
- backup and retention；
- observation evidence check；
- health/alert escalation。

任务定义、enable state、last/next run、lease owner 和 heartbeat 写入同一 store，API
只读这份 truth，不重建静态列表。

### 8.2 Single Leader

使用数据库 lease 或进程锁。lease 有 owner ID、acquired/renewed/expires time。
只有 owner 可开始新 cycle；失去 lease 时当前非外部阶段安全停止，外部提交阶段按
uncertain outcome recovery 处理。

### 8.3 Failure Classification

```text
AUTH            -> freeze, bounded periodic credential/account recheck; no question
VALIDATION      -> reject item, no retry
BROKER_REJECT   -> record reason, no blind retry
RATE_LIMIT      -> bounded Retry-After/backoff
TRANSIENT       -> bounded retry, then external blocker/freeze
PROTOCOL        -> freeze integration path
DATA_QUALITY    -> no-trade / degraded research
MODEL_SCHEMA    -> repair/fallback, then no-trade
RECONCILIATION  -> freeze execution
SAFETY          -> hard stop
```

## 9. API and UI Architecture

### 9.1 API

- versioned Pydantic schemas and explicit pagination cursors；
- read endpoints query application projections, never raw external services ad hoc；
- write endpoints call application commands with idempotency and audit；
- SSE/WebSocket only for bounded local status/stream views，断开不影响交易状态；
- no endpoint accepts arbitrary URL/provider/broker payload；
- OpenAPI snapshot changes are intentional and tested。

### 9.2 UI

UI preset is Soft (5/5/5). Target information architecture:

```text
Overview
Markets
News & Sentiment
AI Research
Strategies & Backtests
Risk
OANDA Account
Orders & Trades
Scheduler & Alerts
30-Day Observation
Settings
```

UI 只展示 server truth。任何 data source 为 fake、stale、partial、offline 或 frozen
必须有显著状态标签。Trace explorer 以 cycle 为根串起 evidence -> discussion ->
proposal -> intent -> risk rules -> order -> transactions -> reconciliation。

## 10. Testing Architecture

### 10.1 Test Types

- domain unit/property tests；
- provider/OANDA official-schema contract fixtures；
- HTTP cassette/mock transport integration tests；
- migration/failure injection/crash recovery tests；
- API/CLI schema parity tests；
- UI component/responsive/a11y/visual tests；
- security negative tests；
- controlled practice E2E；
- real observation evidence。

### 10.2 Environment Truth

Local sandbox inability to bind localhost is an environment limitation only when the same
test passes in an approved environment. Tests must classify that explicitly; they cannot be
deleted or permanently skipped. OANDA runtime tests are separate from deterministic local
tests and cannot leak credentials/artifacts。

## 11. Accepted Architecture Decisions

### ADR-001 - Modular Monolith

**Status**: Accepted.
**Decision**: 保持 Python modular monolith + local API/scheduler，不拆微服务。
**Rationale**: 单用户、低吞吐、共享事务和恢复比独立扩容更重要。
**Trade-off**: 需要严格 package boundaries 和 single-writer 纪律。
**Revisit**: 只有出现多用户隔离或独立扩容的真实需求。

### ADR-002 - OANDA Practice Is the Only Broker

**Status**: Accepted.
**Decision**: 删除多券商和生产模拟器 fallback。
**Rationale**: 一个账户 truth 才能完成可审计对账和 30 天证明。
**Trade-off**: 账户不提供的类别不再由其他 venue 补齐。
**Mitigation**: 动态展示支持/不支持，不虚构能力。

### ADR-003 - Account-Discovered Universe

**Status**: Accepted.
**Decision**: `/accounts/{id}/instruments` 是 universe authority。
**Rationale**: OANDA 地区和账户权限不同。
**Trade-off**: 分类需要 versioned taxonomy，且账户变化影响候选集。
**Mitigation**: 原始 type/name 永久保留，unknown 分类可见。

### ADR-004 - Persistent State Machine

**Status**: Accepted.
**Decision**: daily cycle 和 autonomous development loop 都使用显式状态机。
**Rationale**: 需要跨崩溃/上下文压缩恢复和非法 transition 拒绝。
**Trade-off**: schema 和测试更多。
**Mitigation**: 状态小而明确，不引入分布式 workflow engine。

### ADR-005 - Append-Only Facts plus Projections

**Status**: Accepted.
**Decision**: 关键 audit facts append-only，current views 可重建。
**Rationale**: 获得审计和恢复，不进行完整 event-sourcing 重写。
**Trade-off**: projection consistency 要测试。
**Mitigation**: transaction cursor/checkpoint 原子提交和 rebuild tests。

### ADR-006 - Deterministic Risk Authority

**Status**: Accepted.
**Decision**: AI 后置一个纯确定性、持久化 RiskGate。
**Rationale**: 模型不适合作安全裁决。
**Trade-off**: 会拒绝部分看似合理的模型提案。
**Mitigation**: 清晰 reason/tags 和可调但版本化的 owner policy。

### ADR-007 - DuckDB with Coordinated Writer

**Status**: Accepted for this blueprint.
**Decision**: 继续 DuckDB，本地单写者/lease、迁移、备份。
**Rationale**: 现有技术栈和单用户规模足够。
**Trade-off**: 不适合多进程高并发写。
**Mitigation**: 所有写经 coordinator；冲突 fail closed。
**Revisit**: 经测量仍无法满足 scheduler/API 可靠性时再评估 Postgres。

### ADR-008 - ModelGateway as Sole Model Boundary

**Status**: Accepted.
**Decision**: provider adapter、fallback、schema、records 全在 ModelGateway。
**Trade-off**: 需要把旧 API defaults 迁移。
**Mitigation**: contract tests and no-direct-SDK static gate。

### ADR-009 - Research and Execution Are Separately Gated

**Status**: Accepted.
**Decision**: trading freeze 不停止 ingestion/research/report；execution 单独 gate。
**Rationale**: 风险冻结期间仍需要观察和解释。
**Trade-off**: scheduler 状态多一个维度。
**Mitigation**: UI 明确 Research/Execution 双状态。

### ADR-010 - Real-Time Evidence Cannot Be Simulated

**Status**: Accepted.
**Decision**: mock/local tests 不能满足 practice E2E；回放不能满足 30 日历日。
**Trade-off**: 最终完成需要外部凭证和时间。
**Mitigation**: code-complete/runtime-validating 状态分离，等待时推进独立工作。

### ADR-011 - Soft UI Preset

**Status**: Accepted by owner.
**Decision**: DESIGN_VARIANCE=5、MOTION_INTENSITY=5、VISUAL_DENSITY=5。
**Trade-off**: 不是极密集终端式界面，也不是实验型大动效。
**Mitigation**: 数据密集页面使用 progressive disclosure 和 responsive tables。

### ADR-012 - No Separate Documentation Archive

**Status**: Accepted.
**Decision**: 删除旧 plans/logs/reports，不移动到 docs/archive。
**Rationale**: archive 仍会被 agent 搜到并误用；Git history 已保存。
**Trade-off**: 旧历史不在工作树直接浏览。
**Mitigation**: 需要时通过 Git history 明确检索，不作为当前事实。

## 12. Architecture Change Rule

只有当 module boundary、state ownership、persistence model、external contract 或
safety invariant 改变时才更新本文件。每轮进度、测试数字、完成记录写入 progress/
ledger，不写进 architecture。
