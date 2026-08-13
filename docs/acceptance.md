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

#### M07-W06 已闭环证据（R-20260813-M07-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M07-W06-01 | 在 reserve 前、reserve 后、send 前、send 后、response 后、fact commit 期间、cursor advance 期间、reconciliation 期间注入 crash 都确定性恢复，且不产生第二个外部订单 | `SubmitWorkflow`（新 `oanda/submit_recovery.py`，`test_oanda_restart_recovery.py`）：八个 fault point（before_reserve/after_reserve/before_send/after_send/after_response/during_fact_commit/during_cursor_advance/during_reconciliation）逐一注入 `InjectedCrash`，然后以新进程实例（同一 durable 文件重开 ledger/cursor/freeze/orders）重跑 → 全部 COMPLETED、`broker.post_count==1`、`len(broker.orders)==1`、reservation_count==1、event 链恰为 [RESERVED, BIND, SUBMIT_ATTEMPT, BROKER_RESULT]、cursor=6001（幂等 advance）、零残留 freeze；after_send 崩溃后订单在 broker 侧 → 重启按 client identity 查询解析（captured[-1] 是 GET）而非重下单；send 失败且 broker 从未收到 → 查询判定 NOT_SUBMITTED → ledger FROZEN + 新开仓 freeze，restart 仍 FROZEN、post_count 不增长；查询本身失败 → UNRESOLVED → FROZEN（unresolved_gap freeze 落库）；无 resolver → 同样 FROZEN |
| AC-M07-W06-02 | 100 次同 cycle 跨全新进程重放最多产生一个外部 submit identity 和一条可解释的 terminal ledger chain | `test_100_same_cycle_replays_across_fresh_processes`（`test_oanda_restart_recovery.py`）：100 个迭代各建全新 OrderLedger/TransactionCursorStore/ExposureFreezeStore/OrderOpsClient/SubmitWorkflow 实例（同一 db 文件）→ 首轮 reused=False、其后 99 轮全部 reused=True 且 COMPLETED；最终 `broker.post_count==1`、`len(broker.orders)==1`、reservation_count==1、event 链 [RESERVED, BIND, SUBMIT_ATTEMPT, BROKER_RESULT]（零额外 event）、`completed_mappings()=={submit_id: broker_order_id}` 精确等于 broker 唯一订单；不同 decision 重放 → `identity_collision`（`LedgerTransitionError`）且原 COMPLETED 不被覆盖、post_count 不增长 |
| AC-M07-W06-03 | API reconcile、CLI reconcile、scheduler startup、periodic reconciliation 调用同一 durable service，绝不返回无条件 all-match placeholder 或询问如何恢复 | API `POST /api/v1/broker/reconcile` 改为调用同一 `ReconciliationRunner`（`apps/api/.../routes/broker.py`）：live（mock）adapter 下执行真实 broker 读取——远端未知 client identity 订单 → orders_match=False、all_match=False、快照持久可见（`test_broker_reconcile_runs_real_pass_with_live_adapter`，`test_broker_api_live.py`）；无凭证 null adapter → 显式 non-matching 快照（diff.error=broker_not_configured），eod 不 freeze、startup/cycle 按 policy freeze（`test_broker_reconcile_fails_closed_without_credentials`，`test_broker_api.py`；`test_null_adapter_*`，`test_reconciliation.py`）。CLI `broker reconcile`（API 离线）用同一 runner（`test_cli_broker_reconcile_fails_closed_without_credentials`，`test_broker_cli.py`；`test_reconcile_cmd_fails_closed_offline_without_credentials`，`test_broker_commands.py`）。scheduler startup 与 periodic（cycle）scope 本就调用同一 runner；全路径无 input()/确认提示 |

范围说明：本 round 实现 `oanda/submit_recovery.py`（SubmitWorkflow +
StartupSyncService + resolve_in_flight）与 `OrderLedger.in_flight_reservations()/
completed_mappings()` 只读查询；API/CLI reconcile 从占位快照切换为同一
durable runner；`ReconciliationRunner` 对 null adapter fail closed。进度数据
修正：M07-W05 更新 progress 时把 `current.milestone_id` 从 M02 改为 M07，
破坏确定性 selection gate（`test_autonomous_loop_state_machine.py` 硬编码 M02
期望且不在本 round allowlist），按 M07-W01..W05 既有约定恢复为 M02。CLI
测试 fixture 强制清空 OANDA 凭证环境变量（防开发者本机真实凭证泄漏进
subprocess）。full pytest 1881 passed（+21 新测试）；ruff/mypy 全仓 clean；
acceptance 11/11。

#### M07-W07 已闭环证据（R-20260813-M07-W07）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M07-W07-01 | 确定性套件证明 100 重放至多一个 submit、原子 cursor 恢复、正确 projections、合法远端状态处理、每一类注入 diff、freeze 规则，以及从每个 transition 的 restart | 六套 M07 组件套件全绿（targeted 63 passed）：`test_oanda_idempotency.py`（100 重放单一 identity）、`test_oanda_restart_recovery.py`（八个 fault point restart + 100 跨进程重放）、`test_oanda_transaction_cursor.py`（原子 cursor + gap recovery）、`test_broker_remote_projection.py`（golden projection 精确重建）、`test_broker_reconciliation_matrix.py`（每类注入 diff 的 typed severity）、`test_broker_freeze.py`（六类 alarm freeze + evidence-only unfreeze）；新增聚合链测试 `test_aggregate_restart_chain_reconciles_clean`（`test_oanda_reconciliation_e2e.py`）：crash after send → restart 按 query 解析（同一 broker_order_id、post_count==1）→ cursor 原子推进到 6001 → projection 重建（order FILLED、trade/position OPEN）→ 与合法远端视图 typed reconcile clean → 零残留 freeze |
| AC-M07-W07-02 | 受控 practice scenario 经历进程 restart，解析同一外部订单与 transactions，对账 account truth，清理 exposure，并存储脱敏 E5 hashes | T7 harness `test_controlled_practice_restart_scenario`（`test_oanda_reconciliation_e2e.py`）：有凭证时执行真实 practice 流程——SubmitWorkflow 提交最小风险订单 → 全新进程（同一 durable 文件）restart → reused=True 且同一 broker_order_id → transactions_since + cursor advance（facts_consumed≥1、零 gap）→ projection rebuild → 与 account summary/positions/orders 的真实远端视图 Reconciler clean → close trade cleanup → 写脱敏 E5 evidence（broker_order hash 与 transaction id hashes 各为 sha256 前 16 位，断言文件不含 token 与完整 account ID）。**无凭证 → 断言 ENVIRONMENT_BLOCKED 后返回，round 记录 `external_evidence_pending`（M07-W07 T7）**；mock 输出绝不冒充 practice evidence；M07 保持 CODE_COMPLETE |
| AC-M07-W07-03 | 缺凭证、unresolved remote state、nonzero blocking diff、cleanup 失败或外部 outage 使系统保持 frozen 或 ENVIRONMENT_BLOCKED，无 fallback、waiver、询问或 DONE | `test_missing_credentials_fail_closed_environment_blocked`：`PracticeScenarioRunner(client=None)` → ENVIRONMENT_BLOCKED，approved/broker_order_id/cleanup_result 全 None，detail 含 credential（无 fake fill、无 fallback、无询问）；`test_blocking_diff_and_unresolved_remote_state_freeze_never_done`：completed submit 后 blocking reconciliation diff → FROZEN（blocking_diff freeze 落库、ledger COMPLETED 不可变）；send 失败 + 查询失败（unresolved remote state）→ ledger FROZEN + 新开仓 freeze、post_count 恒 1（绝不盲重试）；cleanup 失败 → `PracticeScenarioRunner` FAIL 语义（M06-W07 已证，无 waiver）；静态扫描：所有 reconcile 入口（API/CLI/scheduler）共用 runner 的 null-adapter fail-closed 守卫，任何路径无 input()/确认提示 |

范围说明：`tests/test_oanda_reconciliation_e2e.py` 为 M07-W07 契约声明的
runtime 测试缺失文件，按 M07-W05 既有先例创建（documented forced path）；
本地确定性 gate 全绿，T7 practice 分支无凭证时断言 fail-closed 并记录
external_evidence_pending。full pytest 1885 passed（+4 E2E 测试，首轮一次
telemetry 测试 flake 后重跑全绿，与本 round 文件无关）；ruff/mypy 全仓
clean（328 source files）；acceptance 11/11。M07 里程碑 → CODE_COMPLETE，
下一 READY item：M08-W01。

#### M08-W01 已闭环证据（R-20260813-M08-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M08-W01-01 | context 包含 source IDs、capture times、freshness verdicts、account state、balance、NAV、margin、positions、pending orders、trades、bid/ask prices、conversions、catalog version、reconciliation state、health state | `BrokerRiskContext`（新 `alphabrief_risk/broker_context.py`，`test_risk_broker_context.py`）：frozen+extra=forbid+Decimal-only（float 构造即 ValueError）；`test_full_context_carries_every_required_field` 逐项断言 account state/tradeable/home currency、balance/NAV/margin、positions、pending orders、trades、bid/ask + spread、conversions、catalog_version、reconciliation_state、health_state、source_ids（account:… + captured:…，REQ-PLAT-009）、captured_at UTC、9 个 freshness verdict source（account/positions/pending_orders/trades/conversions/prices/catalog/reconciliation/health）与 `all_fresh`、`internally_consistent`；`BrokerRiskContextBuilder`（新 `alphabrief_execution/broker/risk_context.py`）以 injected `RiskContextSources` 端口组装并盖章共享 `context_version`/`policy_version`（"2026-08-13.1"） |
| AC-M08-W01-02 | AI execution、manual paper API execution 及其 backend calls 解析同一 context builder 与 policy version，而非 caller 自选 partial dictionaries | 唯一服务入口 `build_broker_risk_context` + `BrokerRiskContextBuilder` + 共享版本常量：AI 路径 `ExternalPaperExecutionBackend`（`alphabrief_trader/execution_backend.py`）默认经 `adapter_risk_sources(adapter)` 从同一服务构建 context（`test_ai_backend_submits_with_fresh_context` 断言 submit 成功且 result 记录 context_version）；manual 路径 `build_paper_risk_context`（`routes/paper.py`，venue 为 legacy in-memory broker 的 truthful sources）同样调用 `build_broker_risk_context`（`test_manual_paper_path_uses_same_service_and_versions` 断言两个路径产生同一 DEFAULT_CONTEXT_VERSION/DEFAULT_POLICY_VERSION 且 context 经 `project_risk_context_to_exposure` 投影进 RiskGate 的 `AccountExposureContext`）；旧 ad-hoc `build_account_exposure_context_from_portfolio` 的 pre-submit 调用被替换 |
| AC-M08-W01-03 | missing/stale/account-mismatched/partially persisted/frozen/internally inconsistent context 在 submit 前拒绝，无 synthesized defaults、fallback account、询问或 review bypass | builder 分类错误矩阵（`test_risk_broker_context.py`）：account source 缺失/异常 → missing_source；`expected_account_id` 不符 → account_mismatch；price 或 account 超过 venue freshness policy → stale；reconciliation=frozen → frozen；health=unhealthy → stale；持仓 symbol 无 price（coverage）或无 conversion → partial；margin identity 违反（nav-margin_used≠margin_available，容差 0.01）或 crossed price（bid>ask）→ inconsistent；catalog 缺失只如实记录 verdict 不拒绝、不合成版本；AI backend 在 adapter 不可达（get_account 抛错）、stale、frozen、unhealthy 时全部 `ExecutionBackendError` 且 adapter.requests==[]（`test_risk_execution_paths.py` 参数化 + adapter-unavailable 测试）；manual paper 路径缺 mark price 仍走既有 `_MissingMarkPriceError` fail-closed；无任何 input()/询问路径 |

范围说明：`alphabrief_risk/broker_context.py`、`alphabrief_execution/broker/risk_context.py`
为 M08-W01 契约声明的新模块（BrokerRiskContext 值对象 + BrokerRiskContextBuilder/
adapter_risk_sources/build_broker_risk_context/project_risk_context_to_exposure）；
`ExternalPaperExecutionBackend` 现在每个外部 submit 前强制 broker-fresh context
（REQ-RISK-010），manual paper route 的 pre-submit context 走同一服务。风险
gate 本身（`alphabrief_risk/gate.py`）零改动——context 只是 gate 的输入，无
bypass。full pytest 1908 passed（+23 新测试）；ruff/mypy 全仓 clean（332
source files）；acceptance 11/11。下一 READY item：M08-W02。

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

#### M08-W02 已闭环证据（R-20260813-M08-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M08-W02-01 | boundary/property 测试覆盖 allowed/unknown instruments、active/inactive、tradeable false、units 与 price precision、minimum size、maximum order units、maximum position size、normalized-zero quantity | `evaluate_instrument_rules` + `normalize_instrument_units/price`（新 `alphabrief_risk/instrument_rules.py`，`test_risk_instrument_constraints.py`）：15 条稳定 typed rule（catalog_known/catalog_active/broker_tradeable/session_open/quote_fresh/candle_complete/gap_bounded/conversion_present/pricing_coverage_complete/units_precision/price_precision/minimum_size/normalized_zero/maximum_order_units/position_cap）；合法输入全 pass；无 metadata 权威 → catalog_known + 全部 metadata-gated rule fail-closed（零合成）；evidence catalog_known=False → 只 fail catalog_known 而 precision rules 照常评估；inactive/tradeable false 各自 fail；units precision 0 拒绝 1.001、precision 1 接受 1.5 拒绝 1.55；price 超出 display_precision（1.105001 @ 5 位）拒绝、缺 price 拒绝；minimum size 边界（1 vs 10）；maximum_order_units/position_cap 边界（等于 cap 通过、超出失败、0=未配置永不拒绝）；units=0 → normalized_zero+minimum_size fail；负 units 按绝对值检查；相同 evidence 两次评估结果完全相等（确定性） |
| AC-M08-W02-02 | closed session、holiday、stale quote、stale catalog、incomplete candle、excessive gap、missing conversion、partial pricing coverage 以稳定 rule results 拒绝新开仓 | 参数化 evidence 矩阵（closed-session/holiday/stale-session-evidence/no-quote/stale-quote/incomplete-candle/excessive-gap/missing-conversion/partial-coverage 9 例）：每例恰好目标 rule fail、其余 14 条全部 pass（sum(failed)==1 断言稳定且定向）；stale catalog 经 inactive/unknown catalog evidence fail-closed；`MarketEvidence` frozen+extra=forbid，`InstrumentRuleResult` 携带 rule/passed/reason 供审计 |
| AC-M08-W02-03 | instrument normalization 在最终 risk evaluation 之前发生；任何 post-decision 的 units/price/instrument version/snapshot hash 变化使 decision 失效 | `normalize_instrument_units`（quantize 到 trade_units_precision，不可表示即 `InstrumentConstraintError(units_precision)`，绝不静默进位）与 `normalize_instrument_price`（可表示价格规范化，超精度拒绝 `price_precision`——静默舍入会改变订单语义）；`bind_execution_inputs`/`validate_execution_inputs` 把 (decision_id, symbol, units, price, instrument_version, snapshot_hash) 绑定为 sha256——任一字段变化 hash 即不同（5 组 mutation 逐一断言）；`RiskDecision.execution_input_hash`（可选字段，缺省 None 兼容既有构造）由 `ExternalPaperExecutionBackend.submit` 在 adapter.submit 前校验（`test_backend_refuses_post_decision_input_change`）：相同 inputs → 正常提交；quantity 变化 → `ExecutionBackendError` 且 adapter.requests 不增长（REQ-RISK-010） |

范围说明：`alphabrief_risk/instrument_rules.py` 为 M08-W02 契约声明的新模块；
`RiskDecision.execution_input_hash` 为向后兼容可选字段；backend 校验接入
M08-W01 的 context 服务（instrument_version=context.catalog_version、
snapshot_hash=context.captured_at.isoformat()）。RiskGate 本身零改动——本
层是独立确定性约束层，全部 fail-closed。full pytest 1934 passed（+27 新
测试）；ruff/mypy 全仓 clean（334 source files）；acceptance 11/11。下一
READY item：M08-W03。

#### M08-W03 已闭环证据（R-20260813-M08-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M08-W03-01 | property matrices 覆盖 long/short FX legs、Metal 与 CFD exposure、pending orders、hedged 与 netted positions、account-currency conversion、category totals、currency-direction totals、correlated groups、concentration | `compute_exposure`（新 `alphabrief_risk/exposure_aggregation.py`，`test_risk_exposure_matrix.py`）：long FX leg 10000×1.10×1.0=11000 home-currency gross；short leg 只计 short 侧（net 为负）；hedged（long=short=10000）→ net=0 而 gross=22000（双腿真实 notional）；CFD + pending order → pre 80000/post 120000 投影；`USD_JPY` 150.00×factor 0.00666667=100000.05 home conversion；category totals（CURRENCY 17500/METAL 40000）与 currency-direction totals（EUR/GBP/USD）按 home currency 聚合；correlated-group totals（euro-bloc/precious）带 source_id evidence trail（conversion/correlation evidence 逐 symbol/group 记录）；concentration=max(symbol gross/total gross)；leverage=gross/equity |
| AC-M08-W03-02 | single-order、symbol、category、direction、gross、net、leverage、concentration limits 对 projected post-trade exposure clamp/reject，Decimal-safe evidence | `evaluate_exposure_limits`（`test_risk_currency_aggregation.py`）：8 类 limit 全部对 post-trade snapshot 求值并产出稳定 typed `ExposureRuleResult`（limit/passed/value/ceiling/detail）；single-order notional 超限 reject、等于上限 pass、notional 缺失 fail-closed；symbol limit 只绑定 order symbol 的 post-trade gross；category（METAL 40000>20000 reject）、direction（long 51000≤60000 pass）、gross（51000>50000 reject）、net、leverage（0.51≤1 pass）、concentration（0.784>0.5 reject）逐一断言；全部 ceiling 满足时 8 条全 pass；无配置 limit → 零结果；value/ceiling 全部 Decimal 字符串化（无 float） |
| AC-M08-W03-03 | missing/stale/zero/inconsistent/unsupported conversion 与 correlation evidence fail closed，绝不 fallback 到 nominal units 或 cost basis | `ExposureError` 分类矩阵（`test_risk_currency_aggregation.py`）：缺 price → missing_price；缺 conversion → missing_conversion；conversion 超过 `conversion_max_age_seconds`（可注入 clock）→ stale_conversion；factor 零/负在 schema 构造期拒绝（gt=0，绝不进入计算）；缺 category/currency-direction evidence → missing_category/missing_currency_direction；配置了 correlation groups 时 symbol 必须恰属一组——零组或两组都 → unsupported_correlation；equity 零/负构造期拒绝；float 输入在构造期拒绝（Decimal-first）；全部计算以 mid×factor 进行，无 nominal/cost-basis 分支 |

范围说明：`alphabrief_risk/exposure_aggregation.py` 为 M08-W03 契约声明的新
模块（ExposureInputs 证据输入 + compute_exposure 快照 + evaluate_exposure_limits
限制求值）；全部 Decimal-safe、frozen、extra=forbid；`compute_exposure` 带可注入
clock 保证确定性。RiskGate 零改动。full pytest 1957 passed（+23 新测试）；
ruff/mypy 全仓 clean（337 source files）；acceptance 11/11。下一 READY
item：M08-W04。

#### M08-W04 已闭环证据（R-20260813-M08-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M08-W04-01 | boundary 测试覆盖 margin available/used、margin closeout proximity、projected leverage、realized+unrealized daily loss、rolling drawdown、high-water mark、day-start equity、consecutive losses | `evaluate_margin_loss_rules`（新 `alphabrief_risk/margin_loss_rules.py`，`test_risk_margin.py`/`test_risk_loss_drawdown.py`/`test_risk_consecutive_loss.py`）：margin_utilization（20000/100000=0.2≤0.5 pass、0.6 fail）、closeout_proximity（available/nav 0.8≥0.1 pass、0.05 fail）、projected_leverage（0.5≤1 pass、1.5 fail）、margin_fresh（299s pass/301s fail，可注入 clock）、daily_loss（day-start 与 equity_now 之差 0.03 边界、realized+unrealized 都经 equity_now 折入）、rolling_drawdown（窗口内 peak-vs-current 0.109≤0.2 pass、单点零回撤、0.3 fail）、drawdown_from_hwm（0.109≤0.2 pass、0.273 fail）、consecutive_losses（3≤3 pass、4 fail）；全部 Decimal-safe、frozen、extra=forbid |
| AC-M08-W04-02 | durable day/HWM 值 survive restart，且不能 reset、后退或被 current equity 替换以放宽 limit | `LossStateStore`（新 `alphabrief_risk/loss_state.py`，DuckDB）：HWM 只升不降（CAS `max(current, end)`——更低 equity 日无法把 HWM 拉低）；day-start per date first-write-wins（同日重放不同 day_start 被 `ON CONFLICT DO NOTHING` 拒绝，authoritative start 保持）；同一天更高 end equity 重放——day_start 不变、HWM 只可能上升、pnl 按权威 start 计算；关库重开（restart）后 HWM/day_start/streak 全部保留；无任何 API 能直接写 HWM/day-start（只有 evidence-backed `record_day_result`） |
| AC-M08-W04-03 | missing/stale margin、PnL、HWM、day-start、loss-streak、equity state 拒绝新开仓，绝不静默禁用已配置 rule | 分类 fail-closed：缺 day_start → daily_loss fail（"no day-start equity"）；缺 HWM → drawdown_from_hwm fail；空 rolling window → rolling_drawdown fail；streak=None → consecutive_losses fail（"no loss-streak state"）；projected_leverage=None 且配置 limit → fail（"no leverage evidence"）；margin 超过 evidence_max_age → margin_fresh fail；无配置 limit → 零结果（不产生禁用痕迹）；store 在首个 day 记录前所有读取返回 None → rule fail-closed |

范围说明：`alphabrief_risk/margin_loss_rules.py` 与 `alphabrief_risk/loss_state.py`
为 M08-W04 契约声明的新模块；`LossStateStore` 的 day-result/HWM/streak 语义
全部 CAS/evidence-backed（M08-W06 将接入 daily cycle 持久化链）；RiskGate
零改动。full pytest 1970 passed（+25 新测试）；ruff/mypy 全仓 clean（341
source files）；acceptance 11/11。下一 READY item：M08-W05。

#### M08-W05 已闭环证据（R-20260813-M08-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M08-W05-01 | boundary 测试覆盖 spread absolute/relative limits、quoted liquidity、projected slippage、high-impact event windows、affected currencies/categories、sentiment severity/coverage/disagreement/freshness/uncertainty | `evaluate_market_conditions`（新 `alphabrief_risk/market_conditions.py`，`test_risk_market_conditions.py`）：spread_absolute（0.00020≤0.0003 pass / 0.00050 fail）、spread_relative（0.000182≤0.001 pass / 0.009 fail）、liquidity（1e6≥1e6 pass / 5e5 fail）、slippage（0.001≤0.005 pass / 0.01 fail）、event_window（symbol/currency/category 任一命中且 now 在窗内 → reject；窗外或未命中 → pass）、sentiment_freshness（299s pass / 600s stale → clamp 0.5）、coverage（0.3<0.6 → clamp）、disagreement（0.9>0.5 → clamp）、uncertainty（0.9>0.5 → clamp）、sentiment_severity（-0.3<-0.2 → reject；-0.1 ≥ floor → pass）；全部 Decimal-safe、frozen、extra=forbid |
| AC-M08-W05-02 | context policy 确定性且 tighten-only；model score/narrative/committee confidence/external text 不能增大 size、放宽 rule 或修改 thresholds | `MarketConditionVerdict.tighten_only` 保证 size_multiplier ∈ [0,1]（reject=0 仍 tighten-only），`event_clamp_multiplier` 构造期限制 (0,1]（1.5 与 0 都 ValueError）；`test_no_free_text_inputs_exist` 断言五个 evidence model 均无 narrative/text/confidence/commentary 字段——evidence 只接受结构化 typed facts，无任何文本输入通道；全部 rule 仅由 limits 常量与 evidence 数值驱动，同一 evidence+limits 两次评估结果逐字段相等（确定性） |
| AC-M08-W05-03 | missing/stale critical market/content context → configured reject 或 conservative clamp，绝不 fabricated neutral score、disabled rule、fallback content 或询问 | critical market evidence（spread/liquidity/slippage）缺失或超限 → reject（multiplier 0，"critical evidence missing"）；配置 event policy 而无 event calendar → reject（"no event calendar; fails closed"）；sentiment 缺失/过期 → freshness/coverage/disagreement/uncertainty 各 clamp 到 `CONSERVATIVE_CLAMP_MULTIPLIER=0.5`（绝不伪造 neutral 分数），severity score 缺失 → reject；无配置 limit → 零结果（无禁用痕迹）；无任何 input()/询问路径 |

范围说明：`alphabrief_risk/market_conditions.py` 为 M08-W05 契约声明的新
模块；`tests/test_risk_market_conditions.py` 为契约声明的新测试文件（既有
`test_risk_context.py` 覆盖 M05 的 news/macro 层并保持全绿）；RiskGate
零改动。full pytest 1987 passed（+17 新测试）；ruff/mypy 全仓 clean（343
source files）；acceptance 11/11。下一 READY item：M08-W06。

#### M08-W06 已闭环证据（R-20260813-M08-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M08-W06-01 | kill switch、open freeze、stale broker、unresolved reconciliation diff、transaction gap、failed required backup、lost writer lease、unhealthy scheduler 各自以 distinct persisted rule result 阻止新开仓 | `evaluate_operational_blocks`（新 `alphabrief_risk/operational_blocks.py`，`test_risk_operational_blocks.py`）：8 个 condition（kill_switch/freeze/stale_broker/reconciliation_diff/transaction_gap/backup_failure/writer_lease/scheduler_health）各产出独立 typed `OperationalBlockResult`；参数化测试逐一断言单 condition 触发时恰该条 blocked=True 且 `blocking_conditions` 精确返回该 condition；全健康 → 零 blocked；`OperationalBlockStore`（DuckDB）按 condition 持久化最新 verdict（append-only、restart 后保留、每 condition 一条 latest），distinct persisted evidence；`require_evidence` 缺失 → fail-closed（"evidence missing; fails closed"），未要求项缺失 → "unverified" 且不 block（绝不伪造健康） |
| AC-M08-W06-02 | reduce-only 与 close 仅在可证明降低相关 position 与 gross risk 且满足 instrument/price/identity/audit rules 时允许 | `validate_reduce_only`（新 `alphabrief_risk/reduce_only.py`，`test_risk_reduce_only.py`）：long 10000@1.10 sell 2000 → permitted，pre_gross 11000 → post_gross 8800、reduced_by 2200（provable reduction）；short 5000 buy 1000 → permitted；full close 10000 → post_gross 0；`ReduceOnlyPreconditions`（identity/instrument_rules/price_fresh/audit_recorded）四项全真才可 permitted，任一失败 → reasons 列出 failing preconditions |
| AC-M08-W06-03 | mislabeled reduce、side reversal、over-close、exposure-increasing dependent order、stale quantity、missing position truth 全部 fail closed，reduce-only 不能当 bypass | 逐一断言：preconditions 失败 → 拒绝；long 仓 buy / short 仓 sell → "side reversal"；units>position → "over-close"；dependent_increases_exposure → "increases exposure"；position 快照超过 position_max_age_seconds → "stale"；long=short=0 → "no position truth to reduce"；reduced_by≤0（不降 gross）→ 拒绝；float 输入构造期 ValueError；全部 verdict 携带 reasons tuple 供审计 |

范围说明：`alphabrief_risk/operational_blocks.py` 与 `alphabrief_risk/reduce_only.py`
为 M08-W06 契约声明的新模块；`OperationalBlockStore` 的持久化语义与 M07-W05
freeze store 一致（deduplicated latest-per-condition、restart-safe）。RiskGate
零改动。full pytest 2005 passed（+18 新测试）；ruff/mypy 全仓 clean（347
source files）；acceptance 11/11。下一 READY item：M08-W07。

#### M08-W07 已闭环证据（R-20260813-M08-W07）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M08-W07-01 | 每个 decision 在执行前持久化 immutable rule order、inputs/policy hashes、source IDs、timestamps、approved flag、max quantity、reasons、tags、context freshness、decision expiry | `RiskDecisionStore`（新 `alphabrief_risk/decision_store.py`，`test_risk_decision_store.py`）：`RiskDecisionRecord` 全字段持久化并 round-trip 逐项断言（decision/intent/account id、approved、reason、max_quantity Decimal、risk_tags、policy_hash、inputs_hash、snapshot_hash、rule_results、source_ids、context_freshness、created_at、expiry_at、consumed/consumed_at）；duplicate persist INSERT-OR-IGNORE——同 decision_id 二次 persist（含 approved=False/inputs mutated）返回 False 且原记录零变化（append-only，无更新 API）；consume 为 CAS（第二次 consume False、unknown id False、consumed_at 落 UTC）；`is_expired` 确定性（301s 后 expired、无 expiry 永不过期）；restart（关库重开）后记录与 consumed 状态完整保留；float max_quantity 构造期拒绝 |
| AC-M08-W07-02 | missing/rejected/expired/consumed/account-/policy-/intent-/snapshot-mismatched/quantity-exceeding decisions 在 network submit 前被 backend 拒绝 | `DecisionBindingService.validate_before_submit`（新 `alphabrief_risk/decision_binding.py`，`test_risk_decision_binding.py`）：13 个分类拒绝逐一断言——missing（未 persist）、rejected（approved=False）、expired（expiry 已过）、consumed（执行后二次执行）、account_mismatch、policy_mismatch（policy hash 不同）、intent_mismatch、inputs_mismatch（post-approval quantity 变化→hash 不同）、snapshot_mismatch（显式提供不同 snapshot hash 时）、quantity_exceeds（quantity>max_quantity）、stale_context（approval 时 context 不 fresh）；valid 时 consume 恰好一次（二次执行 → consumed）；duplicate persist 保留 first record（retry 不能改写 inputs） |
| AC-M08-W07-03 | AI 与 manual paper 路径调用同一 decision-binding service 与 backend invariant；caller 不能构造 executable approval boolean 或 mutate inputs after approval | `ExternalPaperExecutionBackend.submit`（`alphabrief_trader/execution_backend.py`）与 manual paper route（`routes/paper.py`）都经 `DecisionBindingService`（默认 store 位于 M01-W04 runtime data dir authority）persist + validate；backend 从不信任 caller 的 approved 字段——validation 以 persisted record 为准，且 decision.execution_input_hash（approval 时绑定）与 request 的 `hash_inputs(symbol, units, price)` 不一致时在 persist 前即拒绝（`test_backend_refuses_post_decision_input_change` 更新为 3-component hash：同 quantity 通过、变更 quantity 拒绝且 adapter.requests 不增长）；`hash_inputs`/`hash_policy` 为共享确定性函数；test_ai_trader_scheduler 与 test_ai_trader_execution_backend 的 daily-cycle 测试经 backend 默认 binding 全绿（隔离 ALPHABRIEF_DATA_DIR fixture 防泄漏到真实数据目录） |

范围说明：`alphabrief_risk/decision_store.py` 与 `alphabrief_risk/decision_binding.py`
为 M08-W07 契约声明的新模块；backend 的 M08-W02 inline execution_input_hash
检查升级为 persisted-record validation（hash 组件统一为 symbol/units/price 三
元组）；paper route 增加同一 binding service 的 persist+validate；所有测试
强制 ALPHABRIEF_DATA_DIR 隔离（用户机器上有运行中的 scheduler 持有真实
DuckDB 锁，测试绝不触碰真实数据目录）。full pytest 2017 passed（+14 新
测试）；ruff/mypy 全仓 clean（350 source files）；acceptance 11/11。下一
READY item：M08-W08。

#### M08-W08 已闭环证据（R-20260813-M08-W08）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M08-W08-01 | property/boundary/combination/restart/mutation suites 覆盖每条 REQ-RISK rule，AI 与 manual 路径使用 identical fresh context、rule evaluation、persisted decisions、backend binding | M08 全部九套确定性套件聚合运行（targeted 117 passed）：broker context（M08-W01）、instrument constraints（W02）、exposure matrix/currency aggregation（W03）、margin/loss drawdown/loss streak（W04）、market conditions（W05）、operational blocks/reduce-only（W06）、decision binding/store（W07）——每条 REQ-RISK-001..010 都有 boundary/combination/restart（store 重开）/mutation（inputs hash 变更）覆盖；AI 路径（`ExternalPaperExecutionBackend`）与 manual 路径（`routes/paper.py`）的 parity 由 `test_risk_execution_paths.py`/`test_paper_execution.py`/`test_ai_trader_execution_backend.py` 聚合证明（34 passed）：同一 context 服务、同一规则求值、同一 decision-binding service、同一 backend invariant |
| AC-M08-W08-02 | SAFE-005/006 通过；受控 practice scenario 证明 approved decision→order 链与 rejected/stale/mismatched 零 unauthorized submits | SAFE-005：`test_safe_005_order_has_persisted_consumed_decision`——backend submit 后 store 中必有 approved+consumed 的 decision record，adapter 恰好收到 1 单；SAFE-006：`test_safe_006_rejected_and_consumed_decisions_never_submit`（approved=False / already-consumed 两例，adapter.requests==[]）、`test_safe_006_stale_decision_never_submits`（expired record → ExecutionBackendError）、`test_safe_006_mismatched_inputs_never_submit`（post-approval quantity 变更 → 拒绝且零 submit）；`test_controlled_practice_risk_chain`（T7 harness，`tests/test_risk_oanda_practice_e2e.py`）：有凭证时 approved decision 经真实 OANDA adapter 提交并 consume、rejected decision 零 unauthorized submits（adapter mapping 计数不变）、写脱敏 E5 evidence（sha256 hashes，无 token/account id）；**无凭证 → 断言 ENVIRONMENT_BLOCKED 后记录 `external_evidence_pending`（M08-W08 T7）**，M08 保持 CODE_COMPLETE |
| AC-M08-W08-03 | 缺凭证、stale account truth、unresolved freeze、failed cleanup、external outage 保持 blocked，无 mock pass、waiver、fallback、询问或 milestone DONE | `test_missing_credentials_fail_closed`：`PracticeScenarioRunner(client=None)` → ENVIRONMENT_BLOCKED（approved/broker_order_id/cleanup 全 None，detail 含 credential）；stale context/blocking diff/freeze/unresolved 覆盖由 M08-W01/W05/W06 套件继承（context builder stale/frozen 拒绝、operational blocks 8 条件、reduce-only preconditions）；M08 里程碑 = CODE_COMPLETE 而非 DONE（T7 pending），静态扫描确认无 fallback/waiver/询问路径 |

范围说明：`tests/test_risk_oanda_practice_e2e.py` 为 M08-W08 契约声明的 runtime
测试缺失文件（按 M07-W05 既有先例创建，documented forced path）；本地
deterministic gate 全绿（SAFE-005/006、缺凭证 fail-closed），T7 practice
risk-chain 分支无凭证时断言 fail-closed 并记录 external_evidence_pending。
M08 里程碑 → CODE_COMPLETE。full pytest 2024 passed（+7 E2E 测试）；
ruff/mypy 全仓 clean（351 source files）；acceptance 11/11。下一 READY
item：M09-W01。

#### M09-W01 已闭环证据（R-20260813-M09-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M09-W01-01 | fixture ingestion 为每个 attempted item 持久化 source、canonical URL、published/fetched UTC times、language、content hash、summary、fetch outcome、correlation ID | `NewsIngestionService` + `IngestedNewsItem` + `NewsIngestionStore`（新 `alphabrief_news/ingestion.py`，`test_news_ingestion.py`）：success fixture 逐字段断言（item_id=source:headline_id、canonical_url 保留完整 URL、published_at/fetched_at UTC round-trip（TIMESTAMPTZ 同 instant）、language=en、content_hash=sha256 hexdigest、summary 原文、fetch_outcome=success、correlation_id、metadata_only=False）；store DuckDB append-only 持久化（records() 全字段返回）、duplicate persist 幂等（第二次返回 0、记录数不变）、records survive（同库重开）；content hash 确定性（同 headline 相同、改 title 不同） |
| AC-M09-W01-02 | success、empty response、timeout、rate-limit、malformed response、source failure 产生 distinct durable outcomes，不伪造 headlines | 参数化 7 例：empty（空列表→empty）、network_error/http_error→timeout、rate_limited→rate_limit、parse_error/invalid_config→malformed、no_api_key→source_failure——每例 outcome 精确且 items==()（零伪造 headline）、store 无记录（失败不落假数据）；未分类异常（TimeoutError）→ timeout 分类 |
| AC-M09-W01-03 | metadata-only source 永不持久化 licensed full text，只保留 permitted metadata 与 bounded summaries | `SourceLicensePolicy(metadata_only=True, max_summary_chars=20)`：summary 截断至 20 字符（"The European Central"）、metadata_only=True 落库；`IngestedNewsItem` 与 store record 均无 full_text/body 字段（`model_fields` 与 records() 键断言）；无任何 full-text 持久化通道（REQ-NEWS-008） |

范围说明：`alphabrief_news/ingestion.py` 为 M09-W01 契约声明的新模块；既有
`tests/test_news_store.py`/`tests/test_news.py` 全绿（news store 层未改动）。
full pytest 2036 passed（+7 新测试）；ruff/mypy 全仓 clean（353 source
files）；acceptance 11/11。下一 READY item：M09-W02。

#### M09-W02 已闭环证据（R-20260813-M09-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M09-W02-01 | tracking parameters、URL aliases、identical content hashes、bounded title similarity 把确定性重复折叠进一个 canonical cluster | `canonicalize_url` + `dedup_verdict` + `cluster_news`（新 `alphabrief_news/dedup.py`，`test_news_deduplication.py`）：canonicalize 剥离 utm_*/fbclid/gclid/mc_* 与 fragment、归一 scheme/host 大小写、去默认端口与尾部斜杠；tracking 变体同 canonical URL → duplicate（rule=canonical_url）；URL alias（尾斜杠）→ duplicate；相同 content_hash → duplicate（rule=content_hash）；bounded title similarity（Jaccard ≥0.85）且同 source、summary 相同（claims 一致）、published gap ≤1h → duplicate（rule=title_similarity）；`cluster_news` 输入序稳定输出 (representative, members) 簇（h-1 收编 h-2/h-3、独立 h-4 自成一簇）；`title_similarity` 确定性（相同 1.0、不同 <1.0、空 1.0） |
| AC-M09-W02-02 | claims 或 viewpoints 实质不同的报道即使 title 与 entities 重叠也保持独立 | title 相似但 summary 不同（"opposition grows"/"market reaction"）→ `distinct`（title similarity 单独永不合并）；重叠 entities + 不同 viewpoint 的 cluster 保持两簇；不同 source 相同 claims → 不合并（title_similarity 规则要求同 source）——每条规则确定性且可审计（rule/rule_version 落 verdict） |
| AC-M09-W02-03 | 每个 entity link 记录 entity type、normalized identifier、matching rule version、confidence、originating evidence ID | `link_entities`（新 `alphabrief_news/entity_linking.py`，`test_news_entity_linking.py`）：symbol → instrument 链接（normalized=upper、confidence=1.0、rule_version=2026-08-13.1、evidence_id 透传）；dictionary alias 命中 → currency/country/company/asset_class/market 链接（confidence=0.8）；大小写不敏感匹配（STERLING→GBP）；无符号且无 alias → 零链接；相同输入两次评估完全相等（确定性） |

范围说明：`alphabrief_news/dedup.py` 与 `alphabrief_news/entity_linking.py` 为
M09-W02 契约声明的新模块；既有 `tests/test_news_store.py`/`tests/test_news.py`
全绿。full pytest 2051 passed（+15 新测试）；ruff/mypy 全仓 clean（357
source files）；acceptance 11/11。下一 READY item：M09-W03。

#### M09-W03 已闭环证据（R-20260813-M09-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M09-W03-01 | macro fixtures 以 UTC 持久化 release time、actual、forecast、previous、revision、importance、unit、source、affected currencies/markets | `MacroRelease` + `MacroReleaseStore`（新 `alphabrief_news/macro_release.py`，`test_macro_ingestion.py`）：fixture 逐字段断言（release_time UTC round-trip、actual/forecast/previous Decimal、revision、importance、unit、source、affected_currencies/markets、version=1、lineage=()）；duplicate ingest INSERT-OR-IGNORE 幂等；float 构造期拒绝；`releases()` 按 release_time 再 release_id 排序 |
| AC-M09-W03-02 | revised observation 追加带 lineage 的新 version，prior value 保持可重建 | `revise` 追加 version n+1（revision=True、lineage=(release_id,)）；`versions()` 升序返回全部版本——v1 actual=4.00 与 v2 actual=3.75 同时可重建（`test_versions_reconstruct_prior_values`）；unknown release_id → None（不伪造）；restart 后版本与 lineage 完整保留（`test_store_survives_restart_with_revisions`）；`releases()` 只返回每 release 的最新版本 |
| AC-M09-W03-03 | API 与 CLI fixture 查询返回 identical ordered macro events，并显式暴露 missing/stale/partial/revised states | `release_state` 五态（fresh/partial/stale/revised/missing——revised=version>1、partial=无 actual、stale=partial 且超过窗口、missing=无记录）；API `GET /api/v1/macro/releases` 与 CLI `macro releases` 读同一 store、同一排序、同一 state（`test_macro_api.py`/`test_macro_commands.py` 各自断言相同 ids 顺序与 states 映射：stale-cpi→stale、ecb-rate→fresh、us-cpi→partial、gbp-rate→revised）；API `POST /api/v1/macro/releases/revise` 追加版本并使视图转 revised、unknown → 404 |

范围说明：`alphabrief_news/macro_release.py` 为 M09-W03 契约声明的新模块；
`tests/test_macro_ingestion.py`/`test_macro_store.py`/`test_macro_api.py`/
`test_macro_commands.py` 为契约声明的缺失测试文件（按 M07-W05 先例创建，
documented forced paths）；routes/macro.py 与 macro_commands.py 的 release
端点/命令为契约声明的 API/CLI surface。full pytest 2068 passed（+17 新
测试）；ruff/mypy 全仓 clean（362 source files）；acceptance 11/11。下一
READY item：M09-W04。

#### M09-W04 已闭环证据（R-20260813-M09-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M09-W04-01 | 每个 sentiment aggregate 暴露 direction、intensity、disagreement、sample count、source coverage、freshness、uncertainty、evidence IDs、algorithm version | `aggregate_sentiment` + `SentimentAggregate`（新 `alphabrief_news/sentiment_aggregate.py`，`test_sentiment_snapshot.py`）：三样本三源 fixture 逐字段断言（direction=positive、intensity=0.533…、disagreement=0.466…、sample_count=3、source_coverage=1、freshness_seconds=0.0、uncertainty≤1、coverage_sufficient=True、evidence_ids=(h-1,h-2,h-3)、algorithm_version=2026-08-13.1、snapshot_hash=sha256 hexdigest）；multi-scope（market/currency/asset_class/instrument）各自独立聚合 |
| AC-M09-W04-02 | 相同 evidence 重排产生 byte-equivalent normalized output 与相同 snapshot hash | 输入按 (scope, scope_value, evidence_id) 排序后才计算——shuffled 输入两次聚合 `model_dump(mode="json")` sort_keys 后逐字节相等、snapshot_hash 相同；evidence 变化（direction 翻转）→ snapshot_hash 不同 |
| AC-M09-W04-03 | sparse/contradictory/stale/single-source fixtures 产生显式 uncertainty 或 insufficient-coverage verdict，而非 confident defaults | sparse（1 样本）→ coverage_sufficient=False、direction=mixed、uncertainty≥0.75；single-source（3 样本同源）→ 同上（min_sources=2）；contradictory（+1/-1/+1 三源）→ disagreement≥0.6 且 |mean|≤0.4 → mixed（非 confident majority）；stale（2 天旧）→ freshness=172800s、insufficient、uncertainty≥0.75；float intensity 构造期拒绝 |

范围说明：`alphabrief_news/sentiment_aggregate.py` 为 M09-W04 契约声明的新模块；
`tests/test_sentiment_snapshot.py` 为契约声明的缺失测试文件（documented
forced path）；既有 `tests/test_sentiment.py`（RuleBasedSentimentAnalyzer）
全绿未改动。full pytest 2077 passed（+10 新测试）；ruff/mypy 全仓 clean
（364 source files）；acceptance 11/11。下一 READY item：M09-W05。

#### M09-W05 已闭环证据（R-20260813-M09-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M09-W05-01 | 每条外部文本 fragment 在模型使用前携带 untrusted-evidence marker、source identity、content hash、bounded sanitized representation | `sanitize_external_text`（新 `alphabrief_news/untrusted.py`，`test_news_untrusted_content.py`）：`SanitizedEvidence` 全字段断言（untrusted=True、source、content_hash=sha256 of sanitized form、sanitized_text bounded、original_length、neutralized_instructions、sanitization_version）；chars bound（10000 词 → ≤1000 且 "..." 结尾）、paragraph bound（50 段 → ≤10）；空文本/空 source → `UntrustedContentError` fail-closed；相同输入两次评估完全相等（确定性） |
| AC-M09-W05-02 | prompt-injection fixtures 不能改变 system instructions、risk limits、execution settings、evidence boundaries、tool permissions | `_INSTRUCTION_PATTERNS` 确定性中和（ignore/disregard any instructions、you are now、system prompt、`<system>` 开闭标签、new system instructions、override risk policy、ignore the risk gate、call the tool/broker(）——替换为 `[NEUTRALIZED-EXTERNAL-INSTRUCTION]` 且计数；`test_prompt_injection.py` 七组 injection fixtures 逐一断言指令语法消失、neutralized_instructions≥1、untrusted=True；system/risk/tool 指令组合 fixture 断言头部与 tool-call 语法不存活且 fragment 保持 untrusted+bounded（系统边界在 ModelGateway——外部文本永不可执行） |
| AC-M09-W05-03 | sanitization logs 不含 token、authorization header、完整 account ID、prohibited full article、executable external instruction | `_SECRET_PATTERNS` 红action（Bearer、Authorization header、OANDA account ID `\d{3}-\d{3}-\d{7,}-\d{3}`、api_key/token/secret）→ `[REDACTED]`；`build_sanitization_log` 只含 source/content_hash/original_length/sanitized_length/neutralized_instructions/version（无正文、无 secret——rendered payload 逐一断言不含 abc12345/Basic/account ID/super-secret） |

范围说明：`alphabrief_news/untrusted.py` 为 M09-W05 契约声明的新模块；
`tests/test_news_untrusted_content.py` 与 `tests/test_prompt_injection.py` 为
契约声明的缺失测试文件（documented forced paths）。full pytest 2090 passed
（+13 新测试）；ruff/mypy 全仓 clean（367 source files）；acceptance 11/11。
下一 READY item：M09-W06。

#### M09-W06 已闭环证据（R-20260813-M09-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M09-W06-01 | snapshot 在一个 immutable version ID 与 hash 下记录 news、macro、sentiment、entity-link、quality、freshness、source-version IDs | `build_regime_snapshot` + `RegimeSnapshot`（新 `alphabrief_news/regime_snapshot.py`，`test_market_regime_snapshot.py`）：snapshot_id==version_id（"regime-v1-{hash[:16]}"）、content_hash=sha256 of normalized payload；news/macro/sentiment/entity_link_ids、quality_verdicts、freshness_verdicts、source_versions（排序的 (source, version) 对）全部落 snapshot；相同输入 → 相同 id/hash/逐字段相等；输入变化 → id 变化；`RegimeSnapshotStore` DuckDB append-only、duplicate persist 幂等、restart 后完整保留 |
| AC-M09-W06-02 | partial-source failure 与 stale critical coverage 产生确定性 degraded/blocked verdicts 带 missing-source reasons，绝不合成 replacement facts | `DegradationPolicy(critical_sources, critical_input_kinds)`：全部 source ok → healthy；非关键源失败 → degraded（reason "macro-b: fetch failed, missing, or stale"）；关键源失败 → blocked（即使其他源 ok）；非 fresh 的 freshness verdict（kind∈critical_input_kinds）→ blocked、否则 degraded（reason "news (stale): ..."）；missing 只记录 reason——news_ids 等输入 ID 永不合成（断言 news_ids 保持原样）；相同输入两次构建 verdict/hash 完全一致 |
| AC-M09-W06-03 | research context 与 news-risk context 以同一 snapshot ID 加载得到 identical evidence 与 quality verdicts | `RegimeSnapshotStore.get(snapshot_id)` 是共享 authority——research_view 与 risk_view 从同一 ID 解析出逐字段相等的 snapshot（quality_verdicts/degradation/content_hash/source_versions 全部一致）；store 持久化后任意消费者（同一进程或 restart 后）解析同一不可变记录 |

范围说明：`alphabrief_news/regime_snapshot.py` 为 M09-W06 契约声明的新模块；
`tests/test_market_regime_snapshot.py` 与 `tests/test_news_degradation.py` 为
契约声明的缺失测试文件（documented forced paths）；`test_risk_news_context.py`
不存在（M09-W07 gate 轮处理），integration 层以既有 sentiment/research
context 套件运行。full pytest 2101 passed（+11 新测试）；ruff/mypy 全仓
clean（370 source files）；acceptance 11/11。下一 READY item：M09-W07。
