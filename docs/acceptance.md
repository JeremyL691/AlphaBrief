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

#### M02-W03 已闭环证据（R-20260813-M02-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M02-W03-01 | PASS/FAIL 只来自 process exit code，agent-authored result field 不能提供 | `run_command` 从 `proc.returncode` 派生 `passed`；`CommandEvidence` model validator 拒绝 `passed` 与 exit_code/timed_out 矛盾的记录；`true`→pass、`false`→fail、`exit 42`→exit_code 42 |
| AC-M02-W03-02 | logs/manifests 脱敏 token、authorization headers、account IDs 和配置的 sensitive patterns | `autonomous_scrub`（authorization/bearer/token/api_key/secret/OANDA account ID/纯数字串 patterns）；artifact 只含 scrubbed bytes，SHA-256 计算于 scrubbed 内容；custom pattern 注入测试 |
| AC-M02-W03-03 | timeout 终止整个 child process group 并产生 classified failed evidence | `start_new_session=True` + `killpg`（SIGTERM → grace → SIGKILL）；`sleep 30` 在 1s timeout 后 timed_out=True、passed=False、classification="timeout"，`pgrep` 证明无残留进程 |

范围说明：本 round 无 allowlist 外路径。full pytest 1439 passed（+10 runner/scrub 测试）。

#### M02-W04 已闭环证据（R-20260813-M02-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M02-W04-01 | resolved allowlist 外的 changed path 使 scope gate 失败 | `scope_gate_violations(contract, changed_paths)`（glob 匹配含 `**` 跨目录与裸文件名）；allowlist 内通过、allowlist 外失败、forbidden paths（`_reference_sources/**`）失败 |
| AC-M02-W04-02 | live hosts、other broker production references、reference imports、seeded secrets 使 safety gate 失败 | `safety_gate_violations(changed_files)`：live host/`live_trading_enabled` selection、`alpaca`/routing/simulated surfaces、`_reference_sources` import、bearer/token/api_key/secret/完整 account ID 模式；clean content 通过 |
| AC-M02-W04-03 | 删除测试、新增 skip/xfail/noqa/type-ignore 或弱化 quality config 需要显式 authorization 否则失败 | `delta_gate_violations`（deleted test 路径、changed content markers、pyproject.toml/ruff/mypy config）；`authorized_paths`/`authorized_markers` 显式豁免 |

范围说明：本 round 无 allowlist 外路径。full pytest 1459 passed（+20 gate 测试）。

#### M02-W05 已闭环证据（R-20260813-M02-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M02-W05-01 | checkpoint 的 base、dirty paths、allowlist 一致时，先重跑 last gate 再 RESUME | `classify_recovery`：base==HEAD 且 dirty ⊆ allowlist → RESUME（`re_run_gate` 携带 checkpoint 的 last_verified_gate）；base mismatch → BLOCK |
| AC-M02-W05-02 | dirty paths 缺失或归属模糊时安全停止，不做 reset/checkout/clean/stash/commit、不提问 | 无 checkpoint + dirty → STOP；dirty 超出 allowlist → STOP；checkpoint 无 gate → STOP；模块只分类不执行任何 git 操作 |
| AC-M02-W05-03 | 重复失败上限产生 QUARANTINED，independent work 仍可选 | `classify_failure_ceiling`（same-failure 3 次或 total 5 次 → QUARANTINE）；QUARANTINED item 不被 selection 选中且不报错 |

范围说明：本 round 无 allowlist 外路径。full pytest 1469 passed（+10 recovery 测试）。

#### M02-W06 已闭环证据（R-20260813-M02-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M02-W06-01 | synthetic passing item 推进、带 trailers commit、append 一行 ledger、选择正确 next item | `controller_run` 全流程（synthetic git repo：M99-W01 DONE、milestone M99 DONE、M98 ACTIVE、next=M98-W01；commit trailers `AlphaBrief-Round/Work-Item/Requirements`；ledger 恰一行且 `controller_enforced=true`；tree clean） |
| AC-M02-W06-02 | synthetic failing 或 acceptance-mutating item 不能 self-certify DONE | failing（exit 1）→ FAILED，无 commit/ledger/progress 变更；acceptance mutation（相对 baseline commit 指纹变化）→ BLOCKED_ACCEPTANCE_MUTATION；scope violation → BLOCKED_SCOPE |
| AC-M02-W06-03 | controller enforcement enabled 下全仓 + acceptance gates 通过 | full pytest 1476 passed exit 0；ruff/mypy exit 0；`acceptance verify` 11/11；progress 的 `controller_enforced` 在 M02 完成后置 true |

范围说明：本 round 无 allowlist 外路径。full pytest 1476 passed（+7 controller/meta-gate 测试）。
M02 里程碑全部 6 个 work items DONE；下一个 READY item 为 M03-W01（依赖 M02-W06 ✓）。

#### M03-W01 已闭环证据（R-20260813-M03-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M03-W01-01 | empty、current-baseline、fixture schema 迁移到同一 latest version | `alphabrief_api.db.migrations`（versioned ledger + ordered apply）；empty DB、pre-migration DB（无 ledger 直接建表）、apply+drop+apply fixture 全部收敛到 v1；`test_database_migrations.py` + `test_api_store.py` |
| AC-M03-W01-02 | 重跑不改变数据；中断迁移原子回滚 | `migrate` 每迁移一个事务（tables+ledger 一起 COMMIT/ROLLBACK）；broken migration 后无 partial table；重复 apply 后数据行不变 |
| AC-M03-W01-03 | newer/corrupt schema 启动失败且无 partial writes | `check_compatibility`（unknown applied version / 超过 expected_latest → SchemaCompatibilityError）；`apply_schema` 先 check 后 migrate |

工程说明：DuckDB 在“同 catalog 多连接、显式事务内 CREATE INDEX”场景存在
dependency-tracking quirk（index 被另一连接 drop 后 commit 失败）。处理：
(1) migration 的 index DDL 移到事务提交后 autocommit 幂等执行；(2) store
`clear()` 改为 drop 后重连；(3) `drop_schema` 显式先 drop indexes。full
pytest 1488 passed（+12 migration/store 测试）。

#### M03-W02 已闭环证据（R-20260813-M03-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M03-W02-01 | 同一 symbol+timestamp 的不同 source version 共存且保留 lineage | Migration v2 把 bars PK 改为 (symbol, timestamp, data_version, source)；`get_bar_facts` 返回全部版本（fact_id/source/data_version/ingested_at）；`test_market_data_store.py` + `test_api_market_data.py` |
| AC-M03-W02-02 | Content、model call、OrderIntent、RiskDecision facts append-only 且 UTC stamped | news INSERT 改 ON CONFLICT DO NOTHING；bars 事实 content-addressed（`bar_fact_id`）；model evaluations / AI cycle attempts 均 append-only 测试（`test_news_store.py`、`test_model_call_store.py`、`test_risk_decision_store.py`） |
| AC-M03-W02-03 | 历史 snapshot 在后继 ingestion 后重建出相同 fact IDs/hashes | `fact_id` 是确定性内容地址；重放同一事实 no-op；不同版本各自 ID；后继 ingestion 不改变旧 fact ID（确定性重建测试） |

范围说明：`tests/test_api_server.py::test_load_csv_reloading_overwrites` 断言的旧
“reload 覆盖”语义已被本 item 的设计取代——`/api/v1/data/load` 的 `bar_count`
改为返回加载后该 symbol 的 decision-view 总数（r1=1、r2=3 的断言在新语义下
原样成立）；该测试文件不在 storage allowlist 内，未改动。full pytest 1500
passed（+12 store/API 测试）。

#### M03-W03 已闭环证据（R-20260813-M03-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M03-W03-01 | cycle transition 与 referenced outputs 在 failure injection 下一起 commit 或全部不 commit | `AiTradingStore.save_cycle` 改为单事务（BEGIN/COMMIT/ROLLBACK，cycle+votes+attempts）；serialization failure injection 后无 cycle/vote/attempt 残留（`test_cycle_checkpoint_store.py`） |
| AC-M03-W03-02 | 当前 projection 从 facts 重建，normalization 后与 stored projection 逐字节相等 | `CycleCheckpointStore.rebuild_projection`（从 ai_daily_cycles + votes/attempts fact tables 重建）+ `projection_matches_stored`（`json.dumps(sort_keys, default=str)` 规范化比较）；后继 cycle ingestion 不改变旧 projection（`test_projection_rebuild.py`） |
| AC-M03-W03-03 | compare-and-set 拒绝 stale writers 与非法 phase transitions | `checkpoint(cycle_id, phase, expected_phase=...)`：expected 不匹配 → False 且 checkpoint 不变；非单调 transition（向后/重复）→ False；未知 phase → ValueError；单调推进 + output_ids 持久化 |

范围说明：queue 声明的 targeted 文件 `tests/test_projection_rebuild.py` 不在
storage profile globs 内（与 test_broker_commands.py 相同的 queue gap 先例），
按声明文件名新建并纳入本 round 的 documented forced path；其余 changed paths
全部在 allowlist 内。full pytest 1510 passed（+10 checkpoint/rebuild 测试）。

#### M03-W04 已闭环证据（R-20260813-M03-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M03-W04-01 | 只有有效 lease owner 能写；expired ownership 在 takeover 后不能 commit | `writer_lease`（acquire/renew/validate/assert_write_authorized/release，SQL CAS on owner+token+expiry）；expiry 后 takeover 成功、旧 token 失效、`assert_write_authorized` 抛 `WriterLeaseError`；renew 只对当前 owner 生效 |
| AC-M03-W04-02 | 无 lease 时 read-only API 调用可用且不能 mutate storage | `open_readonly`（DuckDB `read_only=True` 结构性只读）：无 lease 读 OK，任何 INSERT 在引擎层失败 |
| AC-M03-W04-03 | 并发进程串行化或清晰失败，无 DB 损坏 | 双连接（模拟双进程）测试：第二个 owner 被干净拒绝（非异常风暴），双方仍可完整读取数据 |

范围说明：queue 声明的 targeted 文件 `tests/test_database_writer_lease.py` 不在
storage profile globs 内（同前例），按声明文件名新建并纳入 documented forced
path；其余 changed paths 全部在 allowlist 内。full pytest 1517 passed（+7
lease 测试）。

#### M03-W05 已闭环证据（R-20260813-M03-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M03-W05-01 | backup 原子、含 schema/build/file hashes、不含 configured secret patterns | `create_backup`（CHECKPOINT → 临时文件 → `os.replace` 原子改名 → manifest：source_db_sha256/schema_version/blueprint_version/files sha256/size/retention）；artifact 全量 secret-pattern 扫描，命中即 abort 且无残留（`test_backup_restore.py`） |
| AC-M03-W05-02 | isolated restore 迁移、重建 projections、通过 integrity queries | `restore_backup`（hash 校验后复制到隔离 target → `apply_schema` 迁移到 latest → tables integrity 检查 → cycle projections 从 facts 重建并逐字节比对）；corrupt backup 在复制前被拒（`test_backup_restore.py` + `test_database_migrations.py`/`test_projection_rebuild.py` 集成） |
| AC-M03-W05-03 | retention 只删过期显式 target，保留 newest verified restore point | `apply_retention`（(created_at, backup_id) 确定性排序；expired-by-age / keep-count 规则；newest verified 永不删除；foreign files 不碰）（`test_backup_retention.py`） |

范围说明：本 round 无 allowlist 外路径（`tests/test_backup_*.py` 均在 storage
profile globs 内）。full pytest 1527 passed（+10 backup/retention 测试）。

#### M03-W06 已闭环证据（R-20260813-M03-W06）— M03 里程碑 gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M03-W06-01 | 每个声明 persistence boundary 的 failure injection 留下 old/new 完整状态且 projection rebuild 通过 | migration 失败 → 旧 schema 完整、无 partial table；cycle save 失败 → 旧 projection 仍逐字节 rebuild、新 cycle 不存在；restart 从最后持久 gate 恢复（`test_storage_crash_recovery.py`） |
| AC-M03-W06-02 | clean isolated backup restore 通过全部 storage integrity checks | backup → restore → schema version == latest、tables integrity、cycle projection rebuild 逐字节一致、writer lease 保留（`test_storage_crash_recovery.py` + `test_backup_restore.py`） |
| AC-M03-W06-03 | 全仓 pytest、static、acceptance gates 通过，M03 traceability 完整 | full pytest 1531 exit 0；ruff/mypy exit 0；`acceptance verify` 11/11；REQ-PLAT-004..009 映射见下方 |

#### M03 Requirement Traceability（M03-W01..W06）

| Requirement | 代码/证据 |
|---|---|
| REQ-PLAT-004（versioned migrations, fail closed） | M03-W01：`migrations.py`（ordered/transactional/idempotent + `check_compatibility`） |
| REQ-PLAT-005（关键写入事务边界） | M03-W02/W03：bars facts append-only；`save_cycle` 单事务（cycle+votes+attempts） |
| REQ-PLAT-006（单写者协调） | M03-W04：`writer_lease`（renewable CAS lease + `open_readonly`） |
| REQ-PLAT-007（每日备份/保留/校验/restore） | M03-W05：`backup.py`（atomic backup + manifest hashes + retention + isolated restore） |
| REQ-PLAT-008（UTC 记录） | M03-W02：facts 全部 UTC stamped（ingested_at/created_at/evaluated_at） |
| REQ-PLAT-009（关键 ID 跨层可追踪） | M03-W02/W03：fact_id 内容寻址；checkpoint output_ids；projection 从 facts 重建 |

范围说明：本 round 无 allowlist 外路径。full pytest 1531 passed（+4 crash-recovery
测试）。M03 里程碑全部 6 个 work items DONE；下一个 READY item 为 M04-W01
（依赖 M03-W06 ✓）。

#### M04-W01 已闭环证据（R-20260813-M04-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M04-W01-01 | 有效 practice response 产生 typed account profile（state/currency/margin/capability flags/scrubbed hash/UTC timestamp） | `run_account_preflight` → `OandaAccountProfile`（Decimal 字段、counts、GSL mode、tradeable、retrieved_at UTC）；mock response 全字段断言（`test_oanda_account_preflight.py`） |
| AC-M04-W01-02 | 缺凭证/invalid credentials/live host/account mismatch/non-tradeable/malformed 在任何 catalog sync 或执行前 fail closed，无 fallback 无提问 | 六类分类失败各有测试：missing_credentials、invalid_credentials（BrokerAuthError→分类）、live_host（config 构造即拒 + preflight 防御）、account_mismatch、not_tradeable（balance/margin 缺失）、malformed_response |
| AC-M04-W01-03 | CLI/API/logs/exceptions/evidence 不含 token 或完整 account ID | profile 只含 SHA-256 account_id_hash（64 hex）；serialized JSON/异常消息均不含 token 与完整 account ID；preflight 模块无 logging/print |

范围说明：本 round 无 allowlist 外路径。`OandaHttpClient` 增加显式
token/account_id 注入参数（缺省回退 env），供 preflight 与测试使用。
full pytest 1541 passed（+10 preflight 测试）。

#### M04-W02 已闭环证据（R-20260813-M04-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M04-W02-01 | 每个 response row 恰好一个 strict metadata object（name/displayName/raw type/precisions/sizes/margin/pipLocation/stop-distance） | `parse_instruments_response` → `InstrumentMetadata`（frozen + extra=forbid；display_precision/trade_units_precision/pip_location 为 int；6 个 Decimal 字段；optional trailing-stop distances）；全字段断言（`test_oanda_market_instruments_client.py`、`test_instrument_metadata.py`） |
| AC-M04-W02-02 | unknown fields 保留在 versioned raw payload；缺/坏 required fields 拒绝整个 snapshot，无 partial publication | `raw_payload` 逐行保留（含 futureField）；任一 row 缺 marginRate/name/type 或 precision 非法 → `InstrumentParseError` 且无任何 instrument 输出；空/畸形响应被拒 |
| AC-M04-W02-03 | 解析/规范化 Decimal-safe，绝不从 symbol 命名推断 precision/size | float 输入被拒（parse 与 model 两层）；`XPT_USD` 等带点/横线符号仍使用响应中的显式字段；JSON 序列化保持 Decimal 字符串 |

范围说明：本 round 无 allowlist 外路径。full pytest 1556 passed（+15
instruments/metadata 测试）。

#### M04-W03 已闭环证据（R-20260813-M04-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M04-W03-01 | snapshot、instrument rows、content hash、account correlation、fetched_at UTC、diff 在 failure injection 下一起 publish 或全部不 publish | `publish_snapshot` 单事务（snapshot 行 + rows + diff + fetched_at 一起 COMMIT/ROLLBACK）；row serialization failure 后无 snapshot/rows 残留（`test_instrument_catalog_store.py`） |
| AC-M04-W03-02 | 相同内容 replay 幂等；additions/removals/reactivations/metadata changes 产生可查询历史且不覆盖旧版本 | content_hash 去重（同内容返回同一 snapshot_id）；diff 记录 added/removed/metadata_changed；每版 rows 独立保留（`list_snapshots` 2 版共存） |
| AC-M04-W03-03 | current projection 从 immutable facts 重建且与最新完整 snapshot 的 count/hashes 完全一致 | `current_projection`（最新 snapshot 的 rows 重建）+ `projection_matches_latest_snapshot`（规范化 content hash 逐字节相等） |

范围说明：本 round 无 allowlist 外路径。Migration v3 新增
instrument_catalog_snapshots/rows 表（`test_instrument_catalog_migrations.py`）。
full pytest 1565 passed（+9 catalog 测试）。

#### M04-W04 已闭环证据（R-20260813-M04-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M04-W04-01 | fixtures 覆盖 Currency、Metal、index/commodity/bond/equity CFD 与 unknown，输出确定性 category + taxonomy-version | `classify_instrument` 10 组 parametrized fixtures（CURRENCY/METAL/INDEX_CFD/COMMODITY_CFD/BOND_CFD/EQUITY_CFD/CRYPTO_CFD/OTHER_CFD）；`classify_snapshot` 全行覆盖 |
| AC-M04-W04-02 | 未识别 broker type 或 display pattern 保持 unknown 可见（raw value），不消失于 catalog counts/search | OTHER_CFD 保留 raw_type/display_name/basis；持久化 catalog 中 unknown instrument 仍在 projection 计数与分类结果中（`test_instrument_taxonomy.py` + catalog store 集成） |
| AC-M04-W04-03 | taxonomy 变更产生新 derived version，且不 mutate raw instrument snapshot | `TAXONOMY_VERSION = "oanda-taxonomy-1"` 常量版本化；classification 前后 `InstrumentMetadata.model_dump()` 逐字段相等（frozen 不可变） |

范围说明：本 round 无 allowlist 外路径。full pytest 1581 passed（+16
taxonomy 测试）。

#### M04-W05 已闭环证据（R-20260813-M04-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M04-W05-01 | API 与 CLI 对同一 query 返回相同 total/filtered counts/metadata/taxonomy/active state/catalog version/freshness | 共享 `InstrumentCatalogStore.query()`（单一 truth）；API `GET /api/v1/data/catalog` 与 CLI `alphabrief data catalog` 输出 JSON 全等断言（`test_instrument_catalog_api_cli.py`） |
| AC-M04-W05-02 | pagination、exact-name、case-insensitive search、category/active filters、unknown categories、empty results 有确定 schema 与排序 | 分页不重叠且按 name 排序；exact `XAU_USD` 与 fuzzy `gold` 均命中；OTHER_CFD filter 与无结果返回确定性空结构；items 带 category/taxonomy_version/active |
| AC-M04-W05-03 | missing/stale/account-mismatch catalog 返回显式 unavailable states，绝不替换 hard-coded allowlist 或触发 broker write | `availability ∈ {missing, stale, account_mismatch, available}`；query 只读（snapshot 数量不变）；API/CLI 无任何 broker 调用路径 |

范围说明：本 round 无 allowlist 外路径。full pytest 1590 passed（+9
catalog API/CLI 测试）。

#### M04-W06 已闭环证据（R-20260813-M04-W06）— M04 里程碑 gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M04-W06-01 | fixture gate 证明 response count == immutable store == API == CLI counts，无 hard-coded allowlist loss，每 row 完整 required metadata | fixture 4 instruments（含 unknown CFD）→ parse → publish → API/CLI 全等且 count=4；每 row 全字段类型断言；unknown CFD 在三处 surface 均可见（`test_oanda_market_catalog_e2e.py`） |
| AC-M04-W06-02 | 配置的 OANDA practice contract run 证明 account catalog response、persisted version、exposed count 一致并存储 scrubbed E5 evidence | **T7 PENDING（external_evidence_pending）**：本地无 OANDA credentials，未进行真实 practice run；`test_controlled_practice_catalog_run` 在无凭证时断言 fail-closed，有凭证时执行完整 practice contract（preflight→fetch→persist→counts）并打印 scrubbed E5 summary；mock 不冒充 practice evidence |
| AC-M04-W06-03 | 缺凭证/unavailable practice service → ENVIRONMENT_BLOCKED，无 mock substitution/waiver/fallback/提问/false DONE | 无凭证时 preflight 抛 `missing_credentials`；e2e 本地路径断言同样 fail-closed；进度标记 CODE_COMPLETE 而非 DONE |

范围说明：本 round 无 allowlist 外路径。full pytest 1593 passed（+3 e2e 测试）。
M04-W06 为 CODE_COMPLETE（缺 T7 practice evidence）；M04 里程碑 CODE_COMPLETE，
M05 激活并继承 `external_evidence_pending`（按 autonomous_loop §5.1，M00-M15
工程项可把 CODE_COMPLETE 当 code dependency satisfied）。

#### M05-W01 已闭环证据（R-20260813-M05-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M05-W01-01 | fixtures 覆盖全部官方 granularity、M/B/A 组合、count/time ranges、daily/weekly alignment、pagination boundaries、UTC timestamps | 21 个 granularity parametrized parse；M/B/A 三组件同 row 各自成 fact；count/from/to/dailyAlignment/weeklyAlignment 传入 URL 断言；UTC 规范化（`test_oanda_market_candles.py`） |
| AC-M05-W01-02 | bid/ask/mid OHLC + volume + complete flags Decimal-safe，不 collapse 组件、不覆盖其他 source version | 每组件独立 `OandaCandle`（component 保留）；float 输入拒绝；缺失组件价格拒绝；两个 candle source versions 在 store 中按 (symbol, timestamp, data_version, source) 共存（`test_market_data_store.py` 集成） |
| AC-M05-W01-03 | pagination bounded 且 duplicate-free；incomplete candles 可查询 raw facts 但排除出 completed decision inputs | `count <= 5000` 上限；重复 (time, component) 拒绝而非合并；`completed_only()` 过滤；`next_from_time` 供分页 |

范围说明：progress 的 `current` 新增 `external_evidence_pending` 字段（§5.1 标记），
`CurrentRoundSchema` 同步接受该字段（loop-controller schema 的文档化 forced
path）。full pytest 1625 passed（+32 candles 测试）。

#### M05-W02 已闭环证据（R-20260813-M05-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M05-W02-01 | 请求按配置上限确定性分块；响应保留 bid/ask ladders、spread、liquidity、tradeable、closeout、conversion factors、broker time、request correlation | `PricingRequest.max_instruments_per_request`（默认 50、上限 500）确定性分块（7 symbols/3 → 3 请求）；`OandaPrice` 全字段保留（Decimal ladder entries + spread + closeout + conversion_factor + broker_time UTC + request_id + source_version）；chunk correlation ID 唯一（`test_oanda_market_pricing.py`） |
| AC-M05-W02-02 | missing sides、crossed prices、nonpositive conversion factors、duplicate instruments、malformed timestamps 失败而非静默修复 | 五类 quality validation 各有测试：空 bids/asks → failed；bid>ask → failed；conversion factor<=0 → failed；重复 instrument → failed；非法时间 → failed；float 输入拒绝 |
| AC-M05-W02-03 | partial broker response 发布显式 per-instrument coverage，不能表示为完整 pricing snapshot | `InstrumentCoverage`（requested/returned/missing/failed/complete）；partial（1/3 返回）→ missing 明确列出且 complete=False；全量返回 → complete=True |

范围说明：本 round 无 allowlist 外路径。full pytest 1636 passed（+11
pricing 测试）。

#### M05-W03 已闭环证据（R-20260813-M05-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M05-W03-01 | 单 runtime owner 最多保持配置的 stream connection；subscription 原地 reconcile，不为每 instrument/consumer 开新连接 | `PricingStream`（`MAX_STREAM_CONNECTIONS=1`、connection_count 上限断言）；`update_subscriptions` 原地增删、`connection_count` 恒为 1；unsubscribed symbol frame 按 protocol error 拒绝（`test_oanda_market_stream.py`） |
| AC-M05-W03-02 | disconnect/heartbeat loss/malformed/rate limit/server error 走 bounded classified backoff 并在 consumer 视缓存价为 fresh 前标记 stale | heartbeat 超时 → `stale(heartbeat_loss)`；disconnect → classified + bounded exponential backoff（上限封顶）→ 重连；reconnect 次数达上限 → `stale(server_error)`；crossed/missing-side frame → `stale(malformed_frame)`；`price_is_fresh` 在 stale 后恒 False |
| AC-M05-W03-03 | shutdown 取消 reads/reconnect timers、关闭连接、持久化最终 cursor state、不 busy-loop 不提问 | `shutdown()` 返回 `StreamCursor`（symbol → 最后 broker time）；连接 closed；poll 在 shutdown 后返回 shutdown 状态且不再连接；idle poll 立即返回 |

范围说明：本 round 无 allowlist 外路径。full pytest 1646 passed（+10
stream 测试）。

#### M05-W04 已闭环证据（R-20260813-M05-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M05-W04-01 | Currency/Metal/各 CFD 类别/unknown、overnight boundaries、DST、weekends、configured holidays 有确定性 session verdict fixtures | `CATEGORY_SESSIONS` 8 类窗口（FX overnight Mon 21:00→Fri 21:00、CFD Mon 00:00→Fri 21:00、Crypto 24x7）；week-minute 圆环算法（overnight wrap 确定性）；holiday calendar 关闭；UTC-fixed（DST 无影响）；窗口表 ≥3 个不同窗口（非单一全局窗口）（`test_oanda_market_sessions.py`、`test_instrument_sessions.py`） |
| AC-M05-W04-02 | broker tradeable=false、catalog inactive、session closed、stale evidence、unknown calendar state 全部对新敞口 fail closed | `evaluate_exposure_readiness` 五类 fail-closed 分支各有测试（not tradeable/inactive/closed/stale/unknown） |
| AC-M05-W04-03 | 无 execution-relevant path 只依赖单一 global Mon-Fri start/end window | session 表按 category 区分（≥3 不同窗口）；catalog taxonomy 驱动 instrument 的 session（Crypto Sunday ready、Currency/Index Sunday closed） |

范围说明：本 round 无 allowlist 外路径。full pytest 1661 passed（+15
sessions 测试）。

#### M05-W05 已闭环证据（R-20260813-M05-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M05-W05-01 | 相同 immutable inputs + quality-policy version 产生相同 snapshot ID/manifest hash/source IDs/quality results/normalized serialization | `build_market_snapshot` 确定性（snapshot_id/manifest_hash 由 normalized inputs + quality version 派生）；双构建全等断言（built_at 为 wall-clock 元数据、排除于 manifest，规范化比较）；quality version 不同 → 不同 snapshot；publish 幂等（`test_market_data_snapshot_store.py`） |
| AC-M05-W05-02 | incomplete candles/stale quotes/missing conversion/catalog mismatch/unacceptable gaps/abnormal spread/partial coverage 产生显式 rule results 和 non-executable verdict | 7 类 quality rules 各有 fail 测试（incomplete/stale/mismatch/gaps>30min/spread>5%/not-ready）；executable 只在全部 rule passed 时为 True |
| AC-M05-W05-03 | 后继 ingestion 创建新 facts 与新 lineage-linked snapshot，不改变已被 decision 引用的 snapshot | `MarketSnapshotStore`（migration v4 表）原子 publish；lineage 链查询（v3→v2→v1）；已存 v1 逐字段不变（`test_market_data_lineage.py`） |

范围说明：本 round 无 allowlist 外路径。full pytest 1673 passed（+12
snapshot/lineage 测试）。

#### M05-W06 已闭环证据（R-20260813-M05-W06）— M05 里程碑 gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M05-W06-01 | fixture/fault suites 证明 granularity、components、pagination、stream budgets、freshness、sessions、quality、snapshot reproducibility、immutable lineage 覆盖每类返回 instrument 与可用 category | M05-W01..W05 全部本地 suites 重跑通过（candles/pricing/stream/sessions/snapshot/lineage + API 集成共 84 项）；e2e fixture suite 覆盖 M/B/A 三组件 36 facts + sessions/readiness |
| AC-M05-W06-02 | 配置的 practice run 记录 scrubbed E5 candle/quote evidence 并发布一个完整 immutable snapshot | **T7 PENDING（external_evidence_pending）**：本地无 OANDA credentials；`test_controlled_practice_market_data_run` 无凭证时断言 fail-closed，有凭证时执行 preflight→candles→pricing→catalog→snapshot publish 并打印 scrubbed E5 summary；mock 不冒充 practice evidence |
| AC-M05-W06-03 | 缺凭证/unavailable categories/外部 outage → 显式 ENVIRONMENT_BLOCKED 或 partial evidence，无 synthetic data/fallback prices/提问/false completion | 无凭证 preflight `missing_credentials` 断言；malformed candle frame 本地 fail-closed；进度标记 CODE_COMPLETE 而非 DONE |

范围说明：本 round 无 allowlist 外路径。full pytest 1677 passed（+4 e2e 测试）。
M05-W06 为 CODE_COMPLETE；M05 里程碑 CODE_COMPLETE，M06 激活并继续继承
`external_evidence_pending`。

#### M06-W01 已闭环证据（R-20260813-M06-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M06-W01-01 | property tests 证明 positive=buy、negative=sell、zero 拒绝，quantity/price/distance 从 instrument metadata 精确规范化后才序列化 | 确定性生成 property loops（正/负 units 全量、whole-unit 精度、price 精度边界）；zero 与“normalize 后为零”均拒绝；price 超精度拒绝而非静默舍入；`order_side`/`normalize_order`（`test_oanda_order_models.py`） |
| AC-M06-W01-02 | Market/Limit/Stop/Market-if-Touched、dependent orders、FOK/IOC/GTC/GTD 及 supported trigger 组合序列化为精确 contract fixtures | `serialize_order` fixtures：4 类 order type、4 种 TIF、GTD gtdTime、TP/SL/trailing/GSLO `*OnFill` 键、无 `side` 字段（signed units 编码方向）（`test_oanda_order_contracts.py`） |
| AC-M06-W01-03 | DAY 与所有 unsupported/account-incompatible 组合失败，绝不静默映射/舍入/提交/送人工 review | DAY 在模型层被拒（不映射 FOK/GTC——替换旧 adapter 的 silent mapping）；MARKET+price、GTD 缺 gtd_time、gtd_time 无 GTD、dependent order price/distance 二选一、GSLO 账户不支持、price 超精度——全部 ValueError fail-closed |

范围说明：本 round 无 allowlist 外路径。property tests 用确定性生成替代
hypothesis 依赖（未声明 dependency 不引入）。full pytest 1700 passed（+23
order 测试）。

#### M06-W02 已闭环证据（R-20260813-M06-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M06-W02-01 | create/get/list(paginated)/cancel/replace 产生精确 typed responses 与正确 state transitions | `OrderOpsClient` 全流程测试（create→PENDING、get 全字段、list 分页 has_more、cancel→CANCELLED、replace→新 order id）（`test_oanda_order_operations.py` + in-memory mock broker） |
| AC-M06-W02-02 | invalid request IDs、unknown orders、race conditions、stale replaces 以 classified errors fail closed | `invalid_request_id`（空 id）、`unknown_order`（404→分类）、`order_state_invalid`（FILLED 不能 cancel；read 与 replace 之间 state 变化 → 拒绝） |
| AC-M06-W02-03 | 每个 response 保留 request correlation；retries 不重复下单（create 对 clientExtensions.id 幂等） | `request_id` 贯穿所有结果（create/get/list/cancel/replace）；同 client_order_id 二次 create 返回同一 broker_order_id 且 `reused=True`，broker 侧仅 1 单 |

范围说明：本 round 无 allowlist 外路径。full pytest 1708 passed（+8
order ops 测试）。

#### M06-W03 已闭环证据（R-20260813-M06-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M06-W03-01 | 每个 transition fixture 产生 immutable ordered facts，带 broker transaction ID、related ID、UTC 时间、quantity/price/reason/financing、correlation ID | `OrderTransition` frozen 模型（extra=forbid、Decimal-only、float 拒绝、occurred_at 强制 UTC）；fixture 全字段断言 + DuckDB 持久化后重读一致（`test_oanda_order_transitions.py`） |
| AC-M06-W03-02 | immediate fill/pending/partial fill/cancel/reject/expire/reissue/reduce/close/dependent create-cancel 确定性投影、无 impossible jumps | `apply_transition` 状态机：CREATED→PARTIAL_FILL→FILLED 累积 open/filled；CANCELLED/REJECTED/EXPIRED；REISSUED 保持投影身份（related_id 记录新 broker order id）；REDUCED/CLOSED 仅允许自 FILLED/PARTIALLY_FILLED；DEPENDENT_* 不改父订单；FILLED→PENDING 等跳变拒绝 |
| AC-M06-W03-03 | duplicate/out-of-order/malformed/conflicting facts 幂等忽略或 quarantine，绝不改 terminal fact 或虚构 fill | duplicate transition_id → applied=False 不落库；terminal state（FILLED/CANCELLED/REJECTED/EXPIRED/CLOSED）被后继 transition 触碰 → quarantine 表记录、投影不变；PARTIAL_FILL/REDUCE/CLOSE 无前置订单 → quarantine（不虚构 open quantity）；malformed kind/float/after_state 冲突 → 构造期或应用期拒绝 |

范围说明：本 round 无 allowlist 外路径。修复路径集中在
`broker/oanda/transitions.py`（initial-fill 投影、union 返回类型、行宽）；
full pytest 1722 passed（+14 transition 测试）；ruff/mypy 全仓 clean。

#### M06-W04 已闭环证据（R-20260813-M06-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M06-W04-01 | trade/position get/list/partial-close/full-close/side-specific close/dependent modification/account summary/account changes 匹配精确 request/response fixtures | `TradeOpsClient`/`PositionOpsClient`/`AccountOpsClient`（`test_oanda_trade_position_lifecycle.py` + `test_oanda_account_changes.py`，in-memory mock transport）：trade get/list 分页 has_more、position long/short 独立 units/avgPrice/PL、TP/SL/trailing/GSLO 四选一依赖单、summary 全字段、changes 九类计数 + state 余额 |
| AC-M06-W04-02 | partial-close units、ALL semantics、long/short side handling、realized PnL、financing、margin、related transaction IDs 各自 distinct 且 Decimal-safe | close ALL 以 fill transaction units 为准（broker truth）；partial close 保留剩余 units；position close 显式 ALL/NONE/positive units（OANDA 缺省即 ALL，未指定侧绝不静默全平）；realizedPL/financing Decimal 精确；orderCreate/orderFill/tradeClose（trade）与 long/short 两侧（position）transaction ID 互不重合；summary margin/counts/lastTransactionID 精确 fixture |
| AC-M06-W04-03 | missing/stale/already-closed/account-mismatched/over-close/unsupported 请求 fail closed，无本地合成仓位变更 | unknown trade/position（404→unknown_*）、already closed（trade_state_invalid）、stale race（read 与 close 之间已关 → broker cancel+no-fill → trade_state_invalid）、negative units（invalid_units）、over-close（over_close，读后即拒、无 PUT 发出）、GSLO 未启用（unsupported_dependent）、多依赖类型（invalid_dependent）、双 None（invalid_units）；全部断言 broker 侧零变更、零本地合成 |

范围说明：本 round 无 allowlist 外路径；两个 targeted 测试文件为契约声明的
缺失文件，按既有先例创建（documented forced path）。OANDA position-close
语义（缺省 ALL、ALL/NONE/DecimalNumber）已对照官方 API 文档核实。
full pytest 1755 passed（+33 trade/position/account 测试）；ruff/mypy 全仓 clean。

#### M06-W05 已闭环证据（R-20260813-M06-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M06-W05-01 | detail/ID-range/paginated-range/since-ID 请求以 OANDA transaction ID 为游标权威，绝不替换为本地时间戳 | `TransactionOpsClient`（`test_oanda_transactions.py` + in-memory mock transport）：get detail 全字段精确（id/type/time/instrument/units/price/pl/financing，time 来自 broker 字符串）；range 请求参数精确回显 `idrange?from=..&to=..`、since 精确回显 `sinceid?id=..`；datetime/非 digit 游标一律 `invalid_cursor`；from>to → `invalid_range`；page_size 越界 → `invalid_page_size` |
| AC-M06-W05-02 | 空页、重叠页、重复 ID、乱序 ID、声明 range、缺失 range 产生确定性规范化输出与显式 gap 信号 | 乱序+重复 → 按 broker ID 升序去重（`duplicate_count` 计数）；声明 range 内缺失 span → `TransactionGap(gap_from,gap_to)`（含整段缺失 → 全 span gap）；分页自动拉全（page_size=2 拉 5 条、跨页重叠去重）；空页容忍；since 模式内部空洞 → gap；无限分页 → `pagination_limit_exceeded` fail-closed |
| AC-M06-W05-03 | cursor candidate 与 durable advancement 分离，失败消费者不能确认未见 transaction | `cursor_candidate` 仅返回最高完全连续前缀（首个空洞即封顶，since 模式下首 ID 缺失 → candidate None）；端口无 advance API、不持有 durable state：同 since 重复调用结果完全一致；消费者在 candidate 与持久化之间崩溃 → 重试仍见相同窗口 |

范围说明：本 round 无 allowlist 外路径；targeted 测试文件为契约声明的缺失
文件，按既有先例创建（documented forced path）。分页循环有界（50 页上限
fail-closed），端口从不隐式推进任何游标（durable advancement 归 M07
reconciliation 所有）。full pytest 1772 passed（+17 transaction 测试）；
ruff/mypy 全仓 clean。

#### M06-W06 已闭环证据（R-20260813-M06-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M06-W06-01 | auth/validation/reject/rate limit/transient server/transport timeout/disconnect/parse/unknown-outcome 映射稳定 typed classes，retry eligibility bounded | `classify_http`/`classify_failure`（`test_oanda_transport_faults.py`）：401/403→AUTH、400→VALIDATION、404→NOT_FOUND、422→REJECT、429→RATE_LIMIT、5xx→TRANSIENT_SERVER、299→PARSE；transient 消息标记（HTTP 429/503、"timed out"、"Connection reset"、"ssl handshake"）精确分类；`is_retriable` 仅 RATE_LIMIT/TRANSIENT_SERVER/TIMEOUT/DISCONNECT；`should_retry` 到达 max_attempts 即停；executor GET 429+503 后成功（3 attempts）、3 次 5xx 后 `ClassifiedFailure` fail-closed、422/401 一次即止 |
| AC-M06-W06-02 | submit 后 timeout/disconnect 必须先按持久化 client identity 查询再重试；unresolved 冻结后续提交，不猜测不询问 | `ClassifiedRequestExecutor`：mutating 请求遇 TIMEOUT/DISCONNECT/TRANSIENT_SERVER → `UnknownOutcomeFailure`（断言仅 1 次 POST，零自动重试）；`UnknownOutcomeResolver`（`test_oanda_order_commands.py`）：absorbed submit → 查询 GET /orders 找到 clientExtensions.id → RESOLVED_ACCEPTED（含 broker_order_id/state）；drop submit → 穷举无匹配 → RESOLVED_NOT_SUBMITTED → 单次 bounded 重试成功且仅 1 单；查询失败/超页 → UNRESOLVED → `SubmissionGate.freeze` → `FrozenSubmissionError` 阻断一切后续提交；resolver 幂等（重复 resolve 结果一致） |
| AC-M06-W06-03 | telemetry 记录 method family/endpoint template/status/broker request ID/latency/attempts/error class/scrubbed correlation；排除 token/完整 account ID/敏感 payload | `TelemetryRecorder`（`test_oanda_telemetry.py`）：DuckDB round-trip 全字段；token 与 "Bearer" 永不出现；完整 account ID 与所有 digit broker ID 被模板化为 `{account_id}`/`{id}`；payload 的 units/price 不落库（仅 had_body 标志）；correlation 以 `corr-` + sha256 前 16 位非可逆存储、确定性、不含明文；method family 映射 17 种端点稳定（order.create/list/get/update/cancel、trade.*、position.*、account.summary/changes、transaction.get/idrange/sinceid） |

范围说明：本 round 无 allowlist 外路径；targeted 两个与 integration 一个测试
文件均为契约声明的缺失文件，按既有先例创建（documented forced path）。
429 视为明确未处理可 bounded 重试；5xx/timeout/disconnect 对 mutating 请求
一律 unknown-outcome（绝不自动重试）。full pytest 1799 passed（+27
faults/telemetry/commands 测试）；ruff/mypy 全仓 clean。

#### M06-W07 已闭环证据（R-20260813-M06-W07）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M06-W07-01 | contract/fault suites 覆盖 supported orders、TIF、dependent orders、signed units、precision、全部 declared transitions、trade/position close、transactions、errors、redacted telemetry | targeted 六套全绿（`test_oanda_order_models.py` + `test_oanda_order_commands.py` + `test_oanda_order_transitions.py` + `test_oanda_trade_position_lifecycle.py` + `test_oanda_transactions.py` + `test_oanda_transport_faults.py` = 80 passed）：W01 contracts（4 类 order type、FOK/IOC/GTC/GTD、TP/SL/trailing/GSLO、signed units、精度拒绝）、W02 order ops（幂等 create）、W03 全部 10 类 transition、W04 trade/position close + account、W05 transaction ranges/gaps、W06 faults/telemetry scrubbing |
| AC-M06-W07-02 | controlled practice scenarios 走正式产品路径：fixed minimum risk、approved persisted decision、idempotent client identity、automatic cleanup、final reconciliation evidence | `PracticeScenarioRunner`（`test_oanda_lifecycle_e2e.py`，runtime 命令）：OrderIntent → RiskGate（symbol allowlist + fixed cap=1，intent 构造性封顶）→ approved RiskDecision 持久化到 DuckDB `practice_scenarios` 表（decision_id/approved）→ `client_order_id=scenario-intent` 幂等提交（重跑 reused=True、broker 侧仅 1 单 1 仓）→ 自动 cleanup（FILLED→close trade；幂等 replay → already_closed）→ 最终 reconciliation evidence（open_orders/open_trades/open_position_count/balance 全零/精确）；submit units 严格等于 approved decision（intent=2 → broker 只见 1） |
| AC-M06-W07-03 | 缺凭证/unsafe account state/cleanup 未决/外部 outage → ENVIRONMENT_BLOCKED 或 FAIL，绝不 fake fill、fallback、waiver、question、DONE | 缺 client → ENVIRONMENT_BLOCKED（含 credential 语义，零请求发出）；cleanup 失败（broker close timeout）→ FAIL + UNRESOLVED cleanup_result、broker trade 保持 OPEN（零本地合成 fill）；gate 拒绝（quantity 超 cap）→ FAIL 零提交；无任何 waiver/人工 review/询问路径（requires_human_review → FAIL） |

范围说明：本 round 无 allowlist 外路径；runtime 测试文件为契约声明的缺失
文件，按既有先例创建（documented forced path）。真实 OANDA practice E2E
需要 T7 凭证：M06 里程碑 CODE_COMPLETE 并继承 external_evidence_pending
（M06-W07 T7 practice lifecycle evidence）。full pytest 1805 passed（+6
scenario E2E 测试）；ruff/mypy 全仓 clean；acceptance 11/11。

#### M07-W01 已闭环证据（R-20260813-M07-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M07-W01-01 | 一个确定性 cycle+intent identity 在 100 次 sequential/concurrent/timeout/restart replay 下最多保留一个 submit identity | `OrderLedger`（`test_oanda_idempotency.py`）：`submit_id = cycle:intent` 确定性推导 + `UNIQUE(cycle_id, intent_id)`；100 次 replay → 同一 submit_id、reused=True、仅 1 条 RESERVED event；restart（关库重开同文件）→ 同 identity、SUBMITTED 状态保持；timeout replay → in-flight 状态不变、events 完全一致（零重复、零覆盖） |
| AC-M07-W01-02 | reservation/decision binding/submit attempt/broker result/related IDs 原子提交，compare-and-set 转换 + 不可变历史 | 全流程（`test_broker_order_ledger.py`）：RESERVED→BIND→SUBMIT_ATTEMPT→BROKER_RESULT→RELATED_ID×2 严格有序 event 链（event_id 单调、唯一）；每个转换 = 单事务（UPDATE...WHERE status=expected + INSERT event），CAS 失败 → state_conflict 零覆盖；broker result 同参数重放幂等（BROKER_RESULT 仅 1 条）；related IDs 仅在 COMPLETED 后记录 |
| AC-M07-W01-03 | identity collision/payload hash mismatch/stale owner/in-flight ambiguous/missing decision 冻结提交，绝不覆盖/fallback/询问 | 不同 decision 重放 → identity_collision 且原 decision 不被覆盖；payload hash 不同 → payload_mismatch（bind 与 attempt 双路径）；owner 不同 → stale_owner；无 bind 直接 attempt → missing_decision；SUBMITTED 再 attempt → in_flight_ambiguous；FROZEN 后 bind/attempt/result/freeze 全部 state_conflict；与 W06 `UnknownOutcomeResolver` 组合：absorbed timeout → resolve → COMPLETED，broker 侧仅 1 单 |

范围说明：本 round 无 allowlist 外路径；两个 targeted 测试文件为契约声明的
缺失文件，按既有先例创建（documented forced path）。并发由 DuckDB 单写者 +
UNIQUE 约束 + CAS 语义覆盖（restart/竞态 replay 均走 replay verdict）。
full pytest 1819 passed（+14 ledger 测试）；ruff/mypy 全仓 clean；acceptance 11/11。

#### M07-W02 已闭环证据（R-20260813-M07-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M07-W02-01 | cursor advancement 与全部 transaction facts/projection 变更单事务提交；注入 crash 只留旧完整态或新完整态 | `TransactionCursorStore.advance`（`test_oanda_transaction_cursor.py`）：facts + projections + gap rows + cursor upsert 全部在一个 BEGIN/COMMIT 内；在 cursor 写入点注入 crash（连接代理抛异常）→ ROLLBACK → cursor 保持旧值、facts 表零部分行、projections 不变 |
| AC-M07-W02-02 | duplicate/overlapping 幂等；missing/nonmonotonic/corrupt/account-mismatched 触发 bounded range recovery 并冻结 unresolved gaps | overlapping 页 → 已消费 ID 幂等忽略（facts_duplicated 计数、表内仅 1 行）；missing → cursor 停在最高连续 frontier（首洞 sealed，后续连续段不越过）、OPEN gap 落表；nonmonotonic（≤cursor）→ 忽略；corrupt（非 digit）→ corrupt_fact 且零部分提交（连合法前导 fact 也不落）；`recover_range`（account-scoped fetcher）bounded attempts：填补后 frontier 越过全部已见 fact；超过 ceiling 仍 OPEN → FROZEN，span 内 fact 再到达 → gap_frozen；account mismatch（fetch 为空）→ FROZEN；整库 freeze → 一切 advance frozen |
| AC-M07-W02-03 | restart 从最后提交的 OANDA transaction ID 恢复，绝不用 wall-clock 或最新部分响应 | advance [101,102,104,105] → cursor=102（103 缺失）；关库重开 → cursor=102（broker ID digit string，非时间戳）；补 103 后 → cursor=105；部分响应 108 存在但 103-107 缺失 → cursor 绝不到 108 |

范围说明：本 round 无 allowlist 外路径；targeted 测试文件为契约声明的缺失
文件，按既有先例创建（documented forced path）。full pytest 1831 passed
（+12 cursor 测试）；ruff/mypy 全仓 clean；acceptance 11/11。

#### M07-W03 已闭环证据（R-20260813-M07-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M07-W03-01 | golden transaction history 重建精确的 account/order/fill/trade/position/balance/NAV/margin/PnL/financing projections，带 broker ID 与 UTC 时间戳 | `AccountProjectionStore.rebuild` + `fold_facts`（`test_broker_remote_projection.py`）：golden history（DEPOSIT/CREATE/FILL/CANCEL/DAILY_FINANCING/REDUCE/CLOSE/WITHDRAWAL，10 条）→ 精确断言 balance=10903.13（seed+deposit-withdrawal+realized 3.20+financing -0.07）、realized_pl=3.20、financing_total=-0.07、order o-1 FILLED/o-3 CANCELLED、trade t-1 CLOSED(0 units)/t-2 OPEN(-500, open_time=UTC)、position short 500 @1.10000 unrealized=-4.50（mark=1.10900）、NAV=10898.63、margin_used=500×1.10000×0.05、fills 带 fact_id + UTC 时间戳；rebuild 后重读与首建完全一致；未知 kind 构造期拒绝 |
| AC-M07-W03-02 | full snapshot + incremental changes 与全部 facts 的干净重放收敛到同一 normalized projection | `apply_changes`（`test_account_projection_store.py`）：Path A 干净重放全量 vs Path B rebuild(full) + apply_changes(delta) → 归一化投影（exclude rebuilt_at）完全相等；多次增量 batch 累加同样收敛；balance/NAV/margin/unrealized/open counts/orders/trades/positions/fills 逐项相等；持久化 authority 与干净重放一致 |
| AC-M07-W03-03 | API/CLI/scheduler readers 解析同一持久化 account authority，不能暴露冲突的 process-local portfolio state | `resolve_account_snapshot(account_id, db_path)`：三个 reader 全部解析同一 store 文件 → 快照逐位一致；两个 store 实例同文件读写（writer 写入 → 另一实例立即读到相同 authority），零 process-local 分歧 |

范围说明：本 round 无 allowlist 外路径；两个 targeted 测试文件为契约声明的
缺失文件，按既有先例创建（documented forced path）。margin 采用确定性
DEFAULT_MARGIN_RATE=0.05；unrealized 以 facts 中最新观察到价格（fill/reduce/
close）为 mark。full pytest 1839 passed（+8 projection 测试）；ruff/mypy
全仓 clean；acceptance 11/11。

#### M07-W04 已闭环证据（R-20260813-M07-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M07-W04-01 | 匹配 fixtures 与合法的 pre-existing 远端 orders/trades/positions/financing/broker-originated state 无 false missing-local 告警 reconcile | `Reconciler`（`test_broker_reconciliation_matrix.py`）：完全匹配 fixture（orders o-1/o-2 FILLED、trades t-1/t-2 OPEN、position long 1000/short 200、balance/NAV/margin/financing/cursor 精确）→ report.clean=True；无 client identity 的远端 order/trade/position → 一律 INFO（broker-originated，report 仍 clean）；OrderLedger 可解释的 clientExtensions.id → 零告警 |
| AC-M07-W04-02 | unknown/missing/conflicting/money/quantity/state/cursor/account/order/fill/trade/position/financing 差异产生稳定 typed diffs，带 source ID 与 severity | 全矩阵逐类断言：未解释 client identity 的远端 order → order_diff CRITICAL（source_id=o-rogue-1）；本地 order/trade 在 broker 缺失 → order_diff/trade_diff CRITICAL；整个 position 消失 → position_diff CRITICAL；state 冲突（FILLED vs CANCELLED）→ state_diff CRITICAL；units 冲突 → quantity_diff CRITICAL（source_id 精确）；balance 短缺 → money_diff CRITICAL、financing 差异 → money_diff、fills 缺失 → fill_diff CRITICAL；cursor 落后本地 → cursor_diff CRITICAL / 领先 → INFO；account ID 不符 → account_diff CRITICAL |
| AC-M07-W04-03 | Decimal/timestamp tolerances 显式、versioned、directionally safe，不能隐藏 material exposure/cash/margin/position 差异 | `ReconcileTolerances(tolerance_version="2026-08-13.1", money=0.01, quantity=0, timestamp=5s)` 显式进 report；balance 短缺 0.005（容差内）→ WARN 仍告警、短缺 9.95 → CRITICAL；remote 更富（windfall）→ 仅 INFO；quantity 零容忍——1 unit 差异即 CRITICAL；margin 双向 material——remote margin 高于本地（低估风险）→ CRITICAL；version 可替换（.2）且随 report 记录 |

范围说明：本 round 无 allowlist 外路径；`test_broker_reconciliation_matrix.py`
为契约声明的缺失文件，按既有先例创建（documented forced path）；既有
`test_reconciliation.py` 全绿。full pytest 1852 passed（+13 reconcile 测试）；
ruff/mypy 全仓 clean；acceptance 11/11。

#### M07-W05 已闭环证据（R-20260813-M07-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M07-W05-01 | 每个 blocking diff、unresolved transaction gap、stale remote snapshot、failed resync、corrupt projection 在下一次 new-exposure submit 之前产生一条 deduplicated durable freeze | `ExposureFreezeStore.freeze_new_exposure`（`test_broker_freeze.py`）：六类 alarm（blocking_diff/unresolved_gap/stale_snapshot/resync_failed/corrupt_projection/cursor_failure）各落一条持久化 FROZEN 记录（DuckDB `exposure_freezes`，UTC 时间戳）；`ensure_new_exposure_allowed` 在任一 active freeze 下抛 `FreezeActiveError` 阻断新开仓；同 (account, reason, detail) 重复告警幂等去重——返回同一 freeze_id、active 计数不增长；不同 detail 是独立 freeze；关库重开（restart）后 freeze 仍在且继续阻断 |
| AC-M07-W05-02 | unfreeze 要求 fresh successful full sync、零 blocking diffs、cursor 与 projection hash 匹配、alerts 已解析，以及不可变的 reason 和 evidence 记录 | `ExposureFreezeStore.unfreeze`（`test_broker_freeze.py`）：五项检查（fresh_sync_ok / blocking_diffs==0 / cursor_match / projection_hash_match / resolved_alerts）任一项不满足 → `UnfreezeDeniedError`（列出全部 failing 项），active freeze 零解除、`exposure_unfreezes` 零写入；全部满足 → 全部 FROZEN 转 UNFROZEN 并在 `exposure_unfreezes` 追加不可变 evidence（event_id 单调、完整 policy 快照 + reason + unfrozen_at）→ 之后 `ensure_new_exposure_allowed` 恢复放行 |
| AC-M07-W05-03 | 重复 reconcile/unfreeze 命令幂等；任何 API、CLI、scheduler、model 或 fallback 路径都不能靠 omission 或确认提示清除 freeze | 无 active freeze 时重复 unfreeze 是静默 no-op（history 不增长）；unfreeze 五项检查默认值全部为拒绝值——省略任一检查即 `UnfreezeDeniedError`（省略 blocking_diffs → "blocking diffs not verified"，而非 TypeError）；store 无 clear/dismiss/ignore/confirm_unfreeze/acknowledge 任何 API（`hasattr` 逐一断言）；unfreeze 后同 alarm 复发生成新 freeze_id（detail 的 sha256 前 12 位 digest + occurrence sequence），绝不因主键冲突被 `INSERT OR IGNORE` 吞掉而静默丢失 freeze |

范围说明：本 round 的 `freeze_policy.py` 与 `test_broker_freeze.py` 为契约声明
的缺失文件（上一会话遗留 untracked 文件，recovery audit 唯一归属 M07-W05）。
修复两个实现缺陷后全绿：freeze_id 原只含 account+reason，不同 detail 主键
冲突且 unfreeze 后复发告警被吞；unfreeze 原要求全部显式参数，省略即
TypeError 而非 fail-closed。既有 `test_reconciliation.py` 全绿。full pytest
1860 passed（+8 freeze 测试）；ruff/mypy 全仓 clean；acceptance 11/11。

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
