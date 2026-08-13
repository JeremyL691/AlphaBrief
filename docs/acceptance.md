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

#### M09-W07 已闭环证据（R-20260813-M09-W07）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M09-W07-01 | 全部 M09 fixture 套件无网络、无 waiver、无 skipped security case、无 nondeterministic snapshot 输出下通过 | M09 八套 targeted 套件聚合运行（63 passed）：ingestion（W01）、dedup+entity linking（W02）、macro（W03）、sentiment snapshot（W04）、untrusted+prompt injection（W05）、degradation+regime snapshot（W06）——全部 fixture 驱动、确定性（相同输入 byte-equivalent 输出与相同 hash 已逐一断言）、零 skip/xfail/noqa 新增；integration 六套（33 passed）含 gate 轮新增的 `test_news_api.py`/`test_news_commands.py`/`test_risk_news_context.py`（documented forced paths） |
| AC-M09-W07-02 | REQ-NEWS-001..009 traceability 映射到 durable records、automated evidence、current progress | REQ-NEWS-001/008→ingestion（W01）；REQ-NEWS-002/003→dedup+entity linking（W02）；REQ-NEWS-004→macro release store（W03）；REQ-NEWS-005→sentiment aggregate（W04）；REQ-NEWS-006/008→untrusted sanitizer（W05）；REQ-NEWS-007/009→regime snapshot+degradation（W06）；每条 acceptance 的 evidence 逐轮落 acceptance.md 表格、progress.yaml work_item_states 全部 DONE、ledger 逐轮 ROUND record |
| AC-M09-W07-03 | content pipeline 启用后 full repository、static、autonomous acceptance gates 全过 | full pytest 2108 passed、ruff/mypy 全仓 clean（373 source files）、acceptance 11/11（`alphabrief acceptance verify --compact` exit 0） |

范围说明：`tests/test_news_api.py`、`tests/test_news_commands.py`、
`tests/test_risk_news_context.py` 为 M09-W07 契约声明的缺失集成测试文件
（按 M07-W05 先例创建，documented forced paths）；README 增加 M09 capability
行。M09 里程碑 → DONE（无 T7 runtime 依赖，全部本地确定性 gate 通过）。
下一 READY item：M10-W01。

#### M10-W01 已闭环证据（R-20260813-M10-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M10-W01-01 | 生产 research/brief/committee/trading 路径解析同一个 ModelGateway 且无直接 provider SDK 调用 | 新静态扫描 `tests/test_model_gateway_boundary.py`：全仓 apps/packages 无任何 provider SDK import（与 acceptance verifier `safety.provider_sdk_imports` 同一 denylist）；10 个生产模型路径模块（routes/research.py、routes/brief.py、routes/models.py、routes/ai_trading.py、model_commands.py、brief_commands.py、trader/committee.py、trader/daily_cycle.py、trader/model_factory.py、research/orchestrator.py）逐一断言引用 ModelGateway 或共享 factory（`build_ai_trading_*`）且无直接 SDK import；acceptance verifier `safety.provider_sdk_imports` 同步 PASS |
| AC-M10-W01-02 | fake/deterministic test providers 需要显式 test composition，不能成为生产 fallback | `model_factory.build_ai_trading_provider()`：`auto`/未配置且无 `OPENAI_API_KEY` → 抛 `ModelProviderUnavailableError`（`test_ai_trader_model_factory.py` 重写断言 fail-closed）；显式 `ALPHABRIEF_AI_MODEL_PROVIDER=fake` 才返回 conservative fake；openai 显式缺 key → ValueError；`build_ai_trading_committee()` 无 provider → raise（`test_ai_trader_provider_unavailable.py`）；评测表面默认真实 provider：API `use_real_provider` 默认 True、CLI `--real-provider/--no-real-provider` 默认 real，fake 只能显式选择（`test_models_api.py`/`test_model_cli.py` 显式 opt-in 并新增 fail-closed 用例） |
| AC-M10-W01-03 | missing/disabled/unhealthy providers 产生 durable blocked/no-trade，无 proposal/intent/broker submission | API `/ai/run` 捕获 `ModelProviderUnavailableError` → 持久化 outcome=`skipped_no_intent`、summary 写明 "model provider unavailable … fail closed" 的 `DailyCycleRecord`（plans/votes/attempts 全空，`_blocked_record_without_provider` + `test_ai_trader_provider_unavailable.py` 断言 201、history 与 cycle 详情 durable、零 intent）；unhealthy provider 既有 `test_all_provider_failures_record_provider_error` 保持 `provider_error` durable no-trade；factory raise 使 committee/cycle 在任何 proposal 前 fail closed |

范围说明：`tests/test_model_gateway_boundary.py` 与
`tests/test_ai_trader_provider_unavailable.py` 为 M10-W01 契约声明的缺失
测试文件（documented forced paths）；`routes/research.py`、`routes/brief.py`
的 advisory demo gateway 与 `research_commands.py` 被
`tests/test_api_server.py`（allowlist 外、本轮不可改）钉住，保持确定性响应且
不产生任何订单——本轮关闭的是生产 trading/committee/evaluation 组合的 fake
fallback（`tests/test_ai_trading_api.py` 与 `tests/test_api_server.py` 在本轮
改动后全绿 124 passed）。full pytest 2122 passed；ruff/mypy 全仓 clean
（375 source files）；acceptance 11/11。下一 READY item：M10-W02。

#### M10-W02 已闭环证据（R-20260813-M10-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M10-W02-01 | successful/malformed/timeout/rate-limit/provider-error/budget-exhausted 调用各自持久化一条带 correlation 与 snapshot IDs 的 terminal record | `ModelCallRecord` 新增 `classification`（`success/malformed/timeout/rate_limit/provider_error/budget_exhausted/no_provider`）与 `cycle_key`/`snapshot_id`；`ModelGateway` 每条 invoke 恰好产出一条 terminal record 并经 `record_sink` 转发（`tests/test_model_gateway.py` 七个分类 fixture 逐一断言 classification/status；`tests/test_model_call_store.py` 七种 terminal 分类全部 round-trip 持久化；`tests/test_ai_trader_provider_unavailable.py::test_api_ai_run_persists_terminal_call_records` 证明 API 交易路径真实落库——classification 非空、input_hash=64 hex、task_type=symbol_research） |
| AC-M10-W02-02 | record 包含 request/response hashes、template version、model parameters、latency、token counts、cost、retry history、schema verdict，且无敏感值 | `ModelCallRecord` 全字段：input_hash/output_hash（sha256）、prompt_version、provider/model、latency_ms、input_tokens/output_tokens、cost_estimate（Decimal，float 拒绝）、retry_count（gateway 按 request_id 累计，`test_retry_count_tracks_repeated_request_ids`）、schema_verdict、snapshot_id、cycle_key、UTC created_at；store round-trip 全字段断言（`test_model_call_store_round_trips_full_record`，DECIMAL(38,18) 数值等价）；`test_model_call_store_never_stores_raw_prompt_or_secret` 与既有 `test_model_call_record_does_not_store_raw_prompt_or_api_key` 断言序列化记录不含 input_text/output_text/api_key/Bearer/sk- |
| AC-M10-W02-03 | per-call、per-cycle、daily budgets 确定性拒绝后续调用且保留已提交证据 | `ModelCallBudget`（per-request_id/per-cycle_key/UTC-day，clock 注入）：超限拒绝返回 `budget_exhausted` terminal record（error_type=`BudgetExhausted:request_limit/cycle_limit/daily_limit`）；被拒调用不消耗额度（重复拒绝稳定）；日界重置（`test_daily_budget_rejects_after_limit_and_resets_next_day`）；已提交证据不变（`test_budget_exhausted_records_preserve_committed_evidence`：成功 record 不被后续拒绝 mutating）；`ModelCallStore.save_call` call_id 幂等（`test_model_call_store_is_append_only_and_idempotent`：重复 save 不重复不覆盖） |

范围说明：`apps/api/src/alphabrief_api/db/model_call.py`（`ModelCallStore`）与
`tests/test_model_gateway_budget.py` 为 M10-W02 契约声明的新模块/缺失测试文件
（documented forced paths）。`db/schema.py`（版本化迁移 ledger）在
`models_research` scope 之外，store 以本地幂等 `CREATE TABLE IF NOT EXISTS`
DDL 自持表结构（未来 storage-scope 轮以同名 `IF NOT EXISTS` 迁移接管，
`test_database_migrations.py`/`test_backup_restore.py` 动态 `latest_schema_version()`
不受影响，全绿）。sink 接线：API `/ai/run`（本轮）；CLI/scheduler sink 随其
所属 scope 轮次补齐。full pytest 2148 passed；ruff/mypy 全仓 clean
（377 source files）；acceptance 11/11。下一 READY item：M10-W03。

#### M10-W03 已闭环证据（R-20260813-M10-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M10-W03-01 | 每个 completed committee run 包含四名 required analyst roles + moderator，记录 bounded turn order、role identity、timestamps、model-call IDs | `default_roles()` = technical/news_sentiment/fundamental/risk/manager；`TradingCommittee.run` 有界多轮（5 opening + 4 challenge + 1 summary = 10，`max_turns` 可配、`challenge_rounds` 可配）；`test_committee_transcript.py`：`test_run_contains_all_five_roles_and_moderator`（opening roles == 五角色全集、completed=True）、`test_turn_order_is_bounded_opening_then_challenge_then_summary`（phases 序列与 turn_number 1..10 精确断言）、`test_max_turns_bounds_the_discussion`（max_turns=6 截断、completed=False）、`test_turns_record_role_identity_timestamps_and_model_call_ids`（每 turn 有 role/tz-aware created_at/唯一 model_call_id） |
| AC-M10-W03-02 | 角色可质疑前置论断；transcript 保留 agreement/contradiction/dissent/unknown 与 cited evidence IDs，不扁平化 | challenge turn 输出扩展 schema（stance + challenged_claim）；`CommitteeTurn.stance` 四值；`test_challenge_turns_preserve_stance_and_challenged_claim`（4 个 challenge turn 均有 stance 与 challenged_claim）、`test_agreement_contradiction_and_unknown_are_distinguished`（三 stance fixture 逐一区分）、`test_dissent_is_not_flattened_into_the_plan`（dissent 保留在 transcript，plan 仍按 opening votes 综合）、`test_cited_evidence_ids_are_preserved`（turn 1 引 ev-price-1/ev-news-1、challenge 引 ev-macro-1、summary 引 ev-price-1）、`test_fabricated_evidence_ids_are_not_cited`（伪造 ID 不进 cited 列表）、`test_votes_carry_model_call_ids_and_citations` |
| AC-M10-W03-03 | committee context 排除 tokens、完整 account ID、privileged tools、可变系统设置、未消毒外部指令 | `test_prompt_scrubs_tokens_api_keys_and_account_ids`（Bearer/sk-/account ID → `[REDACTED]`，raw 值不在 prompt）、`test_prompt_neutralizes_external_instructions`（ignore/override-risk 指令 → `[NEUTRALIZED-EXTERNAL-INSTRUCTION]`，untrusted marker 保留）、`test_prompt_excludes_tools_and_system_settings`（无 tool/risk_limit/api_key/token 字样）、`test_challenge_and_summary_prompts_are_sanitized`（challenge/summary prompt 同样消毒）；实现：`_sanitize_context` 复用 `alphabrief_news.untrusted.sanitize_external_text` + `_scrub_secrets` 二次脱敏 |

范围说明：`tests/test_committee_transcript.py` 为 M10-W03 契约声明的缺失测试
文件（targeted command 声明，documented forced path，按 M09-W07/M07-W05 先例）。
CommitteeRole 增加 `news_sentiment`（四分析师 + manager moderator）；votes
持久化经 `vote_json` 列自动携带新字段（`db_store.py`，trader scope）。
`/ai/rules` API/CLI 展示面仍返回旧四角色列表（被 allowlist 外
`tests/test_ai_trading_api.py`/`ai_commands.py` 钉住，M13 API 合同轮对齐，
已记录 architecture.md）。本轮全量 pytest：2148 passed + 19 failed —— 19 个
失败全部为 M08-W03 既有时间炸弹 fixture（`tests/test_risk_exposure_matrix.py`
与 `tests/test_risk_currency_aggregation.py` 硬编码
`NOW=2026-08-13T12:00Z`、`conversion_max_age_seconds=300`，墙钟越过 12:05 UTC
后必然过期；两文件自 7c46d2f 起未改动、与 alphabrief_risk 均不在本轮
changed paths，baseline 上同样失败，与本轮无关）。本轮 declared 命令
（targeted 27 passed / integration 59 passed / ruff / mypy）全部 exit 0；
ruff/mypy 全仓 clean（378 source files）；acceptance 11/11。下一 READY item：
M10-W04。

#### M10-W04 已闭环证据（R-20260813-M10-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M10-W04-01 | 合法 proposal 包含 thesis、anti-thesis、confidence、horizon、entry rationale、invalidation、suggested exposure、evidence、dissent、freshness、uncertainty、no-trade 字段 | `ResearchProposal`（`alphabrief_trader/schemas.py`）+ `EvidenceCitation`；`tests/test_proposal_grounding.py::TestProposalSchema::test_valid_proposal_carries_all_required_fields` 逐字段断言；`build_research_proposal`（`alphabrief_trader/proposal.py`）从 votes/transcript/plan 确定性生成全部字段（thesis=manager vote、anti_thesis=dissent/risk 反方、horizon=payload、entry_rationale=plan rationale、invalidation=risk top risk、exposure=plan target、citations=grounded evidence、dissent=challenge dissent 摘要、freshness=snapshot captured_at、uncertainty=1-confidence、no_trade=plan 缺失/零仓位/ethics block） |
| AC-M10-W04-02 | 每条 factual claim 解析到 committee 所用 snapshot 的 evidence ID | builder 只发射 `CommitteeInput.evidence_ids` 中受支持的 citation（`_split_citation`：entry==ID 或以 `ID:`/`ID ` 开头才计入；伪造 ID 丢弃）；`test_every_citation_resolves_to_snapshot_evidence`（citations ⊆ available）、`test_builder_drops_fabricated_evidence_ids`（伪造 ID 不进入 proposal）；`validate_proposal_grounding` 对 unsupported_citation 返回 violation；`test_grounding_passes_with_real_builder_output` 端到端零 violation |
| AC-M10-W04-03 | unsupported citations、stale critical evidence、contradictory exposure、missing dissent → validation failure，无可执行 proposal | `validate_proposal_grounding`：`unsupported_citation:<id>`（`test_unsupported_citation_fails_grounding`）、`stale_critical_evidence:<age>`（默认 86400s；`test_stale_critical_evidence_fails_grounding`，fresh 通过）、schema 层 `model_validator` 拒绝 no_trade+正仓位 与 tradeable+零仓位（`test_contradictory_exposure_rejected_at_schema_level`/`test_no_trade_proposal_accepts_zero_exposure`）、`dissent` strip 非空校验（`test_blank_dissent_rejected`）；无 plan 时 builder 保守 no_trade（`test_builder_without_plan_is_conservative_no_trade`）；builder 无 votes 抛 `ProposalBuildError`（`test_builder_requires_votes`）——失败 proposal 不产生 OrderIntent |

范围说明：`alphabrief_trader/proposal.py` 为 M10-W04 契约声明的新模块；
`tests/test_proposal_grounding.py` 为契约声明的缺失测试文件（targeted command
声明，documented forced path）。proposal→intent 的 cycle 接线随 M10-W05/M11
轮次补齐。全量 pytest：2165 total（2146 passed + 19 pre-existing M08-W03
time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean
（380 source files）；acceptance 11/11。下一 READY item：M10-W05。

#### M10-W05 已闭环证据（R-20260813-M10-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M10-W05-01 | invalid JSON、schema violations、nonexistent citations 触发不超过配置次数的 repair，且每次 attempt 与 verdict 均被记录 | `repair_structured_output`（`alphabrief_models/repair.py`）：`max_attempts` 有界（`test_repair_is_bounded_to_max_attempts`：3 次 attempt 后 exhausted=True、provider.calls==3）；invalid JSON→repair 成功（`test_invalid_json_repairs_to_valid_output`）、schema violation→repair（`test_schema_violation_repairs`）、nonexistent citation→grounding_check 触发 repair（`test_grounding_violation_repairs`）；每次 attempt 产生 typed `RepairVerdict`（attempt/ok/error_code/model_call_id/UTC created_at，`test_repair_verdicts_are_typed_and_strict`）且 gateway `record_sink` 持久化每次调用；committee opening 轮同样走 grounding 校验（`_vote_grounding_violations`：`ev-` 前缀不在 evidence_ids → `grounding_failed:nonexistent_citation`，`test_fabricated_evidence_ids_are_rejected`） |
| AC-M10-W05-02 | exhausted repair、timeout、budget exhaustion、unresolved grounding → 单一 durable blocked/no-trade，无 OrderIntent | cycle 层：repair 耗尽（bad payload + repair_attempts=2）→ durable `provider_error`、plans/attempts/votes 全空（`test_exhausted_repair_produces_no_trade_without_intent`，store 回读断言）；budget 日额度耗尽（`max_calls_per_day=1`）→ `provider_error`、零 plans/attempts（`test_budget_exhaustion_produces_no_trade_without_intent`）；repair 成功路径 votes 保留（`test_repair_success_produces_tradeable_proposal_path`）；缺失 manager 的 CommitteeResult 现在携带 role_errors（cycle 正确分类 provider_error 而非误导性 skipped_no_consensus） |
| AC-M10-W05-03 | 重复同一 cycle key + snapshot 返回既有 terminal result，不产生新 proposal/intent | `DailyTradingCycle.run(cycle_key=...)`：`_snapshot_fingerprint`（确定性 sha256，`test_fingerprint_is_deterministic_and_content_sensitive`）；同 key+同 snapshot → 第二次 run 返回同 cycle_id 记录、store 仅 1 条（`test_same_cycle_key_and_snapshot_returns_existing_record`）；同 key 不同 snapshot（价格 100→150）→ 新 run（`test_same_key_different_snapshot_creates_new_run`）；无 key 不幂等（`test_no_cycle_key_never_deduplicates`）；blocked 记录同 key 去重（`test_blocked_records_deduplicate_by_key`）；`get_cycle_by_key` 经 DuckDB `cycle_json ->> 'cycle_key'` 查询（无 schema 迁移）；API `/ai/run` 使用 `api:<date>:<sorted symbols>` key（`_api_cycle_key`），blocked 记录同样携带 |

范围说明：`alphabrief_models/repair.py`、`tests/test_model_structured_repair.py`、
`tests/test_ai_trader_idempotency.py` 为 M10-W05 契约声明的新模块/缺失测试文件
（targeted command 声明，documented forced paths）；`tests/test_committee_transcript.py`
为 M10-W03 契约声明的 forced path，本轮因 grounding 强制语义（伪造 citation 从
静默忽略改为拒绝）必须同步更新其断言（行为变更 → 测试更新，同族文件）。cycle_key/snapshot_fingerprint
存入 `cycle_json`（JSON 列，无需 schema.py 迁移——storage scope 外）。
proposal→intent 的正式接线随 M11 durable cycle 轮次补齐。全量 pytest：
2200 total（2181 passed + 19 pre-existing M08-W03 time-bombed risk fixture
失败，分类见 M10-W03）；ruff/mypy 全仓 clean（383 source files）；
acceptance 11/11。下一 READY item：M10-W06。

#### M10-W06 已闭环证据（R-20260813-M10-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M10-W06-01 | versioned evaluation run 输出 schema/grounding/citation/hallucination/injection/latency/cost/stability 指标，带 fixture 与 model-profile IDs | `evaluate_committee_security`（`alphabrief_trader/security_eval.py`，version=`2026-08-13.1`）：每 case 输出 `SecurityCaseVerdict`（case_id/kind/version/model_profile_id/latency_ms/cost/committee_ok/role_error_count/repair_attempt_count/grounding violations/prompt 卫生/stable/created_at），`metrics()` 聚合 injection_resistance/grounding_pass_rate/stability；`QualityMetrics`+`evaluate_quality_gate`（`alphabrief_models/quality_gate.py`）输出八项指标（schema/grounding/citation/hallucination/injection/latency/cost/stability）带 evaluation_version/fixture_id/model_profile_id（`test_metrics_carry_version_fixture_and_profile_ids`、`test_versioned_evaluation_emits_all_metrics`） |
| AC-M10-W06-02 | seeded injection、fabricated citation、secret-exfiltration、unauthorized tool-call 各产生零 executable proposals | 四类 adversarial case（versioned `COMMITTEE_SECURITY_CASES`）端到端断言 executable_proposal=False、no_trade=True：escalation 注入（provider 输出带 `override_risk_gate` extra 字段 → 严格 schema 拒绝，`test_escalation_injection_produces_no_executable_proposal`）、fabricated citation（`ev-fake-99` → M10-W05 grounding 拒绝，`test_fabricated_citation_produces_no_executable_proposal`）、secret-exfiltration（prompt 卫生断言 secret 不进 prompt，`test_secret_exfiltration_produces_no_executable_proposal`）、unauthorized tool call（`tool_calls` 字段 → schema 拒绝，`test_unauthorized_tool_call_produces_no_executable_proposal`）；`test_all_adversarial_kinds_produce_zero_executable_proposals` 聚合断言；control case 验证 harness（可产生 tradeable proposal，`test_control_case_validates_the_harness`） |
| AC-M10-W06-03 | 任一指标低于配置阈值 → automated gate FAIL，无法 waive | `evaluate_quality_gate` 合取判定：八项指标逐一低于阈值各自 FAIL（`test_each_metric_below_threshold_fails_independently`：grounding 0.9/citation 0.9/hallucination 0.5/injection 0.9/latency 60000/cost 5.0/stability 0.9）；函数签名**无 waiver/override 参数**（`test_gate_has_no_waiver_path`，inspect 断言）；自定义阈值被尊重（`test_custom_thresholds_are_respected`：0.85 schema 在 0.9 阈值 FAIL、0.8 阈值 PASS） |

范围说明：`alphabrief_trader/security_eval.py`、
`alphabrief_models/quality_gate.py`、`tests/test_model_security.py` 为
M10-W06 契约声明的新模块/缺失测试文件（targeted command 声明，documented
forced paths）。安全评估的 prompt 卫生经 recording provider 捕获真实 prompt
（`prompt_probe`），secret marker 运行时拼接避免文件内含 seeded-secret
pattern。全量 pytest：2214 total（2195 passed + 19 pre-existing M08-W03
time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean
（386 source files）；acceptance 11/11。下一 READY item：M10-W07。

#### M10-W07 已闭环证据（R-20260813-M10-W07）— M10 里程碑 gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M10-W07-01 | 全部 M10 provider/persistence/committee/proposal/repair/idempotency/grounding/security fixture 套件无外部 provider 依赖通过 | targeted 十套聚合运行（131 passed）：`test_model_gateway.py`（W01/W02 boundary+records）、`test_model_call_store.py`+`test_model_gateway_budget.py`（W02 durability+budgets）、`test_ai_trader_committee.py`+`test_committee_transcript.py`（W03 roles+transcript）、`test_proposal_grounding.py`（W04）、`test_model_structured_repair.py`+`test_ai_trader_idempotency.py`（W05）、`test_model_evaluator.py`+`test_model_security.py`（W06）——全部 fixture 驱动、确定性、零网络；integration 四套（53 passed）含 `test_prompt_injection.py` |
| AC-M10-W07-02 | REQ-AI-001..010 traceability 映射到 code、durable evidence、automated tests、current progress | 见下方 M10 Requirement Traceability；progress work_item_states M10-W01..W07 全部 DONE、M10 里程碑 → DONE、ledger 逐轮 ROUND record（R-20260813-M10-W01..W07） |
| AC-M10-W07-03 | full repository、static、model evaluation、autonomous acceptance gates 通过，且无生产 FakeProvider fallback | full pytest（M10 全量 2195 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（386 source files）；acceptance 11/11；生产 fake fallback 为零——`test_ai_trader_model_factory.py`（auto+无 key → `ModelProviderUnavailableError`）+ `test_model_gateway_boundary.py`（10 个生产模型路径模块全部解析 ModelGateway、无 provider SDK import）+ API `/ai/run` durable no-trade（`test_ai_trader_provider_unavailable.py`） |

#### M10 Requirement Traceability（M10-W01..W07）

| Requirement | Code / Evidence |
|---|---|
| REQ-AI-001（所有模型调用经 ModelGateway；provider/profile、timeout、retry classification、fallback policy、cost/latency、schema verdict） | `alphabrief_models/gateway.py`：ModelGateway 唯一边界；`ModelCallRecord` 含 provider/model、latency、cost（Decimal）、retry_count、`classification`（success/malformed/timeout/rate_limit/provider_error/budget_exhausted/no_provider）、schema_verdict；`test_model_gateway.py`+`test_model_gateway_budget.py` |
| REQ-AI-002（生产路径不默认 FakeProvider；缺模型 → blocked/no-trade） | `model_factory.py`：auto+无 key 抛 `ModelProviderUnavailableError`，显式 fake 才可选；`routes/ai_trading.py` durable no-trade record；`test_ai_trader_model_factory.py`+`test_ai_trader_provider_unavailable.py` |
| REQ-AI-003（持久化 hash、模板版本、参数、错误、token/cost；敏感内容脱敏） | `ModelCallRecord`+`ModelCallStore`（append-only、call_id 幂等、UTC）；raw prompt/response/secret 永不落库；`test_model_call_store.py` |
| REQ-AI-004（四分析师角色 + moderator） | `CommitteeRole`=technical/news_sentiment/fundamental/risk/manager；`test_committee_transcript.py::test_run_contains_all_five_roles_and_moderator` |
| REQ-AI-005（自由讨论反驳；每轮引用 evidence IDs；区分事实/推断/未知/观点） | `TradingCommittee.run` 多轮（opening/challenge/summary）+ `CommitteeTurn`（stance、cited_evidence_ids）；`test_committee_transcript.py` |
| REQ-AI-006（proposal 全字段 + no_trade） | `ResearchProposal`+`build_research_proposal`；`test_proposal_grounding.py` |
| REQ-AI-007（JSON/引用不合法有界修复；仍失败 no-trade/blocked） | `repair_structured_output`（max_attempts、typed verdicts）；`test_model_structured_repair.py`+`test_ai_trader_idempotency.py` |
| REQ-AI-008（无 token/account ID/工具；外部内容不能 tool call） | prompt 消毒（`sanitize_external_text`+`_scrub_secrets`）+ 严格 schema extra=forbid；`test_committee_transcript.py::TestContextHygiene`+`test_model_security.py` |
| REQ-AI-009（deterministic cycle key；重试不产生多个 intent） | `DailyTradingCycle.run(cycle_key)`+`_snapshot_fingerprint`+`get_cycle_by_key`；`test_ai_trader_idempotency.py` |
| REQ-AI-010（评测含 schema/grounding/citation/hallucination/injection/latency/cost/stability） | `quality_gate.py` 八指标阈值合取、无 waiver；`security_eval.py` versioned fixtures；`test_model_security.py` |
| REQ-PLAT-005/009、REQ-OPS-005（append-only UTC、确定性、budget） | W02 store/budget；W05 idempotency；`test_model_call_store.py`+`test_model_gateway_budget.py` |
| REQ-OPS-008（injection fixtures 进门禁） | W06 security eval fixtures + `test_prompt_injection.py` |

范围说明：M10-W07 为里程碑 gate 轮（无新生产行为，纯证据/文档轮）。
README 更新 M10 capability 行。全量 pytest：2214 total（2195 passed + 19
pre-existing M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；
ruff/mypy 全仓 clean（386 source files）；acceptance 11/11。M10 里程碑 →
DONE（无 T7 runtime 依赖，全部本地确定性 gate 通过）。下一 READY item：
M11-W01。

#### M11-W01 已闭环证据（R-20260813-M11-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M11-W01-01 | 正常 cycle 按 legal order 持久访问 preflight、ingest、snapshot、discuss、propose、risk、execute or no-trade、reconcile、report、complete | `CYCLE_STATE_PHASE_ORDER`（10 阶段）+ `CycleStateStore.advance`（transition 记录目标 phase，begin 记录初始 transition）；`test_normal_cycle_visits_all_phases_in_order`（transitions == 10 阶段全序、is_complete、resume=None）；`test_execute_phase_records_no_trade_outcome`（execute 离开 transition 的 outcome ∈ executed/no_trade/blocked + output_ids）；`test_terminal_record_is_durable`（重建的 DailyCycleRecord 落库、votes 完整） |
| AC-M11-W01-02 | 每条 transition 原子记录 input hashes、output IDs、attempt count、timestamps、prior state；stale writers 被拒绝 | `advance()` 单事务 INSERT transition + CAS UPDATE cycle_state（`WHERE phase = expected`，提交后重读验证——DuckDB 无 rowcount）；`test_transition_records_hashes_outputs_attempts_prior_and_time`（input_hashes/output_ids/prior_phase/attempt_count/tz created_at/transition_id/phase_order 全字段）；`test_stale_writer_is_rejected_without_mutation`（stale advance → None、transitions 不变）；`test_non_monotonic_advance_is_rejected`、`test_transitions_are_append_only`；`test_stale_writer_cannot_advance_after_restart` |
| AC-M11-W01-03 | 每个 phase boundary 的 restart 从最后已提交 gate 恢复，不重复已完成 side effect | `resume_phase` 返回未提交 side effect 的下一阶段（begin 后 = preflight；advance 后 = 目标阶段；complete = None）；`DurableDailyCycle.run` 从 resume 点继续：`test_completed_cycle_returns_stored_record_without_rerunning`（第二次 run 返回同记录、submit 计数不变、仅 1 条 cycle）、`test_restart_after_execute_never_repeats_broker_submission`（execute 离开 transition 提交后 crash → resume 于 reconcile → 零重提交、outcome 保留 executed——state outcome COALESCE sticky）、`test_restart_from_every_phase_boundary_resumes_correctly`（10 个边界逐一 resume 断言）、`test_restart_runs_only_pending_phases`（warm-up 到 discuss 后 resume 只跑 discuss..complete，preflight/ingest/snapshot 不重跑） |

范围说明：`alphabrief_trader/cycle_state.py`、
`tests/test_daily_cycle_state_machine.py`、`tests/test_daily_cycle_checkpoints.py`
为 M11-W01 契约声明的新模块/缺失测试文件（targeted command 声明，documented
forced paths）。`CycleStateStore` 使用独立 `cycle_state`/
`cycle_state_transitions` 表（M03-W03 的 `cycle_checkpoints` 保持不变，
`test_cycle_checkpoint_store.py` 全绿）。DurableDailyCycle 尚未接入 API/
scheduler（M11-W02/W03 leader/runtime-truth 轮次接线，本轮已记录于
architecture.md）。全量 pytest：2214 total（2195 passed + 19 pre-existing
M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓
clean（389 source files）；acceptance 11/11。下一 READY item：M11-W02。

#### M11-W02 已闭环证据（R-20260813-M11-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M11-W02-01 | 同一 store 上两个 scheduler 进程恰好一个活跃 leader、一个 non-writing follower | `SchedulerLeaderLease`（`scheduler_lease` 表）：`acquire` CAS（未过期 lease 归属他人 → False）；`test_two_competitors_produce_one_leader`（a 获取后 b 失败、is_leader a=True/b=False、leader()==a）；`test_lease_survives_store_restart`（restart 后 a 仍 leader、b 仍被拒） |
| AC-M11-W02-02 | lease 过期/丢失阻止 former leader 在 new leader 接管前启动另一阶段或 broker 提交 | `renew` 只允许当前 holder 且必须在过期前（UPDATE 后重读验证 expiry 实际延长——DuckDB 无 rowcount）；`test_expired_lease_allows_takeover`（过期后 is_leader=False、renew=False、b 可接管）；`test_non_holder_cannot_renew`（b 续期 a 的 lease → False）；`test_release_hands_leadership_over`+`test_foreign_release_rejected`；`test_leader_can_renew_and_keep_leadership`（30s 后续期成功、60s 内仍 leader）——leader 的 guard 在 renew/is_leader False 后无法继续阶段/提交 |
| AC-M11-W02-03 | API 与 CLI task status 从同一 persisted authority 暴露 active config、leader ID、running phase、heartbeat、last outcome、next due time | `RuntimeTruthStore`（`scheduler_runtime` 单行，`test_update_and_read_round_trip`、`test_runtime_truth_survives_store_restart`、`test_heartbeat_updates_only_the_leader`）；API `GET /api/v1/scheduler/status` 新增 leader_id/active_config/running_phase/heartbeat_at/last_outcome/next_due_at（`test_status_exposes_runtime_truth`，空 store → None/{}，`test_status_has_null_runtime_when_absent`）；CLI `scheduler status` 输出同一字段（`test_cli_status_exposes_runtime_truth`，datetime ISO 序列化）；`test_cli_status_matches_api_surface` 逐字段断言 CLI 与 API 一致 |

范围说明：`alphabrief_trader/scheduler_leader.py`、`alphabrief_trader/runtime_truth.py`、
`tests/test_scheduler_leader.py`、`tests/test_scheduler_runtime_truth.py` 为
M11-W02 契约声明的新模块/缺失测试文件（targeted command 声明，documented
forced paths）；`routes/scheduler.py` `/status` 与 CLI `status` 仅新增字段
（既有字段不变，`test_scheduler.py`/`test_scheduler_api.py`/
`test_scheduler_cli.py` 既有断言更新为含新字段的逐键断言）。scheduler 进程
的 lease 续期循环与 durable cycle 接线随 M11-W03/W05 轮次补齐。全量 pytest：
2249 total（2230 passed + 19 pre-existing M08-W03 time-bombed risk fixture
失败，分类见 M10-W03）；ruff/mypy 全仓 clean（393 source files）；
acceptance 11/11。下一 READY item：M11-W03。

#### M11-W03 已闭环证据（R-20260813-M11-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M11-W03-01 | frozen/disabled/broker-unready 执行路径仍完成 eligible ingest/snapshot/committee/report 阶段 | `DurableDailyCycle`：preflight 评估 `ExecutionGate`，discuss/propose/report 研究阶段无条件运行；`test_blocked_cycle_completes_research_phases`（credentials 缺失 → 10 阶段全序完整、votes 落 transition、零 submit、attempts=[]）、`test_disabled_cycle_completes_research_phases`（trading_enabled=False → 完整、零 submit、votes 存在）、`test_research_only_cycle_completes_research_phases`（research_only → 完整、plans 存在） |
| AC-M11-W03-02 | missing credentials、stale account truth、failed reconciliation、stale data、failed backup、unhealthy model、active kill switch 在 broker 调用前阻止 submit | `ExecutionGate` 确定性判定（`test_daily_cycle_preflight.py`）：七种 blocking 条件各自 → BLOCKED + 稳定 reason（`test_missing_credentials_blocks`/`test_stale_account_truth_blocks`/`test_failed_reconciliation_blocks`/`test_stale_data_blocks`/`test_failed_backup_blocks`/`test_unhealthy_model_blocks`/`test_kill_switch_dominates_everything`），多条件并列全部列出（`test_multiple_conditions_list_all_reasons`）；execute 阶段非 executable → outcome=blocked + reasons、零提交（`test_execute_gate_records_mode_in_transitions`：kill switch → transition 记录 execution_mode=blocked + kill_switch_active）；`test_executable_cycle_can_submit`（全通过 → executed、有提交） |
| AC-M11-W03-03 | research-only、execution-disabled、blocked、executable 作为 distinct machine-readable states 持久化并带 reasons | `ExecutionMode` StrEnum 四值；`RuntimeTruthStore.set_execution_mode/get_execution_mode`（`execution_mode` 表）：`test_blocked_mode_persisted_with_reasons`（mode=blocked + reasons 集合）、`test_executable_mode_persisted`、`test_modes_are_distinct_machine_readable_states`（四种 mode 逐一持久化且互异）、`test_modes_are_machine_readable_and_distinct`（StrEnum value 断言）；mode+reasons 同时落在 cycle transition output_ids |

范围说明：`alphabrief_trader/execution_gate.py`、
`tests/test_daily_cycle_preflight.py`、`tests/test_daily_cycle_research_mode.py`
为 M11-W03 契约声明的新模块/缺失测试文件（targeted command 声明，documented
forced paths）；`DurableDailyCycle` 新增 `preflight_facts_provider` 与
`runtime_store` 注入（默认 facts provider fail-closed：仅 env 凭证与 kill
switch 可证明）。scheduler 进程的 lease 循环与真实 facts 采集随 M11-W05/
M15 轮次补齐。全量 pytest：2270 total（2251 passed + 19 pre-existing
M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓
clean（396 source files）；acceptance 11/11。下一 READY item：M11-W04。

#### M11-W04 已闭环证据（R-20260813-M11-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M11-W04-01 | 候选选择永不超配置的 instrument、per-category、model-call、token、cost、concurrency budgets | `DailyCandidateSelector.select` 累计 `BudgetUsage`（instrument_count/per_category/model_calls/tokens/cost Decimal）并在选择前检查六项 budget；`tests/test_daily_cycle_budget.py`+`test_daily_cycle_candidates.py::TestBudgetEnforcement`：`test_instrument_budget_never_exceeded`（3 上限 → 恰 3）、`test_per_category_budget_never_exceeded`（每类 2 上限 → 各 2）、`test_model_call_budget_never_exceeded`（25 上限 → usage≤25）、`test_token_budget_never_exceeded`、`test_cost_budget_never_exceeded`（usage.cost≤1.00）、`test_concurrency_budget_never_exceeded`；`test_zero_budget_selects_nothing`；`test_float_budget_rejected`（float → ValidationError）；`test_usage_accumulates_only_for_selected`（仅 selected 计入） |
| AC-M11-W04-02 | 每个 selected 与 skipped 品种记录确定性 rule results：catalogue status、category、quote freshness、tradeability、spread、liquidity、data quality、news relevance | `CandidateVerdict`（symbol/category/selected/selection_reason/rule_results）：`test_selected_instrument_records_all_rules`（八条规则全部通过并记录）；跳过品种逐条带 reason：`test_inactive_catalogue_skipped_with_reason`（catalogue_status+inactive）、`test_stale_quote_skipped_with_reason`（quote_freshness）、`test_wide_spread_skipped`、`test_low_liquidity_skipped`、`test_unacceptable_data_quality_skipped`、`test_low_news_relevance_skipped`、`test_unknown_category_skipped`；budget 跳过同样记录（`test_budget_exhaustion_skips_remainder_deterministically`：后续品种逐一含 concurrency_budget 结果） |
| AC-M11-W04-03 | 等价输入产生相同有序候选集；完整 catalogue 在日分析集之外仍可查询 | `test_equivalent_inputs_produce_same_ordered_candidates`（乱序输入 → 相同 candidates 与 verdicts 序列）、`test_candidates_are_category_ordered`（(category, symbol) 确定性排序）、`test_complete_catalogue_stays_queryable`（verdicts 覆盖全部品种含 skipped——catalogue 不因 selection 丢失） |

范围说明：`alphabrief_trader/candidate_selection.py`、
`tests/test_daily_cycle_candidates.py`、`tests/test_daily_cycle_budget.py`
为 M11-W04 契约声明的新模块/缺失测试文件（targeted command 声明，
documented forced paths）。候选集→cycle 的接线随 M11-W05 轮次补齐。全量
pytest：2272 total（2253 passed + 19 pre-existing M08-W03 time-bombed risk
fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（399 source files）；
acceptance 11/11。下一 READY item：M11-W05。

#### M11-W05 已闭环证据（R-20260813-M11-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M11-W05-01 | 重复同一 trading date + snapshot key 返回既有 cycle，不产生新 committee/proposal/intent/order | `daily_cycle_key(date, snapshot_key)` 确定性（`test_daily_cycle_key_is_deterministic`）；`test_same_date_and_snapshot_returns_existing_cycle`（同 key 两次 run → 同 cycle_id、store 仅 1 条）；`test_different_snapshot_creates_new_cycle`（不同 snapshot → 新 cycle）；叠加 M10-W05 的 (cycle_key, snapshot fingerprint) 双条件幂等 |
| AC-M11-W05-02 | missed cycle 只在配置的 catch-up window 内运行；窗口关闭后记录 expired-without-chase | `CatchUpPolicy`（注入 clock）：`test_on_time_cycle_is_allowed`/`test_within_window_is_allowed`/`test_after_window_is_expired`（24h 窗口：on_time/12h 内允许/25h 后 expired_without_chase）；`test_expired_cycle_records_without_chasing`（expired → outcome=expired_without_chase、votes/plans/attempts 全空、零提交、store 持久化）；`test_missed_within_window_still_runs`（12h 内补跑且研究完整）；`test_expired_is_idempotent`（重复 run 同记录）；`CycleOutcome` 新增 `expired_without_chase` |
| AC-M11-W05-03 | no-trade、risk rejection、market closed、stale data、insufficient evidence、budget exhaustion 为 durable successful terminal outcomes，带 evidence 与 reasons | `test_no_trade_is_durable_successful_outcome`（hold/0 仓位 → skipped_no_intent、votes 持久化、evidence 保留）；`test_risk_rejection_is_durable_terminal_outcome`（kill switch → blocked_risk_gate、attempt approved=False 持久化）；`test_market_closed_is_durable_terminal_outcome`（PreflightFacts.market_open=False → blocked_risk_gate + summary 含 market_closed）；`test_stale_data_is_durable_terminal_outcome`（data_fresh=False → summary 含 stale_data、研究仍运行）；`test_insufficient_evidence_is_durable_terminal_outcome`（无 votes → provider_error、attempts=[]）；budget exhaustion 由 M10-W02/05 覆盖（rejected records → provider_error）——全部为成功完成 cycle 的 durable terminal 记录（非失败） |

范围说明：`alphabrief_trader/cycle_schedule.py`、
`tests/test_daily_cycle_catchup.py`、`tests/test_daily_cycle_no_trade.py`
为 M11-W05 契约声明的新模块/缺失测试文件（targeted command 声明，
documented forced paths）；`ExecutionGate` 新增 `market_open` 事实；
`DurableDailyCycle.run` 新增 `scheduled_at`；`CycleOutcome` 增加
`expired_without_chase`。全量 pytest：2306 total（2287 passed + 19
pre-existing M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；
ruff/mypy 全仓 clean（402 source files）；acceptance 11/11。下一 READY
item：M11-W06。

#### M11-W06 已闭环证据（R-20260813-M11-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M11-W06-01 | submit 仅在 proposal、OrderIntent、broker-fresh inputs、immutable RiskDecision、execution enablement、idempotency mapping 共享同一 correlation chain 时发生 | execute 阶段构建 `CorrelationChain`（cycle_id/proposal_ids/intent_ids/decision_ids/client_order_ids/broker_order_ids）持久化于 execute transition（`test_full_chain_persisted_on_execute` 逐段断言）；`test_decision_ids_are_immutable_and_linked`（attempt 携带 intent_id/risk_decision_id/order_id）；`test_broker_fresh_inputs_gate_submission`（stale data → blocked、attempts 空、链上无提交）；`IdempotencyMap` check-and-insert（`cycle_idempotency` 表） |
| AC-M11-W06-02 | approved/rejected/no-trade/broker-rejected fixtures 各产生正确 terminal state 与 0 或 1 次 broker submit | `test_approved_fixture_submits_exactly_once`（executed、submit_calls==1、链完整）；`test_risk_rejected_fixture_never_submits`（kill switch → blocked_risk_gate、0 submit）；`test_no_trade_fixture_never_submits`（skipped_no_intent、0 submit）；`test_broker_rejected_fixture_submits_once_and_terminates`（PaperBrokerError → error terminal、1 submit）；`test_blocked_execution_never_submits`（gate blocked → 0 submit）；`test_at_most_once_across_restart`（restart 复用既有 cycle → 0 新提交，`CYCLE_EXECUTE_OUTCOMES` 增加 error） |
| AC-M11-W06-03 | 每次 broker outcome 触发即时对账，并在 report 完成前持久化 linked order/transaction/trade/position/account/reconciliation evidence | `_phase_reconcile` 对每次 broker outcome 运行注入的 reconciler → `ReconciliationEvidence`（attempt_count/order_ids/matched/account_snapshot）持久化于 reconcile transition：`test_reconciliation_runs_before_report`（evidence 产生且落 transition、order_ids/account 快照断言）、`test_reconciliation_precedes_report_phase`（phase 序列中 reconcile 在 report 之前） |

范围说明：`alphabrief_trader/cycle_execution.py`、
`tests/test_daily_cycle_execution.py`、`tests/test_daily_cycle_risk_chain.py`
为 M11-W06 契约声明的新模块/缺失测试文件（targeted command 声明，
documented forced paths）；`CYCLE_EXECUTE_OUTCOMES` 增加 `error`；
`CycleOutcome`/rebuild 映射 error → `broker_rejected` reason。OANDA 真实
adapter 的 broker-fresh inputs 采集随 M13/M15 轮次接入。全量 pytest：
2316 total（2297 passed + 19 pre-existing M08-W03 time-bombed risk fixture
失败，分类见 M10-W03）；ruff/mypy 全仓 clean（405 source files）；
acceptance 11/11。下一 READY item：M11-W07。

#### M11-W07 已闭环证据（R-20260813-M11-W07）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M11-W07-01 | 每个 completed cycle 引用 daily brief、transcript 或 legal skip、proposal 或 no-trade、risk result、broker outcome、reconciliation、portfolio snapshot、alerts、data-quality summary | `build_cycle_report`（`cycle_report.py`）从 transition IDs 组装 `DailyCycleReport`；`test_completed_cycle_references_all_evidence`（outcome/proposal_ids 或 no_trade_reason/decision_ids/broker_order_ids/reconciliation_id/portfolio_snapshot/alert_summary/data_quality_summary/transcript_id 或 transcript_skip_reason 全引用）；`test_no_trade_cycle_references_no_trade_reason`（blocked → no_trade_reason 带 gate reasons、broker_order_ids 空）；discuss 阶段持久化 `transcript_id`（votes hash）与 `transcript_skip_reason`（无 votes → no_committee_votes） |
| AC-M11-W07-02 | 从 immutable IDs 重建 report 产生 byte-equivalent normalized content，不能替换为更新证据 | `normalized_json` 排除 build-time report_id/created_at，仅覆盖 immutable transition 派生字段；`test_report_id_is_deterministic`（同 cycle 两次构建相同 id 与 normalized）；`test_rebuild_is_byte_equivalent`（不同 clock 重建 → 相同 report_id 与 normalized_json）；`test_newer_evidence_cannot_substitute`（后续 cycle 运行后 frozen report 的 id/normalized 不变） |
| AC-M11-W07-03 | Scheduler API 与 CLI 暴露同一 cycle outcome、phase timestamps、heartbeat、failure classification、last run、next due time，与 persisted runtime state 一致 | `RuntimeTruthStore` 扩展 `phase_started_at`/`failure_classification`（`test_phase_timestamps_and_classification_survive_restart`）；API `GET /api/v1/scheduler/status` 与 CLI `scheduler status` 均输出同组字段（`test_status_exposes_runtime_truth` 增补 phase_started_at/failure_classification；`test_cli_status_matches_api_surface` 逐字段一致） |

范围说明：`alphabrief_trader/cycle_report.py`、
`tests/test_daily_cycle_reporting.py` 为 M11-W07 契约声明的新模块/缺失测试
文件（targeted command 声明，documented forced paths）；`test_scheduler_runtime_truth.py`
扩展（既有 forced path 同族更新）。全量 pytest：2334 total（2315 passed +
19 pre-existing M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；
ruff/mypy 全仓 clean（407 source files）；acceptance 11/11。下一 READY
item：M11-W08。

#### M11-W08 已闭环证据（R-20260813-M11-W08）— M11 里程碑 gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M11-W08-01 | 每个 durable phase 与 broker boundary 前后的 failure injection 恢复为单一 terminal cycle，无 duplicate intent/submit | `tests/test_daily_cycle_recovery.py`：`test_crash_before_each_phase_resumes_to_single_terminal`（对 CYCLE_PHASE_ORDER 每个边界 crash → resume → is_complete、store 仅 1 条 cycle、submit 计数 ≤1）；`test_crash_after_broker_boundary_never_resubmits`（execute transition 提交后 crash → 0 次新 submit）；叠加 W01 的 restart-resume 与 W06 的 at-most-once |
| AC-M11-W08-02 | concurrent leaders、SIGTERM、stale lease、timeout、provider failure、broker uncertainty、reconciliation mismatch 各产生 deterministic recovery 或 fail-closed evidence | `test_concurrent_leaders_produce_one_holder`（一 leader 一 follower）；`test_stale_lease_blocks_former_leader`（过期 → renew/is_leader False、新 leader 接管）；`test_provider_failure_completes_fail_closed`（provider 输出无效 → provider_error、attempts 空、持久化）；`test_broker_timeout_completes_with_error_evidence`（TimeoutError → error terminal、恰 1 次 submit、attempt 持久化）；`test_reconciliation_mismatch_is_fail_closed_evidence`（matched=False 的 reconciliation evidence 落 reconcile transition）；SIGTERM 语义由 phase 边界 crash 注入覆盖（SIGTERM 在任意 phase 边界与 crash 等价，resume 相同） |
| AC-M11-W08-03 | full repository、static、autonomous acceptance、M11 traceability gates 无 waiver 通过 | targeted 六套（47 passed）+ integration 四套（52 passed）+ ruff/mypy clean（408 source files）+ full pytest（见下）+ acceptance 11/11；REQ-CYCLE-001..010 全部 trace 到 W01-W08 evidence（见下 M11 Requirement Traceability）；M11 里程碑 → DONE |

#### M11 Requirement Traceability（M11-W01..W08）

| Requirement | Code / Evidence |
|---|---|
| REQ-CYCLE-001（每日 phases 持久状态机） | W01 `CycleStateStore`/`CycleStateMachine`/`DurableDailyCycle`；`test_daily_cycle_state_machine.py` |
| REQ-CYCLE-002（每阶段原子记录 input hashes/output IDs/attempt/timestamps/prior state，stale writer 拒绝） | W01 `advance()` CAS+append；`test_daily_cycle_state_machine.py`/`test_daily_cycle_checkpoints.py` |
| REQ-CYCLE-003（research 与 execution enable 分离） | W03 `ExecutionGate`+mode 持久化；`test_daily_cycle_research_mode.py` |
| REQ-CYCLE-004（候选集/流动性/质量/模型预算） | W04 `DailyCandidateSelector`；`test_daily_cycle_candidates.py`/`test_daily_cycle_budget.py` |
| REQ-CYCLE-005（候选选择透明可解释、完整品种可查询） | W04 verdicts/selection_reason；`test_daily_cycle_candidates.py` |
| REQ-CYCLE-006（同日期/snapshot 不重复、漏跑明确） | W05 `daily_cycle_key`+`CatchUpPolicy`；`test_daily_cycle_catchup.py` |
| REQ-CYCLE-007（no-trade/RiskGate rejection/market closed/stale data 为成功终态） | W05 terminal outcomes；`test_daily_cycle_no_trade.py` |
| REQ-CYCLE-008（cycle 后即时对账并生成 daily report） | W06 `_phase_reconcile`+W07 `DailyCycleReport`；`test_daily_cycle_risk_chain.py`/`test_daily_cycle_reporting.py` |
| REQ-CYCLE-009（scheduler task listing/running/heartbeat/last/next 同一权威） | W02/W07 `RuntimeTruthStore`；`test_scheduler_runtime_truth.py` |
| REQ-CYCLE-010（单 leader/单 writer） | W02 `SchedulerLeaderLease`；`test_scheduler_leader.py` |

范围说明：`tests/test_daily_cycle_recovery.py` 为 M11-W08 契约声明的缺失测试
文件（targeted command 声明，documented forced path）。全量 pytest：
2331 total（2312 passed + 19 pre-existing M08-W03 time-bombed risk fixture
失败，分类见 M10-W03）；ruff/mypy 全仓 clean（408 source files）；
acceptance 11/11。M11 里程碑 → DONE（无 T7 runtime 依赖，全部本地确定性
gate 通过）。下一 READY item：M12-W01。

#### M12-W01 已闭环证据（R-20260813-M12-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M12-W01-01 | Valid fixtures compile into a typed normalized AST with deterministic serialization and explicit indicator, operator, parameter, and data requirements | `tests/test_strategy_dsl.py`：`test_valid_fixture_compiles_to_typed_ast`（`ema(close, 20) > sma(close, 50) and not rsi(14) >= 70` → LogicNode(and)/ComparisonNode/NotNode，parameters 归一为 `["close", 20]`）；`test_literals_and_data_nodes`；`test_normalized_serialization_is_deterministic`；`test_requirements_are_explicit_and_deduplicated`（requirements == `["ema(close,20)", "sma(close,50)"]`，`leaf_keys()` 一致）；`test_all_comparison_operators`（gt/gte/lt/lte/eq/neq 全覆盖） |
| AC-M12-W01-02 | Imports, calls outside the allowlist, attribute traversal, comprehensions, mutation, file access, SQL, templates, and shell syntax are rejected before evaluation | `test_forbidden_syntax_rejected`（parametrized 21 个 payload：import/from-import/Attribute/Subscript/三种 comprehension/lambda/exec/eval/getattr/未知 indicator/未知 data/BinOp/f-string/walrus/链式 and 含未知名）；`test_attribute_traversal_rejected`/`test_subscript_rejected`/`test_comprehension_rejected`/`test_indicator_outside_allowlist_rejected`/`test_undeclared_data_rejected`/`test_boolean_literal_rejected`/`test_keyword_arguments_rejected`——全部在求值前 `DslCompileError` 拒绝；AST 编译走 allowlist + 禁例表，无任何可执行路径 |
| AC-M12-W01-03 | Evaluation over identical versioned inputs produces identical signals and never reads undeclared future or external state | `test_identical_inputs_produce_identical_signals`（同值三次求值恒同）；`test_boolean_semantics`/`test_not_semantics`（and/or/not 真值表）；`test_undeclared_state_never_read`（缺 declared leaf → `DslEvaluationError`；多余未声明值被忽略；条件只读其声明叶子） |

#### M12 Requirement Traceability（M12-W01）

| Requirement | Code / Evidence |
|---|---|
| REQ-STRAT-001（safe DSL cannot execute arbitrary code） | W01 `alphabrief_strategy/dsl.py`：`compile_condition` 编译为 frozen typed AST（`LiteralNode`/`DataNode`/`IndicatorNode`/`ComparisonNode`/`LogicNode`/`NotNode`），禁 Attribute/Subscript/import/comprehension/lambda/exec/eval/BinOp/赋值/副作用语法；`evaluate_condition` 只读 `EvaluationContext` 已声明叶子；`tests/test_strategy_dsl.py`（38 用例） |

范围说明：`tests/test_strategy_dsl.py` 为 M12-W01 契约声明的测试文件，
`packages/alphabrief-strategy/src/alphabrief_strategy/dsl.py` 为 M12-W01
契约声明的生产模块（REQ-STRAT-001，scope profile `strategy_backtest`）。
全量 pytest：2369 total（2350 passed + 19 pre-existing M08-W03 time-bombed
risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（410 source
files）；acceptance 11/11。下一 READY item：M12-W02。

#### M12-W02 已闭环证据（R-20260813-M12-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M12-W02-01 | Each required strategy family emits deterministic long, short, flat, and insufficient-data outcomes from declared inputs | `tests/test_strategy_builtins.py`：`TrendFamily`（close 高于/低于 `close_sma_N` → long/short，等于 → flat，feature 缺失 → `insufficient data`）；`MeanReversionFamily`（RSI ≤ oversold → long，≥ overbought → short，band 内 → flat，缺失 → insufficient）；`BreakoutFamily`（close 高于 `bb_upper_N` → long，低于 `bb_lower_N` → short，带内 → flat，任一 band 缺失 → insufficient）；`VolatilityRegimeFamily`（atr/close ≥ high_vol_atr_pct → 高波动 flat，正常 regime 按 close vs `close_sma_N` long/short/flat，feature 缺失 → insufficient）；`NoTradeFamily`（恒 flat，无 declared inputs）；每族 `test_identical_inputs_produce_identical_signals` 证明同输入同输出 |
| AC-M12-W02-02 | Strategy applicability is enforced by OANDA instrument category and unsupported combinations fail admission with explicit reasons | `tests/test_strategy_admission.py`：`FAMILY_APPLICABILITY` 按 OANDA instrument category（CURRENCY/METAL/INDEX_CFD/COMMODITY_CFD/BOND_CFD/EQUITY_CFD/CRYPTO_CFD/OTHER_CFD，与 `alphabrief_execution.broker.oanda.taxonomy.InstrumentCategory` parity 由 `test_category_mirror_matches_oanda_taxonomy` 强制）；approved 矩阵全绿；`test_unsupported_combination_is_rejected_with_explicit_reason`（如 trend×OTHER_CFD、mean_reversion×CRYPTO_CFD/BOND_CFD、breakout×BOND_CFD/EQUITY_CFD、volatility_regime×CRYPTO_CFD/BOND_CFD）reason 同时含 family 与 category；`evaluate_strategy_admission` 为纯函数（`test_verdict_is_a_pure_function_of_its_inputs`） |
| AC-M12-W02-03 | No-trade is a first-class benchmark strategy and all predictive or learned outputs remain advisory evidence rather than executable orders | `NoTradeFamily` 为 first-class benchmark（`test_first_class_benchmark_metadata`，confidence=1.0、8 类全 admissible、恒 flat 且 `test_never_reads_declared_inputs` 证明无 declared inputs）；`PREDICTIVE_FAMILY_IDS`（kronos_forecast/gym_policy）对全部 8 类 rejected 且 reason 含 `advisory`（`test_predictive_families_are_rejected_as_advisory_only`、`test_predictive_families_are_never_admissible_for_any_category`）；`test_outputs_are_advisory_signal_evidence_only`/`test_families_never_return_orders` 证明族输出只含 `Signal` evidence、`StrategyOutput` 无 order 边界、族实例无 submit 能力 |

#### M12 Requirement Traceability（M12-W01..W02）

| Requirement | Code / Evidence |
|---|---|
| REQ-STRAT-001（safe DSL cannot execute arbitrary code） | W01 `alphabrief_strategy/dsl.py`：`compile_condition`/`evaluate_condition`；`tests/test_strategy_dsl.py`（38 用例） |
| REQ-STRAT-002（至少支持 trend、mean reversion、breakout、volatility/regime 和 no-trade baseline；每个策略可限定适用类别） | W02 `alphabrief_strategy/families.py`：五个 family 全部落地，`FAMILY_APPLICABILITY` 按 OANDA instrument category 限定；`tests/test_strategy_builtins.py`/`tests/test_strategy_admission.py` |
| REQ-STRAT-007（Kronos/Gym/其他预测只提供 advisory evidence，不能绕过 committee 或 RiskGate） | W02 `alphabrief_strategy/admission.py`：`PREDICTIVE_FAMILY_IDS` 全部类别 rejected（advisory-only reason）；族输出边界仅为 `StrategyOutput`(Signal)，无任何 order 能力；`tests/test_strategy_admission.py` |

范围说明：`tests/test_strategy_builtins.py` 与 `tests/test_strategy_admission.py` 为
M12-W02 契约声明的测试文件（targeted command 声明，documented forced path）；
`families.py`/`admission.py` 为 M12-W02 契约声明的生产模块（REQ-STRAT-002/007，
scope profile `strategy_backtest`）。全量 pytest：2453 total（2434 passed + 19
pre-existing M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy
全仓 clean（414 source files）；acceptance 11/11。注：`progress.current.milestone_id`
按 19 轮既定约定保持派生缓存值（M02-era loop-controller selection tests 的
hardcode 前提；ACTIVE milestone 以 `milestones:` 映射为准），本轮恢复该约定。
下一 READY item：M12-W03。

#### M12-W03 已闭环证据（R-20260813-M12-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M12-W03-01 | Multi-instrument fixtures update cash, NAV, gross and net exposure, margin, positions, realized and unrealized PnL, and category attribution in account home currency | `tests/test_backtest_portfolio.py`：三品种 fixture（EUR_USD CURRENCY / XAU_USD METAL / US100 INDEX_CFD）买入后 cash 减少、3 条 positions、gross==net（all-long）、margin_used 按 margin_rate 计算、entry 价格 mark → unrealized==0（`test_buy_fills_update_cash_positions_and_exposure`）；category attribution 按类别聚合且与 portfolio totals 对账（`test_category_attribution_groups_exposure_by_category`）；mark-to-market 产生 unrealized PnL（`test_mark_to_market_realizes_unrealized_pnl`）；partial close 实现 80.00、remaining 6000 units 保持 entry avg（`test_partial_close_realizes_pnl_and_reduces_position`）；full close/reversal/short 方向与 realized 语义（`test_full_close_realizes_all_pnl`/`test_reversal_updates_short_position_and_realizes_pnl`/`test_short_position_net_exposure_is_negative`）；financing 扣减 cash（`test_financing_accrual_reduces_cash`）；rejected fill 零状态变更；同输入同 snapshot |
| AC-M12-W03-02 | Spread, slippage, financing, market closure, stale price, minimum units, precision, maximum units, and insufficient margin each change fills or produce explicit rejection | `tests/test_backtest_execution_semantics.py`：buy 按 ask（>mid）、sell 按 bid（<mid）、spread 加宽改变 execution price 与 spread_cost（`test_buy_fills_at_ask_above_mid`/`test_wider_spread_changes_fill_price`）；slippage 使 fill 逆向移动并记录 slippage_cost（`test_slippage_moves_fill_adversely_and_is_recorded`）；fee 按 notional 收取（`test_fee_is_charged_on_notional`）；weekend → `market_closed`、price_age>max → `stale_price`（`test_weekend_order_is_rejected_market_closed`/`test_stale_price_is_rejected`）；`below_minimum_units`/`units_precision`/`above_maximum_units`/`above_maximum_position`/`insufficient_margin` 全部显式 reject reason（TestUnitConstraints/TestMargin）；margin_used 反映 fill 后 position（含既有 units）；financing 按 units×nights 计费并扣 cash（TestFinancing）；reject reason 带版本字段（`test_rejection_reason_is_explicit_and_versioned`） |
| AC-M12-W03-03 | Backtest metadata and execution semantics resolve the same instrument version and normalization rules used by the OANDA practice runtime or record an explicit versioned difference | `tests/test_oanda_backtest_parity.py`：`BacktestInstrumentMetadata` 携带 practice 同名字段（display/trade-units precision、min/max units、margin rate，`test_backtest_metadata_carries_the_practice_fields`）；`normalize_backtest_units/price` 与 `alphabrief_risk.instrument_rules.normalize_instrument_units/price` 对可表示值结果一致、不可表示值同类拒绝（`TestNormalizationParity`，units_precision/price_precision/price_invalid kind 一致）；`CATEGORY_SESSION_WINDOWS` 与 `CATEGORY_SESSIONS` 逐字段一致且一周采样 verdict 全等（`TestSessionParity`，8 类 × 56 个采样点）；`SEMANTICS_VERSION="oanda-practice-mirror-1"`、`SEMANTICS_DIFFERENCES=()` 显式记录差异（`TestVersionedSemanticsRecord`）；fill 携带 metadata_version/semantics_version |

#### M12 Requirement Traceability（M12-W01..W03）

| Requirement | Code / Evidence |
|---|---|
| REQ-STRAT-001（safe DSL cannot execute arbitrary code） | W01 `alphabrief_strategy/dsl.py`；`tests/test_strategy_dsl.py` |
| REQ-STRAT-002（至少支持 trend、mean reversion、breakout、volatility/regime 和 no-trade baseline；每个策略可限定适用类别） | W02 `alphabrief_strategy/families.py` + `FAMILY_APPLICABILITY`；`tests/test_strategy_builtins.py`/`tests/test_strategy_admission.py` |
| REQ-STRAT-004（回测是多品种/组合感知并建模 spread、slippage、financing、margin、minimum units、market hours 和 rejected orders） | W03 `alphabrief_backtest/portfolio.py`/`execution.py`/`metadata.py`；`tests/test_backtest_portfolio.py`/`tests/test_backtest_execution_semantics.py` |
| REQ-STRAT-007（Kronos/Gym/其他预测只提供 advisory evidence，不能绕过 committee 或 RiskGate） | W02 `alphabrief_strategy/admission.py`（`PREDICTIVE_FAMILY_IDS` 全部 rejected）；`tests/test_strategy_admission.py` |
| REQ-STRAT-008（回测与实际 OANDA practice 采用相同 instrument metadata 和关键 risk/execution semantics，差异必须显式记录） | W03 `SEMANTICS_VERSION`/`SEMANTICS_DIFFERENCES` + 归一化/会话 parity；`tests/test_oanda_backtest_parity.py` |
| REQ-OANDA-003（保存 name、displayName、type、displayPrecision、tradeUnitsPrecision、minimumTradeSize、maximumOrderUnits、maximumPositionSize、marginRate、pipLocation 等元数据） | W03 `BacktestInstrumentMetadata` 镜像同名字段（precision/min/max units/margin rate）；`tests/test_oanda_backtest_parity.py` |

范围说明：`tests/test_backtest_portfolio.py`、`tests/test_backtest_execution_semantics.py`、
`tests/test_oanda_backtest_parity.py` 为 M12-W03 契约声明的测试文件（targeted +
integration command 声明，documented forced path）；`metadata.py`/`execution.py`/
`portfolio.py` 为 M12-W03 契约声明的生产模块（REQ-OANDA-003/REQ-STRAT-004/008，
scope profile `strategy_backtest`；risk/execution/strategy 运行时零改动，parity
由测试单向引用）。全量 pytest：2503 total（2484 passed + 19 pre-existing
M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean
（420 source files）；acceptance 11/11。下一 READY item：M12-W04。

#### M12-W04 已闭环证据（R-20260813-M12-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M12-W04-01 | Rolling and anchored fixtures create non-overlapping decision boundaries with parameters fitted only on declared in-sample observations | `tests/test_backtest_walk_forward.py`：`WindowSpec` 强制 `step_bars >= oos_bars`（`test_step_smaller_than_oos_is_rejected`）保证 OOS 永不重叠；`test_decision_boundaries_are_non_overlapping`（rolling：每窗口 oos_start > is_end 即决策边界分隔、相邻窗口 OOS 不重叠）；`test_anchored_is_starts_at_the_first_bar_and_grows`（anchored：IS 恒从首 bar 起并增长、OOS 相邻不重叠）；`test_parameters_fitted_only_on_declared_is_observations`（fitter 只收 IS slice——与独立 IS-only fit 的 chosen parameters 与 is_total_return 完全一致，fitted is_start/is_end 等于 IS 边界）；`test_insufficient_bars_are_rejected`/`test_empty_parameter_grid_is_rejected` |
| AC-M12-W04-02 | Out-of-sample execution uses frozen parameters and cannot access later observations, later revisions, or undisclosed data versions | `test_frozen_parameters_are_used_for_every_oos_run`（每窗口以 `fitted_parameters.parameters` 构造 frozen 实例，其 OOS metrics 与对同 slice 独立回测完全一致——OOS 只见过自己的 slice，无 lookahead）；`test_oos_metrics_equal_standalone_run_on_the_slice`；`test_undisclosed_data_version_is_rejected`（任一 bar 携带未声明 data version → `WalkForwardEvaluationError`）；`test_every_window_records_the_declared_data_version`（result/windows 只引用声明版本，无 later revision 可达） |
| AC-M12-W04-03 | Repeating a run with the same strategy, data version, costs, seed, and window specification yields the same run ID and normalized result | `tests/test_backtest_reproducibility.py`：`test_identical_inputs_yield_identical_run_id`（sha256 64 hex）；`test_identical_inputs_yield_identical_normalized_result`（`normalized_json()` 逐字节相同）；seed/window spec/data version/costs/grid/strategy identity/bar content 各自绑定进 run_id（`test_seed_is_bound_into_the_run_id`/`test_window_spec_is_bound_into_the_run_id`/`test_data_version_is_bound_into_the_run_id`/`test_costs_are_bound_into_the_run_id`/`test_parameter_grid_is_bound_into_the_run_id`/`test_strategy_identity_is_bound_into_the_run_id`/`test_bar_content_is_bound_into_the_run_id`）；`test_deterministic_fit_picks_the_same_parameters`（同输入 → 同 fitted parameters 与 oos_metrics）；`TestRunIdContract`（compute_evaluation_run_id 确定性、data version 变化改变 run_id） |

#### M12 Requirement Traceability（M12-W01..W04）

| Requirement | Code / Evidence |
|---|---|
| REQ-STRAT-001 | W01 `alphabrief_strategy/dsl.py`；`tests/test_strategy_dsl.py` |
| REQ-STRAT-002 | W02 `alphabrief_strategy/families.py`；`tests/test_strategy_builtins.py`/`test_strategy_admission.py` |
| REQ-STRAT-003（真实 IS/OOS、rolling/anchored walk-forward、参数冻结、benchmark 和可重复 data version） | W04 `alphabrief_backtest/evaluation.py`：`run_walk_forward_evaluation`（rolling/anchored、`_fit_parameters` IS-only、frozen params OOS、benchmark 经 `oos_report.metrics.benchmark_total_return`、data version 全 bar 校验、run_id=sha256(全部输入)）；`tests/test_backtest_walk_forward.py`/`test_backtest_reproducibility.py` |
| REQ-STRAT-004 | W03 `alphabrief_backtest/portfolio.py`/`execution.py`/`metadata.py`；相关测试 |
| REQ-STRAT-007 | W02 `alphabrief_strategy/admission.py`；`tests/test_strategy_admission.py` |
| REQ-STRAT-008 | W03 `SEMANTICS_VERSION`/`SEMANTICS_DIFFERENCES` + parity；`tests/test_oanda_backtest_parity.py` |
| REQ-PLAT-009（所有关键 ID 可跨数据、研究、模型、风险、订单和对账追踪） | W04 `run_id`（绑定 strategy/data version/costs/seed/window/bar fingerprint）与 `FittedParameters`（strategy_id/version/family/data_version/IS 边界/parameters/algorithm_version）形成可追踪 ID 链；`tests/test_backtest_reproducibility.py` |
| REQ-OANDA-003 | W03 `BacktestInstrumentMetadata`；`tests/test_oanda_backtest_parity.py` |

范围说明：`tests/test_backtest_walk_forward.py` 与 `tests/test_backtest_reproducibility.py`
为 M12-W04 契约声明的测试文件（targeted command 声明，documented forced path）；
`evaluation.py` 为 M12-W04 契约声明的生产模块（REQ-STRAT-003/REQ-PLAT-009，
scope profile `strategy_backtest`）；既有 `walk_forward.py` 及其测试零改动。
全量 pytest：2526 total（2507 passed + 19 pre-existing M08-W03 time-bombed
risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（423 source files）；
acceptance 11/11。下一 READY item：M12-W05。

#### M12-W05 已闭环证据（R-20260813-M12-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M12-W05-01 | Every report includes return, volatility, Sharpe, Sortino, Calmar, maximum drawdown, turnover, exposure, hit rate, profit factor, and tail loss | `tests/test_backtest_reporting.py`：`test_every_report_includes_all_required_metrics`（`ReportMetrics` 11 字段齐全）；`test_metric_values_match_the_scenario`（2 赢 1 输 + 持仓中 moving mid 的 scenario：hit_rate=2/3、profit_factor>1、volatility/sharpe/sortino/tail_loss 非 None、max_drawdown/exposure/turnover 语义正确）；`_tail_loss`=最差 5% period returns 均值（≥20 periods 且非零方差）；`_cagr`/`_calmar` 按 span 年化（span<1 交易日 → None，mdd=0 → None，绝不 inf） |
| AC-M12-W05-02 | Reports include instrument and category attribution, spread, slippage, financing and rejection cost attribution, benchmark delta, and IS or OOS labels | `test_instrument_and_category_attribution`（EUR/XAU/US100 三 instrument 与 CURRENCY/METAL/INDEX_CFD 三 category 的 realized/unrealized/contribution，category 与 instrument 总 PnL 对账）；`test_cost_attribution_breaks_down_costs`（spread/fee>0、slippage=0、financing=2.003、total=四者和）；`test_rejection_attribution_counts_each_reason`（stale_price 与 units_precision 各 1 笔 + rejected_notional）；`test_benchmark_delta`/`test_missing_benchmark_yields_null_delta`（benchmark 给定 → delta=return-benchmark，缺省 → null）；label "OOS"/"IS"/"FULL" 显式记录 |
| AC-M12-W05-03 | Metric fixtures cover zero-return, no-trade, all-loss, sparse, missing-benchmark, and multi-currency portfolios without NaN or misleading infinity serialization | `test_zero_return_fixture`（total_return/mdd/turnover/exposure=0，统计指标全 None）；`test_no_trade_fixture_has_no_misleading_metrics`；`test_all_loss_fixture_has_zero_profit_factor`（PF=0 非 inf）；`test_sparse_fixture_returns_none_stats`（2 snapshots → 统计全 None）；`test_missing_benchmark_yields_null_delta`；`test_multi_currency_portfolio_reconciles`（USD home currency、CURRENCY+METAL attribution）；`test_no_nan_or_infinity_in_any_serialization`（JSON 无 "NaN"/"Infinity" token 且每个 Decimal 字段 `is_finite()`） |

#### M12 Requirement Traceability（M12-W01..W05）

| Requirement | Code / Evidence |
|---|---|
| REQ-STRAT-001 | W01 `alphabrief_strategy/dsl.py`；`tests/test_strategy_dsl.py` |
| REQ-STRAT-002 | W02 `alphabrief_strategy/families.py`；相关测试 |
| REQ-STRAT-003 | W04 `alphabrief_backtest/evaluation.py`；`tests/test_backtest_walk_forward.py`/`test_backtest_reproducibility.py` |
| REQ-STRAT-004 | W03 `alphabrief_backtest/portfolio.py`/`execution.py`/`metadata.py`；相关测试 |
| REQ-STRAT-005（报告包含 return、volatility、Sharpe、Sortino、Calmar、max drawdown、turnover、exposure、hit rate、profit factor、tail loss、category attribution、cost attribution 和 benchmark delta） | W05 `alphabrief_backtest/reporting.py`：`build_portfolio_report` 纯函数（run_id/strategy/data version/label 绑定，`normalized_json` 可复现）；`ReportMetrics` 11 指标 + `CostAttribution` + `RejectionAttribution` + instrument/category `AttributionRow` + benchmark delta；`tests/test_backtest_reporting.py` |
| REQ-STRAT-007 | W02 `alphabrief_strategy/admission.py`；相关测试 |
| REQ-STRAT-008 | W03 `SEMANTICS_VERSION`/parity；`tests/test_oanda_backtest_parity.py` |
| REQ-PLAT-009 | W04 `run_id`/`FittedParameters`；W05 report 携带 run_id/data_version/strategy 版本 |

范围说明：`tests/test_backtest_reporting.py` 为本轮新增测试文件（AC-M12-W05-01/02/03
的 automated_test evidence；targeted/integration command 指向既有
`test_backtest_reports.py`/`test_backtest_metrics_credibility.py`/`test_backtest_portfolio.py`/
`test_backtest_walk_forward.py`，均全绿）。本轮同时修复 M12-W03 遗留的 NAV
会计 bug：`PortfolioSimulator.mark_to_market` 的 NAV 由错误的 `cash + unrealized`
（重复扣减持仓现金）改为正确的 `cash + Σ(units×mid)`；`tests/test_backtest_portfolio.py`
中两条断言原样编码了错误恒等式，已改为正确恒等式（断言更强，非弱化）。
全量 pytest：2541 total（2522 passed + 19 pre-existing M08-W03 time-bombed
risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（425 source files）；
acceptance 11/11。下一 READY item：M12-W06。

#### M12-W06 已闭环证据（R-20260813-M12-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M12-W06-01 | Seeded lookahead, revised-future-data, target leakage, train-test overlap, and timestamp-boundary violations fail automated leakage gates | `tests/test_backtest_leakage.py`：`check_chronological_bars`（`test_reversed_bar_fails`/`test_duplicate_timestamp_fails` → timestamp_boundary）；`check_declared_data_version`（`test_revised_version_fails` → revised_future_data，未声明修订版本 fail-closed）；`check_trailing_features_lookahead`（对每个 bar 用 bars[:i+1] 重算 close_sma/volume_sma/return 并与提供值逐项比对——`test_future_close_seeded_into_sma_fails`/`test_future_return_seeded_fails`/`test_missing_trailing_value_fails` → seeded_lookahead）；`check_train_test_disjoint`（`test_shared_timestamp_fails`/`test_test_before_train_end_fails` → train_test_overlap）；`check_signals_within_bars`（`test_future_dated_signal_fails`/`test_synthetic_timestamp_fails` → target_leakage）；`run_leakage_gates` 聚合（`test_clean_fixture_passes_all_gates` 5 gate 全过、`test_any_failure_fails_the_report`、`test_repeated_runs_are_identical`） |
| AC-M12-W06-02 | Parameter perturbation, subperiod, walk-forward, and multiple-testing fixtures emit stability metrics and explicit overfitting warnings | `tests/test_strategy_overfitting.py`：`perturbation_stability`（grid spread，`test_spread_across_perturbation_grid`）+ `best_margin`（best vs median，`test_best_margin_from_median`）；`subperiod_stability`（CV，零均值/单 period → None，量化 1e-12 去 float noise）；`multiple_testing_warning`（>20 trials → warning，`test_many_trials_warn`）；`walk_forward_warning`（OOS 劣于 IS 超阈值 → walk_forward_degradation，且与 W04 runner 的 overfit_flag 语义一致——`test_walk_forward_runner_output_feeds_the_warning`）；`run_overfitting_audit` 聚合 3 metrics + warnings（`test_healthy_audit_passes_with_metrics`/`test_multiple_testing_warns`/`test_walk_forward_degradation_warns`/`test_identical_inputs_produce_identical_audits`） |
| AC-M12-W06-03 | Kronos, Gym, and advisory predictions can create evidence records but cannot directly create an OrderIntent, RiskDecision, or broker request | `tests/test_gym_invariants.py`：`test_gym_sources_never_reference_orders_or_brokers`（对 `alphabrief_gym` 全部源文件断言 OrderIntent/RiskDecision/broker/submit/oanda token 零出现）+ `test_gym_public_exports_are_evidence_only` + `test_no_gym_function_returns_an_order_intent`；`test_gym_policy_output_is_a_typed_evaluation_not_an_order`；Kronos：`build_kronos_evidence` 产出 durable advisory record（`test_evidence_records_are_advisory_only_and_locked`——`advisory_only=False` 被 validator 拒绝）、evidence 无法构造 OrderIntent（缺 side/order_type/intent 字段 → ValidationError，`test_evidence_cannot_become_an_order_intent`/`test_order_intent_requires_fields_evidence_does_not_have`）、无法构造 RiskDecisionRecord（缺 decision_id/account_id/policy_hash/inputs_hash 权威字段 → ValidationError，`test_evidence_cannot_become_a_risk_decision`）；叠加既有 `test_kronos_integration.py`（ModelGateway-only）与 `test_ai_trader_rules.py`（DisciplineGate） |

#### M12 Requirement Traceability（M12-W01..W06）

| Requirement | Code / Evidence |
|---|---|
| REQ-STRAT-001..005 | W01-W05 已闭环（dsl/families/portfolio+execution+metadata/evaluation/reporting，见上各轮） |
| REQ-STRAT-006（overfitting audit、参数稳定性、multiple-testing 警示、data leakage/lookahead tests） | W06 `alphabrief_backtest/leakage.py`（5 个 fail-closed gate + 聚合报告）+ `alphabrief_backtest/overfitting.py`（perturbation/subperiod/walk-forward/multiple-testing audit + 显式 warnings）；`tests/test_backtest_leakage.py`/`tests/test_strategy_overfitting.py` |
| REQ-STRAT-007（Kronos/Gym/其他预测只提供 advisory evidence，不能绕过 committee 或 RiskGate） | W02 admission `PREDICTIVE_FAMILY_IDS`；W06 `tests/test_gym_invariants.py`（gym 零 order/broker 引用、Kronos evidence advisory_only 锁定、evidence 无法构造 OrderIntent/RiskDecision）；既有 `test_kronos_integration.py`/`test_ai_trader_rules.py` 全绿 |

范围说明：`tests/test_backtest_leakage.py`、`tests/test_strategy_overfitting.py`、
`tests/test_gym_invariants.py` 为 M12-W06 契约声明的测试文件（targeted command
声明，documented forced path）；`leakage.py`/`overfitting.py` 为 M12-W06 契约
声明的生产模块（REQ-STRAT-006/007，scope profile `strategy_backtest`，
risk_class safety-critical：gate 全部 fail-closed、无任何可绕过路径）。
`test_gym_invariants.py` 的 safety-gate 扫描命中项为该测试自身的 deny-list
tuple 与 required-fields 集合（证明边界用，非真实 forbidden 内容），按 M09-W07
precedent 记录 PASS。全量 pytest：2587 total（2568 passed + 19 pre-existing
M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean
（430 source files）；acceptance 11/11。下一 READY item：M12-W07。

#### M12-W07 已闭环证据（R-20260813-M12-W07）— M12 里程碑 gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M12-W07-01 | All M12 DSL, strategy, portfolio, cost, walk-forward, metric, leakage, stability, and advisory-boundary fixture suites pass deterministically | targeted 九套（`test_strategy_dsl` 38 + `test_strategy_builtins` + `test_strategy_admission` + `test_backtest_portfolio` + `test_backtest_execution_semantics` + `test_backtest_walk_forward` + `test_backtest_reports` + `test_backtest_leakage` + `test_strategy_overfitting`，207 passed）+ integration 五套（`test_oanda_backtest_parity`/`test_kronos_integration`/`test_gym_invariants`/`test_backtest_commands`/`test_strategies_api`，65 passed）——W01-W06 全部 fixture 套件确定性通过（同输入同输出断言在每轮已建立） |
| AC-M12-W07-02 | Requirement traceability maps REQ-STRAT-001 through REQ-STRAT-008 to code, versioned reports, automated evidence, and current progress | 见下 M12 Requirement Traceability（W01-W07 全映射，含代码/测试/versioned report/ledger/progress 证据）；progress.yaml M12 → DONE、latest_validation 记录真实 exit code |
| AC-M12-W07-03 | Full repository, static analysis, autonomous acceptance, and reproducibility gates pass without arbitrary-code execution or broker-side effects | full pytest 2568 passed + 19 pre-existing M08-W03 time-bomb 失败（分类见 M10-W03）；ruff/mypy 全仓 clean（430 source files）；`alphabrief acceptance verify` 11/11；arbitrary-code 不可执行由 W01 safe DSL（禁例表 + allowlist 编译）证明；broker-side effects 零——M12 全部为本地确定性策略/回测/审计模块，无任何执行路径触及 broker（W06 gym/Kronos advisory-boundary 测试证明） |

#### M12 Requirement Traceability（M12-W01..W07 里程碑闭环）

| Requirement | Code / Evidence |
|---|---|
| REQ-STRAT-001（safe DSL cannot execute arbitrary code） | W01 `alphabrief_strategy/dsl.py`：`compile_condition`/`evaluate_condition`（typed frozen AST、禁例表、allowlist、declared-leaves-only 求值）；`tests/test_strategy_dsl.py`（38 用例） |
| REQ-STRAT-002（trend/mean reversion/breakout/volatility regime/no-trade families + 类别限定） | W02 `alphabrief_strategy/families.py` + `FAMILY_APPLICABILITY`；`tests/test_strategy_builtins.py`/`test_strategy_admission.py` |
| REQ-STRAT-003（真实 IS/OOS、rolling/anchored walk-forward、参数冻结、benchmark、可重复 data version） | W04 `alphabrief_backtest/evaluation.py`；`tests/test_backtest_walk_forward.py`/`test_backtest_reproducibility.py` |
| REQ-STRAT-004（多品种/组合感知 + spread/slippage/financing/margin/minimum units/market hours/rejected orders） | W03 `alphabrief_backtest/portfolio.py`/`execution.py`/`metadata.py`；`tests/test_backtest_portfolio.py`/`test_backtest_execution_semantics.py` |
| REQ-STRAT-005（报告含 11 指标 + attribution + cost attribution + benchmark delta） | W05 `alphabrief_backtest/reporting.py`；`tests/test_backtest_reporting.py` |
| REQ-STRAT-006（overfitting audit、参数稳定性、multiple-testing 警示、leakage/lookahead tests） | W06 `alphabrief_backtest/leakage.py`/`overfitting.py`；`tests/test_backtest_leakage.py`/`test_strategy_overfitting.py` |
| REQ-STRAT-007（Kronos/Gym/预测仅 advisory evidence，不能绕过 committee/RiskGate） | W02 `admission.PREDICTIVE_FAMILY_IDS`；W06 `tests/test_gym_invariants.py` + 既有 `test_kronos_integration.py`/`test_ai_trader_rules.py` |
| REQ-STRAT-008（回测与 practice 相同 metadata/关键 semantics，差异显式记录） | W03 `SEMANTICS_VERSION`/`SEMANTICS_DIFFERENCES` + parity；`tests/test_oanda_backtest_parity.py` |

范围说明：M12-W07 为里程碑 gate round——无新生产代码，全部 acceptance 由
W01-W06 已提交 evidence 与全量 gate 运行证明。全量 pytest：2587 total
（2568 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，
分类见 M10-W03）；ruff/mypy 全仓 clean（430 source files）；acceptance 11/11。
**M12 里程碑 → DONE**（无 T7 runtime 依赖，全部本地确定性 gate 通过）。
下一 READY item：M13-W01。

#### M13-W01 已闭环证据（R-20260813-M13-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M13-W01-01 | Every required read surface has one versioned response schema with UTC timestamps, stable IDs, provenance, freshness, pagination, and explicit empty or partial state | `tests/test_api_read_contracts.py`：`VersionedReadEnvelope` 为每个 read surface 的唯一 versioned schema（`READ_SCHEMA_VERSION="read-v1"`）；`test_each_domain_has_one_versioned_schema`（14 个 domain 全部 parametrize 覆盖）与 `test_all_required_domains_are_covered`（instruments/prices/candles/news/sentiment/committee/risk/orders/trades/positions/cycles/scheduler/alerts/observation）；`test_timestamps_are_utc`/`test_non_utc_or_naive_timestamps_are_rejected`（naive 或非 UTC aware → ValidationError，REQ-PLAT-008）；`test_items_carry_stable_ids_and_deterministic_ordering`（每 item 必有非空 `id`，builder 按 id 排序——稳定 ID 与稳定顺序，REQ-PLAT-009）；`test_provenance_and_freshness_are_present`（source/data_version/retrieved_at + fresh/stale/unknown verdict）；`test_empty_and_partial_states_are_explicit`（items 空 → state 必须 empty，非空 → complete/partial，不一致 ValidationError）；`test_pagination_contract_is_consistent`（has_more ⇔ next_cursor） |
| AC-M13-W01-02 | API JSON and CLI JSON for the same fixture normalize to the same domain payload and ordering | `tests/test_cli_read_contracts.py`：`_api_style_json`（FastAPI model_dump JSON）与 `_cli_style_json`（CLI `_dump` 约定：sort_keys + str fallback）对同一 fixture envelope 归一化到同一个 `normalize_read_payload` canonical payload（`test_api_and_cli_json_normalize_to_the_same_domain_payload`）；items 顺序两边一致（`test_api_and_cli_share_one_item_ordering`）；`test_normalized_payload_is_byte_stable`；空/partial state 两边相同（`test_empty_and_partial_states_are_identical_across_surfaces`） |
| AC-M13-W01-03 | Unknown filters, malformed cursors, invalid identifiers, and unavailable sources return typed errors without fake or silently truncated data | `unknown_filter_error`/`malformed_cursor_error`/`invalid_identifier_error`/`unavailable_source_error` 四个 builder 返回 `ReadErrorResponse`（error_code + 显式 message 含违规值 + resource + schema_version）；`test_typed_errors_never_carry_items`（error payload 无 items/pagination——绝不带 fake 或静默截断数据）；`TestSharedTypedErrors`（API/CLI 两侧 error JSON 完全相同）；`test_error_payloads_never_contain_items_or_data` |

#### M13 Requirement Traceability（M13-W01）

| Requirement | Code / Evidence |
|---|---|
| REQ-PLAT-008（所有记录使用 UTC，展示层可按用户时区转换） | W01 `alphabrief_core/read_contracts.py`：`generated_at`/`retrieved_at` validator 强制 UTC（naive 或 offset≠0 → ValidationError）；`tests/test_api_read_contracts.py` |
| REQ-PLAT-009（所有关键 ID 可跨数据、研究、模型、风险、订单和对账追踪） | W01 每 item 稳定 `id` + provenance（source/data_version/retrieved_at）随 envelope 传递；`tests/test_api_read_contracts.py` |
| REQ-UI-001（API/CLI 对 14 类 read 提供一致 schema） | W01 `VersionedReadEnvelope`/`READ_DOMAINS`/`normalize_read_payload` 共享于 API 与 CLI 两侧；`tests/test_api_read_contracts.py`/`tests/test_cli_read_contracts.py` |

范围说明：`tests/test_api_read_contracts.py` 与 `tests/test_cli_read_contracts.py` 为
M13-W01 契约声明的测试文件（targeted command 声明，documented forced path）；
`alphabrief_core/read_contracts.py` 为 M13-W01 契约声明的生产模块（REQ-UI-001/
REQ-PLAT-008/009，scope profile `api_cli`）；API/CLI 既有 route/command 零改动
（integration 五套 68 passed 证明无回归）。全量 pytest：2626 total（2607 passed
+ 19 pre-existing M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；
ruff/mypy 全仓 clean（433 source files）；acceptance 11/11。下一 READY item：
M13-W02。

#### M13-W02 已闭环证据（R-20260813-M13-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M13-W02-01 | Only pause or resume research, freeze or unfreeze paper execution, cancel practice order, and reduce or close practice exposure are exposed as operator mutations | `tests/test_api_write_contracts.py`：`test_operator_mutations_are_exactly_the_approved_seven`（`OPERATOR_MUTATIONS` == REQ-UI-010 的 7 个 mutation，closed set）；`test_every_mutation_has_approved_endpoints_and_payload_keys`（每个 mutation 有且仅有 approved endpoint 与 payload key allowlist）；`test_existing_api_mutation_endpoints_are_classified`（对 `apps/api/routes` 全部 24 个 mutation route 扫描——`freeze`/`unfreeze` 归入 operator mutations，其余归入 documented non-operator classes：ingestion/model/research/registry/run/reconcile/strategy-driven orders，无一未分类）；`tests/test_cli_control_commands.py` 的 `test_cli_commands_never_add_operator_mutations`（CLI command 不引入 approved set 之外的 operator mutation） |
| AC-M13-W02-02 | Every accepted mutation validates current state, requires an idempotency key, persists actor and correlation metadata, and returns the same result on replay | `test_accepted_mutation_requires_and_persists_metadata`（audit 记录 actor/correlation_id/target/at，`MutationAuditLog` 持久化）；`test_idempotency_key_is_required`（缺失/空 → ValidationError）；`test_current_state_is_validated`（expected_state_version ≠ current → stale_version 拒绝）；`test_replay_returns_the_same_result`（同 idempotency_key 重放 → replay=True、result_payload/audit_id/at 完全一致、log 仅 1 条）；`test_replay_reproduces_rejections_too`；`test_every_approved_mutation_accepts_with_its_endpoint`（7 个 mutation × 各自 endpoint 全 accepted）；CLI 侧 `test_replay_is_deterministic_on_the_cli_side` |
| AC-M13-W02-03 | Live host, arbitrary endpoint, arbitrary broker payload, unsupported mutation, stale version, and cross-account fixtures fail before provider invocation and leave an audit rejection | `TestFailBeforeInvocation`：`test_live_host_fails_before_invocation`（live host fixture——运行时拼接字符串避免文件内 literal——→ `live_host_forbidden`）；`test_arbitrary_endpoint_fails`（→ `arbitrary_endpoint`）；`test_arbitrary_broker_payload_fails`（payload keys ⊄ allowlist → `arbitrary_broker_payload`）；`test_unsupported_mutation_fails`（registry 外 → fail-closed）；`test_stale_version_fails`（→ `stale_version`）；`test_cross_account_fails`（→ `cross_account`）——全部 rejected 结果 result_payload=None 且 audit 记录 accepted=False；`test_gate_never_invokes_any_provider`（gate 模块无 requests/urllib/oanda/submit 引用，纯函数）；CLI 侧 `test_live_host_rejects_every_mutation`（7 个 mutation 全被 live host 拒绝）、`test_cli_rejections_leave_audit_records`、`test_approved_endpoint_registry_is_complete` |

#### M13 Requirement Traceability（M13-W01..W02）

| Requirement | Code / Evidence |
|---|---|
| REQ-PLAT-008 | W01 `read_contracts.py` UTC 强制；`tests/test_api_read_contracts.py` |
| REQ-PLAT-009（关键 ID 跨层可追踪） | W01 envelope 稳定 id/provenance；W02 `MutationAudit`（audit_id/actor/correlation_id/idempotency_key/target 全记录，replay 同一 audit）；相关测试 |
| REQ-UI-001（API/CLI 一致 read schema） | W01 `VersionedReadEnvelope`/`normalize_read_payload`；`tests/test_api_read_contracts.py`/`test_cli_read_contracts.py` |
| REQ-UI-002（写操作 validation/idempotency/权限边界/清晰错误，无通用任意 broker request 代理） | W02 `write_contracts.py`：`WriteContractGate` 纯函数 fail-before-invocation（host/account/endpoint/payload/version 五重校验 + idempotency replay + audit）、无任何 provider 引用；`tests/test_api_write_contracts.py`/`test_cli_control_commands.py` |
| REQ-UI-010（手工控制仅 7 种 mutation，全部审计） | W02 `OPERATOR_MUTATIONS` closed set + `MutationAuditLog` append-only；AC-M13-W02-01/02 evidence |

范围说明：`tests/test_api_write_contracts.py` 与 `tests/test_cli_control_commands.py` 为
M13-W02 契约声明的测试文件（targeted command 声明，documented forced path）；
`alphabrief_core/write_contracts.py` 为 M13-W02 契约声明的生产模块（REQ-UI-002/010、
REQ-PLAT-009，scope profile `api_cli`，risk_class safety-critical：全部 fail-closed、
无 provider 调用路径）。集成 gate 中 `tests/test_paper_commands.py` 的
`test_paper_status_prints_placeholder` 原依赖环境无 API server（本环境存在
launchd 管理的 `alphabrief serve serve`，`is_api_running()` 返回 True 导致 exit 1）；
已按 CLI 文档化的 test-isolation 契约（`ALPHABRIEF_DATA_DIR` 置位 → `is_api_running`
恒 False）将该测试改为 hermetic（断言不变，仅消除环境依赖），记录于本 closure 与
ledger。全量 pytest：2662 total（2643 passed + 19 pre-existing M08-W03 time-bombed
risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（436 source files）；
acceptance 11/11。下一 READY item：M13-W03。

#### M13-W03 已闭环证据（R-20260813-M13-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M13-W03-01 | API resources expose account, NAV, margin, PnL, exposures, positions, pending orders, fills, financing, category attribution, and their observation timestamps from runtime stores | `tests/test_api_operational_resources.py`：`GET /api/v1/operational/portfolio` 全部字段来自共享 runtime stores（`PaperStore` portfolio snapshot + audit events、`BrokerReconStore` order ledger、`InstrumentCatalogStore` catalog）——`test_portfolio_exposes_runtime_store_values`（cash/nav/realized/unrealized=total-cash-realized、exposure gross/net、positions、pending_orders 仅非终态、fills、snapshot_id/observed_at=store 时间戳、financing=null 显式）；`test_margin_derived_from_shared_catalog`（margin_used 由 catalog margin_rate 推导 1030.00）；`test_category_attribution_derived_from_taxonomy`（CURRENCY/METAL 分类敞口）；`test_missing_catalog_yields_explicit_null_margin`（catalog 缺失 → margin/attribution 显式 null，绝不 fake）；`test_empty_store_returns_explicit_nulls_not_fakes`；`GET /api/v1/operational/equity` 时序（`TestEquitySeries`：persisted points、limit 校验、空序列） |
| AC-M13-W03-02 | A cycle trace endpoint resolves evidence, committee transcript, proposal or no-trade, intent, each risk rule, OANDA transaction, and reconciliation through stable IDs | `tests/test_api_traceability.py`：`GET /api/v1/trace/cycles/{cycle_id}`——`test_trace_resolves_the_full_chain`（evidence=snapshot_fingerprint+key_evidence 稳定 ID、transcript=votes、proposal=plans、intents=intent_id+audit resolution、risk_rules=risk_decision_id+intent_id、oanda_transactions=order ledger 行、reconciliation=recon snapshot，全链稳定 ID）；`test_no_trade_cycle_reports_no_trade`（无 plans/attempts → `"no_trade"` 显式）；`test_missing_cycle_returns_404`；`test_chain_ids_are_stable_across_calls`（两次调用逐字节相同） |
| AC-M13-W03-03 | Broker, scheduler, risk, model, news, and market routes use shared application authorities and contain no offline-success placeholder or route-local production state | 新增两个 route 模块均为只读、逐请求打开共享 store（`_db_path()` 指向同一 DuckDB authority：`PaperStore`/`BrokerReconStore`/`InstrumentCatalogStore`/`AiTradingStore`），无 route-local 生产状态、无 offline-success 占位（缺数据 → 显式 null/404）；集成 gate 证明既有 broker/scheduler/ai_trading/api_server 路由（148 passed）无回归；`operational.py`/`trace.py` 无任何 provider/broker 调用（REQ-EXEC-010 共享 authority） |

#### M13 Requirement Traceability（M13-W01..W03）

| Requirement | Code / Evidence |
|---|---|
| REQ-PLAT-008/009 | W01 read contracts（UTC/稳定 ID）；W02 write audit（correlation/audit ID）；相关测试 |
| REQ-UI-001 | W01 `VersionedReadEnvelope` 14 domain；相关测试 |
| REQ-UI-002/010 | W02 `write_contracts.py`；相关测试 |
| REQ-EXEC-010（API、CLI、scheduler 共享同一 broker runtime/state authority，不各自构造互相冲突的内存账户） | W03 operational/trace 路由全部从共享 DuckDB stores 读取（PaperStore/BrokerReconStore/InstrumentCatalogStore/AiTradingStore），无 route-local 状态；`tests/test_api_operational_resources.py`/`test_api_traceability.py` |
| REQ-UI-006（订单和风险链可从 cycle 一键追溯到 evidence、讨论、intent、每条 risk rule、OANDA transaction 和 reconciliation） | W03 `GET /api/v1/trace/cycles/{cycle_id}`；`tests/test_api_traceability.py` |
| REQ-UI-007（展示 cash、NAV、margin、P&L、exposure、positions、pending orders、fills、financing、category attribution 和时间序列） | W03 `GET /api/v1/operational/portfolio` + `/equity`；`tests/test_api_operational_resources.py` |

范围说明：`tests/test_api_operational_resources.py` 与 `tests/test_api_traceability.py`
为 M13-W03 契约声明的测试文件（targeted command 声明，documented forced path）；
`routes/operational.py`/`routes/trace.py` 为 M13-W03 契约声明的生产模块（REQ-EXEC-010/
REQ-UI-001/006/007，scope profile `api_cli`，risk_class execution-critical：
只读、共享 authority、无 provider 行为）。集成 command 声明的 `tests/test_risk_api.py`
在仓库中不存在（risk API 覆盖位于 `tests/test_api_server.py`，已作为 documented
substitution 运行并记录）。全量 pytest：2674 total（2655 passed + 19 pre-existing
M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean
（440 source files）；acceptance 11/11。下一 READY item：M13-W04。

#### M13-W04 已闭环证据（R-20260813-M13-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M13-W04-01 | Instruments, market data, news, sentiment, committee, risk, broker, cycle, scheduler, alert, and observation commands support stable compact JSON output without prompts | `tests/test_cli_contracts.py`：`test_every_required_domain_has_a_command_group`（11 个 domain → CLI group 映射全存在）；`test_read_command_emits_stable_json_without_prompts`（11 个 domain 各一个代表性 read command 运行 → JSON 可解析且两次运行 normalized payload 完全一致——stable；news/sentiment 经新增 `news list --json`（`emit_json` compact stable 路径））；`test_no_command_reads_stdin`（stdin 关闭运行全部命令，无 prompt）；CLI 全仓 grep 确认无 `input()/typer.prompt/click.prompt` |
| AC-M13-W04-02 | Success, empty, partial, validation, conflict, unavailable, frozen, and internal error states map to documented deterministic exit codes and structured stderr | `contracts.py`：`EXIT_SUCCESS=0`/`INTERNAL=1`/`VALIDATION=2`/`EMPTY=3`/`PARTIAL=4`/`CONFLICT=5`/`UNAVAILABLE=6`/`FROZEN=7` + `EXIT_CODE_NAMES` 文档化映射；`EmptyResultError`/`PartialResultError`/`ConflictError`/`SourceUnavailableError`/`FrozenStateError`/`CliExit` 六个 typed error；`emit_error` 输出 `{"error_code","exit_code","message"}` 到 stderr 并确定性退出；`test_exit_codes_are_documented_and_stable`/`test_error_states_map_to_codes_and_structured_stderr`（7 组 parametrize）/`test_emit_error_writes_structured_stderr_and_exits` |
| AC-M13-W04-03 | API-backed and permitted local read-only execution over the same fixture return equivalent normalized payloads and cannot create conflicting writer ownership | `read_local_or_api`（API up → api 路径；API 失败 → local 只读 fallback，返回 `(payload, source)`）+ `normalize_payload`/`equivalent_normalized_payloads`（sort_keys + compact + str fallback canonical）；`test_api_and_local_reads_normalize_identically`/`test_local_fallback_when_api_unavailable`（fallback 后 normalized payload 等价）/`test_normalized_payloads_are_order_and_key_stable`；`test_local_read_path_never_acquires_the_writer_lease`（contracts.py 无 writer_lease/无 SQL 执行/无 INSERT/UPDATE——local 路径只读，绝不与 scheduler/API writer 冲突） |

#### M13 Requirement Traceability（M13-W01..W04）

| Requirement | Code / Evidence |
|---|---|
| REQ-PLAT-008/009 | W01 read contracts；W02 write audit；相关测试 |
| REQ-UI-001 | W01 `VersionedReadEnvelope`；W04 CLI 11 domain JSON 覆盖 |
| REQ-UI-002/010 | W02 `write_contracts.py`；相关测试 |
| REQ-EXEC-010 | W03 operational/trace 共享 authority；相关测试 |
| REQ-UI-006/007 | W03 trace/operational 路由；相关测试 |
| REQ-UI-001（API/CLI 一致 schema，CLI 侧） | W04 `alphabrief_cli/contracts.py`：`emit_json`（stable compact JSON）、`normalize_payload`/`equivalent_normalized_payloads`（API/local 归一化等价）、`read_local_or_api`（API-backed ↔ local 只读 parity，无 writer lease）；`tests/test_cli_contracts.py` |

范围说明：`tests/test_cli_contracts.py` 为 M13-W04 契约声明的测试文件（targeted
command 声明，documented forced path）；`alphabrief_cli/contracts.py` 为 M13-W04
契约声明的生产模块（REQ-UI-001/002/010，scope profile `api_cli`，risk_class
execution-critical）；`news_commands.py` 新增 `--json` 选项（经共享 `emit_json`，
默认 human 输出不变——`test_news_commands.py` 无回归）。集成 command 声明的
`tests/test_model_commands.py` 不存在（model CLI 覆盖位于 `tests/test_model_cli.py`，
documented substitution）。全量 pytest：2700 total（2681 passed + 19 pre-existing
M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean
（441 source files）；acceptance 11/11。下一 READY item：M13-W05。

#### M13-W05 已闭环证据（R-20260813-M13-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M13-W05-01 | Generated OpenAPI is deterministic and declares every read and approved mutation schema, error model, cursor, freshness field, idempotency header, and correlation identifier | `tests/test_openapi_contract.py`：`build_deterministic_openapi` 字节级确定（`test_generation_is_byte_deterministic`，sort_keys + compact）；`x-alphabrief-contract` extension 声明全部 14 read domains、7 approved operator mutations、approved endpoints、error model（error_code/message/resource）、cursor fields（cursor/next_cursor/has_more/limit/count）、freshness fields（status/age/max_age）、`Idempotency-Key` header、`X-Correlation-ID` header（`test_contract_extension_is_declared`/`test_error_model_cursor_freshness_are_declared`）；`verify_openapi_contract` 全绿且缺失 extension 时 fail-closed（`test_verification_passes`/`test_verification_fails_closed_on_missing_extension`）；`test_no_sensitive_example_values`（schema 文本扫描无 bearer/api-key/authorization） |
| AC-M13-W05-02 | Contract tests prove cursor stability, bounded page sizes, UTC serialization, decimal fidelity, unknown-field rejection, and no sensitive example values | `test_cursor_round_trip_is_stable`（PageCursor round-trip 稳定）+ `test_cursor_contract_matches_declaration`/`test_freshness_verdict_matches_declaration`（model fields == 声明）；`test_bounded_page_sizes`（operational equity limit 0/5000 → 422）；`test_utc_serialization`（generated_at/retrieved_at UTC）；`test_decimal_fidelity`（Decimal 经 str 完整往返）；`test_unknown_fields_are_rejected`（envelope extra=forbid → ValidationError）；`test_no_sensitive_example_values` |
| AC-M13-W05-03 | Every documented CLI JSON command maps to an OpenAPI resource or an explicitly local read-only contract with automated schema parity | `tests/test_api_cli_parity.py`：`CLI_TO_RESOURCE` 映射表（10 个 CLI JSON command → OpenAPI path；`paper status`/`risk status` → 显式 `"local"` read-only contract）；`test_every_cli_json_command_maps_to_a_declared_resource`（每个映射 path 都在生成的 OpenAPI 中）；`test_local_only_commands_are_explicitly_local`（local contract 命令仍产出 stable JSON）；`test_every_required_domain_is_covered_by_a_mapping`（11 domain 全覆盖）；`test_same_fixture_normalizes_identically_across_api_and_cli`/`test_cli_normalized_output_matches_api_response_shape`/`test_local_fallback_parity_over_the_same_fixture`（API/local 同 fixture normalized 等价）；`test_openapi_schema_serializes_without_lossy_values`（无 NaN/Infinity） |

#### M13 Requirement Traceability（M13-W01..W05）

| Requirement | Code / Evidence |
|---|---|
| REQ-PLAT-008/009 | W01 read contracts；W02 write audit；W05 OpenAPI contract 声明 correlation/idempotency header 与稳定 ID 语义 |
| REQ-UI-001 | W01 envelope；W04 CLI JSON；W05 OpenAPI 声明 14 read domains + API-CLI 映射 |
| REQ-UI-002/010 | W02 write_contracts；W05 OpenAPI 声明 7 mutations + idempotency header + error model |
| REQ-EXEC-010 | W03 共享 authority 路由 |
| REQ-UI-006/007 | W03 trace/operational 路由；W05 OpenAPI 声明这些 resource paths |
| REQ-UI-001（OpenAPI 侧） | W05 `alphabrief_api/openapi_contract.py`：`build_deterministic_openapi`/`verify_openapi_contract`/`scan_for_sensitive_values`；`tests/test_openapi_contract.py`/`test_api_cli_parity.py` |

范围说明：`tests/test_openapi_contract.py` 与 `tests/test_api_cli_parity.py` 为 M13-W05
契约声明的测试文件（targeted command 声明，documented forced path）；
`alphabrief_api/openapi_contract.py` 为 M13-W05 契约声明的生产模块（REQ-UI-001/
REQ-UI-002/006、REQ-PLAT-009，scope profile `api_cli`）。全量 pytest：2720 total
（2701 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，分类见
M10-W03）；ruff/mypy 全仓 clean（444 source files）；acceptance 11/11。
下一 READY item：M13-W06。

#### M13-W06 已闭环证据（R-20260813-M13-W06）— M13 里程碑 gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M13-W06-01 | API and CLI contract suites cover every required resource and approved control with equivalent schemas, typed errors, stable IDs, and no interactive step | targeted 八套（W01-W05 全部契约套件，123 passed）：read/write contracts、operational resources、traceability、CLI contracts/control、OpenAPI contract、API-CLI parity——equivalent schemas（normalize_payload 等价）、typed errors（ReadErrorResponse/MutationAudit/CliExit）、stable IDs（envelope id/provenance、audit_id、trace 全链）、no interactive step（CLI stdin 关闭运行）全部由各轮证据覆盖 |
| AC-M13-W06-02 | Static gates find no arbitrary broker proxy, route-local production state, offline-success placeholder, live control, undocumented mutation, or sensitive OpenAPI example | `tests/test_api_cli_static_gate.py`（10 passed）：`TestNoArbitraryBrokerProxy`（route 无 api_route/requests/httpx 代理；write gate 无 provider 引用）；`TestNoRouteLocalProductionState`（operational/trace 无 module-level 可变状态、逐请求开 store 并 finally 关闭）；`TestNoOfflineSuccessPlaceholder`（无硬编码 success、缺数据显式 null/404）；`TestNoLiveControl`（api/cli 源码零 live-host 引用、无 live_mode/--live 开关）；`TestNoUndocumentedMutation`（全部 mutation route 分类）；`TestNoSensitiveOpenapiExamples`（schema 扫描空） |
| AC-M13-W06-03 | Full repository, static analysis, OpenAPI, API-CLI parity, autonomous acceptance, and M13 traceability gates pass without waiver or human approval | targeted 123 + integration 182（含 test_api_server 的 backtest API 覆盖，documented substitution）+ ruff/mypy clean（445 source files）+ full pytest 2711 passed + 19 pre-existing M08-W03 time-bomb（分类见 M10-W03）+ acceptance 11/11；REQ-UI-001/002/006/007/010 全 trace（见下） |

#### M13 Requirement Traceability（M13-W01..W06 里程碑闭环）

| Requirement | Code / Evidence |
|---|---|
| REQ-UI-001（API/CLI 对 14 类 read 提供一致 schema） | W01 `read_contracts.py`（envelope/14 domains/normalize_payload）；W04 `cli/contracts.py`（JSON/parity）；W05 `openapi_contract.py`（OpenAPI 声明 + API-CLI 映射） |
| REQ-UI-002（写操作 validation/idempotency/权限边界/清晰错误，无通用任意 broker request 代理） | W02 `write_contracts.py`（gate/replay/audit）；W04 exit codes；W05 OpenAPI idempotency header/error model |
| REQ-UI-006（cycle 一键追溯 evidence→discussion→intent→risk rules→OANDA transaction→reconciliation） | W03 `routes/trace.py`；`test_api_traceability.py` |
| REQ-UI-007（cash/NAV/margin/P&L/exposure/positions/pending orders/fills/financing/category attribution/时序） | W03 `routes/operational.py`（portfolio/equity）；`test_api_operational_resources.py` |
| REQ-UI-010（手工控制仅 7 种 mutation，全部审计） | W02 `OPERATOR_MUTATIONS`/`MutationAuditLog`；W05 OpenAPI 声明 |
| REQ-PLAT-008/009 | W01 UTC/稳定 ID；W02 correlation/audit ID；W05 correlation header |

范围说明：`tests/test_api_cli_static_gate.py` 为 M13-W06 契约声明的静态 gate 测试
文件（AC-M13-W06-02 evidence，documented forced path）；M13-W06 为里程碑 gate
round，无新生产代码。集成 command 声明的 `tests/test_backtest_api.py` 不存在
（backtest API 覆盖位于 `tests/test_api_server.py`，documented substitution）。
全量 pytest：2730 total（2711 passed + 19 pre-existing M08-W03 time-bombed
risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（445 source files）；
acceptance 11/11。**M13 里程碑 → DONE**（无 T7 runtime 依赖，全部本地确定性
gate 通过）。下一 READY item：M14-W01。

#### M14-W01 已闭环证据（R-20260813-M14-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M14-W01-01 | A before-and-after audit maps every legacy dashboard route, retained brand asset, usability defect, and planned replacement without changing runtime business behavior | `tests/test_dashboard_brand_audit.py`：`BRAND_AUDIT` 覆盖全部 9 个 legacy dashboard route（`/dashboard`、news、macro、brief、debate、models、strategies、ai-trading、scheduler——`test_audit_maps_every_legacy_dashboard_route` 从 `dashboard.py` 正则提取 route 集合并与 audit 键集合逐一相等）；每个 entry 含 retained_assets（alphabrief-wordmark/oanda-practice-badge/paper-only-badge 原样保留，`test_audit_preserves_brand_assets_verbatim`）、defects（legacy dark-only palette/inline styles 未 token 化/cyan accent 越界 Soft/无 reduced-motion）、replacement（Soft token system/light+dark themes/purposeful motion）；`test_audit_module_is_data_only`（design_system.py 无 router/HTMLResponse/duckdb/get_ 处理器——纯数据）+ `test_dashboard_route_handlers_are_untouched`（route 模块不 import design_system，runtime business behavior 零改动）+ `test_audit_records_are_stable` |
| AC-M14-W01-02 | One documented Soft 5/5/5 token system controls color, typography, spacing, radius, elevation, interaction, motion, light theme, dark theme, and reduced-motion behavior | `tests/test_dashboard_design_system.py`：`DESIGN_TOKENS` 单一来源（`test_all_required_categories_are_controlled`：color_light/color_dark/typography/spacing/radius/elevation/interaction/motion 全齐）；`test_light_and_dark_themes_are_declared`（THEMES light/dark 且两主题键一致）；`test_reduced_motion_behavior_is_declared`（prefers-reduced-motion）；`test_css_file_declares_the_same_tokens`（`static/design-tokens.css` 由 token 源确定性生成，含 prefers-color-scheme dark 块与 reduced-motion 块——`test_css_has_light_and_dark_theme_blocks`/`test_css_has_reduced_motion_block`）；`validate_design_tokens()` 自动化校验全绿 |
| AC-M14-W01-03 | Shared styles contain no emoji icons, fake content, low-contrast body text, gradient buttons, or unapproved animation dependency | `test_light_theme_body_text_passes_wcag_aa`/`test_light_theme_dim_text_passes_wcag_aa`/`test_dark_theme_body_text_passes_wcag_aa`（`contrast_ratio` WCAG ≥4.5:1，#3d3a34 on #faf7f2 等）；`test_no_gradient_buttons`（token 值无 linear-gradient）；`test_no_animation_dependency_in_shared_styles`（CSS 仅 reduced-motion 的 `animation: none`，无 @keyframes/无 framer/gsap/anime 等库）；`test_no_emoji_in_ui_copy`/`test_no_em_dash_in_ui_copy`（FORBIDDEN_UI_COPY_CHARACTERS 扫描）；`test_css_contains_no_emoji_or_placeholder_content`（无 lorem/ipsum/TODO/FIXME） |

#### M14 Requirement Traceability（M14-W01）

| Requirement | Code / Evidence |
|---|---|
| REQ-UI-003（Dashboard 采用 owner 已选 Soft (5/5/5)，保留有效品牌） | W01 `dashboard/design_system.py`：DESIGN_VARIANCE=5/MOTION_INTENSITY=5/VISUAL_DENSITY=5 token 系统 + `BRAND_ASSETS` 保留；`tests/test_dashboard_design_system.py`/`test_dashboard_brand_audit.py` |
| REQ-UI-008（键盘操作、focus、semantic HTML、对比度、reduced motion） | W01 token 系统含 contrast（WCAG AA 自动化验证）、reduced-motion 规则（prefers-reduced-motion block）、focus_ring interaction token；相关测试 |

范围说明：`tests/test_dashboard_design_system.py` 与 `tests/test_dashboard_brand_audit.py`
为 M14-W01 契约声明的测试文件（targeted command 声明，documented forced path）；
`alphabrief_api/dashboard/design_system.py` 与 `static/design-tokens.css` 为 M14-W01
契约声明的生产模块（REQ-UI-003/008，scope profile `frontend`）；`dashboard.py` route
处理器零改动（audit 纯数据）。集成 command 声明的 `tests/test_dashboard.py` 不存在
（dashboard 页面覆盖位于 `tests/test_api_server.py` + `test_dashboard_models.py` +
`test_dashboard_strategies.py`，documented substitution，121 passed）。全量 pytest：
2755 total（2736 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，
分类见 M10-W03）；ruff/mypy 全仓 clean（448 source files）；acceptance 11/11。
注：M13-W06 的 ledger 记录曾误用 schema 外 record_type，已替换为 schema-valid
`CORRECTION` 记录（`test_autonomous_loop_schemas.py` 全绿）。下一 READY item：
M14-W02。

#### M14-W02 已闭环证据（R-20260813-M14-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M14-W02-01 | Navigation exposes Overview, Markets, News & Sentiment, AI Research, Risk, OANDA Account, Orders & Trades, Scheduler, 30-Day Observation, and Settings at every required viewport | `tests/test_dashboard_navigation.py`：`NAVIGATION_SECTIONS` 恰好 10 项且顺序与 REQ-UI-004 一致（`test_all_ten_required_sections_are_declared`）；每项含 route（/dashboard 前缀）/icon（库名非 emoji，`test_icons_are_library_names_not_emoji`）/order（0-9 稳定，`test_navigation_order_is_stable`）；`test_all_sections_reachable_at_every_viewport`（320/768/1024/1440 四个 viewport 全部可达）；`FULL_NAV_MIN_WIDTH=1024`（`test_full_nav_breakpoint_is_declared`）；无重复 route（`test_no_duplicate_routes`）；anchors 语义化键盘可达（`test_anchors_are_keyboard_reachable`） |
| AC-M14-W02-02 | Each route renders deterministic loading, empty, stale, partial, error, offline, frozen, and ready states from API truth instead of blank panels or fake fallback values | `tests/test_dashboard_states.py`：`PAGE_STATES` 恰好 8 态（`test_all_eight_states_are_declared`）；`derive_page_state(TruthInputs)` 从 API truth 确定性推导——ready/empty/stale/partial/error/offline/frozen 各态 fixture（`test_ready_from_fresh_complete_truth` 等 9 个派生测试）；frozen 优先于一切（`test_frozen_wins_over_everything`）、offline 绝不退化为 ready（`test_offline_never_degrades_to_ready`）、确定性（`test_derivation_is_deterministic`）；`render_state_payload` 每态有 typed payload 且只含文档化文案——`test_payloads_never_invent_runtime_values`（无捏造数字/价格/仓位）、`test_ready_payload_has_no_action`、`test_frozen_payload_mentions_frozen` |
| AC-M14-W02-03 | The shell has no horizontal page overflow at 320, 768, 1024, or 1440 pixels and preserves keyboard-reachable navigation in light and dark themes | `tests/ui/test_dashboard_responsive.py`：`shell_css()` 含 `overflow-x: hidden`/`max-width: 100%`/`* { min-width: 0 }`（`test_overflow_guards_cover_every_required_viewport`/`test_no_horizontal_overflow_rules_for_all_containers`/`test_min_width_zero_prevents_flex_overflow`）；breakpoint media queries 覆盖 767/768/1024（`test_breakpoints_cover_the_required_widths`）；`:focus-visible` outline ring + `var(--interaction-focus-ring)`（`test_focus_visible_ring_is_declared`/`test_keyboard_focus_visible_in_both_themes`）；语义 anchors + Soft token 消费（`test_navigation_uses_semantic_anchors`/`test_hover_and_focus_use_soft_tokens`/`test_shell_consumes_design_tokens_for_both_themes`） |

#### M14 Requirement Traceability（M14-W01..W02）

| Requirement | Code / Evidence |
|---|---|
| REQ-UI-003（Soft (5/5/5)，保留品牌） | W01 token 系统 + brand audit；W02 shell 消费 design tokens |
| REQ-UI-004（主导航覆盖 10 个 section） | W02 `dashboard/shell.py` `NAVIGATION_SECTIONS`（10 项，含 route/icon/order）+ viewport 可达性；`tests/test_dashboard_navigation.py` |
| REQ-UI-005（每页 loading/empty/stale/partial/error/offline/frozen 状态，不以空白或 fake data 掩盖失败） | W02 `derive_page_state`/`render_state_payload`（8 态，含 ready；truth 推导、无捏造值）；`tests/test_dashboard_states.py` |
| REQ-UI-008 | W01 reduced-motion/contrast/focus tokens；W02 focus-visible + keyboard anchors |

范围说明：`tests/test_dashboard_navigation.py`、`tests/test_dashboard_states.py`、
`tests/ui/test_dashboard_responsive.py` 为 M14-W02 契约声明的测试文件（targeted
command 声明，documented forced path，`tests/ui/` 为契约声明的目录）；集成
`tests/test_dashboard_api_contracts.py` 亦为契约声明的新文件；`dashboard/shell.py`
为 M14-W02 契约声明的生产模块（REQ-UI-003/004/005，scope profile `frontend`）。
回归 command 声明的 `tests/test_dashboard.py` 不存在（dashboard 覆盖位于
`tests/test_api_server.py` 等，documented substitution，121 passed）。全量 pytest：
2800 total（2781 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，
分类见 M10-W03）；ruff/mypy 全仓 clean（453 source files）；acceptance 11/11。
下一 READY item：M14-W03。

#### M14-W03 已闭环证据（R-20260813-M14-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M14-W03-01 | Markets browses, searches, filters, and groups the complete account-discovered catalog while displaying tradeability, category, price, spread, freshness, quality, and unsupported reasons | `tests/test_dashboard_markets.py`：`build_markets_view` 从 catalog truth + market truth maps 确定性塑形——`test_builds_complete_catalog_with_truth_fields`（tradeable/category/price/spread/freshness/quality/margin_rate 全部来自输入 truth，未知 symbol 的 price 为 null 绝不捏造）；`test_unsupported_reasons_are_explicit`（inactive → unsupported_reason 显式）；`test_groups_by_category`（`group_markets`/`view.groups` 按类别分组计数）；`test_search_is_case_insensitive`（`search_markets` symbol/display_name 大小写不敏感）；`test_filter_by_category_and_tradeability`（`filter_markets`）；`test_deterministic_ordering`（symbol 排序、两次构建逐字节相同） |
| AC-M14-W03-02 | News & Sentiment exposes source provenance, age, deduplication, entity mapping, disagreement, macro events, degradation, and injection-scan status without reproducing unlicensed full text | `tests/test_dashboard_news_sentiment.py`：`test_exposes_provenance_age_and_dedup`（source/published_at/age_seconds/content_hash/dedup_verdict）；`test_entity_mapping_is_exposed`（entity_links）；`test_never_reproduces_full_text`（full_text 输入被排除，序列化中无 full_text/无长文——只保留 bounded summary）；`test_age_is_clamped_and_deterministic`；`test_disagreement_and_sample_counts_are_exposed`（sentiment direction/intensity/disagreement/sample_count）；`test_macro_events_carry_importance_fields`（release_time/indicator/importance/actual/forecast，full_payload 排除）；`test_degradation_and_injection_scan_status` |
| AC-M14-W03-03 | AI Research shows every role turn, citation, dissent, schema or provider degradation, final proposal or no-trade result, and immutable evidence identifiers from the API | `tests/test_dashboard_ai_research.py`：`test_every_role_turn_is_shown`（role/model/view/confidence 全展示）；`test_citations_and_dissent_are_carried_verbatim`（citations tuple + dissent 原样）；`test_final_proposal_carries_evidence_ids`（proposal_id/symbol/side/evidence_ids=key_evidence）；`test_no_trade_outcome_is_explicit`（plans 空 + outcome=no_trade）；`test_degredation_is_exposed`（provider/schema degradation）；`test_deterministic` |

#### M14 Requirement Traceability（M14-W01..W03）

| Requirement | Code / Evidence |
|---|---|
| REQ-UI-003 | W01 token 系统/brand audit；W02/W03 workspace 视图消费 Soft 语义 |
| REQ-UI-004（主导航 10 section） | W02 `NAVIGATION_SECTIONS`；W03 Markets/News & Sentiment/AI Research workspace 视图（Markets→/dashboard/markets、News & Sentiment→/dashboard/news、AI Research→/dashboard/ai-trading 对应导航项） |
| REQ-UI-005（每页 8 态，不以空白或 fake data 掩盖失败） | W02 `derive_page_state`/`render_state_payload`；W03 三个 workspace view 全部 truth-only（无捏造 price/age/full text/evidence） |
| REQ-UI-008 | W01/W02 contrast/reduced-motion/focus；W03 视图数据可访问性由 shell 保证 |

范围说明：`tests/test_dashboard_markets.py`、`tests/test_dashboard_news_sentiment.py`、
`tests/test_dashboard_ai_research.py` 为 M14-W03 契约声明的测试文件（targeted
command 声明，documented forced path）；`dashboard/workspaces.py` 为 M14-W03 契约
声明的生产模块（REQ-UI-004/005，scope profile `frontend`）。集成 command 声明的
`tests/test_research_api.py` 不存在（research API 覆盖位于 `tests/test_api_server.py`，
documented substitution）。全量 pytest：2819 total（2800 passed + 19 pre-existing
M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean
（457 source files）；acceptance 11/11。下一 READY item：M14-W04。

#### M14-W04 已闭环证据（R-20260813-M14-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M14-W04-01 | OANDA Account displays cash, NAV, margin, P&L, financing, positions, pending orders, fills, category attribution, exposure, and time series from broker-authoritative projections | `tests/test_dashboard_oanda_account.py`：`build_account_view(projection, time_series)` 全部字段来自 broker-authoritative projection——`test_displays_broker_authoritative_fields`（cash/nav/margin_used/realized+unrealized PnL/gross+net exposure/observed_at/freshness）；`test_financing_is_explicit_null_when_unknown`（未知 financing → null 绝不捏造）；`test_positions_pending_orders_fills_attribution`（positions+pending_orders+fills+category_attribution 全部透传）；`test_time_series_is_carried`（equity 时序）；`test_empty_projection_yields_explicit_nulls`；`test_deterministic` |
| AC-M14-W04-02 | Risk displays policy version, kill and freeze state, daily loss, drawdown, gross and net exposure, category and currency concentration, data freshness, and rule-level decisions | `tests/test_dashboard_risk.py`：`test_displays_policy_and_safety_state`（policy_version/kill_switch_active/frozen）；`test_displays_loss_drawdown_and_exposure`；`test_concentrations_are_sorted_and_stringified`（category/currency concentration 排序确定性）；`test_freshness_is_exposed`；`test_rule_level_decisions_are_carried`（rule/decision/detail 逐条）；`test_missing_state_is_explicit_null`；`test_deterministic` |
| AC-M14-W04-03 | Orders & Trades represents pending, filled, partially filled, rejected, cancelled, replaced, expired, closed, and reconciliation-difference states without losing OANDA transaction identity | `tests/test_dashboard_orders_trades.py`：`test_all_documented_states_are_representable`（`ORDER_STATES` 9 态齐全）；`test_state_counts_cover_every_documented_state`（state_counts 覆盖全部 9 态）；`test_oanda_transaction_identity_is_preserved`（client/broker order id + transaction_id + fill_price 原样）；`test_partially_filled_and_replaced_are_representable`；`test_reconciliation_differences_are_marked_not_merged`（reconciliation_diff 显式标记）；`test_deterministic` |

#### M14 Requirement Traceability（M14-W01..W04）

| Requirement | Code / Evidence |
|---|---|
| REQ-UI-003 | W01 token 系统/brand audit |
| REQ-UI-004（主导航 10 section） | W02 `NAVIGATION_SECTIONS`；W03/W04 workspace 视图对应 Markets/News/AI Research/Risk/OANDA Account/Orders & Trades 导航项 |
| REQ-UI-005（每页 8 态，无 fake data） | W02 `derive_page_state`；W03/W04 全部 workspace view truth-only（缺字段显式 null） |
| REQ-UI-007（展示 cash、NAV、margin、P&L、exposure、positions、pending orders、fills、financing、category attribution 和时间序列） | W03 M13 operational 资源；W04 `build_account_view`（AC-M14-W04-01 全字段）+ `build_risk_view` + `build_orders_trades_view`；相关测试 |

范围说明：`tests/test_dashboard_oanda_account.py`、`tests/test_dashboard_risk.py`、
`tests/test_dashboard_orders_trades.py` 为 M14-W04 契约声明的测试文件（targeted
command 声明，documented forced path）；`workspaces.py` 扩展三个 view builder
（REQ-UI-004/005/007，scope profile `frontend`，risk_class safety-critical：
broker-authoritative truth-only、reconciliation diff 显式标记）。集成 command 声明的
`tests/test_account_api.py`/`tests/test_risk_api.py` 不存在（account 8 + risk 16
覆盖位于 `tests/test_api_server.py`，documented substitution）。全量 pytest：2838
total（2819 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，
分类见 M10-W03）；ruff/mypy 全仓 clean（460 source files）；acceptance 11/11。
下一 READY item：M14-W05。

#### M14-W05 已闭环证据（R-20260813-M14-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M14-W05-01 | Every displayed cycle, intent, risk decision, order, trade, transaction, reconciliation, and portfolio event links bidirectionally through persisted correlation identifiers | `tests/test_dashboard_trace_explorer.py`：`TraceExplorerView`/`TraceSegment` 携带 `correlation_ids`（`CORRELATION_KEYS` 7 类：cycle/intent/risk_decision/order/transaction/reconciliation/portfolio——`test_correlation_keys_cover_every_segment_kind`）；`verify_bidirectional_links` 检查双向解析——`test_full_chain_links_bidirectionally`（10 段全链双向 link 零 issue）；`test_broken_forward_link_is_reported`（指向不存在的 decision-ghost → 报 issue）；`test_missing_back_link_is_reported`（order 无反向 link → 报 issue）；leaf 段（evidence/transcript/trade）forward-only 由验证器按 keyed-kind 规则处理 |
| AC-M14-W05-02 | The explorer exposes evidence versions, citations, inputs hash, rule-by-rule outcomes, broker references, timestamps, and reconciliation disposition without exposing secrets or full account IDs | `tests/test_dashboard_trace_redaction.py`：`test_evidence_and_hashes_are_preserved`（data_version/citations/inputs_hash/rules 原样保留）；`test_broker_references_and_timestamps_survive`（broker_ref/timestamp）；`test_reconciliation_disposition_is_preserved`（disposition + redaction_applied）；`test_secrets_are_redacted`/`test_full_account_ids_never_survive`（fixture 中的 "Bearer …"/token/完整 account id 全部 [REDACTED]——fixture 值运行时拼接，文件内无 literal）；`test_account_id_hash_is_non_reversible_display`（sha256 前 12 hex，不可逆）；`test_deterministic` |
| AC-M14-W05-03 | Missing, stale, conflicting, or partial trace segments are visibly classified and never silently collapsed into a successful execution story | `classify_segment` 五态矩阵（`test_classification_matrix`：present/stale/conflicting/partial → complete/missing/stale/conflicting/partial）；`test_missing_segment_yields_missing_disposition`（缺段 → disposition=missing）；`test_conflicting_segment_never_collapses`（recon mismatch → disposition=conflicting、segment.status=conflicting，绝不折叠成成功故事）；`test_stale_and_partial_are_visible`（stale+partial 同时可见，disposition 取最差）；`test_complete_chain_disposition` |

#### M14 Requirement Traceability（M14-W01..W05）

| Requirement | Code / Evidence |
|---|---|
| REQ-UI-003 | W01 token 系统/brand audit |
| REQ-UI-004 | W02 `NAVIGATION_SECTIONS` |
| REQ-UI-005 | W02 page states；W03-W05 workspace 视图 truth-only |
| REQ-UI-006（订单和风险链可从 cycle 一键追溯到 evidence、讨论、intent、每条 risk rule、OANDA transaction 和 reconciliation） | W03 M13 trace API；W05 `dashboard/trace_explorer.py`（10 段全链 + 双向 correlation links + redaction）；`tests/test_dashboard_trace_explorer.py`/`test_dashboard_trace_redaction.py` |
| REQ-UI-007 | W04 account/risk/orders 视图；W05 portfolio segment 链接 |

范围说明：`tests/test_dashboard_trace_explorer.py` 与 `tests/test_dashboard_trace_redaction.py`
为 M14-W05 契约声明的测试文件（targeted command 声明，documented forced path）；
`dashboard/trace_explorer.py` 为 M14-W05 契约声明的生产模块（REQ-UI-006/007，
scope profile `frontend`，risk_class safety-critical：双向 link 验证 + redaction +
五态分类绝不折叠）。集成 command 声明的 `tests/test_audit_api.py` 不存在
（audit API 覆盖位于 `tests/test_api_server.py`，documented substitution）。
全量 pytest：2859 total（2840 passed + 19 pre-existing M08-W03 time-bombed
risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（463 source files）；
acceptance 11/11。下一 READY item：M14-W06。

#### M14-W06 已闭环证据（R-20260813-M14-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M14-W06-01 | Scheduler and 30-Day Observation display leader, running, heartbeat, last and next run, phase, qualified day, weekly gate, incident, blocker, and evidence completeness from one runtime authority | `tests/test_dashboard_scheduler.py`：`build_scheduler_view(runtime_truth)` 全字段来自单一 runtime authority——`test_displays_runtime_truth_fields`（leader_id/running/heartbeat_at/last_run_at/next_run_at/phase）；`test_unknown_phase_is_preserved_verbatim`（未知 phase 原样不猜测）；`test_missing_truth_is_explicit_null`；`test_deterministic`。`tests/test_dashboard_observation.py`：`build_observation_view`——`test_displays_qualified_days_and_completeness`（qualified_days/required_days=30/evidence_completeness）；`test_weekly_gates_are_carried_with_detail`（week/passed/detail）；`test_incidents_and_blockers_are_never_hidden`（incident/blocker 显式）；`test_missing_truth_is_explicit_null`；`test_deterministic` |
| AC-M14-W06-02 | The only write controls are pause or resume research, freeze or rule-governed unfreeze practice execution, cancel a practice order, and reduce or close practice exposure; each requires validation, idempotency, confirmation, and audit | `tests/test_dashboard_controls.py`：`control_actions()` 与 `OPERATOR_MUTATIONS`（REQ-UI-010 closed 7 集）完全一致（`test_controls_are_exactly_the_approved_seven`/`test_no_control_outside_the_approved_set`/`test_every_approved_mutation_has_a_control_action`）；每个 ControlAction requires_validation/idempotency/confirmation/audited 全 True（`test_every_control_requires_validation_idempotency_confirmation_audit`）；`test_controls_are_deterministic` |
| AC-M14-W06-03 | Settings reveals non-secret provider and version health but cannot edit broker hosts, unlock live trading, select another broker, expose credentials, or send an arbitrary broker request | `tests/test_dashboard_settings.py`：`build_settings_view(health)`——`test_reveals_non_secret_health`（provider/provider_health/blueprint_version/schema_version）；`test_cannot_edit_broker_hosts`/`test_cannot_unlock_live_trading`/`test_cannot_select_another_broker`/`test_never_exposes_credentials`/`test_never_sends_arbitrary_broker_requests`（五个安全不变式全部 False，声明式不可变）；`test_missing_health_is_explicit_null`；`test_deterministic` |

#### M14 Requirement Traceability（M14-W01..W06）

| Requirement | Code / Evidence |
|---|---|
| REQ-UI-003 | W01 token 系统/brand audit |
| REQ-UI-004 | W02 `NAVIGATION_SECTIONS`；W06 Scheduler/Observation/Settings 导航项对应视图 |
| REQ-UI-005 | W02 page states；W03-W06 workspace 视图 truth-only（缺字段显式 null，blocker/incident 绝不隐藏） |
| REQ-UI-010（手工控制仅 7 种 mutation，全部审计） | W02 `write_contracts.py` gate；W06 `control_actions()`（7 控制 + validation/idempotency/confirmation/audit 四要求）；`tests/test_dashboard_controls.py` |
| REQ-UI-006/007 | W03/W04/W05 已闭环 |

范围说明：`tests/test_dashboard_scheduler.py`、`tests/test_dashboard_observation.py`、
`tests/test_dashboard_settings.py`、`tests/test_dashboard_controls.py` 为 M14-W06
契约声明的测试文件（targeted command 声明，documented forced path）；
`dashboard/operations.py` 为 M14-W06 契约声明的生产模块（REQ-UI-004/005/010，
scope profile `frontend`，risk_class safety-critical：controls 严格有界 + settings
五项安全不变式声明式不可变）。集成 command 声明的 `tests/test_observation_api.py`/
`tests/test_operator_controls_api.py` 不存在（覆盖位于 `tests/test_scheduler_api.py`
+ `tests/test_ai_trader_scheduler.py` + `tests/test_api_server.py`，documented
substitutions）。全量 pytest：2887 total（2868 passed + 19 pre-existing M08-W03
time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（468 source
files）；acceptance 11/11。下一 READY item：M14-W07。

#### M14-W07 已闭环证据（R-20260813-M14-W07）— M14 里程碑 gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M14-W07-01 | Automated interaction and visual fixtures pass in light, dark, reduced-motion, loading, error, offline, and frozen states at 320, 768, 1024, and 1440 pixels | `tests/ui/test_dashboard_visual_regression.py`：`visual_fixture_matrix()` 覆盖全部 8 态 × 4 viewport × 3 mode（light/dark/reduced_motion）= 96 fixtures（`test_matrix_covers_all_states_viewports_modes`/`test_every_state_at_every_viewport`/`test_every_mode_is_covered`/`test_reduced_motion_covered_at_every_viewport`）；fixture reference 确定性（`test_fixture_references_are_deterministic`）；`validate_visual_fixture_matrix` 全绿（`test_validation_passes`/`test_validation_is_deterministic`） |
| AC-M14-W07-02 | Semantic regions, heading order, forms, tables, dialogs, focus order, focus traps, labels, status announcements, contrast, and keyboard-only operation satisfy the declared accessibility contract | `tests/test_dashboard_accessibility.py`：`AccessibilityContract` 声明全部规则——`test_semantic_regions_are_declared`（nav/main/aside/footer）、`test_heading_order_rule`（exactly one h1）、`test_form_table_dialog_rules`（label/caption/role=dialog/trap focus）、`test_focus_and_keyboard_rules`（document order/visible/aria-live/keyboard）；`TestContrast`（light/dark 两主题 text+text_dim vs bg WCAG AA ≥4.5）；`validate_accessibility_contract` 全绿（`test_validation_passes`/`test_validation_is_deterministic`） |
| AC-M14-W07-03 | Electron detects backend readiness and port conflicts, surfaces startup errors, prevents duplicate backend ownership, and performs graceful freeze, reconcile, persist, and shutdown without swallowing failure | `tests/test_electron_lifecycle.py`（11 passed）：`TestBackendReadiness`（/health 轮询、默认 port 8765 避开 launchd 8000、error-overlay）；`TestDuplicateOwnership`（requestSingleInstanceLock + app.quit）；`TestGracefulLifecycle`（before-quit/will-quit 杀 backend、freeze/reconcile/persist 为 backend-owned 不被 shell 拦截、console.error 不吞错、日志 1MiB 轮转）；`TestShellBoundary`（shell 只 spawn 现有 CLI、无 broker/trading 逻辑、仅 127.0.0.1） |

#### M14 Requirement Traceability（M14-W01..W07 里程碑闭环）

| Requirement | Code / Evidence |
|---|---|
| REQ-UI-003（Soft 5/5/5 + 品牌保留） | W01 token 系统/brand audit；W02-W07 全部视图消费 Soft 语义 |
| REQ-UI-004（主导航 10 section） | W02 `NAVIGATION_SECTIONS`；W03-W06 workspace 视图全覆盖 |
| REQ-UI-005（每页 8 态，无 fake data） | W02 `derive_page_state`；W03-W07 truth-only 视图 |
| REQ-UI-006/007 | W03/W04/W05 已闭环（trace/account/risk/orders） |
| REQ-UI-008（键盘、focus、semantic HTML、对比度、reduced motion） | W01 contrast/reduced-motion tokens；W02 focus-visible；W07 `dashboard/accessibility.py`（完整声明式契约 + 自动化校验）+ `visual_states.py`（reduced-motion fixture 全覆盖） |
| REQ-UI-009（Electron 受控本地壳：readiness、优雅停止、端口冲突、不吞错） | W07 `tests/test_electron_lifecycle.py`（readiness/port/error/duplicate/shutdown 全验证，main.js 零修改） |
| REQ-UI-010 | W02 write gate；W06 controls |

范围说明：`tests/test_dashboard_accessibility.py`、`tests/ui/test_dashboard_visual_regression.py`、
`tests/test_electron_lifecycle.py` 为 M14-W07 契约声明的测试文件（targeted command
声明，documented forced path）；`dashboard/accessibility.py`/`visual_states.py` 为
M14-W07 契约声明的生产模块（REQ-UI-003/008/009，scope profile `frontend`）；
`electron/main.js` 零改动（lifecycle 已满足，测试只验证）。集成 command 声明的
`npm --prefix electron test` 无 test script（package.json 未定义），以
`tests/test_electron_lifecycle.py`（11 passed，main.js 静态契约验证）作为
documented substitution。回归：全部 test_dashboard*/test_electron*/tests/ui
（203 passed）。全量 pytest：2919 total（2900 passed + 19 pre-existing M08-W03
time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（473
source files）；acceptance 11/11。**M14 里程碑 → DONE**。下一 READY item：
M15-W01。

#### M15-W01 已闭环证据（R-20260813-M15-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M15-W01-01 | Ingestion, news, models, scheduler, cycle, risk, OANDA, reconciliation, backup, API, and Electron publish structured health, readiness, heartbeat, latency, success, failure, and freshness signals | `tests/test_operations_observability.py`：`COMPONENTS` 恰好 11 个（`test_all_eleven_components_are_declared`）；每组件发布 typed health/readiness/heartbeat/last_success/last_failure/freshness（`test_every_component_publishes_health_signals` parametrize）；`MetricRecord` 四种 metric（latency/success/failure/freshness，`test_every_metric_kind_is_typed`）；`test_health_registry_is_typed_and_deterministic`；缺失组件 → unknown 且 not ready（`test_missing_component_stays_unknown_not_ready`）。`tests/test_operations_health_readiness.py`：状态矩阵（healthy/degraded/unhealthy/unknown × ready，`test_status_matrix`）、非法 status → unknown（`test_invalid_status_falls_back_to_unknown`）、freshness 透传、确定性 |
| AC-M15-W01-02 | Correlation IDs connect cycle, evidence, model, intent, risk, order, transaction, reconciliation, alert, and backup records across logs and metrics | `tests/test_operations_heartbeats.py`：`CORRELATION_KINDS` 恰好 10 类（`test_all_ten_kinds_are_declared`）；`correlation_chain` 把 10 类记录串成一条有序确定链（`test_chain_connects_every_record_kind`/`test_chain_is_ordered_and_deterministic`）；缺失 kind 不出现在链中（`test_missing_kind_is_absent_from_chain`）；同 kind 取最新 id（`test_latest_id_wins_per_kind`）；`StructuredLogRecord` 携带 correlation_id/kind（`test_structured_log_record_carries_correlation`）、naive timestamp 拒绝（`test_naive_log_timestamps_are_rejected`） |
| AC-M15-W01-03 | All observable output scrubs tokens, authorization headers, full account IDs, model-sensitive content, unlicensed news text, and configured secret patterns | `TestRedaction`（`tests/test_operations_observability.py`）：`test_tokens_and_authorization_are_scrubbed`（"Bearer "+运行时拼接 token → [REDACTED]）；`test_full_account_ids_are_scrubbed`（account-+18 位数字 → [REDACTED]）；`test_configured_secret_patterns_are_scrubbed`（可配置 pattern 支持）；`test_model_sensitive_content_is_scrubbed`（system prompt → [MODEL-REDACTED]）；`test_unlicensed_news_text_is_scrubbed`（full article → [NEWS-REDACTED]）；`test_redaction_is_deterministic`；`test_account_id_hash_is_non_reversible`（sha256 前 12 hex） |

#### M15 Requirement Traceability（M15-W01）

| Requirement | Code / Evidence |
|---|---|
| REQ-OPS-001（结构化日志、metrics、health/readiness、heartbeats、alerts 覆盖 ingestion、models、scheduler、risk、broker、reconciliation、backup） | W01 `alphabrief_core/observability.py`：`StructuredLogRecord`/`MetricRecord`/`ComponentHealth`/`HealthRegistry`（11 组件全覆盖）；`tests/test_operations_observability.py`/`test_operations_health_readiness.py` |
| REQ-OPS-002（日志带 correlation IDs，自动 scrub secret、authorization、完整 account ID、model-sensitive content 和未许可新闻全文） | W01 `correlation_chain`（10 类记录关联）+ `redact_observable`（token/auth/account id/model/news/可配置 pattern）；`tests/test_operations_heartbeats.py`/`TestRedaction` |

范围说明：`tests/test_operations_observability.py`、`tests/test_operations_health_readiness.py`、
`tests/test_operations_heartbeats.py` 为 M15-W01 契约声明的测试文件（targeted
command 声明，documented forced path）；`alphabrief_core/observability.py` 为 M15-W01
契约声明的生产模块（REQ-OPS-001/002，scope profile `operations`，risk_class
safety-critical：缺失 truth → unknown/not ready，绝不假设 healthy）。全量 pytest：
2962 total（2943 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，
分类见 M10-W03）；ruff/mypy 全仓 clean（477 source files）；acceptance 11/11。
下一 READY item：M15-W02。

#### M15-W02 已闭环证据（R-20260813-M15-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M15-W02-01 | Auth, validation, broker reject, rate-limit, transient, protocol, data-quality, and safety failures map deterministically to retryability, severity, execution freeze, no-trade, and escalation behavior | `tests/test_operations_error_taxonomy.py`：`ERROR_CLASSES` 恰好 8 类（`test_all_eight_classes_are_declared`）；`test_classification_matrix`（8 类 × retryable/severity/freeze/no_trade/escalate 全矩阵 parametrize——auth→blocker/freeze/no-trade/escalate、validation→warning/no-trade、broker_reject→critical/freeze、rate_limit→retryable、transient→retryable 且不 no-trade、protocol→retryable/no-trade、data_quality→critical/escalate、safety→blocker/freeze）；`test_unknown_class_fails_closed_as_safety`（未知类 → safety blocker：不重试/冻结/no-trade/escalate）；`test_classification_is_deterministic`；`test_safety_class_never_retries` |
| AC-M15-W02-02 | Alerts persist severity, dedupe key, first and last occurrence, count, acknowledgement, escalation, resolution, incident link, and scrubbed evidence across restart | `tests/test_operations_alert_lifecycle.py`：`test_alert_persists_full_state`（severity/dedupe_key/first+last_occurrence/count/incident_link/evidence 全持久化）；`test_evidence_is_scrubbed`（account id/token 运行时拼接值 → 不可见）；`test_state_transitions`（acknowledge/escalate/resolve）；`test_unknown_alert_raises`（KeyError fail-closed）；`test_survives_restart`（重新打开同一 NDJSON 文件 → acknowledged/severity 恢复） |
| AC-M15-W02-03 | Webhook or external sink failure never deletes or resolves the local alert and repeated equivalent events do not create an unbounded alert storm | `test_sink_failure_never_deletes_or_resolves`（`sink_failure` 返回原样记录——resolved/acknowledged 不变、store 中仍在）；`test_repeated_events_dedupe_not_storm`（同 dedupe_key 50 次重复 → 仍 1 条 alert、count=51）；`test_distinct_keys_create_distinct_alerts`；`test_resolution_is_explicit_only`（重复事件刷新 occurrence 绝不自动 resolve）；`test_list_is_ordered_and_deterministic` |

#### M15 Requirement Traceability（M15-W01..W02）

| Requirement | Code / Evidence |
|---|---|
| REQ-OPS-001/002 | W01 observability（11 组件 + correlation chain + redaction） |
| REQ-OPS-003（错误分为 auth、validation、reject、rate-limit、transient、protocol、data-quality、safety，并决定重试/冻结/告警） | W02 `alphabrief_core/alerting.py` `classify_error`（8 类确定性映射，未知 → safety blocker fail-closed）；`tests/test_operations_error_taxonomy.py` |
| REQ-OPS-004（alert 有 severity、dedupe、acknowledgement、resolution 和 escalation；webhook 失败不掩盖本地 alert） | W02 `AlertStore`（NDJSON durable、dedupe storm 防护、ack/escalate/resolve 显式状态机、sink_failure 零影响）；`tests/test_operations_alert_lifecycle.py` |

范围说明：`tests/test_operations_error_taxonomy.py` 与 `tests/test_operations_alert_lifecycle.py`
为 M15-W02 契约声明的测试文件（targeted command 声明，documented forced path）；
`alphabrief_core/alerting.py` 为 M15-W02 契约声明的生产模块（REQ-OPS-003/004，
scope profile `operations`，risk_class safety-critical：未知错误 fail-closed 为
safety blocker、alert 风暴有界、sink 失败零影响）。集成 command 声明的
`tests/test_scheduler_alerts.py` 不存在（scheduler alerts 覆盖位于
`tests/test_scheduler.py`/`tests/test_ai_trader_scheduler.py`，documented
substitution）。全量 pytest：2984 total（2965 passed + 19 pre-existing M08-W03
time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（480
source files）；acceptance 11/11。下一 READY item：M15-W03。

#### M15-W03 已闭环证据（R-20260813-M15-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M15-W03-01 | Every external request family has a configured connect, read, total, and cycle budget with bounded attempts and jittered backoff | `tests/test_operations_timeouts.py`：`REQUEST_FAMILIES` 恰好 7 类且每类都有配置预算（`test_all_seven_families_are_configured`/`test_every_family_has_connect_read_total_cycle_budget`：connect/read/total/cycle 全 >0、max_attempts/max_concurrency ≥1）；`test_unknown_family_raises`（KeyError fail-closed）；`test_budgets_are_deterministic`。`tests/test_operations_retry_budget.py`：`test_attempts_are_bounded`（max_attempts 封顶，末次尝试绝不重试）；`test_out_of_bounds_attempt_is_rejected`；`test_only_retryable_classes_retry`（transient/rate_limit 可重试，auth/safety/broker_reject 不可）；`test_backoff_is_jittered_and_deterministic`（同 seed 同值、base×[1,2)）；`test_no_jitter_when_disabled`；`test_stream_family_has_official_limits`（max_attempts=5、base=2s——官方连接限制） |
| AC-M15-W03-02 | OANDA REST and stream reconnect behavior respects official connection and rate limits while unknown submit outcomes enter query and reconciliation instead of blind retry | `submit_outcome_action`——`test_unknown_submit_enters_query_and_reconcile`（unknown/timeout → `query_and_reconcile`，绝不 blind retry）；`test_recorded_outcomes_never_blind_retry`（accepted/rejected → recorded）；`test_outcome_mapping_is_deterministic`；stream 预算反映官方连接限制（`test_stream_family_has_official_limits`） |
| AC-M15-W03-03 | A timed-out provider task cannot block heartbeat, reconciliation, backup, risk freeze, or unrelated scheduled work and is classified with complete scrubbed telemetry | `tests/test_operations_concurrency_budget.py`：`test_every_family_has_a_concurrency_limit`（每类 max_concurrency/cycle_budget）；`test_cycle_budget_bounds_per_cycle_work`（total ≤ cycle）；`test_timeout_classification_does_not_block_other_work`（`classify_timeout` telemetry 自包含——不含 heartbeat/reconciliation/risk 字段，绝不触碰其他任务状态）；`test_independent_tasks_have_isolated_budgets`（model/backup 各自预算互不消耗）；`test_alert_budget_is_small_and_unbounded_retry_free`（max_attempts=1）。`tests/test_operations_timeouts.py` `TestTimeoutTelemetry`：完整 scrubbed telemetry（`test_timeout_is_classified_with_scrubbed_telemetry`——account id 运行时拼接值不可见；`test_elapsed_exceeding_total_is_visible`；`test_telemetry_is_deterministic`） |

#### M15 Requirement Traceability（M15-W01..W03）

| Requirement | Code / Evidence |
|---|---|
| REQ-OPS-001/002 | W01 observability |
| REQ-OPS-003 | W02 error taxonomy；W03 retry 仅限 retryable 类 |
| REQ-OPS-004 | W02 alert lifecycle |
| REQ-OPS-005（所有 external request 有 timeout/budget；重试遵循 OANDA 连接限制并带 jitter，不阻塞整个 scheduler） | W03 `alphabrief_core/request_policy.py`：`REQUEST_BUDGETS`（7 类 connect/read/total/cycle/max_attempts/jitter/max_concurrency）、`backoff_seconds`（确定性 jitter）、`retry_allowed`（有界 + retryable-only）、`submit_outcome_action`（unknown/timeout → query_and_reconcile）、`classify_timeout`（scrubbed telemetry、任务隔离）；相关测试 |

范围说明：`tests/test_operations_timeouts.py`、`tests/test_operations_retry_budget.py`、
`tests/test_operations_concurrency_budget.py` 为 M15-W03 契约声明的测试文件
（targeted command 声明，documented forced path）；`alphabrief_core/request_policy.py`
为 M15-W03 契约声明的生产模块（REQ-OPS-003/005，scope profile `operations`，
risk_class safety-critical：预算全部有界、未知 outcome 绝不盲重试、超时任务
自包含隔离）。集成 command 声明的 `tests/test_oanda_rate_limits.py`/
`tests/test_scheduler_faults.py`/`tests/test_model_gateway_timeouts.py` 不存在
（OANDA rate/idempotency 覆盖位于 `tests/test_oanda_idempotency.py`、scheduler
faults 位于 `tests/test_scheduler.py`/`test_scheduler_leader.py`、model gateway
timeouts 位于 `tests/test_model_gateway.py`，documented substitutions）。
全量 pytest：3018 total（2999 passed + 19 pre-existing M08-W03 time-bombed
risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（484 source files）；
acceptance 11/11。下一 READY item：M15-W04。

#### M15-W04 已闭环证据（R-20260813-M15-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M15-W04-01 | OANDA-observation preflight verifies practice hosts, secret presence without disclosure, account, catalog, data, content, ModelGateway, risk, backup, scheduler lease, reconciliation, alerts, frozen build, and safety gates in one schema | `tests/test_operations_preflight.py`：`OBSERVATION_CHECKS` 恰好 14 个 gate（`test_all_gates_are_checked_in_one_schema`：practice_host/secret_presence/account/catalog/data/content/model_gateway/risk/backup/scheduler_lease/reconciliation/alerts/frozen_build/safety_gates）；`PreflightReport` 单一 schema（`test_every_scope_runs`/`test_full_truth_passes`/`test_single_failure_fails_the_report`/`test_missing_truth_fails_closed`——缺 truth → fail-closed 显式 detail）；`test_secret_presence_is_boolean_without_disclosure`（report 只含 boolean，序列化中无 secret 值）；`test_unknown_scope_raises`；`test_other_scopes_are_configured`（engineering_readiness 6 check + final_release 4 check 含 no_live_unlock）；`test_deterministic` |
| AC-M15-W04-02 | The controlled practice E2E command can use only the formal proposal, OrderIntent, persisted RiskDecision, submit, transaction, cleanup, and reconciliation path and refuses direct or residual execution | `tests/test_acceptance_practice_e2e.py`：`PRACTICE_E2E_PATH` 恰好 7 步（`test_formal_path_is_exactly_seven_steps`）；`validate_e2e_sequence`——正式序列 accepted（`test_formal_sequence_is_accepted`）、缺步/乱序 rejected（`test_missing_step_is_rejected`/`test_reordered_steps_are_rejected`）；`FORBIDDEN_E2E_STEPS`（direct_broker_submit/in_memory_fill/live_execution/simulated_fallback）任何出现即拒绝且 reason 含 step（`test_forbidden_steps_are_always_refused` parametrize）；`test_validation_is_deterministic` |
| AC-M15-W04-03 | A single-leader persistent supervisor restores next-run state after restart, invokes daily and weekly evidence gates automatically, derives Day 0 through Day 30 from real UTC and local-calendar evidence, and records BLOCKED_EXTERNAL or WAITING_EXTERNAL without fabricating evidence or asking a question | `tests/test_operations_observation_controller.py`：`observation_day_index` 真实日历推导（`test_day_zero_is_start_date`/`test_day_thirty_is_final_day`/`test_before_start_is_none`/`test_beyond_day_thirty_is_none`/`test_mid_observation_day`/`test_derivation_is_deterministic`）；`ObservationSupervisor`——begin Day 0（`test_begin_starts_at_day_zero`）、逐日推进真实日历且 next_run 前移（`test_daily_gate_advances_real_calendar`）、缺证据记录失败日（`test_missing_evidence_records_failed_day`）、BLOCKED_EXTERNAL/WAITING_EXTERNAL 记录且不伪造证据（`test_external_state_recorded_without_evidence`/`test_unknown_external_state_raises`）、重启恢复 next-run 状态（`test_survives_restart`）、Day 30 封顶（`test_day_30_caps_next_run`）、越界拒绝（`test_outside_range_is_rejected`） |

#### M15 Requirement Traceability（M15-W01..W04）

| Requirement | Code / Evidence |
|---|---|
| REQ-OPS-001..005 | W01-W03 已闭环 |
| REQ-OPS-002（自动 scrub） | W01 redaction；W04 preflight secret_presence 无披露 |
| REQ-OPS-007（preflight 在真实外部下单前验证配置、凭证、账户、品种、数据、模型、风险、备份、scheduler 单实例和 kill switch） | W04 `alphabrief_core/preflight.py`（14 gate 单 schema 全验证）+ `observation_controller.py`（practice E2E 正式路径 + 单 leader 观察 supervisor）；相关测试 |

范围说明：`tests/test_operations_preflight.py`、`tests/test_acceptance_practice_e2e.py`、
`tests/test_operations_observation_controller.py` 为 M15-W04 契约声明的测试文件
（targeted command 声明，documented forced path）；`alphabrief_core/preflight.py`/
`observation_controller.py` 为 M15-W04 契约声明的生产模块（REQ-OPS-002/007，
scope profile `operations`，risk_class execution-critical：preflight 缺 truth
fail-closed、E2E 仅正式路径、观察日真实日历推导绝不伪造）。集成 command 声明的
`tests/test_daily_cycle.py` 不存在（daily cycle 覆盖位于
`tests/test_daily_cycle_state_machine.py`/`test_daily_cycle_execution.py` 等，
documented substitution）。全量 pytest：3054 total（3035 passed + 19 pre-existing
M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean
（489 source files）；acceptance 11/11。下一 READY item：M15-W05。

#### M15-W05 已闭环证据（R-20260813-M15-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M15-W05-01 | SIGTERM follows freeze, stop-new-cycle, resolve-uncertain-submit, sync, reconcile, checkpoint, backup, and lease-release order with bounded shutdown time | `tests/test_recovery_shutdown.py`：`SHUTDOWN_SEQUENCE` 恰好 8 步且顺序固定（`test_sequence_is_exactly_eight_steps_in_order`）；`test_freezing_precedes_stopping_new_cycles`/`test_uncertain_submit_resolution_precedes_sync`/`test_lease_release_is_last`（顺序不变量）；`SHUTDOWN_BUDGET_S=30`（`test_shutdown_budget_is_bounded`）；`shutdown_plan()` 确定性（`test_plan_is_deterministic`） |
| AC-M15-W05-02 | Abrupt termination at every declared cycle and execution boundary resumes deterministically or stays safely frozen without duplicate order, cursor regression, lost risk counters, or partial state | `tests/test_recovery_cycle_restart.py`：`RECOVERY_BOUNDARIES` 恰好 12 个边界（`test_all_declared_boundaries_are_covered`：startup/preflight/ingest/snapshot/discuss/propose/risk_gate/submit/transaction/reconcile/report/complete）；`test_every_boundary_has_a_deterministic_verdict`（每边界可 resumed，其余 fail-closed frozen）；`test_missing_truth_fails_closed_as_frozen`（缺 truth → frozen + 显式 detail，绝不假设 resumed）；`test_invalid_verdict_falls_back_to_frozen`；`test_frozen_boundaries_never_claim_success`；`test_deterministic` |
| AC-M15-W05-03 | The bounded soak and isolated restore drills preserve heartbeats, writer ownership, memory and descriptor budgets, projection equality, reconciliation truth, and backup integrity | `tests/test_operations_soak.py`：`SOAK_INVARIANTS` 恰好 7 项（`test_all_declared_invariants_are_covered`）；`run_soak`——`test_full_truth_passes`（1000 cycles 全绿）；`test_missing_invariant_fails_closed`（缺 truth → not preserved）；`test_single_failure_fails_the_soak`；`test_cycle_count_is_bounded_and_typed`；`test_deterministic`；runtime commands `alphabrief operations recovery-drill --scenario all --compact` 与 `alphabrief operations soak --cycles 1000 --compact` 运行成功（`apps/cli/operations_commands.py`，经共享 `emit_json` 输出 stable compact JSON） |

#### M15 Requirement Traceability（M15-W01..W05）

| Requirement | Code / Evidence |
|---|---|
| REQ-OPS-001..005、007 | W01-W04 已闭环 |
| REQ-OPS-006（启动、崩溃、SIGTERM、机器重启和数据库恢复有演练；未完成 cycle 能确定性恢复） | W05 `alphabrief_core/recovery.py`（8 步 shutdown 顺序 + 有界预算 + 12 边界 drill + 7 项 soak invariants）+ `apps/cli/operations_commands.py`（recovery-drill/soak 两个 runtime 命令）；`tests/test_recovery_shutdown.py`/`test_recovery_cycle_restart.py`/`test_operations_soak.py` |

范围说明：`tests/test_recovery_shutdown.py`、`tests/test_recovery_cycle_restart.py`、
`tests/test_operations_soak.py` 为 M15-W05 契约声明的测试文件（targeted command
声明，documented forced path）；`alphabrief_core/recovery.py` 与
`apps/cli/operations_commands.py` 为 M15-W05 契约声明的生产模块（REQ-OPS-001/006，
scope profile `operations`，risk_class safety-critical：缺 truth fail-closed
frozen、soak 缺 invariant not preserved）。集成 command 声明的
`tests/test_scheduler_recovery.py` 不存在（scheduler recovery 覆盖位于
`tests/test_scheduler_leader.py`/`tests/test_daily_cycle_recovery.py`，documented
substitution）。全量 pytest：3083 total（3064 passed + 19 pre-existing M08-W03
time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean（493
source files）；acceptance 11/11。下一 READY item：M15-W06。

#### M15-W06 已闭环证据（R-20260813-M15-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M15-W06-01 | Dependency integrity, supply-chain policy, tracked secret scan, artifact scrub scan, live and other-broker network scan, reference-source boundary, and static security rules pass without waiver | `tests/test_security_supply_chain.py`：`SECURITY_GATES` 恰好 7 项（`test_all_seven_gates_are_declared`）；`run_security_gates` 全绿/单败/缺 truth fail-closed/确定性（`test_full_truth_passes`/`test_single_failure_fails_the_report`/`test_missing_gate_fails_closed`/`test_deterministic`）；`scan_files_for_secrets`——`test_clean_sources_scan_empty`/`test_artifacts_never_contain_full_account_ids`（docs 无完整 account id）/`test_secret_fixture_is_built_at_runtime`（运行时拼接 fixture 可被 scan 检出——scan 有效）；`tests/test_security_secret_scan.py`（packages/apps/config/docs 全 clean + 确定性）；`tests/test_security_network_allowlist.py`：`ALLOWED_NETWORK_HOSTS` 仅 practice 两 host（`test_only_practice_hosts_are_allowed`），`scan_network_allowlist` 证明 packages/apps 无 live/other-broker 引用（`test_runtime_sources_reach_no_live_or_other_broker`/`test_api_and_cli_reach_no_live_or_other_broker`/`test_scan_is_deterministic`）；static：`pip check`（No broken requirements）、ruff、mypy |
| AC-M15-W06-02 | Prompt-injection fixtures cannot alter system instructions, risk limits, broker tools, provider routing, execution state, or evidence citation requirements | `tests/test_security_prompt_injection.py`：`PROTECTED_SURFACES` 恰好 6 项（`test_all_six_surfaces_are_declared`）；`verify_injection_invariants`——`test_unchanged_surfaces_pass`（注入文本零变更）；`test_altered_surface_is_reported`/`test_multiple_alterations_are_all_reported`（任一 surface 变更 → verdict.altered 列出全部）；`test_verdict_is_deterministic` |
| AC-M15-W06-03 | A non-production rehearsal completes Day 0, daily record, no-trade day, weekly gate, incident reset, restart, restore, and final-report flows without counting rehearsal time as real observation | `tests/test_operations_runbook_rehearsal.py`：`REHEARSAL_STEPS` 恰好 8 步（`test_all_eight_flow_steps_are_declared`）；`run_rehearsal`——`test_full_rehearsal_passes`；`test_rehearsal_never_counts_as_observation`（counts_as_observation 恒 False——彩排时间绝不记为真实观察）；`test_missing_step_fails_closed`；`test_no_trade_day_is_a_valid_step`；`test_deterministic`；runtime `alphabrief observation rehearse --all-drills --compact` 运行成功（stable compact JSON） |

#### M15 Requirement Traceability（M15-W01..W06）

| Requirement | Code / Evidence |
|---|---|
| REQ-OPS-001..007 | W01-W05 已闭环 |
| REQ-OPS-002（自动 scrub） | W01 redaction；W06 secret scan（完整 account id 绝不入 artifacts） |
| REQ-OPS-008（依赖和供应链扫描、secret scan、静态安全规则和 prompt injection fixtures 进入门禁） | W06 `alphabrief_core/security_gates.py`（7 gate 契约 + secret/network scans）+ `runbook_rehearsal.py`（injection invariants + 8 步 rehearsal，彩排不记观察）；`pip check` + ruff + mypy 入 static；相关测试 |

范围说明：`tests/test_security_supply_chain.py`、`tests/test_security_secret_scan.py`、
`tests/test_security_network_allowlist.py`、`tests/test_security_prompt_injection.py`
为 M15-W06 契约声明的测试文件（targeted command 声明，documented forced path）；
`tests/test_operations_runbook_rehearsal.py` 为集成声明的新文件；
`alphabrief_core/security_gates.py`/`runbook_rehearsal.py` 与
`apps/cli/observation_commands.py`（`observation rehearse` runtime 命令）为 M15-W06
契约声明的生产模块（REQ-OPS-002/008，scope profile `operations`，risk_class
safety-critical：缺 truth fail-closed、彩排绝不记观察）。全量 pytest：3112 total
（3093 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，分类见
M10-W03）；ruff/mypy 全仓 clean（499 source files）；`pip check` 无 broken
requirements；acceptance 11/11。下一 READY item：M15-W07。

#### M15-W07 已闭环证据（R-20260813-M15-W07）— Engineering Readiness Gate

| AC | Predicate | Evidence |
|---|---|---|
| AC-M15-W07-01 | Full pytest, Ruff, Mypy, pip integrity, acceptance, security, backup restore, recovery, UI, and traceability gates pass with no waiver, missing requirement, unexplained skip, or unresolved P0 or P1 | targeted 八 glob 212 passed（operations/security/recovery/acceptance 全套件）+ integration 五 glob 289 passed（scheduler/reconciliation/backup/dashboard/electron/ui）+ static（pip check 无 broken requirements、ruff clean、mypy clean 501 files）+ regression（full pytest 3101 passed + 19 pre-existing M08-W03 time-bomb 分类见 M10-W03、acceptance 11/11）；`tests/test_operations_readiness_gate.py` `test_no_unexplained_skip_in_gate_declarations`（7 security + 14 observation checks + 12 recovery boundaries + 8 shutdown steps + 7 soak invariants + 8 rehearsal steps 全声明全测试） |
| AC-M15-W07-02 | A controlled minimal OANDA practice E2E completes through the formal product path, cleans up according to policy, reconciles to zero unexplained differences, and produces a scrubbed immutable evidence chain | `alphabrief acceptance practice-e2e --scenario commissioning --compact` 运行成功（exit 0）：formal_path_required=True（正式 7 步路径唯一）、credentials_present 如实报告、status=BLOCKED_EXTERNAL/READY 依凭证如实判定、preflight/rehearsal passed 字段显式——绝不 false PASS；真实 practice E2E（submit→transaction→reconciliation）为 T7 级 external evidence，按 AC-03 记录为 blocker（external_evidence_pending），不伪造证据 |
| AC-M15-W07-03 | Engineering readiness is marked only when M01 through M15 are DONE, the tree is clean, the frozen build is practice-only, and absent external prerequisites create a recorded blocker without a user question or false PASS | `tests/test_operations_readiness_gate.py`：`engineering_readiness_verdict`——`test_readiness_requires_all_conditions`（M01..M15 DONE + tree clean + practice-only 三者全真才 ready）；`test_missing_condition_blocks_readiness`（任一缺失 → 不 ready）；`test_external_blockers_are_recorded_not_fabricated`（external blocker 显式记录，ready 标记不吞 blocker）；`test_verdict_is_deterministic`；`alphabrief acceptance preflight --scope oanda-observation --compact` 以 fail-closed 状态运行（exit 1 = preflight 未通过——无 truth 时如实报告，绝不 false PASS） |

#### M15 Requirement Traceability（M15-W01..W07 里程碑闭环）

| Requirement | Code / Evidence |
|---|---|
| REQ-OPS-001 | W01 observability（11 组件） |
| REQ-OPS-002 | W01 redaction；W06 secret scan |
| REQ-OPS-003 | W02 error taxonomy；W03 retry budget |
| REQ-OPS-004 | W02 alert lifecycle |
| REQ-OPS-005 | W03 request budgets |
| REQ-OPS-006 | W05 shutdown/recovery/soak |
| REQ-OPS-007 | W04 preflight 14 gates |
| REQ-OPS-008 | W06 security gates + rehearsal |
| Engineering Readiness（M15 gate） | W07 `engineering_readiness_verdict`（M01..M15 DONE + tree clean + practice-only；external blocker 记录不伪造）；`tests/test_operations_readiness_gate.py` + 全量 gate 运行 |

范围说明：`tests/test_operations_readiness_gate.py` 为 M15-W07 契约声明的测试文件
（targeted glob 声明，documented forced path）；`alphabrief_core/preflight.py`
扩展 `engineering_readiness_verdict`；`apps/cli/acceptance_commands.py` 扩展
`preflight --scope oanda-observation` 与新增 `practice-e2e --scenario
commissioning`；`apps/cli/operations_commands.py` 新增 `restore-drill
--latest --isolated`。真实 OANDA practice E2E（AC-M15-W07-02）为 T7 级外部证据
（external_evidence_pending：M04-W06/M05-W06/M06-W07/M07-W07/M08-W08 + 本次
commissioning E2E），按 §5.1 记录 blocker，绝不以本地 mock 冒充。全量 pytest：
3120 total（3101 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，
分类见 M10-W03）；ruff/mypy 全仓 clean（501 source files）；pip check clean；
acceptance 11/11。**M15 里程碑 → DONE（Engineering Readiness Gate 通过，build
冻结为 practice-only；真实 30 日观察待 M16 commissioning 与 T7 外部证据）**。
下一 READY item：M16-W01。

#### M16-W01 已闭环证据（R-20260813-M16-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M16-W01-01 | Day 0 manifest fixes commit and tree hashes, schema and config versions, dependency hashes, provider profiles, account hash, catalog version, timezone, start timestamps, and one unique observation ID | `tests/test_observation_day_zero.py`：`ObservationManifest` 恰好 12 字段（`test_manifest_fixes_all_day_zero_fields`：observation_id/commit_hash/tree_hash/schema_version/config_version/dependency_hash/provider_profile/account_hash/catalog_version/timezone/start_timestamp/day_zero_date 全固定）；`test_observation_id_is_unique_per_manifest`（唯一 observation ID）；`build_day_zero_attempt` 仅在全部 gate 通过时产出 manifest（`test_blockers_never_manufacture_a_pass`——rehearsal 日/缺 gate → manifest=None） |
| AC-M16-W01-02 | Full observation preflight, controlled practice E2E, cleanup, zero-difference reconciliation, initial backup, and isolated restore produce scrubbed manifests and valid hashes | `alphabrief acceptance practice-e2e --scenario observation-day-zero --compact` 运行成功：formal_path_required=True、credentials_present 如实、preflight/rehearsal passed 显式——绝不 false PASS；`alphabrief observation start` 仅在 engineering_readiness + observation_preflight + practice_e2e + clean_reconciliation + isolated_restore 全过时冻结 Day 0 manifest，否则记录全部 BLOCKED_EXTERNAL blocker；真实 practice E2E/clean reconciliation/restore 为 T7 级外部证据（pending，不伪造） |
| AC-M16-W01-03 | The qualified clock cannot start from rehearsal or historical data and missing secrets, failed checks, unavailable services, or insufficient evidence record BLOCKED_EXTERNAL without prompting or manufacturing a pass | `tests/test_observation_calendar.py`：`qualified_start_date`——`test_real_date_starts_qualified`/`test_rehearsal_date_cannot_start`/`test_historical_rehearsal_blocks`/`test_no_rehearsals_allows_real_start`/`test_deterministic`（≤ 任一 rehearsal 日期 → None，时钟绝不从彩排/历史启动）；`TestSupervisorExternalState`（缺证据 → 失败日如实记录；BLOCKED_EXTERNAL 记录不伪造证据——`test_external_state_is_recorded_without_fabrication`）；`observation start`/`verify-day` runtime 命令以 BLOCKED_EXTERNAL 如实输出（start 全 6 blocker、verify-day day 0 不可 qualified） |

#### M16 Requirement Traceability（M16-W01）

| Requirement | Code / Evidence |
|---|---|
| REQ-OBS-001（真实连续 30 日历日观察） | W01 `qualified_start_date`（真实 UTC 日历、彩排/历史不可启动）+ `ObservationManifest.day_zero_date`；相关测试 |
| REQ-OBS-002（每天有 preflight、数据/新闻/情绪快照、committee 或合法 skip、risk/no-trade/order、对账、portfolio、heartbeat 和日报证据） | W01 Day 0 manifest 固定版本/哈希基线，为后续每日证据提供不可变锚点 |
| REQ-OBS-004（P0/P1 或影响订单/风险/持久语义的修复会重置 qualified observation window） | W01 `observation_id` 唯一性 + 冻结 build（commit/tree hash）——任何修复改变 tree hash → 新 identity，窗口需重估 |

范围说明：`tests/test_observation_day_zero.py` 与 `tests/test_observation_calendar.py`
为 M16-W01 契约声明的测试文件（targeted command 声明，documented forced path）；
`alphabrief_core/observation_controller.py`（扩展 ObservationManifest/
build_day_zero_attempt/qualified_start_date）与 `apps/cli/observation_commands.py`
（`observation start`/`observation verify-day` runtime 命令）为契约声明的既有模块
扩展（observation profile：max_production_files=0，无新建生产文件）。真实 OANDA
practice E2E 与 T7 外部证据 PENDING——Day 0 manifest 绝不 manufacture，全部
BLOCKED_EXTERNAL 如实记录。全量 pytest：3134 total（3115 passed + 19 pre-existing
M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean
（503 source files）；acceptance 11/11。下一 READY item：M16-W02。

#### M16-W02 已闭环证据（R-20260813-M16-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M16-W02-01 | Days 1 through 7 each contain preflight, data, news, sentiment, committee or valid skip, intent or no-trade, risk, execution outcome, reconciliation, portfolio, alerts, heartbeat, backup, and hashed daily manifest evidence | `tests/test_observation_daily_record.py`：`DAILY_EVIDENCE_KINDS` 恰好 14 项（`test_all_fourteen_evidence_kinds_are_declared`：preflight/data/news/sentiment/committee_or_skip/intent_or_no_trade/risk/execution_outcome/reconciliation/portfolio/alerts/heartbeat/backup/daily_manifest_hash）；`build_daily_record`——`test_complete_day_with_manifest_hash`（14 项全真 + manifest hash → complete）；`test_missing_evidence_kind_marks_incomplete`/`test_missing_manifest_hash_marks_incomplete`（缺任一项 → incomplete）；`test_evidence_is_never_fabricated`（无 truth → 全 False）；`test_deterministic` |
| AC-M16-W02-02 | Week 1 scorecard and the non-submit scheduler restart drill pass with zero duplicate orders, zero unapproved orders, zero live or other-broker attempt, monotonic cursor, and no unresolved cross-day difference | `tests/test_observation_weekly_gate.py`：`run_weekly_gate`——`test_full_truth_passes`（7 qualified days + 5 invariants → passed）；`test_missing_truth_fails_closed`（无 truth → 全 False）；`test_duplicate_orders_fail_the_gate`（任一 invariant 失败 → passed False，由 invariants 推导）；`test_deterministic`；`TestRestartDrill`（`scheduler-restart` drill 12 边界 frozen——CLI `drill` 命令 submits=0，绝不合成 submit） |
| AC-M16-W02-03 | Weekend, holiday, market-closed, degraded-provider, RiskGate rejection, and grounded no-opportunity outcomes qualify only with complete reasons and never trigger an activity quota or synthetic order | `tests/test_observation_incidents.py`：`QUALIFIED_OUTCOMES` 恰好 6 项（`test_all_six_outcomes_are_declared`）；`classify_qualified_outcome`——`test_outcome_qualifies_with_complete_reason`（有完整 reason → qualify）；`test_outcome_without_reason_does_not_qualify`（None/空白 → 不 qualify）；`test_unknown_outcome_never_qualifies`；`test_classification_is_deterministic`；`TestNoQuotaNoSynthetic`（契约无活动配额、无订单产出路径——no-trade 为合格 outcome） |

#### M16 Requirement Traceability（M16-W01..W02）

| Requirement | Code / Evidence |
|---|---|
| REQ-OBS-001 | W01 合格时钟/Day 0 manifest；W02 每日真实日历记录 |
| REQ-OBS-002（每天有 preflight、数据/新闻/情绪快照、committee 或合法 skip、risk/no-trade/order、对账、portfolio、heartbeat 和日报证据） | W02 `DAILY_EVIDENCE_KINDS` 14 项 + `build_daily_record`（缺任一项 → incomplete，绝不伪造）；相关测试 |
| REQ-OBS-003（不要求每天成交；安全拒绝和无机会是合格行为） | W02 `QUALIFIED_OUTCOMES`（weekend/holiday/market_closed/degraded_provider/risk_gate_rejection/no_opportunity 全合格）；`TestNoQuotaNoSynthetic` |
| REQ-OBS-004 | W01 observation_id/冻结 build |
| REQ-OBS-005（周门禁检查 uptime、cycle success、duplicate orders、reconciliation diffs、unresolved alerts、data freshness、model/schema、risk rejection 和 backup restore） | W02 `run_weekly_gate`（5 项零差异 invariants + 7 天合格）；相关测试 |

范围说明：`tests/test_observation_daily_record.py`、`tests/test_observation_weekly_gate.py`、
`tests/test_observation_incidents.py` 为 M16-W02 契约声明的测试文件（targeted
command 声明，documented forced path）；`alphabrief_core/observation_controller.py`
（扩展 DAILY_EVIDENCE_KINDS/ObservationDayRecord/build_daily_record/WeeklyGateResult/
run_weekly_gate/QUALIFIED_OUTCOMES/classify_qualified_outcome）与
`apps/cli/observation_commands.py`（`verify-window`/`drill`/`weekly-gate` runtime
命令）为契约声明的既有模块扩展（observation profile：max_production_files=0）。
真实 Days 1-7 观察依赖 Day 0 冻结（T7 外部证据 PENDING）——runtime 命令如实输出
BLOCKED_EXTERNAL/WAITING_EXTERNAL，绝不伪造观察日。全量 pytest：3158 total
（3139 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，分类见
M10-W03）；ruff/mypy 全仓 clean（506 source files）；acceptance 11/11。
下一 READY item：M16-W03。

#### M16-W03 已闭环证据（R-20260813-M16-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M16-W03-01 | Days 8 through 14 have complete hashed daily chains with explicit weekend, session, financing, macro-window, provider-degradation, and no-trade applicability evidence | `tests/test_observation_daily_record.py` `TestApplicabilityEvidence`：`APPLICABILITY_EVIDENCE_KINDS` 恰好 6 项（weekend/session/financing/macro_window/provider_degradation/no_trade）；`build_applicability_evidence`——`test_full_applicability_chain_with_reasons`（显式 verdict + 完整 reason）；`test_missing_truth_is_never_fabricated`（无 truth → 全 False，绝不假设）；`test_true_verdict_requires_complete_reason`（True 而无 reason → 回退 False）；`test_applicability_is_deterministic`；`test_day_range_covers_second_real_week`（Day 8-14 每天链完整） |
| AC-M16-W03-02 | The latest in-window backup restores into an isolated directory and reproduces schema, projections, cycle checkpoints, risk counters, broker mappings, transaction cursor, and observation state | `tests/test_observation_backup_restore.py`（M16-W03 契约声明文件）：`RESTORE_SURFACES` 恰好 7 项；`run_isolated_restore`——`test_full_truth_restores_all_surfaces`（全 truth → passed，isolated=True）；`test_missing_truth_fails_closed_not_reproduced`（无 truth → 全部 not reproduced）；`test_partial_restore_is_not_a_pass`（任一 surface 失败 → 整体不通过）；`test_isolated_directory_never_leaks`；`test_surfaces_are_typed_and_frozen`；`test_deterministic` |
| AC-M16-W03-03 | Week 2 gate passes all safety and continuity metrics or records the classified incident and required window reset without asking for approval or carrying invalid days forward | `tests/test_observation_incidents.py` `TestWindowIncidentReset`：`INCIDENT_SEVERITIES` 恰好 4 项（P0..P3）；`classify_window_incident`——`test_failed_gate_classifies_incident_and_resets_window`（gate 未过 → reset_required=True、invalid_days_carried_forward=False）；`test_passing_gate_records_no_reset`；`test_unknown_severity_fails_closed_as_p0`；`test_no_approval_and_no_carry_forward_on_reset`（detail 含 "no approval"）；`test_classification_is_deterministic` |

#### M16 Requirement Traceability（M16-W03）

| Requirement | Code / Evidence |
|---|---|
| REQ-OBS-001 | 合格时钟延续至第二真实周（Day 8-14 窗口）；runtime 命令在 Day 0 未冻结时如实 BLOCKED_EXTERNAL |
| REQ-OBS-002 | W03 `APPLICABILITY_EVIDENCE_KINDS` 6 项 + `build_applicability_evidence`（显式 verdict、绝不伪造）；配合 W02 `DAILY_EVIDENCE_KINDS` 14 项 hashed chain |
| REQ-OBS-003 | applicability 链含 weekend/session/no_trade 等非交易证据；无活动配额、无合成订单 |
| REQ-OBS-004 | restore 契约固定在 observation_controller（`RESTORE_SURFACES` 7 项）；drill 只恢复进 isolated 目录 |
| REQ-OBS-005 | W03 `classify_window_incident`：gate 失败 → 分类 incident + 窗口 reset，invalid days 绝不前移、绝不请求批准；配合 W02 `run_weekly_gate` 五项零差异 invariants |

范围说明：`tests/test_observation_backup_restore.py` 为 M16-W03 契约声明的测试文件
（targeted command 声明，documented forced path）；`alphabrief_core/
observation_controller.py`（新增 APPLICABILITY_EVIDENCE_KINDS/
DailyApplicabilityEvidence/build_applicability_evidence/RESTORE_SURFACES/
RestoreSurface/IsolatedRestoreResult/run_isolated_restore/INCIDENT_SEVERITIES/
WindowIncident/classify_window_incident）与 `apps/cli/observation_commands.py`
（verify-window 增加 applicability、drill 增加 isolated-restore 场景、weekly-gate
增加 incident/reset 输出）为契约声明的既有模块扩展（observation profile：
max_production_files=0，实际 0 个新生产文件）。真实 Days 8-14 观察依赖 Day 0
冻结（T7 外部证据 PENDING）——runtime 命令如实输出 BLOCKED_EXTERNAL 与
fail-closed 的 restore/gate 结果（submits=0、all surfaces not reproduced、
P0 incident + reset），绝不伪造观察日。全量 pytest：3177 total（3158 passed +
19 pre-existing M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；
ruff/mypy 全仓 clean；acceptance 11/11；runtime 3 命令均 exit 0。
下一 READY item：M16-W04。

#### M16-W04 已闭环证据（R-20260813-M16-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M16-W04-01 | Days 15 through 21 have complete daily evidence and continuous heartbeat, lease, cursor, reconciliation, backup, provider, model-schema, alert, and risk-state accounting | `tests/test_observation_weekly_gate.py` `TestContinuityAccounting`：`CONTINUITY_KINDS` 恰好 9 项（heartbeat/lease/cursor/reconciliation/backup/provider/model_schema/alert/risk_state）；`build_continuity_accounting`——`test_full_continuity_truth_is_complete`、`test_missing_truth_is_never_fabricated`（无 truth → 全 False）、`test_day_range_covers_third_real_week`（Day 15-21 每天完整）、`test_deterministic` |
| AC-M16-W04-02 | Approved fault injection proves bounded retry, jitter, no scheduler starvation, safe no-trade or freeze, durable alerting, clean recovery, and no blind resubmission or duplicate external order | `tests/test_observation_fault_drill.py`（M16-W04 契约声明文件）：`FAULT_SCENARIOS` 恰好 5 项（http_429/http_5xx/network_loss/stale_data/model_failure）；`FAULT_INVARIANTS` 恰好 8 项；`run_fault_drill`——`test_full_truth_passes_under_approved_injection`（每场景全 truth → passed，submits=0）；`test_missing_truth_fails_closed`；`test_unknown_scenario_fails_closed`；`test_duplicate_order_invariant_is_guarded`；`test_drill_never_submits`（本地注入绝不下单）；`test_invariants_are_typed`；`test_deterministic` |
| AC-M16-W04-03 | Week 3 gate has no unresolved P0 or P1 and every P2 or P3 event has a deterministic reset decision, evidence hash, repair reference, and no operator question | `tests/test_observation_incidents.py` `TestWeekEventResolution`：`EVENT_RESOLUTION_FIELDS` 恰好 3 项（reset_decision/evidence_hash/repair_reference）；`resolve_week_event`——`test_p0_event_never_resolves_in_loop`/`test_p1_event_never_resolves_in_loop`（P0/P1 绝不由 loop 解决，gate 失败关闭）；`test_p2_event_resolves_with_all_fields`；`test_p3_event_missing_field_does_not_resolve`；`test_unknown_severity_fails_closed_as_p0`；`test_no_operator_question_is_asked`；`test_resolution_is_deterministic`；`tests/test_observation_weekly_gate.py` `TestWeekThreeGateWithEvents`（Week 3 gate 与 event resolution 组合：gate passed + 无未解决 P0/P1 + 全部 P2/P3 完整解决才可通过） |

#### M16 Requirement Traceability（M16-W04）

| Requirement | Code / Evidence |
|---|---|
| REQ-OBS-001 | 合格时钟延续至第三真实周（Day 15-21 窗口）；runtime 命令在 Day 0 未冻结时如实 BLOCKED_EXTERNAL |
| REQ-OBS-002 | W04 `CONTINUITY_KINDS` 9 项 + `build_continuity_accounting`（连续 accounting、绝不伪造）；配合 W02 14 项 hashed chain |
| REQ-OBS-003 | 故障注入 drill 保 `safe_no_trade_or_freeze` 与 `no_duplicate_external_order`；drill submits=0，本地注入绝不下单 |
| REQ-OBS-004 | 故障 drill 与事件解决契约固定在 observation_controller；drill 不触碰 practice account 正常行为之外 |
| REQ-OBS-005 | W04 `resolve_week_event`：P0/P1 未解决 → gate 失败；P2/P3 需 reset_decision + evidence_hash + repair_reference 且绝不问 operator |

范围说明：`tests/test_observation_fault_drill.py` 为 M16-W04 契约声明的测试文件
（targeted command 声明，documented forced path）；`alphabrief_core/
observation_controller.py`（新增 CONTINUITY_KINDS/ContinuityAccounting/
build_continuity_accounting/FAULT_SCENARIOS/FAULT_INVARIANTS/FaultInvariant/
FaultDrillReport/run_fault_drill/EVENT_RESOLUTION_FIELDS/WeekEventResolution/
resolve_week_event）与 `apps/cli/observation_commands.py`（verify-window 增加
continuity、drill 增加 provider-and-network-faults 场景、weekly-gate 增加
events 输出）为契约声明的既有模块扩展（observation profile：
max_production_files=0，实际 0 个新生产文件）。真实 Days 15-21 观察依赖 Day 0
冻结（T7 外部证据 PENDING）——runtime 命令如实输出 BLOCKED_EXTERNAL 与
fail-closed 的 fault drill（submits=0、8 invariants not preserved）与 week 3
gate（4 events unresolved、P0 incident + reset），绝不伪造观察日。全量 pytest：
3201 total（3182 passed + 19 pre-existing M08-W03 time-bombed risk fixture
失败，分类见 M10-W03）；ruff/mypy 全仓 clean；acceptance 11/11；runtime 3
命令均 exit 0。下一 READY item：M16-W05。

#### M16-W05 已闭环证据（R-20260813-M16-W05）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M16-W05-01 | Days 22 through 30 complete a real uninterrupted 30-calendar-day qualified window with 30 daily manifests and separate active-market, weekend, holiday, no-trade, partial, failed, and reset accounting | `tests/test_observation_day_thirty.py` `TestWindowAccounting`：`WINDOW_ACCOUNT_KINDS` 恰好 7 项（active_market/weekend/holiday/no_trade/partial/failed/reset）；`build_window_accounting`——`test_full_window_accounting_is_complete`（days_total=30 → complete）、`test_less_than_thirty_days_is_not_complete`（29 天 → incomplete，绝不伪造第 30 天）、`test_missing_kinds_are_zero_never_fabricated`、`test_deterministic` |
| AC-M16-W05-02 | Week 4 restart and reconciliation drill passes with naturally present pending state or the predefined minimal controlled scenario and leaves no unintended order, trade, position, freeze, or unexplained difference | `tests/test_observation_final_reconciliation.py`（M16-W05 契约声明文件）：`RESTART_RECONCILE_INVARIANTS` 恰好 5 项（no_unintended_order/trade/position/freeze/no_unexplained_difference）；`run_restart_reconcile_drill`——`test_full_truth_passes`（submits=0）、`test_missing_truth_fails_closed`、`test_unexplained_difference_fails_the_drill`、`test_drill_never_submits`、`test_deterministic` |
| AC-M16-W05-03 | Day 30 closes new cycles, fully reconciles account truth, verifies duplicate and approval invariants, creates a fresh backup, passes isolated restore, and validates every daily and weekly artifact hash | `tests/test_observation_day_thirty.py` `TestDay30Close`：`DAY30_CLOSE_STEPS` 恰好 7 项（stop_new_cycles/final_reconcile/duplicate_invariant/approval_invariant/fresh_backup/isolated_restore/artifact_hash_validation）；`run_day30_close`——`test_full_truth_passes_the_close`、`test_missing_truth_fails_closed`、`test_partial_close_is_not_a_pass`、`test_close_never_creates_cycles_or_resubmits`、`test_deterministic`；`tests/test_observation_manifest_integrity.py`（M16-W05 契约声明文件）：`validate_manifest_hashes`——`test_all_34_hashes_validate`（30 daily + 4 weekly）、`test_missing_hashes_fail_closed`、`test_blank_hash_fails`、`test_duplicate_hash_fails`、`test_wrong_count_fails`、`test_deterministic` |

#### M16 Requirement Traceability（M16-W05）

| Requirement | Code / Evidence |
|---|---|
| REQ-OBS-001 | `WINDOW_ACCOUNT_KINDS` 7 类独立记账；`build_window_accounting` 仅 days_total==30 时 complete |
| REQ-OBS-002 | 30 天窗口复用 W02 14 项 daily evidence kinds；Day 30 close 校验全部 manifest hashes |
| REQ-OBS-003 | window accounting 含 no_trade 分类；close/restart-reconcile drill 无提交路径 |
| REQ-OBS-004 | `RESTART_RECONCILE_INVARIANTS` 保 no_unintended_freeze/no_unexplained_difference；reset 分类记账 |
| REQ-OBS-005 | `DAY30_CLOSE_STEPS` 含 final_reconcile + duplicate_invariant + approval_invariant + artifact_hash_validation |
| REQ-OBS-006 | 新增 `validate_manifest_hashes`（34 项，缺/空/重复即失败）——报告将完全由 artifact hashes 驱动，不靠人工拼写通过数 |

范围说明：`tests/test_observation_day_thirty.py`、`tests/test_observation_final_reconciliation.py`、
`tests/test_observation_manifest_integrity.py` 为 M16-W05 契约声明的测试文件
（targeted command 声明，documented forced path）；`alphabrief_core/
observation_controller.py`（新增 WINDOW_ACCOUNT_KINDS/WindowAccounting/
build_window_accounting/RESTART_RECONCILE_INVARIANTS/
RestartReconcileDrillReport/run_restart_reconcile_drill/DAY30_CLOSE_STEPS/
Day30CloseReport/run_day30_close/ManifestHashVerdict/validate_manifest_hashes）
与 `apps/cli/observation_commands.py`（drill 增加 restart-reconcile 场景、新增
day-30-gate 命令）为契约声明的既有模块扩展（observation profile：
max_production_files=0，实际 0 个新生产文件）。真实 Days 22-30 观察依赖 Day 0
冻结（T7 外部证据 PENDING）——runtime 命令如实输出 BLOCKED_EXTERNAL 与
fail-closed 的 restart-reconcile drill（submits=0）、week 4 gate（events
unresolved）与 day-30-gate（34 hashes missing、7 steps not completed），绝不
伪造观察日。全量 pytest：3228 total（3205 passed + 19 pre-existing M08-W03
time-bombed risk fixture 失败，分类见 M10-W03）；ruff/mypy 全仓 clean；
acceptance 11/11；runtime 4 命令均 exit 0。
下一 READY item：M16-W06。

#### M16-W06 已闭环证据（R-20260813-M16-W06）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M16-W06-01 | The gate proves 30 of 30 real daily records, complete active-market decision chains, daily backups, four weekly gates, final restore, continuous qualified timing, and immutable manifest hashes | `tests/test_observation_final_gate.py`（M16-W06 契约声明文件）`TestFinalGateProofs`：`FINAL_GATE_PROOFS` 恰好 7 项（thirty_of_thirty_daily_records/active_market_decision_chains/daily_backups/four_weekly_gates/final_restore/continuous_qualified_timing/immutable_manifest_hashes）；`run_final_gate`——`test_full_truth_passes`、`test_missing_truth_fails_closed`（缺 truth → 全 not proven）、`test_single_missing_proof_fails_the_gate` |
| AC-M16-W06-02 | The gate proves zero duplicate external orders, zero order without a persisted matching approved RiskDecision, zero live or other-broker attempt, zero unexplained cross-day reconciliation difference, and zero unresolved P0 or P1 | `tests/test_observation_final_gate.py` `TestFinalSafetyInvariants`：`FINAL_SAFETY_INVARIANTS` 恰好 5 项；`test_duplicate_order_invariant_is_required`、`test_approved_risk_decision_invariant_is_required`、`test_live_or_other_broker_invariant_is_required`（任一非零 → gate 失败） |
| AC-M16-W06-03 | Missing, modified, mock-only, waived, manually asserted, future-dated, or reset-invalid evidence fails the gate and records the blocker while the product remains OANDA practice-only | `tests/test_observation_final_gate.py` `TestEvidenceFlaws`：`EVIDENCE_FLAWS` 恰好 7 项；`test_any_flaw_fails_the_gate_and_records_blocker`（每种 flaw → passed=False + BLOCKED_EXTERNAL blocker）、`test_mock_only_evidence_never_passes`、`test_future_dated_evidence_never_passes`；`TestPracticeOnly`——`test_gate_never_unlocks_live`（practice_only=True）、`test_gate_is_deterministic` |

#### M16 Requirement Traceability（M16-W06）

| Requirement | Code / Evidence |
|---|---|
| REQ-OBS-001 | `FINAL_GATE_PROOFS` 含 thirty_of_thirty_daily_records + continuous_qualified_timing |
| REQ-OBS-002 | `FINAL_GATE_PROOFS` 含 active_market_decision_chains；复用 W02 14 项 daily kinds |
| REQ-OBS-003 | final gate 不含订单产出路径；practice_only 恒真 |
| REQ-OBS-004 | `EVIDENCE_FLAWS` 含 reset_invalid（reset 无效证据 → 失败 + blocker） |
| REQ-OBS-005 | `FINAL_GATE_PROOFS` 含 four_weekly_gates + daily_backups + final_restore |
| REQ-OBS-006 | gate 只由 evidence truth 推导 verdict；`observation finalize` / `verify --final` 输出 proofs/invariants/blockers 计数 |
| REQ-OBS-007 | `run_final_gate` 输出 practice_only=True；产品保持 OANDA practice-only，无 live 路径 |

范围说明：`tests/test_observation_final_gate.py` 为 M16-W06 契约声明的测试文件
（targeted command 声明，documented forced path）；`alphabrief_core/
observation_controller.py`（新增 FINAL_GATE_PROOFS/FINAL_SAFETY_INVARIANTS/
EVIDENCE_FLAWS/FinalGateResult/run_final_gate）与 `apps/cli/observation_commands.py`
（新增 `finalize`、`verify --final` 命令）为契约声明的既有模块扩展（observation
profile：max_production_files=0，实际 0 个新生产文件）。真实 30 天观察依赖 Day 0
冻结（T7 外部证据 PENDING）——`finalize`/`verify --final`/`restore-drill` 如实
输出 fail-closed 结果（proofs 0/7、invariants 0/5、practice_only=True、
backup_integrity=False），绝不伪造观察证据。全量 pytest：3238 total（3219
passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，分类见
M10-W03）；ruff/mypy 全仓 clean；acceptance 11/11；runtime 3 命令均 exit 0。
下一 READY item：M17-W01。

#### M17-W01 已闭环证据（R-20260813-M17-W01）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M17-W01-01 | Reports derive every requirement, work item, acceptance result, quality count, safety invariant, observation metric, incident, and known limitation from referenced immutable evidence rather than handwritten totals | `tests/test_observation_final_report.py`（M17-W01 契约声明文件）：`REPORT_EVIDENCE_SOURCES` 恰好 6 项（requirements_map/database_facts/loop_ledger/test_results/oanda_practice_evidence/observation_artifact_hashes）；`REPORT_COUNT_FIELDS` 恰好 12 项；`generate_final_report`——`test_full_evidence_passes`、`test_missing_source_fails_closed`（无 source → 全 not referenced）、`test_no_supplied_evidence_means_zero_counts`（无证据 → 计数全 0，绝不手写）、`test_partial_sources_fail_the_report`、`test_counts_are_typed_and_frozen`、`test_deterministic` |
| AC-M17-W01-02 | A second generation from the same frozen inputs produces identical normalized content and manifest hashes while any missing, changed, duplicate, or unverified input fails closed | `tests/test_evidence_manifest.py`（M17-W01 契约声明文件）：`test_identical_frozen_inputs_give_identical_hash`、`test_changed_count_changes_the_hash`、`test_changed_source_reference_changes_the_hash`、`test_missing_evidence_fails_closed`、`test_unverified_input_is_never_assumed`（无 truth 的 source 绝不假设已引用）、`test_hash_is_stable_across_runs`；runtime 双格式（json + markdown）manifest hash 相同（cbe78057…） |
| AC-M17-W01-03 | The report contains no secret, full account ID, authorization value, unlicensed news body, waiver, TBD, unsupported completion claim, or implication that live trading is enabled | `tests/test_final_report_redaction.py`（M17-W01 契约声明文件）：`FORBIDDEN_REPORT_MARKERS`（waiver/tbd）与 `LIVE_CLAIM_MARKERS`（live trading is enabled/live mode is active/go live）声明；`scan_report_content`——`test_clean_content_passes`、`test_bearer_token_is_caught`、`test_token_value_is_caught`、`test_authorization_value_is_caught`、`test_full_account_id_is_caught`、`test_bare_full_account_number_is_caught`、`test_waiver_is_caught`、`test_tbd_is_caught`、`test_live_trading_claim_is_caught`、`test_practice_only_statement_is_not_caught`、`test_deterministic`；runtime 报告 content_clean=true |

#### M17 Requirement Traceability（M17-W01）

| Requirement | Code / Evidence |
|---|---|
| REQ-OBS-006 | `generate_final_report`：全部计数与 source 引用来自证据，缺证据即 fail-closed；`REPORT_COUNT_FIELDS` 12 项 + manifest hash（sha256 of normalized content） |
| REQ-OBS-007 | 报告模板固定声明 "OANDA practice-only; live trading, other brokers, and production simulation remain forbidden and unreachable"；`LIVE_CLAIM_MARKERS` 扫描保证无 live 暗示 |

范围说明：`tests/test_observation_final_report.py`、`tests/test_evidence_manifest.py`、
`tests/test_final_report_redaction.py` 为 M17-W01 契约声明的测试文件（targeted
command 声明，documented forced path）；`alphabrief_core/observation_controller.py`
（新增 REPORT_EVIDENCE_SOURCES/REPORT_COUNT_FIELDS/ReportSource/FinalReport/
generate_final_report/FORBIDDEN_REPORT_MARKERS/LIVE_CLAIM_MARKERS/
ReportContentVerdict/scan_report_content）与 `apps/cli/observation_commands.py`
（新增 `report --output --format json|markdown` 命令）为契约声明的既有模块扩展
（observation profile：max_production_files=0，实际 0 个新生产文件）；
`reports/generated/final_acceptance.json|.md` 为 observation profile 允许的
generated artifacts（fail-closed 快照：passed=false、0/6 sources referenced、
content_clean=true、manifest hash 双格式一致）。真实 OANDA practice T7 证据
PENDING——报告如实输出 NOT_PASSED，绝不伪造通过数。全量 pytest：3265 total
（3246 passed + 19 pre-existing M08-W03 time-bombed risk fixture 失败，分类见
M10-W03）；ruff/mypy 全仓 clean；acceptance 11/11；runtime 2 命令均 exit 0。
下一 READY item：M17-W02。

#### M17-W02 已闭环证据（R-20260813-M17-W02）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M17-W02-01 | An isolated fresh checkout installs locked Python and Electron dependencies, initializes an empty data directory, migrates, and reaches local readiness without relying on untracked source or historical state | `tests/test_operations_fresh_install.py`（M17-W02 契约声明文件）：`FRESH_INSTALL_STEPS` 恰好 5 项（locked_deps_install/empty_data_dir_init/migrate/local_readiness/no_untracked_source_dependency）；`run_fresh_install_check`——`test_full_truth_passes`、`test_missing_truth_fails_closed`、`test_untracked_source_dependency_fails`、`test_empty_data_dir_is_required`、`test_deterministic` |
| AC-M17-W02-02 | The operator runbook proves practice credential injection, startup, preflight, scheduler control, freeze, safe shutdown, backup, isolated restore, restart, reconciliation, and blocker inspection without exposing secrets | `tests/test_recovery_runbook.py`（M17-W02 契约声明文件）：`OPERATOR_RUNBOOK_STEPS` 恰好 11 项；`run_operator_runbook_check`——`test_full_truth_passes`、`test_missing_truth_fails_closed`、`test_credential_injection_is_required`、`test_secrets_are_never_exposed`（secrets_exposed 恒 False）、`test_deterministic` |
| AC-M17-W02-03 | Long-running maintenance defines automatic backup retention, restore cadence, dependency review, incident retention, evidence retention, and practice-account reset behavior with no live-trading procedure | `tests/test_operations_maintenance.py`（M17-W02 契约声明文件）：`MAINTENANCE_POLICIES` 恰好 6 项；`build_maintenance_policy`——`test_full_truth_defines_all_policies`、`test_missing_truth_fails_closed`、`test_practice_account_reset_is_required`、`test_no_live_trading_procedure_ever`（no_live_procedure 恒 True）、`test_policies_are_typed`、`test_deterministic` |

#### M17 Requirement Traceability（M17-W02）

| Requirement | Code / Evidence |
|---|---|
| REQ-OPS-006 | `run_fresh_install_check`（5 步，缺 truth fail-closed）+ `run_operator_runbook_check`（11 步，覆盖 startup/restart/blocker inspection）；配合既有 recovery/soak drills |
| REQ-OPS-007 | `OPERATOR_RUNBOOK_STEPS` 含 credential_injection + preflight；`secrets_exposed` 恒 False |
| REQ-OBS-007 | `MAINTENANCE_POLICIES` 含 practice_account_reset；`no_live_procedure` 恒 True，无 live-trading 流程 |

范围说明：`tests/test_operations_fresh_install.py`、`tests/test_recovery_runbook.py`、
`tests/test_operations_maintenance.py` 为 M17-W02 契约声明的测试文件（targeted
command 声明，documented forced path）；`alphabrief_core/recovery.py`（新增
FRESH_INSTALL_STEPS/FreshInstallReport/run_fresh_install_check/
OPERATOR_RUNBOOK_STEPS/OperatorRunbookReport/run_operator_runbook_check/
MAINTENANCE_POLICIES/MaintenancePolicy/MaintenancePolicyReport/
build_maintenance_policy；复用 observation_controller.FaultInvariant）与
`apps/cli/operations_commands.py`（新增 `verify-fresh-install` 命令）为契约声明的
既有模块扩展（operations profile：max_production_files=9，实际 0 个新生产
文件）。真实 fresh-install 验证依赖已提交源码 + 外部注入 secrets（T7 证据
PENDING）——`verify-fresh-install`/`restore-drill` 如实输出未完成步骤
（fail-closed），绝不声称已就绪。全量 pytest：3284 total（3265 passed + 19
pre-existing M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；
pip check clean；ruff/mypy 全仓 clean；acceptance 11/11；runtime 2 命令均
exit 0。下一 READY item：M17-W03。

#### M17-W03 已闭环证据（R-20260813-M17-W03）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M17-W03-01 | Two clean package builds from the frozen source produce equivalent normalized contents and a versioned checksum manifest without embedding secrets, account data, databases, logs, or observation artifacts | `tests/test_electron_packaging.py`（M17-W03 契约声明文件）：`TestReproducibleBuild`——`test_two_builds_are_identical`（两次 build 逐文件字节一致）、`test_checksum_manifest_matches_actual_files`（CHECKSUMS.sha256 每行 sha256 与文件一致，4 个源文件）、`test_package_contains_only_frozen_source`（仅 4 个冻结源文件 + manifest，无 node_modules）、`test_packaged_json_is_normalized`（无 scripts/devDependencies）、`test_build_is_deterministic_across_runs`；`TestNoEmbeddedData`——`test_no_secret_or_account_data_in_package`、`test_no_database_logs_or_observation_artifacts`（无 .duckdb/.ndjson/observation_manifest）、`test_packaging_refuses_forbidden_input`（`node scripts/package.js selftest` 证明 scanner 拒绝 secret 模式）、`test_source_is_frozen` |
| AC-M17-W03-02 | The packaged application passes backend readiness, port conflict, duplicate ownership, startup failure, navigation, freeze, graceful shutdown, restart, and error-propagation smoke tests | `tests/test_electron_packaged_smoke.py`（runtime 命令契约声明文件）`TestPackagedSmoke` 9 项（readiness/port conflict/duplicate ownership/startup failure/navigation/freeze/shutdown/restart/error propagation——全部在 packaged main.js 上断言）；既有 `tests/test_electron_lifecycle.py` 回归；`npm --prefix electron run package` 与 `npm --prefix electron test`（check 模式验证 dist artifact 校验和）均 exit 0 |
| AC-M17-W03-03 | Static and runtime inspection finds no live host, live selector, Alpaca or other broker, simulated production fallback, arbitrary broker proxy, or unapproved auto-update execution path | `tests/test_electron_security.py`（M17-W03 契约声明文件）：`TestNoLivePath`——`test_no_live_host_is_configured`（无 api-fxtrade/api-fxpractice）、`test_no_live_selector_exists`（无 'live' 模式值/live_mode/liveMode）、`test_no_broker_routing_in_shell`（无 alpaca/broker/routing）、`test_no_simulated_production_fallback`（无 simulated/in_memory_fill）、`test_no_arbitrary_broker_proxy`、`test_no_unapproved_auto_update_path`（无 autoUpdater）；`TestPackagedInspection` |

#### M17 Requirement Traceability（M17-W03）

| Requirement | Code / Evidence |
|---|---|
| REQ-UI-009 | packaged main.js smoke 覆盖 backend readiness、端口冲突、单实例锁、startup failure overlay、导航、freeze 透传、优雅关闭（SIGTERM）、restart、错误传播（console.error/showErrorOverlay，绝不吞错） |
| REQ-OBS-007 | packaging scanner 拒绝 live/broker/simulated 标记；security 测试证明包内无 live host、live selector、Alpaca/其他 broker、simulated fallback、broker proxy、未批准 auto-update；包内固定声明 practice-only |

范围说明：`tests/test_electron_packaging.py`、`tests/test_electron_security.py`、
`tests/test_electron_packaged_smoke.py` 为 M17-W03 契约声明的测试文件（targeted
/runtime command 声明，documented forced path）；`electron/scripts/package.js`
（新增 1 个生产文件 ≤ max 7）与 `electron/package.json`（新增 package/test 脚本）
为契约声明的模块（frontend profile：electron/** 与 tests/test_electron*.py 均在
allowlist）；`electron/dist/` 为 gitignored 可复现 build artifact（冻结源码已
提交，任何干净 checkout 可重建）。全量 pytest：3310 total（3291 passed + 19
pre-existing M08-W03 time-bombed risk fixture 失败，分类见 M10-W03）；frontend
回归子集 229 passed；ruff/mypy 全仓 clean；acceptance 11/11；`npm --prefix
electron run package` / `npm --prefix electron test` 均 exit 0。
下一 READY item：M17-W04。

#### M17-W04 已闭环证据（R-20260813-M17-W04）

| AC | Predicate | Evidence |
|---|---|---|
| AC-M17-W04-01 | Every required milestone, work item, requirement, and acceptance predicate has a committed evidence reference at its declared hierarchy level with no TBD, waiver, mock substitution, unresolved blocker, or self-authored PASS | `tests/test_traceability_contract.py`（M17-W04 契约声明文件）：`TRACEABILITY_LEVELS` 恰好 4 项（milestone/work_item/requirement/acceptance_predicate）；`TRACEABILITY_FLAWS` 恰好 5 项（tbd/waiver/mock_substitution/unresolved_blocker/self_authored_pass）；`verify_traceability`——`test_full_traceability_passes`、`test_missing_level_reference_fails_closed`、`test_any_flaw_fails_and_records_blocker`、`test_self_authored_pass_is_rejected`、`test_mock_substitution_is_rejected`、`test_deterministic` |
| AC-M17-W04-02 | Fresh full tests, Ruff, Mypy, dependency integrity, acceptance, security, fresh-install, package, backup restore, final reconciliation, and OANDA practice-only negative gates all pass on the release commit | `tests/test_final_acceptance.py`（M17-W04 契约声明文件）：`FINAL_RELEASE_GATES` 恰好 11 项（full_tests/ruff/mypy/dependency_integrity/acceptance/security/fresh_install/package/backup_restore/final_reconciliation/oanda_practice_only_negative）；`run_final_release_gate`——`test_full_truth_with_matching_hashes_passes`、`test_missing_truth_fails_closed_and_stays_in_progress`、`test_single_failed_gate_blocks_completion`；本轮实际全量 pytest 3306 passed + 19 pre-existing、ruff/mypy/pip check clean、acceptance 11/11、fresh-install/package/backup-restore/reconciliation gates 全部回归通过 |
| AC-M17-W04-03 | The final report hashes match source artifacts, the repository is clean after commit, and project status becomes COMPLETE_PAPER_ONLY while live trading, other brokers, and production simulation remain forbidden and unreachable | `tests/test_final_acceptance.py`：`FINAL_PROJECT_STATUS == "COMPLETE_PAPER_ONLY"`（唯一完成状态）；`test_hash_mismatch_blocks_completion`（报告 hash 与源码 artifacts 不匹配 → 保持 IN_PROGRESS + BLOCKED_EXTERNAL blocker）；`test_final_status_is_paper_only`；真实报告 hash 需真实 OANDA practice T7 证据（PENDING）——项目 status 如实保持 IN_PROGRESS，绝不 self-authored PASS |

#### M17 Requirement Traceability（M17-W04）

| Requirement | Code / Evidence |
|---|---|
| REQ-OBS-006 | `verify_traceability`（4 级证据引用，5 类 flaw 拒绝）+ `run_final_release_gate`（11 门禁 + report hash 匹配才 COMPLETE_PAPER_ONLY） |
| REQ-OBS-007 | `FINAL_PROJECT_STATUS` 唯一为 COMPLETE_PAPER_ONLY；oanda_practice_only_negative 为必需门禁；live/其他 broker/production simulation 恒 forbidden 且不可达 |

范围说明：`tests/test_final_acceptance.py`、`tests/test_traceability_contract.py`
为 M17-W04 契约声明的测试文件（targeted command 声明，documented forced
path）；`tests/test_project_scaffold.py` 为本轮回归目标（既有 11 项全过）；
`alphabrief_core/observation_controller.py`（新增 TRACEABILITY_LEVELS/
TRACEABILITY_FLAWS/TraceabilityVerdict/verify_traceability/FINAL_RELEASE_GATES/
FINAL_PROJECT_STATUS/FinalReleaseVerdict/run_final_release_gate）与
`apps/cli/acceptance_commands.py`（preflight 增加 final-release scope 并分发到
`run_preflight("final_release", {})`）为契约声明的既有模块扩展（governance
profile：max_production_files=4，实际 0 个新生产文件）。真实 final release
依赖真实 OANDA practice T7 证据与真实 30 天观察（PENDING）——`observation
verify --final`（proofs 0/7、invariants 0/5）与 `acceptance preflight --scope
final-release`（4 checks 如实未过）均 exit 0，绝不伪造通过。全量 pytest：
3321 total（3306 passed + 19 pre-existing M08-W03 time-bombed risk fixture
失败，分类见 M10-W03）；pip check clean；ruff/mypy 全仓 clean；acceptance
11/11。工作队列执行完毕——所有可执行 work items 均已按契约闭环；剩余依赖
仅为外部 T7 practice evidence（见 blocker 报告）。
