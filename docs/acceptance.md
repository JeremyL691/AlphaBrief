# AlphaBrief Acceptance and Traceability Contract

版本：2026-08-13.1
原则：验收证明可观察行为，不证明收益。所有 required acceptance 均不允许 waiver。

## 1. Evidence Hierarchy

从弱到强：

```text
E0 prose/design claim                         # 不能验收
E1 static source/config inspection            # 只证明结构
E2 deterministic unit/property test           # 证明局部逻辑
E3 integration/contract/fault-injection test  # 证明本地组合
E4 full repository quality/negative gate      # 证明回归边界
E5 controlled OANDA practice E2E              # 证明外部 practice contract
E6 real calendar-day observation evidence     # 证明连续运行
```

高层 acceptance 不能由低于声明等级的 evidence 替代。Mock OANDA 最多 E3；文档写着
“已完成”仍然只是 E0。

每份 evidence 至少包含：

- evidence ID；
- work item/requirement/acceptance IDs；
- exact command/scenario；
- UTC start/end；
- exit code/outcome；
- passed/failed/skipped counts（适用时）；
- frozen commit/config/schema versions；
- scrubbed artifact path and SHA-256；
- external account/build correlation hash（E5/E6）；
- expiry/revalidation rule。

## 2. Global Safety Acceptance

这些 gate 在 M01 后每个 execution-related milestone 和最终验收都必须 PASS：

| Gate ID | Predicate | Minimum evidence |
|---|---|---|
| SAFE-001 | production graph 没有 Alpaca、other broker 或 simulated fallback | E4 static graph/import/config scan + composition test |
| SAFE-002 | production execution 只可连接 OANDA practice REST/stream constants | E4 negative host tests + network allowlist scan |
| SAFE-003 | live host/mode/account selector 不可配置、不可达 | E4 mutation/negative tests |
| SAFE-004 | 缺 OANDA credentials fail closed 且不会本地假成交 | E3 end-to-end composition test |
| SAFE-005 | 每个 external order 有 persisted approved RiskDecision | E3 ledger invariant + E5 practice chain |
| SAFE-006 | rejected/stale/missing/mismatched decision 无 submit path | E3 property/integration negative tests |
| SAFE-007 | AI/news/web content 不能直接调用 broker 或改变 policy | E4 prompt-injection/tool boundary suite |
| SAFE-008 | provider calls 只经过 ModelGateway | E4 import/call graph gate |
| SAFE-009 | tracked files/log artifacts 无 secrets/完整 account ID | E4 secret/scrub scan |
| SAFE-010 | runtime code 不 import/copy `_reference_sources` | E4 import/path/similarity policy gate |
| SAFE-011 | retry/restart 不重复 external order | E3 fault injection + E5 controlled practice |
| SAFE-012 | `no_trade` 可正常完成，不存在 activity quota 强迫下单 | E3 cycle behavior tests |

任一 SAFE gate FAIL 时项目不能进入 OBSERVING。

## 3. Quality Gate Commands

当前仓库基础命令：

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/alphabrief acceptance verify --compact
```

M02 controller 必须保存真实 exit code 和 artifact hash。Milestone 可以增加命令，不能
通过删目录、`-k` 排除失败、永久 skip、ignore 或降低配置取代基础门禁。

Local sandbox 若禁止 localhost bind，结果只能标 `ENVIRONMENT_BLOCKED`，并在允许
loopback 的隔离环境复验；不能把 12 个 HTTP tests 删除或永久跳过。

## 4. Requirement Ownership Matrix

需求正文在蓝图第 5 节。每个 requirement 必须在 `docs/work_items.yaml` 的至少一个
required item 出现，并在完成时有 acceptance evidence。

| Requirement range | Primary milestone | Required evidence focus |
|---|---|---|
| REQ-PLAT-001..003 | M01/M03 | strict config、practice lock、secret boundary |
| REQ-PLAT-004..009 | M03 | migrations、atomicity、writer、backup、UTC、correlation |
| REQ-OANDA-001..005 | M04 | account/instrument discovery、taxonomy、catalog UI/API |
| REQ-OANDA-006..011 | M05 | candles/pricing/stream、quality、sessions、immutable lineage |
| REQ-NEWS-001..009 | M09 | provenance、dedupe、macro、sentiment、untrusted content |
| REQ-AI-001..010 | M10 | ModelGateway、durability、committee、citations、injection |
| REQ-STRAT-001..008 | M12 | safe DSL、portfolio/walk-forward、costs、leakage |
| REQ-RISK-001..010 | M08 | full account context、exposure、loss、news、persisted decision |
| REQ-EXEC-001..004 | M06 | official order/trade/position lifecycle |
| REQ-EXEC-005..012 | M06/M07 | idempotency、transactions、reconciliation、restart、telemetry |
| REQ-CYCLE-001..010 | M11 | persistent cycle、leader、candidate budget、scheduler truth |
| REQ-UI-001..002 | M13 | API/CLI contracts and safe writes |
| REQ-UI-003..010 | M14 | Soft UI、all states、trace、a11y、Electron、controls |
| REQ-OPS-001..008 | M15 | logs、alerts、scrub、timeouts、recovery、preflight、security |
| REQ-OBS-001..007 | M16/M17 | real 30 days and evidence-derived final report |

Work queue topology validator 必须检测遗漏和重复但冲突的 requirement ownership。

## 5. Milestone Gates

### M00 Documentation Authority

| AC | Predicate | Evidence |
|---|---|---|
| AC-M00-01 | 旧 Phase/Round/duplicated docs 不在工作树 | file manifest/static test |
| AC-M00-02 | 新权威 Markdown links 不断链，YAML/NDJSON 可解析 | doc link + parser tests |
| AC-M00-03 | acceptance/scaffold 只要求新文档和 OANDA preflight contract | targeted tests |
| AC-M00-04 | progress 明确 current routed/Alpaca truth 未完成迁移 | schema + content assertion |
| AC-M00-05 | business trading behavior 未被本轮修改 | changed-path scope gate |

### M01 OANDA-Only Cutover

- Alpaca/routing/sim fallback production references exactly zero；
- only practice host constants；
- missing/invalid credentials and account fail closed；
- API/CLI/scheduler share OANDA runtime；
- no fake external execution；
- full regression + SAFE-001..004。

#### M01-W01 已闭环证据（R-20260813-M01-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M01-W01-01 | PaperExecutionPolicy 只接受 provider oanda_paper 和 OANDA-account market boundary | schema Literal 收窄（`oanda_paper`；market 移除 `us_equity`）+ mutation tests（`routed`/`alpaca_paper`/`us_equity` 均被拒绝） |
| AC-M01-W01-02 | 生产配置不能选择 live host、other broker、routed mode 或 simulated fallback | `alphabrief_execution.broker.safety.production_boundary_violations` 正向门禁（policy mode/provider、oanda base_url 常量、settings live 默认关、selector-line 扫描）+ 6 组 mutation 用例 |
| AC-M01-W01-03 | 缺凭证 fail closed 且不生成订单/成交 | 无凭证时 `OandaHttpClient` 构造抛 `BrokerAuthError`；API 工厂解析为 `_NullBrokerAdapter`，`submit` 抛 `NotImplementedError`；scheduler external cycle 无凭证拒绝运行 |

范围说明：本 item 对已声明全仓 gates（mypy strict、full pytest）的强制涟漪做了两处最小测试更新，
语义不变：(1) `tests/test_risk_account_rules.py` 的 venue-agnostic session fixture 值改为
`oanda_paper`/`multi_asset`（原值已不可能存在）；(2) `tests/test_ai_trader_scheduler.py`
的 policy/provider mismatch 用例改写为“OANDA policy 缺 OANDA 凭证 fail closed”
（mismatch 场景在 OANDA-only 下不再可表达）。`apps/cli/.../scheduler_commands.py` 中
`provider == "routed"` 死分支随字面量收窄删除（mypy 强制，行为不变）。

#### M01-W02 已闭环证据（R-20260813-M01-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M01-W02-01 | Alpaca package、YAML、credential variables、imports、exports、scripts、dedicated helpers 全部 absent | 删除 `broker/alpaca/`（4 文件）、`config/alpaca_paper.yaml`、`tests/test_alpaca_adapter.py`、`tests/_helpers/mock_alpaca_server.py`；`.env.example` 移除 ALPACA_KEY/SECRET contract；全仓扫描仅剩 verifier 的 SDK denylist guard 与 negative-gate mutation fixture |
| AC-M01-W02-02 | execution package imports 与 public API 无 Alpaca surface | `alphabrief_execution/__init__` exports 清理；`routing.py` 移除 alpaca venue/param/branch；API/CLI factory 移除 alpaca 构造；mypy/ruff 全绿 |
| AC-M01-W02-03 | 删测试不降低 broker-neutral/OANDA 覆盖，等价 invariant 由替代测试承担 | API live-path invariants（live parse、503 mapping、null shapes、recon routes 不变）改用 `MockOandaServer` 重写；singleton selection/reset、routing delegation/simulated degrade 用例保留；full pytest 1404 passed（删除 13 个 alpaca 测试，无断言弱化） |

范围说明：`tests/test_alpaca_adapter.py` 与 `.env.example` 不在 core_execution allowlist globs 内，
但分别是 AC-M01-W02-01 的强制删除目标与强制 credential-contract 清理，作为文档化的 forced paths
纳入本 round（其余 changed paths 全部在 allowlist 内）。routing composition 与 simulated fallback
本身仍存在，属 M01-W03 删除范围。

#### M01-W03 已闭环证据（R-20260813-M01-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M01-W03-01 | production dependency graphs 不能实例化 routing 或 in-memory broker adapter | 删除 `broker/routing.py`（RoutingBrokerAdapter/SimulatedBrokerAdapter/route_symbol_to_venue）；AST scan 证明 apps/packages 无 `broker.routing` import；`test_broker_routing.py` 重写为 absence/negative-gate 文件 |
| AC-M01-W03-02 | 未配置的 broker runtime 报告 not ready 且不能 submit | API 与 CLI 的 null adapter `health.healthy=False`（"broker runtime not configured"），`submit` 抛 `NotImplementedError`；API/CLI 两侧均有 automated test |
| AC-M01-W03-03 | test fakes 需要显式 test composition root 且生产 settings 不可达 | `_FakeAdapter`（test_ai_trader_execution_backend.py）、`MockOandaServer`（tests/_helpers）均在测试边界；AST scan 证明 production 模块不 import `tests`/`_helpers`；`_build_adapter` 有凭证时仅返回 `OandaPaperAdapter` |

范围说明：本 round 无 allowlist 外路径。`LocalPaperExecutionBackend` 是显式 local paper
mode（operator 选择），不是缺凭证回退，保持不动；full pytest 1392 passed（routing 原 12
个测试由 5 个 negative-gate 测试替代，无断言弱化）。

#### M01-W04 已闭环证据（R-20260813-M01-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M01-W04-01 | API lifespan、CLI broker commands、scheduler 解析同一个 runtime factory 和 persistent data directory authority | 新增 `alphabrief_execution.broker.runtime`（`BrokerRuntime`/`get_broker_runtime`/`resolve_data_dir`）；API `get_broker_adapter` 与 CLI `_build_adapter` 都委托共享 runtime；`tests/test_broker_commands.py` 覆盖 data-dir authority、offline status/reconcile、process singleton |
| AC-M01-W04-02 | 两个 entry point 不能暴露冲突的 in-memory account state | API adapter 与 scheduler adapter 是同一实例（`is` 断言），idempotency mapping 通过一个 entry point 注册、另一个可见；scheduler 每 cycle 不再新建 adapter |
| AC-M01-W04-03 | shutdown 关闭 OANDA clients 和 stores 且不丢弃 durable mappings | `BrokerRuntime.close()` 先 `flush_idempotency()`（upsert 到 recon store）再关闭 store；测试验证 close 后 mapping 行持久存在 |

范围说明：本 round 无 allowlist 外路径。queue 声明的 targeted 文件 `tests/test_broker_commands.py`
原先不存在，已按 CLI broker commands 真实表面新建（data-dir authority + offline status/reconcile +
invalid-scope + shared runtime 用例）；full pytest 1399 passed（+7 新测试）。durable idempotency
的完整 seeding/cursor 语义属 M07。

#### M01-W05 已闭环证据（R-20260813-M01-W05）— M01 里程碑 gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M01-W05-01 | SAFE-001..004 无 exception/waiver 通过 | `production_safety_violations`（SAFE-001 import scan、SAFE-002 execution-host scan、SAFE-003 config selection）+ 3 组 mutation 用例；SAFE-004 由 fail-closed composition tests 证明（M01-W01 缺凭证测试、M01-W03 not-ready 测试、M01-W04 flush 测试） |
| AC-M01-W05-02 | 全仓 pytest、Ruff、Mypy、acceptance 在 approved environment 通过 | full pytest 1403 passed exit 0；ruff exit 0；mypy 233 files exit 0；`alphabrief acceptance verify` 11/11 exit 0 |
| AC-M01-W05-03 | M01 requirements 映射到 code/evidence，progress 不标记超出现有证明的 runtime capability | 见下方 M01 traceability；progress 中 M01 转 DONE、M02 转 ACTIVE，`current_execution` 仅记录已证明事实（policy oanda_paper、alpaca/simulated absent、discovery/cursor/recon/observation 仍 false） |

#### M01 Requirement Traceability（M01-W01..W05）

| Requirement | 代码/证据 |
|---|---|
| REQ-PLAT-001（schema 校验配置，未知字段失败） | `PaperExecutionPolicy` extra=forbid + `load_paper_execution_policy`（M01-W01）；`tests/test_execution_policy.py` mutation tests |
| REQ-PLAT-002（执行端点只能常量 practice URL） | `PaperProvider` Literal、`OandaPaperConfig` live-host 校验、`production_boundary_violations` base_url 常量断言、SAFE-002 host scan（M01-W01/W05） |
| REQ-PLAT-003（凭证只从 env 读取，输出脱敏） | `read_oanda_credentials`（env-only、缺失抛 BrokerAuthError）；无凭证 fail-closed 测试（M01-W01）；全仓无凭证写入 tracked files |
| REQ-EXEC-010（API/CLI/scheduler 共享 broker runtime authority） | `alphabrief_execution.broker.runtime` 进程级 runtime；API `get_broker_adapter` 与 CLI `_build_adapter` 同一实例（M01-W04 测试） |

范围说明：本 round 无 allowlist 外路径。full pytest 1403 passed（+4 SAFE mutation 用例）。
M01 里程碑全部 5 个 work items DONE；下一个 READY item 为 M02-W01（依赖 M01-W05 ✓）。

#### M02-W01 已闭环证据（R-20260813-M02-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M02-W01-01 | 当前 work_items/progress 在 versioned strict schemas 下解析，未知字段被拒绝 | `alphabrief_acceptance.autonomous_schemas`（全部 frozen + extra=forbid）；`load_work_queue`/`load_progress`/`load_checkpoint`/`load_ledger` 对真实文件解析通过；unknown-field mutation 测试（queue + progress 均被拒） |
| AC-M02-W01-02 | 每个 required work item 解析为完整 immutable execution contract | `resolve_all_execution_contracts` 覆盖全部 112 items；contract 含 resolved allowlist（profile + item additions）、global forbidden paths、untouched modules、static commands、completion defaults；completion_gate override 合并测试 |
| AC-M02-W01-03 | malformed NDJSON、duplicate IDs、missing dependencies、requirement gaps 失败 | `load_ledger` 按行号报错（malformed JSON / schema-invalid）；duplicate work item ID 被拒；unknown dependency 被拒；空 acceptance（gap）与空 predicate 被拒 |

范围说明：本 round 无 allowlist 外路径。full pytest 1417 passed（+14 schema 测试）。

#### M02-W02 已闭环证据（R-20260813-M02-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M02-W02-01 | selection 按 dependency、priority、ID 稳定，且绝不选 blocked dependency | `select_next_work_item`（ACTIVE milestone 内 READY items，deps ∈ {DONE, CODE_COMPLETE}，按 (priority, id) 排序）；重复调用结果一致；unsatisfied dependency 不被选择 |
| AC-M02-W02-02 | BACKLOG->DONE 及其他非法 transition 被拒绝且不 mutate progress | `LEGAL_TRANSITIONS` 显式表（forward/rollback/external-evidence/blocking/repair）；`apply_transition` 冻结输入（frozen schema + 前后 dump 相等断言）；DONE terminal、未知 item 拒绝 |
| AC-M02-W02-03 | milestone/project transition 需要声明 aggregate gates | `milestone_gate_passes`（gate work item + 全部 required items；M15/M16/M17 只接受 DONE）；`project_engineering_ready`（M01..M15 全部 DONE） |

范围说明：本 round 无 allowlist 外路径。full pytest 1429 passed（+12 state machine 测试）。
transition table 已写入 docs/autonomous_loop.md §4.1 附录。

### M02 Loop Controller

- work/progress schema/topology validation；
- illegal transition rejected；
- actual diff outside allowlist rejected；
- commands use real exit codes and hashed artifacts；
- acceptance frozen during round；
- gate-modifying item cannot self-certify；
- dirty-user-change and compaction recovery tests；
- commit trailer/ledger integration；
- failure ceilings terminate loops。

### M03 Storage and Recovery

- empty install/current migration/repeated migration pass；
- immutable data versions and lineage；
- atomic cycle/risk/order/cursor transitions under injected crash；
- concurrent writer conflict safe；
- backup checksum + isolated restore drill；
- projection rebuild equals stored current view。

### M04 Account and Instrument Catalog

- configured practice account validated；
- all `/instruments` fixture/real response rows persisted exactly once per version；
- metadata precision/size/margin/stop fields complete；
- CURRENCY/METAL/CFD subclasses/unknown taxonomy visible；
- delist/change creates history；
- API/CLI counts equal store and account response；
- E5 contract evidence for configured account。

### M05 Market Data

- official granularity/components/pagination fixtures；
- no incomplete candle in completed decision snapshot；
- bid/ask/spread/liquidity/tradeable/conversion preserved；
- stale/stream gap detected and blocks execution；
- category/session/holiday behavior tested；
- immutable snapshot manifest reproducible；
- rate/connection budgets tested；
- E5 quote/candle evidence across every returned OANDA type and available category。

### M06 OANDA Lifecycle

- signed units buy/sell property tests；
- supported order types/TIF/dependent orders exact request/response contracts；
- no silent DAY/TIF conversion；
- unit/price/distance precision per instrument；
- fill/cancel/reject/reissue/partial/expire transitions；
- trade/position full/partial close；
- error/429/5xx/timeout/unknown outcome；
- paginated list and redacted HTTP metadata；
- controlled E5 minimal lifecycle scenarios。

### M07 Idempotency and Reconciliation

- same cycle 100 replays <= 1 external order；
- transaction cursor monotonic/gap recovery/restart；
- order/fill/trade/position/account/financing projections match fixtures；
- legitimate remote state not falsely mismatched；
- injected unknown/missing/money/position diff freezes；
- restart from every submission transition；
- API reconcile uses real service, no all-match placeholder；
- E5 restart/reconcile proof。

### M08 Risk

- all execution paths require full broker-fresh context；
- instrument precision/min/max/tradeable/freshness gates；
- home-currency gross/net/category/currency/concentration property matrix；
- margin/leverage/daily loss/drawdown/consecutive loss；
- spread/liquidity/news/macro/health/freeze/backup rules；
- reduce-only semantics；
- immutable per-rule decision and input hash；
- backend rejects changed/expired/missing/rejected decision；
- full SAFE-005/006。

### M09 News and Sentiment

- provider cassette reliability/degradation；
- canonical URL/hash/similarity dedupe；
- entity links with confidence；
- macro actual/forecast/revision；
- sentiment direction/strength/disagreement/sample/freshness；
- injection payload cannot change tool/policy behavior；
- stale/coverage failure produces no-trade risk input；
- licensing/retention tests；
- daily snapshot reproducible。

### M10 AI Committee

- production path cannot default FakeProvider；
- durable model call + template/config hash；
- bounded timeout/retry/fallback and no-model no-trade；
- all role turns and dissent persisted；
- schema/citation validation 100% for accepted output；
- invalid output bounded repair then no-trade；
- same cycle key no duplicate executable intent；
- prompt injection/model evaluation suite；
- full SAFE-007/008。

### M11 Daily Cycle

- persisted state machine legal transitions；
- crash/restart at every phase；
- scheduler single leader；
- research continues under execution freeze；
- candidate budget and skip reasons；
- catch-up expiry/no duplicate；
- no-trade/reject/closed/stale normal outcomes；
- immediate reconcile and complete daily report；
- API/CLI tasks/running/last/next identical；
- controlled E5 end-to-end day smoke。

### M12 Strategy and Backtest

- safe DSL cannot execute arbitrary code；
- strategy-family fixtures；
- real IS/OOS and walk-forward exposed in API/CLI；
- portfolio/category/risk/cost semantics；
- spread/slippage/financing/margin/session/reject model；
- metric and attribution golden tests；
- lookahead/leakage/overfit fixtures；
- same version reproducibility；
- no strategy/Gym/Kronos execution bypass。

### M13 API/CLI

- versioned schemas/error envelopes/pagination；
- complete required resources；
- write idempotency/audit；
- no arbitrary broker proxy；
- API/CLI schema parity；
- stale/frozen/partial states；
- OpenAPI snapshot and auth/local boundary decision documented/tested。

### M14 UI/Electron

- owner Soft 5/5/5 audit and tokens；
- all target navigation/pages and trace explorer；
- live server data only, fake/stale/partial/offline explicit；
- 320/768/1024/1440 visual and interaction tests；
- light/dark、keyboard、focus、semantic、contrast、screen reader、reduced motion；
- no emoji icons/em-dash UI copy/filler identities/gradient buttons；
- Electron readiness/port conflict/shutdown/error propagation；
- before/after evidence。

### M15 Engineering Readiness

- full pytest/Ruff/Mypy/acceptance/security all exit 0 in approved environment；
- structured logs/metrics/health/alerts scrubbed；
- rate/timeout/fault/restart/SIGTERM drills；
- daily backup and isolated restore；
- secret/dependency/static safety scans；
- all M01-M15 requirements trace complete；
- controlled OANDA practice E2E cleans up and reconciles；
- Day 0 runbook rehearsal；
- unresolved P0/P1 = 0。

### M16 Observation

Use `docs/oanda_30_day_runbook.md` exact daily/weekly/final predicates. Minimum E6:

```text
30/30 calendar manifests
0 duplicate orders
0 order without approved persisted RiskDecision
0 live/other-broker attempts
0 unexplained cross-day reconciliation diffs
0 unresolved P0/P1
100% broker events mapped/resolved
daily backups + final restore
qualified window not invalidated
```

### M17 Final Acceptance

- every required requirement/work item/milestone PASS；
- current full gates re-run；
- fresh install/start/preflight；
- final backup restore；
- evidence-derived report hashes verify；
- README/blueprint/architecture/runbook truth audit；
- clean main tree and release artifact；
- final state `COMPLETE_PAPER_ONLY`，live remains locked。

## 6. Change and Regression Rules

### 6.1 Test Delta Gate

每轮记录 tests added/deleted/skipped/xfail。默认拒绝：

- 删除覆盖相关行为的 test；
- 增加 skip/xfail；
- 把 exact exception 变 broad；
- 把 external/practice evidence 换 mock；
- 降低 assertions；
- 修改 pytest/mypy/ruff exclude；
- 只运行能过的子集却宣称 full gate。

确需改变旧错误预期（例如当前 OANDA sell payload 测试固化了错误）时，work item
必须引用官方 contract，并新增 negative/round-trip test，不能只改一行 expected value。

### 6.2 Gate Change Rule

acceptance/controller 自身修改是 safety-critical governance item：

- 保存 pre-change gate results；
- acceptance hash freeze；
- 有 meta-tests 证明不会非法放行；
- 不能只用改后的 runner 给自身 PASS；
- milestone gate 需要独立 full regression。

### 6.3 External Evidence Expiry

以下会使相关 E5/E6 过期：

- execution/risk/persistence/cycle semantics change；
- OANDA account/division/capability change；
- credential/account replacement；
- schema migration affecting evidence continuity；
- critical dependency/transport change；
- P0/P1 incident；
- frozen build hash change according to runbook reset rules。

## 7. Final Result Schema

M17 生成机器结果：

```yaml
FINAL_ACCEPTANCE_RESULT:
  blueprint_version: 2026-08-13.1
  frozen_commit: sha
  status: COMPLETE_PAPER_ONLY | FAILED | BLOCKED_EXTERNAL
  requirements:
    total: 0
    passed: 0
    failed: 0
    missing: 0
  milestones:
    done: []
    incomplete: []
  quality:
    pytest_exit: 0
    ruff_exit: 0
    mypy_exit: 0
    acceptance_exit: 0
  safety:
    live_attempts: 0
    other_broker_attempts: 0
    unapproved_orders: 0
    duplicate_orders: 0
  observation:
    required_calendar_days: 30
    qualified_calendar_days: 30
    unresolved_p0_p1: 0
    unexplained_cross_day_diffs: 0
  evidence_manifest_sha256: sha256:...
  live_trading_remains_locked: true
```

任意 required 值 unknown/missing/TBD/waived 时 status 不能 COMPLETE。
