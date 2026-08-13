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
| `alphabrief_strategy/dsl` | safe compiled condition DSL | M12-W01 起：`compile_condition` 把 StrategySpec 条件表达式编译为 frozen typed AST（`LiteralNode`/`DataNode`/`IndicatorNode`/`ComparisonNode`/`LogicNode`/`NotNode`，pydantic extra=forbid），在求值前拒绝 Attribute/Subscript/import/comprehension/lambda/exec/eval/BinOp/赋值/副作用语法（`DslCompileError`，禁例表 + indicator/data allowlist）；`evaluate_condition` 是 declared leaves 上的纯函数——只读 `EvaluationContext` 中已声明叶子，缺失/未声明 → `DslEvaluationError` fail-closed，绝不读未来或外部状态；requirements/`leaf_keys()` 显式枚举 indicator signature 与 data name（REQ-STRAT-001） |
| `alphabrief_strategy/families` | category-aware deterministic strategy families | M12-W02 起：`TrendFamily`/`MeanReversionFamily`/`BreakoutFamily`/`VolatilityRegimeFamily`/`NoTradeFamily` 均为 frozen 纯函数——只读 bar 字段与 `required_features()` 声明的 feature keys，同输入恒同输出；feature 缺失 → 显式 `insufficient data` flat，绝不猜测；`FAMILY_APPLICABILITY` 按 OANDA instrument category（与 M04-W04 taxonomy parity 由测试强制）限定适用类别；`StrategyInstrumentCategory` 为 taxonomy 的类型镜像，strategy runtime 不 import broker 代码（REQ-STRAT-002）；族输出仅为 `StrategyOutput`(Signal evidence)，无 order 能力 |
| `alphabrief_strategy/admission` | machine-enforced strategy admission | M12-W02 起：`evaluate_strategy_admission(family_id, category)` 为纯函数——适用组合 approved，不适用组合以同时含 family 与 category 的显式 reason rejected；未知 family rejected；`PREDICTIVE_FAMILY_IDS`（kronos_forecast/gym_policy）对全部类别 rejected 且 reason 含 advisory-only 声明，预测/学习输出永不成为可执行策略（REQ-STRAT-007） |
| `alphabrief_backtest/metadata` | versioned OANDA-semantic backtest instrument metadata | M12-W03 起：`BacktestInstrumentMetadata` 镜像 practice runtime 的 display/trade-units precision、min/max units、margin rate（REQ-OANDA-003）；`normalize_backtest_units/price` 与 `alphabrief_risk.instrument_rules` 语义一致（不可表示即拒绝），`round_backtest_price` 供引擎对 spread/slippage 计算价做 broker 式舍入；`BacktestSessionWindow`/`CATEGORY_SESSION_WINDOWS` 镜像 M05-W04 会话（UTC-fixed、end≤start 整周回绕、naive moment 按 UTC）；`SEMANTICS_VERSION`/`SEMANTICS_DIFFERENCES` 显式记录与 practice runtime 的关系（REQ-STRAT-008） |
| `alphabrief_backtest/execution` | deterministic OANDA-semantic order execution | M12-W03 起：`execute_order` 为纯函数——stale price→`stale_price`、session 关闭→`market_closed`、精度/最小/最大 units→`units_precision`/`below_minimum_units`/`above_maximum_units`/`above_maximum_position`、margin 不足→`insufficient_margin` 全部显式 reject reason；accepted fill 应用 mid-based bid/ask spread、逆向 slippage、fee 并记录 spread/slippage cost 与 margin_used；`financing_charge` 按 units×nights 计费（REQ-STRAT-004） |
| `alphabrief_backtest/portfolio` | multi-instrument portfolio accounting | M12-W03 起：`PortfolioSimulator` 以 account home currency 记账——cash/NAV/gross-net exposure/margin/positions/realized+unrealized PnL/category attribution 全部 Decimal；`apply_fill` 支持 add/partial close/full close/reversal 的 avg-entry 与 realized 语义（realized 在 simulator 级累积，close 后不丢失）；rejected fill 零状态变更；`accrue_financing` 扣减 cash；`trade_log` 记录每笔 closed/partial-close 交易；NAV = cash + Σ(units×mid)（M12-W05 修正 M12-W03 遗留的 cash+unrealized 重复扣减 bug）；closed 类别的 realized PnL 仍出现在 category attribution（REQ-STRAT-004） |
| `alphabrief_backtest/reporting` | research-grade reproducible portfolio reports | M12-W05 起：`build_portfolio_report` 为纯函数——`ReportMetrics` 全 11 指标（return/volatility/Sharpe/Sortino/Calmar/max drawdown/turnover/exposure/hit rate/profit factor/tail loss，退化输入 → None 或真值 0，绝不 NaN/inf）；instrument 与 category `AttributionRow`（realized/unrealized/contribution，与 portfolio totals 对账）；`CostAttribution`（spread/slippage/fee/financing）；`RejectionAttribution`（按显式 reason 计数 + rejected notional）；benchmark delta 与 IS/OOS/FULL label；`normalized_json` 同输入同字节（REQ-STRAT-005） |
| `alphabrief_backtest/leakage` | automated data-leakage and lookahead gates | M12-W06 起：五个纯函数 gate 全 fail-closed——`check_chronological_bars`（timestamp_boundary：非严格递增 → fail）、`check_declared_data_version`（revised_future_data：任何 bar 携带非声明版本 → fail）、`check_trailing_features_lookahead`（seeded_lookahead：对每 bar 用 bars[:i+1] 重算 trailing features 并与提供值比对，任一不符 → fail）、`check_train_test_disjoint`（train_test_overlap：共享时间戳或 test 不晚于 train 结束 → fail）、`check_signals_within_bars`（target_leakage：signal 时间戳必须属于 bar 时间线）；`run_leakage_gates` 聚合 verdicts（REQ-STRAT-006） |
| `alphabrief_backtest/overfitting` | parameter-stability and overfitting audit | M12-W06 起：`perturbation_stability`（grid return spread）+ `best_margin`（best vs median）+ `subperiod_stability`（CV，量化 1e-12）+ `multiple_testing_warning`（>20 trials）+ `walk_forward_warning`（与 W04 overfit_flag 同语义）；`run_overfitting_audit` 输出 `StabilityMetric` 与显式 `OverfitWarning`，退化输入 → None 绝不误导（REQ-STRAT-006） |
| `alphabrief_backtest/evaluation` | reproducible IS/OOS walk-forward evaluation | M12-W04 起：`run_walk_forward_evaluation` 支持 rolling/anchored 双模式（`WindowSpec` 强制 step≥oos 保证决策边界不重叠）；`_fit_parameters` 只在声明的 IS slice 上按 IS total_return 确定性选参（tie 取 grid 序），`FittedParameters` 记录 strategy/version/family/data version/IS 边界/参数/算法版本；OOS 以 frozen parameters 只跑自身 slice（无 lookahead、无 later revision）；全 bar 校验声明 data version，未声明版本 fail-closed；`run_id`=sha256(策略/数据版本/costs/seed/window/grid/bar fingerprint)，同输入 → 同 run_id 与同 normalized result（REQ-STRAT-003、REQ-PLAT-009）；benchmark 复用 `BacktestReport.metrics.benchmark_total_return` |
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
- brief/research 某些 API 默认 FakeProvider（advisory demo 面；M10-W01 起 trading/committee 生产组合不再有任何 fake fallback）。
- ModelGateway 调用记录主要在进程内（M10-W02 处理 durable call records）；provider selection/fallback 已 fail-closed（M10-W01）。
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

AI trading provider 组合（`alphabrief_trader.model_factory`）fail-closed：
`auto`/未配置且无 `OPENAI_API_KEY` 时抛出 `ModelProviderUnavailableError`，
绝不静默回退到 fake；fake provider 只能通过显式
`ALPHABRIEF_AI_MODEL_PROVIDER=fake` 选择（测试组合）。API `/ai/run` 在 provider
缺失时持久化 outcome=`skipped_no_intent`、summary 说明原因的 no-trade cycle
record；模型评测 API/CLI 默认走配置的真实 provider，未配置时 503/非零退出，
`use_real_provider=false`/`--no-real-provider` 才是显式 fake 组合。

每个 terminal ModelGateway 调用（success/malformed/timeout/rate_limit/
provider_error/budget_exhausted/no_provider）生成唯一 `ModelCallRecord`：
request/response hash、prompt version、provider/model 参数、latency、token
counts、cost（Decimal）、retry count、schema verdict、cycle_key/snapshot_id
correlation 与 UTC 时间戳；记录不含 raw prompt、raw response、token 或 secret。
`ModelCallBudget` 按 request_id/cycle_key/UTC 日确定性拒绝超额调用（被拒调用
不消耗额度、不修改已提交证据）。`ModelCallStore`（DuckDB append-only、
call_id 幂等）通过 gateway `record_sink` 持久化；API `/ai/run` 已接入
（`routes/ai_trading.py`），CLI/scheduler 的 sink 接线随其所属 scope 轮次补齐。
表 DDL 为 store 本地幂等 `CREATE TABLE IF NOT EXISTS`
（`db/schema.py` 版本化迁移 ledger 在 storage scope 外，未来 storage 轮以同名
`IF NOT EXISTS` 迁移接管，见 `db/model_call.py` 注释）。

AI 委员会（M10-W03）是有界多轮讨论：五个角色（technical、news_sentiment、
fundamental、risk 四名分析师 + manager moderator）各一个 opening turn，每个
分析师一个 challenge turn（可质疑前置论断并记录 stance：
agreement/contradiction/dissent/unknown + challenged_claim），moderator 一个
summary turn；总轮次由 `max_turns` 有界。每次 turn 记录 role identity、UTC
时间戳、model-call ID 与 cited evidence IDs（仅引用 CommitteeInput 提供的
evidence_ids）。完整 `CommitteeTranscript` 保留 agreement/contradiction/
dissent/unknown 与引用证据，不扁平化为单一答案；plan 仍只由 opening votes 经
确定性 `DisciplineGate` 综合。Committee 上下文卫生：外部 news/macro context
经 `alphabrief_news.untrusted.sanitize_external_text` 消毒（bounded、
instruction-neutralized、untrusted marked），整条 prompt 再经
`_scrub_secrets` 二次脱敏（token/API key/OANDA account ID）；prompt 不含
privileged tools、可变系统设置或未消毒外部指令。注意：`/ai/rules` 等展示面
仍返回旧四角色列表（被 allowlist 外测试钉住，M13 对齐）。

委员会输出经 `alphabrief_trader.proposal`（M10-W04）转换为严格
evidence-grounded `ResearchProposal`：thesis、anti-thesis、confidence、
horizon、entry rationale、invalidation、suggested exposure、citations、
dissent、data freshness、uncertainty 与显式 `no_trade`。每条 citation 必须
解析到 committee 所用 snapshot 的 evidence_ids（builder 只发射受支持 ID）；
`validate_proposal_grounding` 拒绝 unsupported citation、stale critical
evidence（默认 86400s）、contradictory exposure（schema 层 no_trade⟺零仓位
已拒绝）与 missing dissent——任何 violation 的 proposal 不可执行，不产生
OrderIntent；无 plan 时 builder 保守输出 no_trade。proposal 是 advisory
evidence，最终仍需 RiskGate 批准才可提交。

结构化输出修复（M10-W05）：`alphabrief_models.repair.repair_structured_output`
在 invalid JSON / schema violation / nonexistent citation（`ev-` 前缀不在
snapshot evidence_ids）时经 ModelGateway 有界重问（`max_attempts`，默认 2），
每次 attempt 记录 typed `RepairVerdict`（attempt、ok、error_code、
model_call_id、UTC 时间戳）且每次调用经 gateway `record_sink` 持久化；
repair 耗尽/超时/budget 耗尽 → 单一 durable blocked/no-trade（cycle 层
`provider_error` 或 `skipped_no_intent` 记录，零 OrderIntent）。
Committee 幂等（REQ-AI-009）：`DailyTradingCycle.run(cycle_key=...)` 先计算
确定性 snapshot fingerprint（symbol/data_version/captured_at/reference
price/returns/volume/受限 news+macro 的 sha256），同 (cycle_key, fingerprint)
已存在 terminal record 时直接返回既有结果——不重复 committee run、不产生新
proposal/intent；API `/ai/run` 使用 `api:<date>:<sorted symbols>` 作为
cycle key（同日同 universe 幂等，snapshot 变化仍产生新 run）。cycle_key 与
fingerprint 存入 `cycle_json`（`get_cycle_by_key` 经 DuckDB JSON 提取，无需
schema 迁移）。

安全与质量门禁（M10-W06）：`alphabrief_trader.security_eval` 用 versioned
fixtures（control + injection + fabricated_citation + secret_exfiltration +
unauthorized_tool_call）评估 committee 流水线——adversarial 种类必须产生
**零 executable proposals**（proposal 必须 grounded 且 no_trade，或不存在）；
每次 case 记录 latency、committee outcome、role/repair 计数、grounding
violations、prompt 卫生（untrusted instruction 未中和 / secret 泄漏）与
repeat-run stability（同一 pipeline 两次运行 normalized proposal 完全一致，
proposal_id 确定性生成）。`alphabrief_models.quality_gate` 对 schema/
grounding/citation/hallucination/injection/latency/cost/stability 指标按
配置阈值做合取判定：任一指标低于阈值 → gate FAIL；**无 waiver 参数**——
失败无法被转换为通过。fixture 与 model-profile IDs 绑定在每次 evaluation
输出上。

持久化日循环状态机（M11-W01）：`alphabrief_trader.cycle_state` +
`CycleStateStore`（`cycle_state` 当前投影 + `cycle_state_transitions`
append-only 事实表，同一事务提交）以 compare-and-set 覆盖每日循环全部阶段：
preflight → ingest → snapshot → discuss → propose → risk → execute（或
no-trade，outcome 记录 executed/no_trade/blocked）→ reconcile → report →
complete。每条 transition 原子记录 input hashes、output IDs、attempt count、
prior phase 与 UTC 时间戳；stale writer（expected phase 不匹配）与非单调
advance 被拒绝且不产生任何 mutation（DuckDB 无 UPDATE rowcount，CAS 效果以
提交后重读验证）。`DurableDailyCycle` 把每日循环的 side effects 按阶段驱动：
每阶段 side effect 完成后才提交离开 transition，因此 restart 从最后已提交
gate 的下一阶段恢复，**已完成 side effect（尤其 broker 提交）永不重复**；
每阶段 artifacts（votes/plans/attempts/outcome）落在 committed transition
rows 中，report 阶段从 durable facts 重建完整 `DailyCycleRecord`（任意次
restart 后仍完整）。begin 亦记录初始 transition（prior=None），使每个阶段
都有审计行。API `/ai/run` 仍用 one-shot `DailyTradingCycle`（M11-W02/W03
在 scheduler/leader 轮次接入 durable cycle）。

Scheduler 单领导者与运行时真相（M11-W02）：`SchedulerLeaderLease`
（`scheduler_lease` 表）提供可续期持久 lease——同一 store 上两个 scheduler
进程恰好一个活跃 leader（acquire CAS：未过期 lease 归属他人时失败）；只有
当前 holder 能在过期前续期（renew 校验 expiry 实际延长），lease 过期/丢失后
former leader 的续期与 is_leader 全部失败，新 leader 才能在过期后接管——因此
former leader 在新 leader 接管前无法启动另一阶段或 broker 提交。
`RuntimeTruthStore`（`scheduler_runtime` 单行）持久化 active config、
leader ID、running phase、heartbeat、last outcome 与 next due time；
API `GET /api/v1/scheduler/status` 与 CLI `scheduler status` 均从同一
persisted authority 读取这些字段（无 runtime 时返回 None/{}），保证所有
展示面反映同一执行运行时。scheduler 进程的 lease 循环接线随 M11-W03/
W05 轮次补齐。

研究与执行解耦（M11-W03）：`ExecutionGate`（`alphabrief_trader/execution_gate.py`）
对注入的 `PreflightFacts` 做确定性判定，输出恰好一个机器可读 mode——
`executable` / `execution_disabled`（trading 未启用）/ `research_only` /
`blocked`（kill switch、missing credentials、stale account truth、
reconciliation failed、stale data、backup failed、unhealthy model 任一）+
稳定 reasons。mode 经 `RuntimeTruthStore.set_execution_mode` 持久化（
`execution_mode` 表），也记录在 `DurableDailyCycle` preflight transition 的
output_ids。`DurableDailyCycle` 的 preflight 阶段评估 gate，discuss/propose/
report 等研究阶段**始终运行**（frozen/disabled/broker-unready 也完成
ingest/snapshot/committee/report）；execute 阶段仅在 mode==executable 时
提交，否则以 outcome=blocked 与 gate reasons 记录并零 broker 调用——
preflight 在真实外部下单前验证配置/凭证/账户/数据/模型/backup/kill switch
（REQ-OPS-007）。默认 facts provider fail-closed（仅 env 凭证与 kill switch
可证明，其余默认 False）。

每日候选选择（M11-W04）：`DailyCandidateSelector`（
`alphabrief_trader/candidate_selection.py`）从完整 OANDA catalogue 确定性
选择 category-aware 日分析集——按 (category, symbol) 排序逐品种应用八条规则
（catalogue_status、category、quote_freshness、tradeability、spread、
liquidity、data_quality、news_relevance）+ 六项 budget 规则（instrument、
per-category、model-call、token、cost、concurrency），**selected 与 skipped
都记录完整 rule-result 集合与 selection_reason**；累计 usage（counts/calls/
tokens/cost，Decimal）永不超限；等价输入产生相同有序候选集，完整 catalogue
在分析集之外仍可查询（verdicts 覆盖全部品种）。候选集与 cycle 的接线随
M11-W05 轮次补齐。

Catch-up 与 terminal no-trade（M11-W05）：`daily_cycle_key(trading_date,
snapshot_key)` 生成确定性日键（`DurableDailyCycle.run(cycle_key=...)` 已保证
同日同 snapshot 幂等——返回既有 terminal record，不重复 committee/proposal/
intent/order）。`CatchUpPolicy`（注入 clock）判定错过排程：`on_time` /
`within_catchup_window`（窗口内允许补跑）/ `expired_without_chase`（窗口关闭
后记录该 terminal outcome 且**不追单**——研究阶段全部短路、零 broker 调用）。
报告阶段输出结构化 terminal outcome 与 reason（no_trade / risk_rejection /
market_closed（PreflightFacts.market_open）/ stale_data / blocked /
insufficient_evidence / budget_exhaustion），evidence 保留在 durable record
的 votes 中；`CycleOutcome` 新增 `expired_without_chase`。所有 no-trade 类
outcome 都是 durable successful terminal（成功完成 cycle，非失败）。

执行链与即时对账（M11-W06）：`DurableDailyCycle` execute 阶段构建完整
`CorrelationChain`（cycle_id → proposal_ids → intent_ids（确定性派生）→
risk decision_ids → client_order_ids → broker_order_ids）并持久化在 execute
transition 的 `correlation_chain`；仅当 proposal、OrderIntent、broker-fresh
inputs、immutable RiskDecision、execution enablement 与 `IdempotencyMap`
（`cycle_idempotency` 表，check-and-insert）共享同一链时才 submit——
**at-most-once**（restart 复用既有映射，零重复提交）。approved / risk
rejected（0 submit）/ no-trade（0 submit）/ broker-rejected（1 submit +
`error` terminal）fixtures 各产生正确 terminal state。`_phase_reconcile` 在
report 之前对每次 broker outcome 运行注入的 reconciler，把
`ReconciliationEvidence`（attempt/order ids/matched/account snapshot）
持久化在 reconcile transition——对账证据先于 report 完成落库。

每日证据与报告（M11-W07）：`build_cycle_report`（`cycle_report.py`）仅从
immutable transition IDs 构建 `DailyCycleReport`——daily brief、transcript
（或 legal skip：`transcript_skip_reason`）、proposal 或 no_trade（含
reasons）、decision chain、broker outcome、reconciliation、portfolio
snapshot、alerts 与 data-quality summary，`report_id` = normalized content
hash（排除 build-time 的 report_id/created_at）；**rebuild 从相同 IDs 产生
byte-equivalent normalized content 且 report_id 不变**——新证据无法替换旧
report（frozen report 不受后续 cycle 影响）。`RuntimeTruthStore` 扩展
`phase_started_at` 与 `failure_classification`；API `/status` 与 CLI
`scheduler status` 暴露同一组 persisted runtime 字段（cycle outcome、phase
timestamps、heartbeat、failure classification、last run、next due）。

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
| `alphabrief_risk/exposure_aggregation` | home-currency exposure aggregation + limits | M08-W03 起：`compute_exposure` 以 evidence 输入（positions long/short 双腿、pending orders、per-symbol mid price、quote→home conversion factor、category、currency-direction、correlation groups、equity）计算 pre/post gross/net、symbol/category/currency-direction/correlated-group totals、concentration、leverage——全部在 account home currency，Decimal-safe；缺/stale/zero/inconsistent/unsupported 任一 evidence → 分类 `ExposureError` fail-closed（missing_price/missing_conversion/stale_conversion/invalid_conversion/missing_category/missing_currency_direction/unsupported_correlation），绝不 fallback nominal units 或 cost basis；`evaluate_exposure_limits` 对 projected post-trade snapshot 求值 single-order/symbol/category/direction/gross/net/leverage/concentration 8 类 limit，产出稳定 typed `ExposureRuleResult` |
| `alphabrief_risk/margin_loss_rules` | margin/leverage/loss/drawdown/loss-streak rules | M08-W04 起：`evaluate_margin_loss_rules` 对 broker-fresh margin evidence（margin_used/available/nav/projected_leverage + freshness）与 durable daily loss（day-start vs equity_now，realized+unrealized 均折入）、rolling drawdown（窗口 peak-vs-current）、HWM drawdown、consecutive-loss streak 逐条产出稳定 typed `MarginLossRuleResult`；missing/stale 任一 evidence → fail-closed，绝不静默禁用已配置 rule（AC-M08-W04-03） |
| `alphabrief_risk/loss_state` | durable forward-only loss state | M08-W04 起：DuckDB `LossStateStore` 的 `record_day_result` 以 CAS 语义维护 HWM（只升不降）、day-start（per-date first-write-wins）与 loss streak（亏损日+1、盈利/持平日归零，evidence-backed）；值 survive restart，无 API 能直接写回放宽 limit（AC-M08-W04-02） |
| `alphabrief_risk/market_conditions` | tighten-only spread/liquidity/news/macro rules | M08-W05 起：`evaluate_market_conditions` 对 spread absolute/relative、quoted liquidity、projected slippage、high-impact event window（symbol/currency/category 命中，reject 或 clamp policy）、sentiment freshness/coverage/disagreement/uncertainty/severity 逐条产出稳定 typed `MarketRuleResult` 并合成 `MarketConditionVerdict`（size_multiplier ∈ [0,1] 恒 tighten-only，reject=0）；evidence 模型只有结构化 typed facts（无 narrative/text/confidence 字段）——外部文本不可能增大 size、放宽 rule 或修改阈值（AC-M08-W05-02）；critical market evidence 缺失 → reject，content evidence 缺失/过期 → conservative clamp（0.5），绝不伪造 neutral score 或禁用 rule（AC-M08-W05-03） |
| `alphabrief_risk/operational_blocks` | operational health blocks | M08-W06 起：`evaluate_operational_blocks` 对 kill switch/freeze/stale broker/reconciliation diff/transaction gap/backup failure/writer lease/scheduler health 8 个 condition 产出 distinct typed `OperationalBlockResult`；`require_evidence` 缺失 → fail-closed，未要求项缺失 → unverified（绝不伪造健康）；`OperationalBlockStore` 按 condition 持久化最新 verdict（DuckDB，append-only、restart-safe） |
| `alphabrief_risk/reduce_only` | reduce-only and close validation | M08-W06 起：`validate_reduce_only` 仅当 position truth 新鲜、identity/instrument/price/audit preconditions 全真、方向正确、不过量、无 exposure-increasing dependent order、且 post-gross 可证明小于 pre-gross 时 permitted（REQ-RISK-008）；side reversal/over-close/stale/missing truth 全部 fail-closed，reduce-only 不可作 bypass（AC-M08-W06-03） |
| `alphabrief_risk/decision_store` | immutable persisted RiskDecisions | M08-W07 起：`RiskDecisionStore` append-only 持久化每笔 decision（immutable rule order、inputs/policy hashes、source IDs、timestamps、approved、max quantity、reasons、tags、context freshness、expiry）；duplicate persist 忽略（first-write-wins），consume 为 CAS（恰好一次），无任何更新/覆盖 API（REQ-RISK-009） |
| `alphabrief_risk/decision_binding` | decision-binding service (execution contract) | M08-W07 起：`DecisionBindingService.persist_decision` + `validate_before_submit` 是 AI external backend 与 manual paper route 共用的唯一可执行契约——missing/rejected/expired/consumed/account-/policy-/intent-/inputs-/snapshot-mismatch/quantity-exceeding/stale-context 全部分类拒绝（REQ-RISK-010）；`hash_inputs(symbol, units, price)`/`hash_policy` 共享确定性；backend 从不信任 caller 的 approved boolean，只认 persisted record（AC-M08-W07-03） |
| M08 里程碑 | complete deterministic risk chain | W01-W07 全部落地（broker-fresh context/instrument constraints/home-currency exposure aggregation/margin+loss rules/market tightening/operational blocks+reduce-only/decision binding+store）；W08 聚合证明通过——REQ-RISK-001..010 全矩阵 + SAFE-005/006 + AI/manual 路径 parity + 缺凭证 fail-closed；T7 practice risk-chain E2E evidence PENDING（CODE_COMPLETE，M09 继承 external_evidence_pending） |
| `alphabrief_news/ingestion` | news ingestion + provenance contracts | M09-W01 起：`NewsIngestionService.fetch_and_ingest` 对 success/empty/timeout/rate_limit/malformed/source_failure 产出 distinct durable outcomes（失败零伪造 headlines）；`IngestedNewsItem` 持久化 source/canonical URL/published+fetched UTC/language/content hash/bounded summary/outcome/correlation id（REQ-NEWS-001、REQ-PLAT-009）；`SourceLicensePolicy(metadata_only)` 保证版权受限源只存 metadata+短摘要、永不持久化全文（REQ-NEWS-008）；`NewsIngestionStore` DuckDB append-only、duplicate 幂等 |
| `alphabrief_news/dedup` | deterministic news deduplication | M09-W02 起：`canonicalize_url`（剥离 tracking/fragment、归一 host/scheme/port/斜杠）；`dedup_verdict` 三规则——canonical_url/content_hash/（title_similarity≥0.85 且同 source 且同 claims 且 gap≤1h）；title 相似但 claims 不同永不合并（REQ-NEWS-002）；`cluster_news` 输入序稳定输出 canonical clusters（rule_version 审计） |
| `alphabrief_news/entity_linking` | deterministic entity linking | M09-W02 起：`link_entities` 以 symbol→instrument（confidence 1.0）与 dictionary alias→currency/country/company/asset_class/market（confidence 0.8）产出 `EntityLink`（type/normalized identifier/rule_version/confidence/evidence_id），大小写不敏感、完全确定性（REQ-NEWS-003） |
| `alphabrief_news/macro_release` | revision-aware macro calendar store | M09-W03 起：`MacroRelease`（release_time/actual/forecast/previous/revision/importance/unit/source/affected currencies+markets，全 UTC、Decimal-only）与 `MacroReleaseStore`（DuckDB append-only、(release_id, version) PK）；`revise` 追加带 lineage 的新版本、prior 值可重建（REQ-NEWS-004）；`release_state` 显式五态（fresh/partial/stale/revised/missing）；API `GET /api/v1/macro/releases` + `POST .../revise` 与 CLI `macro releases` 读同一 store 输出 identical 有序事件（REQ-PLAT-009） |
| `alphabrief_news/sentiment_aggregate` | explainable multi-scope sentiment aggregation | M09-W04 起：`aggregate_sentiment` 对 market/asset_class/currency/country/company/instrument 各 scope 产出 `SentimentAggregate`（direction/intensity/disagreement/sample_count/source_coverage/freshness/uncertainty/evidence_ids/algorithm_version/snapshot_hash）；输入先按 (scope, scope_value, evidence_id) 排序——重排 byte-equivalent、snapshot hash 相同（AC-M09-W04-02）；sparse/single-source/stale/contradictory → 显式 insufficient-coverage（uncertainty≥0.75）或 mixed，绝不 confident default（REQ-NEWS-005） |
| `alphabrief_news/untrusted` | untrusted external content sanitization | M09-W05 起：`sanitize_external_text` 给每条外部文本打 untrusted marker、source identity、content hash 与 bounded sanitized representation（REQ-NEWS-006）；`_INSTRUCTION_PATTERNS` 确定性中和 prompt-injection 语法（替换为 NEUTRALIZED 标记并计数），system/risk/tool 指令不可改变任何系统边界（REQ-AI-008）；`_SECRET_PATTERNS` 红action token/Authorization/account ID，`build_sanitization_log` 只留 hash+counts（REQ-OPS-002） |
| `alphabrief_news/regime_snapshot` | immutable daily regime + sentiment snapshot | M09-W06 起：`build_regime_snapshot` 把 news/macro/sentiment/entity-link/quality/freshness/source-version IDs 绑定到一个 immutable `RegimeSnapshot`（version_id==snapshot_id、content_hash、algorithm_version）；`DegradationPolicy(critical_sources, critical_input_kinds)` 决定 healthy/degraded/blocked——关键源或关键 kind stale → blocked、非关键失败 → degraded、missing 只记 reason 绝不合成事实（REQ-NEWS-007/009）；`RegimeSnapshotStore` 是 research 与 risk 共享的 snapshot authority（同 ID → identical evidence，REQ-PLAT-009、REQ-RISK-005） |
