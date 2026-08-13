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
| `alphabrief-api db` | DuckDB stores + versioned migration framework | M03-W01 起 schema 由 ordered/transactional/idempotent migrations 管理；newer/corrupt schema 启动 fail closed |
| `alphabrief-trader db` | AI cycle facts + `CycleCheckpointStore` | M03-W03 起 cycle+votes+attempts 单事务提交；checkpoint 为 CAS/单调推进；projection 从 facts 重建并与 stored 逐字节一致 |
| `writer_lease` | 共享 DuckDB 文件的可续期单写者 lease | M03-W04 起 acquire/renew/validate 全为 SQL CAS；过期 ownership 在 takeover 后写被拒；`open_readonly` 结构性只读 |
| `backup` | 原子 DB backup / manifest / restore / retention | M03-W05 起：CHECKPOINT+rename 原子快照、file/schema/build hashes、secret scan、isolated restore（migrate+integrity+projection rebuild）、确定性 retention |
| storage 里程碑 | M03 完成 | versioned migrations、immutable facts、atomic cycle checkpoints、writer lease、verified backup/restore 全部落地；crash recovery boundary suite 通过 |
| `oanda/preflight` | fail-closed account preflight | M04-W01 起：typed profile（Decimal margins + capability flags + scrubbed account hash + UTC retrieved_at）；六类分类失败；无 token/完整 account ID 外泄 |
| `oanda/instruments` | complete instruments contract | M04-W02 起：每 row → 严格 `InstrumentMetadata`（Decimal-safe、raw type/unknown fields 保留于 versioned raw payload）；缺/坏 required fields 拒绝整个 snapshot |
| `instrument_catalog` store | versioned catalog snapshots + diffs | M04-W03 起：migration v3 表；publish 原子（content hash/account correlation/fetched_at UTC/diff 一起提交）；replay 幂等；projection 从 immutable rows 重建并与最新 snapshot 逐字节一致 |
| `oanda/taxonomy` | versioned deterministic taxonomy | M04-W04 起：Currency/Metal/CFD 子类（INDEX/COMMODITY/BOND/EQUITY/CRYPTO/OTHER），display-based 规则，raw type 保留；unknown 永不消失；分类不 mutate raw snapshot |
| catalog API/CLI | read-only catalog surfaces | M04-W05 起：共享 `store.query()`（pagination/search/category/active、确定性排序）；API `/api/v1/data/catalog` 与 CLI `data catalog` 输出全等；missing/stale/mismatch 显式 unavailable，绝不 substitute allowlist 或触发 broker write |
| M04 里程碑 | account + instruments + catalog | W01 preflight、W02 instruments contract、W03 versioned snapshots、W04 taxonomy、W05 API/CLI 全部落地；W06 本地 gates 通过，T7 practice evidence PENDING（CODE_COMPLETE，M05 继承 external_evidence_pending） |
| `oanda/candles` | complete candles contract | M05-W01 起：全部官方 granularity、M/B/A 组件各自成 fact（Decimal-safe）、alignment 参数、bounded duplicate-free pagination、complete 语义（incomplete 保留 raw、排除出 decision inputs）、immutable source_version |
| `oanda/pricing` | batch pricing + conversions | M05-W02 起：确定性分块（默认 50/上限 500）、ladders/spread/liquidity/tradeable/closeout/conversion/broker time/correlation 全保留；quality validation fail-closed；显式 per-instrument coverage（partial 永不视为 complete snapshot） |
| `oanda/stream` | bounded stale-aware pricing stream | M05-W03 起：单连接 owner + 原地 subscription reconcile；classified bounded backoff（disconnect/heartbeat/malformed/rate/server）；stale 先于消费 freshness 判定；shutdown 返回最终 cursor 供持久化 |
| `oanda/sessions` | category-aware sessions/holidays/tradeability | M05-W04 起：8 类窗口（FX overnight、CFD、Crypto 24x7、holidays、UTC-fixed）；`evaluate_exposure_readiness` 对 tradeable/catalog/session/stale/unknown 全 fail-closed；不再依赖单一全局 weekday window |
| `market_snapshot` store | immutable cycle market snapshots | M05-W05 起：migration v4 表；确定性 manifest（source IDs + quality rules + quality version）；7 类 quality rules → non-executable verdict；原子 publish + lineage 链；后继 ingestion 不改变已引用 snapshot |
| M05 里程碑 | OANDA market data | W01 candles、W02 pricing/conversions、W03 stream、W04 sessions/holidays、W05 immutable snapshots 全部落地；W06 本地 gates 通过，T7 practice evidence PENDING（CODE_COMPLETE，M06 继承 external_evidence_pending） |
| `oanda/orders` | strict order contracts | M06-W01 起：signed units（buy+/sell-、zero 拒）、4 类 order type、FOK/IOC/GTC/GTD（DAY 拒）、dependent orders（TP/SL/trailing/GSLO）`*OnFill` 精确序列化；price/distance 从 instrument metadata 精确规范化，超精度拒绝；无 `side` 字段 |
| `oanda/order_ops` | order command/query port | M06-W02 起：create（clientExtensions.id 幂等）/get/list（分页）/cancel/replace（pending-only，stale/race fail-closed）；typed responses + request correlation；classified errors（invalid_request_id/unknown_order/order_state_invalid） |
| `oanda/transitions` + `transition_store` | order transition facts + projection store | M06-W03 起：CREATED/FILLED/PARTIAL_FILL/CANCELLED/REJECTED/EXPIRED/REISSUED/REDUCED/CLOSED/DEPENDENT_* 作为 immutable facts（broker transaction id/related id/UTC/Decimal）；`apply_transition` 确定性投影（immediate fill 直落 FILLED、terminal 不可变、REDUCE/CLOSE 仅限 filled trade、REISSUED 保持身份）；DuckDB append-only 存储，duplicate 幂等忽略、conflict/out-of-order quarantine，绝不虚构 fill |
| `oanda/trade_ops` | trade command/query port | M06-W04 起：get/list（分页）/close（ALL 或 partial units，fill 事实为准，stale race 以 cancel+no-fill fail-closed）/protective dependents（TP/SL/trailing/GSLO 四选一，GSLO 需账户 ENABLED）；typed responses + request correlation；realized/financing 与 create/fill/trade-close transaction ID 各自独立 |
| `oanda/position_ops` | position command/query port | M06-W04 起：get/list（long/short 独立 units/avg/PL）/close（显式 ALL/NONE/positive units——OANDA 缺省即 ALL，故未指定侧绝不静默全平）；over-close/未知 instrument fail-closed，无本地合成仓位变更 |
| `oanda/account_ops` | account summary/changes port | M06-W04 起：summary（balance/NAV/PL/margins/open counts/lastTransactionID）；changes 以 sinceTransactionID 为唯一游标（digit-only，本地时间戳不可替代），lastTransactionID 独立返回供消费者确认后再前进；404/422/protocol 全分类 fail-closed |
| `oanda/transaction_ops` | transaction details/ranges/cursor primitives | M06-W05 起：get detail、inclusive ID-range（分页自动拉全，上限 50 页）、since-ID；broker transaction ID 是唯一游标权威（digit-only，本地时间戳直接拒绝）；输出确定性规范化（按 broker ID 升序、去重计数）并给出显式 gap spans（空页/重叠/重复/乱序/缺失 range 全覆盖）；`cursor_candidate` 只返回最高完全连续前缀，端口不持有任何 durable cursor——失败的消费者永远无法确认未见 transaction |
| `oanda/faults` | failure classification + bounded retry | M06-W06 起：AUTH/VALIDATION/NOT_FOUND/REJECT/RATE_LIMIT/TRANSIENT_SERVER/TIMEOUT/DISCONNECT/PARSE/UNKNOWN_OUTCOME 稳定 typed classes；只有 RATE_LIMIT/TRANSIENT_SERVER/TIMEOUT/DISCONNECT 可 bounded retry；`ClassifiedRequestExecutor`：GET 对可重试类 bounded 重试；mutating 请求遇 TIMEOUT/DISCONNECT/TRANSIENT_SERVER → `UnknownOutcomeFailure`（绝不自动重试），429 明确未处理可重试 |
| `oanda/unknown_outcome` | unknown-outcome resolution + submission gate | M06-W06 起：`UnknownOutcomeResolver` 用持久化 clientExtensions.id 穷举（bounded 分页）查询 broker——match→RESOLVED_ACCEPTED、穷举无匹配→RESOLVED_NOT_SUBMITTED、查询失败/截断→UNRESOLVED；`SubmissionGate.freeze` 后一切后续提交被 `FrozenSubmissionError` 阻断，不猜测、不询问 |
| `oanda/telemetry` | scrubbed request telemetry | M06-W06 起：DuckDB `request_telemetry` 表记录 method family/endpoint template（{account_id}/{id} 占位）/status/broker request ID/latency/attempts/error class/had_body；correlation 以 sha256 前 16 位非可逆 hash 存储；token、完整 account ID、敏感 payload（units/price 等）绝不落库 |
| `oanda/practice_scenarios` | controlled minimal-risk practice scenarios | M06-W07 起：正式产品路径 OrderIntent → RiskGate（固定最小风险 cap，intent 构造性封顶）→ persisted RiskDecision（DuckDB `practice_scenarios` 表）→ 幂等 client identity 提交 → 自动 cleanup（pending cancel / filled trade close，幂等 replay 返回 already_closed）→ 最终 reconciliation evidence；缺凭证 → ENVIRONMENT_BLOCKED，cleanup 未决/外部 outage → FAIL；绝不 fake fill、无 waiver、不询问 |
| M06 里程碑 | OANDA execution | W01-W06 全部落地（contracts/order_ops/transitions/trade-position-account/transactions/faults+telemetry）；W07 生命周期证明通过，T7 practice E2E evidence PENDING（CODE_COMPLETE，M07 继承 external_evidence_pending） |
| `oanda/order_ledger` | idempotency identities + local order ledger | M07-W01 起：`(cycle_id, intent_id)` 确定性推导唯一 submit identity；DuckDB `order_ledger_reservations`（UNIQUE(cycle,intent)）+ 不可变 `order_ledger_events`；状态机 RESERVED→BOUND→SUBMITTED→COMPLETED（FROZEN 终态），全部 compare-and-set 单事务提交（event+update 原子）；identity collision/payload hash mismatch/stale owner/in-flight ambiguous/missing decision 一律冻结绝不覆盖；与 W06 UnknownOutcomeResolver 组合：timeout 后按 client identity 解析再记录 broker result，绝不重复下单 |
| `oanda/transaction_cursor` | atomic account-scoped transaction cursor | M07-W02 起：facts+projections+cursor 单事务推进（注入 crash → 旧完整态或新完整态）；游标只前进到最高完全连续 consumed ID（首洞 sealed），缺失 span 记 OPEN gap；duplicate/overlapping 幂等、nonmonotonic 忽略、corrupt 拒绝且零部分提交；`recover_range` bounded 重取（account-scoped fetcher），超过 ceiling 的 gap 冻结（FROZEN）后拒绝 span 内 fact；restart 从最后提交的 OANDA transaction ID 恢复，绝不用 wall-clock 或部分响应 |
| `oanda/account_projection` | durable remote account projections | M07-W03 起：从 immutable OANDA facts 确定性推导 account/balance/NAV/margin/orders/fills/trades/positions/realized+unrealized PnL/financing（broker ID 排序、UTC 时间戳）；ORDER_CREATE/FILL/CANCEL、TRADE_CLOSE/REDUCE、DAILY_FINANCING、DEPOSIT/WITHDRAWAL 精确 fold；未支持 kind 在构造期拒绝（fail-closed）；`rebuild`（干净重放）与 `apply_changes`（full snapshot + incremental）收敛到同一 normalized projection；`resolve_account_snapshot` 是 API/CLI/scheduler 共享的持久化 authority，杜绝 process-local 状态分歧 |
| `oanda/reconcile` | typed reconciliation without false mismatches | M07-W04 起：`Reconciler` 比较本地 projection 与 `RemoteAccountView`（orders/trades/positions/balance/NAV/margin/financing/fills/cursor/account）；稳定 typed diffs（account/cursor/order/trade/position/money/quantity/state/fill_diff）带 source ID + INFO/WARN/CRITICAL severity；无 client identity 的远端实体 = broker-originated INFO（零 false missing-local 告警），ledger 可解释的 client identity 不告警，无法解释的 → CRITICAL；tolerances 显式/versioned/directionally safe（shortfall 必告警、windfall 仅 INFO、quantity 零容忍、margin 双向 CRITICAL） |
| `oanda/freeze_policy` | evidence-backed exposure freeze + unfreeze | M07-W05 起：`ExposureFreezeStore` 对 blocking diff/unresolved gap/stale snapshot/resync failure/corrupt projection/cursor failure 六类 alarm 落一条 deduplicated durable freeze（DuckDB `exposure_freezes`，同 account+reason+detail 幂等去重、restart 后仍在）；`ensure_new_exposure_allowed` 在任一 active freeze 下抛 `FreezeActiveError` 阻断新开仓；`unfreeze` 仅在 fresh full sync 成功、零 blocking diff、cursor 与 projection hash 匹配、alerts 全解析时放行，并在 `exposure_unfreezes` 追加不可变 evidence（event_id 单调、完整 policy 快照 + reason + unfrozen_at）；五项检查默认全部为拒绝值——省略任一检查即 `UnfreezeDeniedError`，无 clear/dismiss/confirm API，任何 API/CLI/scheduler/model/fallback 路径都不能靠 omission 解冻；unfreeze 后同 alarm 复发生成新 freeze_id（detail sha256 前 12 位 + occurrence seq），绝不因主键冲突被吞 |
| `oanda/submit_recovery` | durable submit workflow + startup sync | M07-W06 起：`SubmitWorkflow` 把每个外部提交过渡串成一条可崩溃恢复的持久路径——reserve → bind approved decision → submit attempt → send → broker result → fact commit → cursor advance → reconciliation，全部对 append-only ledger 做 compare-and-set；八个命名 fault point（before_reserve/after_reserve/before_send/after_send/after_response/during_fact_commit/during_cursor_advance/during_reconciliation）任一崩溃后从新进程以同 (cycle,intent) 重跑即从确定性边界恢复，绝不产生第二个外部订单；in-flight（SUBMITTED）结果一律按持久化 client identity 查询（REQ-EXEC-005），RESOLVED_ACCEPTED → 完成、NOT_SUBMITTED/UNRESOLVED/查询失败 → ledger FROZEN + 新开仓 freeze（evidence_refs 指回 ledger submit）；completed submit 后 blocking reconciliation diff 只冻结新开仓，外部订单本身是不可变终态；`StartupSyncService`（REQ-EXEC-011）在重启时解析全部 in-flight、把 `submit_id → broker_order_id` 映射回进程 adapter（`OrderLedger.completed_mappings`）、并报告持久 cursor——重启绝不重下单、绝不重消费 facts；ledger 新增 `in_flight_reservations()`/`completed_mappings()` 只读查询 |
| `broker/reconciliation` | shared durable reconcile service | M07-W06 起：API `POST /api/v1/broker/reconcile`、CLI `broker reconcile`（API 离线时）、scheduler startup/cycle 全部调用同一 `ReconciliationRunner`（AC-M07-W06-03）；null adapter（缺 OANDA practice 凭证）→ 显式 non-matching 快照（diff.error=broker_not_configured）+ 按 scope freeze 策略，绝不产生无条件 all-match placeholder；无任何路径“询问如何恢复” |
| M07 里程碑 | durable idempotency/account truth/reconciliation | W01-W06 全部落地（idempotency ledger/atomic cursor/projections/typed reconcile/freeze policy/submit recovery+startup sync）；W07 聚合证明通过——六套确定性套件 + 聚合 restart 链测试全绿、共享 durable reconcile 三入口一致、缺凭证/blocking diff/unresolved remote state 全部 fail-closed（ENVIRONMENT_BLOCKED 或 freeze）；T7 practice restart E2E evidence PENDING（CODE_COMPLETE，M08 继承 external_evidence_pending） |
| `alphabrief_risk/broker_context` | versioned broker-fresh risk context value object | M08-W01 起：`BrokerRiskContext`（frozen、extra=forbid、Decimal-only、UTC）携带 account state/tradeable/home currency、balance/NAV/margin、positions（long/short）、pending orders、trades、bid/ask prices（含 spread）、conversions、catalog version、reconciliation state、health state、source IDs（REQ-PLAT-009）、captured_at、per-source freshness verdicts；`internally_consistent` 确定性检查 margin identity（nav-margin_used≈margin_available，容差 0.01）与 uncrossed prices；共享 `context_version`/`policy_version`（"2026-08-13.1"） |
| `alphabrief_execution/broker/risk_context` | one broker-fresh context service for every execution path | M08-W01 起：`BrokerRiskContextBuilder` + `build_broker_risk_context` 是 AI external 与 manual paper 两条执行路径共用的唯一 pre-risk context 服务（AC-M08-W01-02）；`RiskContextSources` 端口注入 venue 事实，`adapter_risk_sources(adapter)` 从 broker-neutral port 组合默认 sources（port 无 prices/trades/conversions/catalog/reconciliation 权威 → 如实记录空/None/unknown，持仓无 price 即 partial 拒绝），paper route 用 `_PaperRiskSources`（legacy venue truthful sources）；`FreshnessPolicy` per-source 期限（account 300s/prices 60s/…，None=venue 不定）；classified `RiskContextError`（missing_source/stale/account_mismatch/partial/frozen/inconsistent）在 submit 前 fail-closed（AC-M08-W01-03），绝不合成默认、不 fallback account、不询问；`project_risk_context_to_exposure` 把 context 投影进 RiskGate 的 `AccountExposureContext` |
| `alphabrief-data` | bar loaders/providers、quality、features | 保留；增加 OANDA native data、immutable lineage |
| `alphabrief-news` | news/sentiment providers | 保留；生产化 provenance/freshness/injection defense |
| `alphabrief-models` | ModelGateway、adapters、evaluation/router | 保留；统一 durable call records/fallback |
| `alphabrief-research` | brief、debate、evidence | 保留；与 daily committee 共享 evidence contract |
| `alphabrief-strategy` | StrategySpec 和 signals | 保留；增加 safe compiler/strategy families |
| `alphabrief-backtest` | vectorized backtest/metrics | 保留；扩展 portfolio/walk-forward/OANDA semantics |
| `alphabrief-risk` | deterministic RiskGate | 保留；所有执行路径必须接入完整 context |
| `alphabrief-execution` | PaperBroker、OANDA、recon、scheduler | M01-W03 后为 OANDA-only runtime port；routing/simulated 已删除，test fake 只在测试边界 |
| `alphabrief-trader` | committee、snapshot、daily cycle、execution backend | 保留；改为持久 cycle state machine |
| `alphabrief-gym` | training environments | 保留为 advisory/research，不能直连 execution |
| `alphabrief-review` | post-trade review | 保留并接入 OANDA ledger/observation |
| `alphabrief-acceptance` | read-only local boundary verifier | 扩展为 blueprint/negative/runtime evidence gates |

`apps/api` 提供 FastAPI 和 server-rendered dashboard；`apps/cli` 提供 CLI 与
scheduler entry point；`electron` 只负责本地 backend lifecycle 和窗口。

### 2.2 Current Execution Path

M01-W01..W04 已把生产执行路径收敛为 OANDA-only、fail-closed，并由
`alphabrief_execution.broker.runtime` 提供进程级共享 runtime authority：

```text
API/CLI broker factory  ->  get_broker_runtime().adapter
       |
  OANDA credentials configured?
    yes -> OandaPaperAdapter (practice constant only)
    no  -> fail-closed null adapter (reports not ready; cannot submit)
```

API lifespan、CLI broker commands 与 scheduler 解析同一个 runtime factory
和 persistent data directory（`resolve_data_dir`，`ALPHABRIEF_DATA_DIR` →
`~/.alphabrief/data`）；进程内只有一个 adapter 实例，idempotency mapping
在 shutdown 时 flush 到 broker recon store，不因关闭而丢弃。剩余事实：

1. OANDA adapter 仍以常量 practice URL 工作，缺凭证绝不本地成交；
2. 完整账户 instruments 权威、candle/pricing/stream、订单生命周期与
   对账仍由 M04-M07 落地；
3. durable idempotency 的完整 seeding/cursor 语义由 M07 落地（M01-W04
   只保证 shutdown 不丢弃 mapping）。

M04-M07 目标结构（accepted target decision，尚未完成）：

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
| `alphabrief_risk/instrument_rules` | deterministic instrument constraint rules | M08-W02 起：`evaluate_instrument_rules` 对 catalog allowability（catalog_known/catalog_active）、broker tradeable、session（open/holiday/stale evidence）、quote freshness、candle completeness、gap、conversion、pricing coverage、units/price precision、minimum size、maximum order units、position cap、normalized-zero 逐条产出稳定 typed `InstrumentRuleResult`（identical evidence → identical results，任一 fail-closed 输入拒绝新开仓，无合成）；`normalize_instrument_units/price` 在最终 risk evaluation 前规范化（不可表示即拒绝，绝不静默进位/舍入改变订单）；`bind_execution_inputs`/`validate_execution_inputs` 把 (decision, symbol, units, price, instrument_version, snapshot_hash) 绑定为 sha256——post-decision 任一输入变化使执行失效（REQ-RISK-010）；`RiskDecision.execution_input_hash` 可选字段由 `ExternalPaperExecutionBackend.submit` 在提交前校验 |
