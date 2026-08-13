# OANDA Practice 30-Day Observation Runbook

版本：2026-08-13.1
适用：M15 Engineering Readiness Gate 通过后的 M16
禁止：在当前 multi-broker/routed 基线直接开始计时

## 1. Purpose

本手册定义如何安全地运行和验收真实连续 30 个日历日的 OANDA v20 practice
模拟盘。它不是开户指南，也不保证策略收益。观察目标是证明：

- 正式产品链每天可恢复运行；
- 数据、新闻、情绪、讨论、风险、执行/不交易、对账和日报可追溯；
- 没有重复订单、无审批订单、live/其他券商访问或跨日未解释差异；
- 周末、休市、网络故障、模型故障和进程重启能安全处理；
- 备份可恢复；
- 系统不会为了产生交易而忽略风险。

## 2. Start Eligibility

只有 `docs/progress.yaml` 同时满足以下条件才允许创建 observation：

```text
project_status = ENGINEERING_READY
M01..M15 = DONE
current production broker = oanda_paper
live trading = forbidden/unreachable
other broker references = 0
production simulated fallback = 0
full local quality gate = PASS
controlled OANDA practice E2E = PASS
backup restore drill = PASS
unresolved P0/P1 = 0
Git tree = clean
```

当前 2026-08-13 基线不满足这些条件，不能把旧 Alpaca/OANDA routed 数据计入
正式观察。

## 3. OANDA Account Boundary

### 3.1 Required Secrets

只在 runtime environment/approved secret store 设置：

```text
ALPHABRIEF_OANDA_TOKEN
ALPHABRIEF_OANDA_ACCOUNT_ID
```

禁止把值写入 `.env.example`、YAML、Markdown、Git、日志、artifact、截图或最终
报告。证据只保存：

- account ID 的不可逆短 hash；
- OANDA RequestID 的 hash 或允许的 request correlation；
- practice host constant；
- 非敏感账户 currency/division/capability summary。

### 3.2 Hosts

允许：

```text
https://api-fxpractice.oanda.com
https://stream-fxpractice.oanda.com
```

任何 `fxtrade` host 或 runtime-selectable live environment 都是 P0 safety event，
立即停止观察并 freeze。

### 3.3 Instrument Scope

Day 0 同步配置账户的 `/instruments` 完整响应。catalog 必须记录所有返回品种和
类型，不以本手册硬编码清单替代。观察期间：

- 每日检测新增/下架/metadata 变化；
- 所有目录品种可在 API/UI 查看；
- AI 每天只分析经过数据质量、可交易性、流动性、风险和预算过滤的有界候选；
- 账户不提供的类别标记 unsupported，不路由其他券商；
- `OTHER_CFD` 仍可见，并记录 taxonomy reason/version。

## 4. Day 0 - Freeze and Commissioning

### 4.1 Freeze Build

记录并锁定：

- Git commit and tree hash；
- blueprint/work queue/progress schema versions；
- Python/Node/OS versions；
- lock/dependency hashes；
- database schema version；
- execution/risk/news/model/template/taxonomy versions；
- config hashes（不含 secrets）；
- model provider/profile names；
- account hash and home currency；
- instrument catalog version/count/category counts；
- start timezone and UTC timestamps。

创建唯一 `observation_id`，所有后续 daily evidence 必须引用。

### 4.2 Full Preflight

M15 必须实现一个确定性 preflight command。最终 command contract：

```bash
.venv/bin/alphabrief acceptance preflight --scope oanda-observation --compact
```

它应只读验证：

1. practice REST/stream hosts locked；
2. token/account present但不输出；
3. configured account details 可读且适合 v20 client extensions；
4. instrument catalog 非空且完整同步；
5. quote/candle freshness；
6. news/macro/sentiment providers 和 degradation policy；
7. ModelGateway production provider；
8. risk policy/version/kill/freeze；
9. scheduler single leader；
10. database migration/writer lease；
11. transaction cursor and reconciliation clean；
12. backup destination writable and last restore drill（M03-W05 起由
    `alphabrief_api.db.backup` 提供原子 backup + manifest hashes +
    isolated restore + retention；restore 后必须跑 migration/integrity/
    projection rebuild 检查）；
12b. account preflight 通过（M04-W01 起由
    `alphabrief_execution.broker.oanda.preflight.run_account_preflight`
    在 catalog sync 与任何执行前验证 credentials/practice host/
    account ownership/tradeable state/malformed response，全程无 token
    与完整 account ID 外泄）；
13. secret scrub/static no-live/no-other-broker gates；
14. alert sink local persistence；
15. current Git/config matches frozen build。

任何 required check 失败都不能开始 Day 1。

### 4.3 Controlled Practice E2E

只通过正式应用路径执行一个最小受控场景：

```text
fresh snapshot
-> deterministic test proposal
-> OrderIntent
-> full RiskGate
-> persisted approved RiskDecision
-> smallest valid practice order
-> broker transaction observed
-> cancel/close as applicable
-> reconciliation clean
-> no residual unintended order/position
```

要求：

- 使用 catalog 中明确允许、当前 tradeable、点差正常的 instrument；
- quantity 为账户允许的最小安全规模且低于 observation risk cap；
- 使用独立 cycle/client ID；
- agent 不得直接 curl OANDA 下单；
- cleanup 失败立即 freeze，不开始观察；
- E2E evidence 含完整 ID chain 和脱敏 OANDA request/transaction reference。

### 4.4 Initial Backup and Restore

停止 writer，创建 backup，校验 hash，在临时 data directory restore，然后运行只读
projection/reconciliation/acceptance。成功后销毁临时 restore（不销毁原 backup）。

## 5. Observation Risk Envelope

观察期 risk limits 由 versioned policy 定义，不在本手册写死金额。必须满足：

- 明显小于 practice account capacity；
- per-order、per-instrument、per-category、gross/net、margin、daily loss、drawdown
  均有 cap；
- candidate budget 和最大 daily new intents 有 cap；
- market data stale、non-tradeable、wide spread、low liquidity 拒绝；
- news/macro high-risk windows size down/reject；
- execution freeze/kill switch 可立即阻止新开仓；
- reduce-only close path 独立审计；
- policy 改变会触发 observation reset 评估。

不以收益或订单数量为目标。

## 6. Daily Operating Sequence

每个日历日必须产生一个 `DailyObservationRecord`。Market closed 也要记录，但不运行
不合时宜的交易。

### 6.1 Start-of-Day Check

1. scheduler leader/heartbeat；
2. process and database health；
3. practice host/account hash/build hash；
4. transaction cursor monotonicity and startup reconciliation；
5. open orders/trades/positions/account/NAV/margin；
6. unresolved freeze/alerts/incidents；
7. latest backup；
8. instrument catalog diff；
9. market/news/model provider health；
10. daily risk counters/high-water mark restored。

任一 safety/reconciliation required check 失败：继续研究可允许，但 execution freeze。

### 6.2 Ingestion Evidence

记录：

- candle/quote snapshot ID、coverage、gaps、freshness、incomplete count；
- bid/ask/spread/tradeable/liquidity/conversion coverage；
- news source success/failure、dedupe counts、newest/oldest age；
- macro events/revisions；
- sentiment direction/strength/disagreement/sample/freshness；
- untrusted-content/injection scan results；
- degradation/no-trade triggers。

### 6.3 Candidate and Discussion Evidence

记录完整目录数量、各过滤阶段数量、最终候选以及每个 skipped reason。对每个实际
讨论候选保留：

- common snapshot/evidence manifest；
- all role turns/model call IDs；
- citations and validation；
- thesis/anti-thesis/dissent；
- confidence/horizon/invalidation；
- model/schema/fallback/cost/latency；
- final `no_trade` or proposal。

### 6.4 Risk and Execution Evidence

每个 proposal：

- intent ID and immutable hash；
- broker-fresh account/risk context ID；
- rule-by-rule RiskDecision；
- approved/rejected/max quantity/reasons；
- submitted request mapping（如 approved）；
- OANDA order/transaction/trade/fill references；
- partial/reject/cancel/expire/dependent order transitions；
- trade/position close 记录（ALL/partial、long/short side、realized/unrealized/financing）与
  account summary/changes（sinceTransactionID 游标）——M06-W04 起由
  `trade_ops`/`position_ops`/`account_ops` 端口提供，游标只前进到已确认
  消费的 lastTransactionID；
- realized/unrealized/financing/fees；
- no-trade/reject 也必须进入日报；
- 提交超时/断连（unknown outcome）必须先用持久化的 clientExtensions.id
  查询 broker（`UnknownOutcomeResolver`）再决定重试；UNRESOLVED 即冻结后续
  提交（`SubmissionGate`），绝不猜测——M06-W06 起由
  `faults`/`unknown_outcome` 提供；每次请求的 scrubbed telemetry
  （method family、endpoint template、status、latency、attempts、error
  class、hash correlation；不含 token/完整 account ID/敏感 payload）记录
  在 `request_telemetry` 表；
- 受控最小风险 practice scenario（`PracticeScenarioRunner`）：正式产品路径
  intent → RiskGate → persisted decision → 幂等 identity → 自动 cleanup →
  最终 reconciliation evidence；缺凭证 → ENVIRONMENT_BLOCKED，cleanup 未决
  → FAIL，绝不 fake fill（M06-W07 起，T7 凭证到位后运行真实场景）。

### 6.5 End-of-Day Check

1. sync through latest transaction ID；
2. compare orders、transactions/fills、trades、positions、balance/NAV/margin；
3. verify all external orders map to local intents and decisions；
4. verify all approved intents resolve to broker/no-submit reason；
5. duplicate detector；
6. calculate exposure/P&L/drawdown in home currency；
7. close/deduplicate alerts or carry incident；
8. create daily backup/hash；
9. generate daily report/evidence manifest；
10. mark day QUALIFIED, QUALIFIED_NO_TRADE, PARTIAL, FAILED, or RESET_REQUIRED。

## 7. Valid No-Trade Days

以下可以是合格日：

- weekend/holiday/all candidates market closed；
- no instrument passes data/spread/liquidity filter；
- committee returns grounded no-trade；
- RiskGate rejects all proposals；
- execution frozen but research/reconciliation/report evidence complete；
- model/provider unavailable and policy correctly fails to no-trade。

必须记录原因、输入和 gate。空白记录或“今天没交易”一句话不合格。

## 8. Weekly Gates

### End of Days 7, 14, 21, 28

自动生成 weekly scorecard：

| Metric | Required interpretation |
|---|---|
| calendar records | 每天存在，不允许静默缺口 |
| active market cycles | 成功/no-trade/failed 分类 |
| duplicate client/intent/order | 必须 0 |
| order without approved persisted decision | 必须 0 |
| unmapped broker event | 必须 0 或同日 closed incident |
| transaction cursor gaps/regressions | 必须 0 |
| reconciliation differences | 不允许跨日 unresolved |
| stale quote/news cycles | 必须 no-trade/frozen，不得仍下单 |
| model schema/citation failures | 有界降级且无非法 intent |
| backup success | 每日 |
| alert acknowledgement/resolution | P0/P1 同日处置 |
| live/other broker network attempts | 必须 0 |
| discovered instrument coverage | 与账户 response 一致 |

### Required Drills

- Week 1：scheduler/process restart during non-submit phase；
- Week 2：restore latest backup to isolated directory；
- Week 3：simulated 429/5xx/network loss/model failure using approved fault injection，
  不直接破坏真实 account；
- Week 4：restart/reconcile with open/pending practice state if naturally present，或
  controlled minimal scenario。

Drill 不能留下未清理订单或持仓。

## 9. Incident Classification

### P0 - Immediate Safety Stop and Window Reset

- live endpoint/account attempt；
- Alpaca/other broker/production simulator execution；
- order without persisted approved RiskDecision；
- duplicate order caused by retry/restart；
- secret leakage；
- RiskGate reject but order submitted；
- uncontrolled/unmapped external order；
- corrupted unrecoverable audit evidence。

动作：kill/freeze new orders、保存脱敏证据、对账和降险、标记
`RESET_REQUIRED`、创建 repair item。不得自动 unfreeze。

### P1 - Critical Reliability, Usually Reset

- transaction gap/incorrect cursor；
- cross-day unexplained reconciliation diff；
- wrong side/quantity/price/order semantics；
- persistent state lost after restart；
- backup cannot restore；
- stale/non-tradeable quote still leads to submit；
- daily loss/margin/exposure rule calculation wrong。

### P2 - Significant but Evaluated

- one provider outage with correct no-trade degradation；
- alert delivery failure while local alert persists；
- UI/API projection stale but execution truth safe；
- report generation delay with all raw evidence intact。

P2 是否重置取决于是否影响 requirement evidence；决定和理由写 ledger。

### P3 - Non-Semantic

- copy/layout/visual defect；
- additive scrubbed logging；
- documentation clarification。

有完整 regression 时通常不重置，但仍记录 release hash change。

## 10. Change Control During Observation

- observation build 默认冻结；
- 任何 code/config/model template/policy change 先创建 work item；
- 运行 full relevant gates、controlled practice check、reconciliation；
- P0/P1 或 risk/execution/persistence/cycle semantics change 从下一完整日重计 30 天；
- dependency security update按影响评估，但不能以“只是依赖”自动免重置；
- 不在同一工作树混入未验证实验；
- 不 force/rewite main history；
- 每个新 build 有 immutable hash and incident/change reference。

## 11. Evidence Layout

最终 M15 controller 应生成 gitignored artifacts：

```text
.agent-artifacts/observation/<observation-id>/
  day-00/
  day-01/
    manifest.json
    preflight.json
    data-quality.json
    content-snapshot.json
    cycle-summary.json
    risk-summary.json
    broker-summary-redacted.json
    reconciliation.json
    portfolio.json
    alerts.json
    backup.json
    command-results.json
  weekly-01/
  incidents/
  final/
```

`manifest.json` 记录每个文件 SHA-256。原始敏感 response 不进入可共享 artifact；
需要保留的本地 evidence 必须加密/限制权限并使用 scrubbed manifest 公开索引。

## 12. Day 30 Final Gate

Day 30 end-of-day 后：

1. 停止新 cycle，允许 account sync/reconcile；
2. 关闭/保留自然持仓按预先 risk policy 执行，不为报告随意平仓；
3. 完整 transaction/order/trade/position/account reconciliation；
4. duplicate/unapproved/live/other-broker/static scans；
5. full local test/lint/type/acceptance/security；
6. fresh backup + isolated restore drill；
7. verify 30 daily manifests and weekly gates；
8. verify qualified window 没有 required reset；
9. 生成 evidence-derived final scorecard；
10. 进入 M17，不直接宣称 COMPLETE。

最低通过标准：

```text
30/30 daily records
0 duplicate external orders
0 external order without approved persisted RiskDecision
0 live or other-broker attempt
0 unexplained cross-day reconciliation difference
0 unresolved P0/P1
100% broker events mapped or explicitly resolved
100% completed cycles have data/content/decision/risk/recon/report chain
daily backups present and final restore successful
```

盈利、Sharpe 或交易次数不属于稳定性通过标准。

## 13. Stop/Resume Operations

优雅停止顺序：freeze new execution -> stop new cycles -> let in-flight uncertain submit
resolve -> transaction sync -> reconcile -> persist checkpoints -> backup -> release lease。

恢复顺序：acquire lease -> validate build/schema/config -> restore daily counters/cursor ->
account details/catalog -> sync changes -> full reconcile -> resolve uncertain submissions ->
health/preflight -> resume research -> explicit execution unfreeze if clean。

机器重启后不得只凭 scheduler heartbeat 自动开新仓。

### 13.1 Execution Freeze and Unfreeze Policy

execution freeze 由 `ExposureFreezeStore`（`oanda/freeze_policy`）持久化，六类 alarm
各产生一条 deduplicated 记录：blocking reconciliation diff、unresolved transaction
gap、stale remote snapshot、failed resync、corrupt projection、cursor failure。
同 (account, reason, detail) 重复告警幂等去重；restart 后 freeze 仍在。任一 active
freeze 存在时，所有 new-exposure submit 被 `FreezeActiveError` 阻断（研究/ingestion
不受影响）。

unfreeze 的唯一路径（M07-W05 起）要求全部证据同时满足：

1. fresh successful full sync；
2. 零 blocking diffs；
3. cursor 与本地一致；
4. projection hash 匹配；
5. alerts 全部解析；
6. 显式 reason。

全部通过后 freeze 转 UNFROZEN 并在 `exposure_unfreezes` 追加不可变 evidence
（完整 policy 快照 + reason + UTC 时间戳）。没有 clear/dismiss/confirm API，
任何路径都不能靠 omission 或确认提示解冻；不得自动 unfreeze。unfreeze 后同一
alarm 复发会生成新的 freeze 记录（detail digest + occurrence sequence），
绝不因主键冲突被静默吞掉。

### 13.2 Restart Recovery（M07-W06 起）

重启恢复由 `SubmitWorkflow` + `StartupSyncService`（`oanda/submit_recovery`）执行，
全部对 append-only order ledger 做 compare-and-set，同一 `(cycle_id, intent_id)`
在任何 crash 点重跑都不会产生第二个外部订单：

- **崩溃恢复**：reserve 前/后、send 前/后、response 后、fact commit 期间、
  cursor advance 期间、reconciliation 期间八个命名 fault point 任一崩溃后，
  以新进程同参数重跑即从确定性边界继续；100 次同 cycle 跨进程重放最多一个
  外部 submit identity 和一条可解释的 terminal ledger chain。
- **in-flight 解析**：SUBMITTED（结果未知）只按持久化 clientExtensions.id 查询
  broker（`UnknownOutcomeResolver`）——RESOLVED_ACCEPTED → 完成；
  NOT_SUBMITTED / UNRESOLVED / 查询失败 → ledger FROZEN + 新开仓 freeze，
  绝不盲重试；重启后 sync 会解析遗留 in-flight 并把
  `submit_id → broker_order_id` 映射恢复进进程 adapter（`completed_mappings`），
  绝不重复下单、绝不重消费 facts。
- **共享 durable reconcile**：API `POST /api/v1/broker/reconcile`、CLI
  `broker reconcile`（API 离线时）与 scheduler startup/cycle 调用同一
  `ReconciliationRunner`；缺 OANDA practice 凭证（null adapter）时记录显式
  non-matching 快照（`broker_not_configured`）并按 scope freeze——绝不产生
  无条件 all-match placeholder，也绝不询问如何恢复。
- **completed submit 后的 blocking diff**：只冻结新开仓（`blocking_diff`
  freeze，evidence_refs 指回 ledger submit），外部订单本身是不可变终态。

**M07-W07 T7 重启演练**（有 practice 凭证时）：受控场景提交最小风险订单 →
模拟进程重启（全新进程、同一 durable 文件）→ 解析同一外部订单与 transactions
→ cursor 推进 + projection 重建 → 与真实 account summary/positions/orders
typed 对账（必须 clean）→ cleanup 平仓 → 写脱敏 E5 evidence（仅 sha256
hashes，不含 token 与完整 account ID）。任一环节异常（gap、对账 diff、
cleanup UNRESOLVED）→ freeze 或 FAIL，不得继续观察。无凭证时保持
ENVIRONMENT_BLOCKED 且 `external_evidence_pending`，mock 输出不得冒充
practice evidence。

## 14. Zero-Intervention Boundaries

M15 必须交付一个由同一 scheduler leader 持有的持久 observation supervisor。Day 0
启动时它注册 start-of-day、daily gate、weekly drill 和 Day 30 gate，保存 `next_run_at`、
lease、attempt 和结果；进程重启后从数据库恢复，而不是依赖一个持续占用 coding-agent
turn 的 sleep。正式观察只允许在 supervisor restart/recovery test 通过后开始。

Coding agent 到达真实时间边界时写 `WAITING_EXTERNAL` 后退出当前 turn；supervisor 继续
生成 runtime evidence。支持 recurring wake 的宿主应按 `next_run_at` 自动再次调用
Prompt C/observation verifier；不支持自动唤醒的宿主被记录为 external orchestration
blocker，不能把人工补写或未来日期当作替代。一次初始启动之外，每日记录、周 gate、
重启恢复和 Day 30 close 都不得要求人工点击或确认。

无人值守 loop 完成所有确定性检查，不向 owner 提问。以下情况使用预定行为：

- OANDA practice secrets 不存在或失效：标记 `BLOCKED_EXTERNAL`，不尝试寻找或
  生成 secrets，继续所有独立工作；
- 账户暂停、合规限制或 OANDA service-side issue：保持 execution freeze，按退避
  定时重查，不请求人工选择；
- P0 safety event：自动创建修复 work item；只有修复门禁、受控 practice E2E、
  完整对账和连续三个 clean reconciliation 都通过后才按规则恢复，并重置观察窗；
- blueprint scope/safety policy change：拒绝执行并记录 out-of-scope；
- destructive recovery 或无法证明无数据损失：不执行破坏操作，记录 blocker。

Agent 不为以上事项或任何逐轮步骤提问。所有剩余依赖被阻塞时，输出机器可读 blocker
并停止；外部状态变化后的下一次启动按恢复协议继续。

## Structured Observability During Observation

M15-W01 起，观察期运行依赖 `alphabrief_core/observability.py` 的结构化可观测
契约：

- 11 个关键子系统（ingestion、news、models、scheduler、cycle、risk、oanda、
  reconciliation、backup、api、electron）各自发布 typed health/readiness/
  heartbeat/latency/success/failure/freshness 信号；缺失 truth 的组件为
  `unknown` 且 not ready，绝不假设 healthy。
- 日志与 metrics 通过 correlation ID 串联 cycle、evidence、model、intent、
  risk、order、transaction、reconciliation、alert、backup 十类记录。
- 所有可观测输出经 `redact_observable` 强制 scrub：token、authorization、
  完整 account ID、model-sensitive 内容、未许可新闻全文与可配置 secret
  pattern；完整 account ID 只以不可逆 sha256 前 12 hex 展示。

观察期日报与周门禁必须引用上述 health/readiness/heartbeat 信号作为证据，
缺失信号按 REQ-OBS-002 视为当日证据不完整。

## Error Taxonomy and Alerts During Observation

M15-W02 起，观察期运行按 `alphabrief_core/alerting.py` 处理失败：

- 8 类错误（auth/validation/broker_reject/rate_limit/transient/protocol/
  data_quality/safety）确定性映射为 retryable/severity/freeze_execution/
  no_trade/escalate；未知错误按 safety blocker fail-closed（不重试、冻结、
  no-trade、升级）。
- Alert 以 NDJSON 持久化（severity/dedupe_key/occurrence/count/ack/
  escalation/resolution/incident link/scrubbed evidence），重启恢复；同
  dedupe_key 重复事件只递增 count，绝不风暴。
- 外部 webhook/sink 失败零影响本地 alert（不删除、不 resolve）。

观察期周门禁须核对 unresolved alerts（REQ-OBS-005）并引用本契约的 alert
记录作为证据。

## External Request Budgets During Observation

M15-W03 起，所有外部请求按 `alphabrief_core/request_policy.py` 执行：

- 7 类请求族（OANDA REST/stream、market-data、content、model、alert、backup）各有 connect/read/total/cycle budget、有界 attempts、确定性 jitter backoff 与并发上限；
- OANDA submit outcome 为 unknown/timeout 时进入 query_and_reconcile，绝不blind retry；
- 超时任务以完整 scrubbed telemetry 分类，自包含隔离，不阻塞 heartbeat、reconciliation、backup、risk freeze 或无关调度工作。

## Preflight and Observation Controller

M15-W04 起，观察期由 `ObservationSupervisor` 驱动：

- 开始前必须通过 `oanda_observation` preflight（14 gate 单 schema；secret 只验证存在性，绝不披露值）；
- 每天按真实 UTC 日历推导 Day 0..30，自动调用 daily evidence gate；缺证据记录失败日，绝不伪造；
- practice E2E 只走正式 7 步路径（proposal→intent→persisted risk decision→submit→transaction→cleanup→reconciliation），任何直接/残留执行一律拒绝；
- 缺外部依赖记录 BLOCKED_EXTERNAL/WAITING_EXTERNAL（无证据、无提问）；
- supervisor 状态 NDJSON 持久化，重启自动恢复 next-run。

## Shutdown, Recovery, and Soak Drills

M15-W05 起，观察期运行按 `alphabrief_core/recovery.py` 演练：

- SIGTERM 按 8 步顺序（freeze→stop new cycle→resolve uncertain submit→sync→reconcile→checkpoint→backup→lease release）在 30s 预算内完成；
- 12 个 cycle/execution 边界任一崩溃确定性恢复或安全 frozen（无重复订单、无 cursor 回退、无丢失 risk 计数、无 partial state）；
- 有界 soak 演练校验 heartbeat、writer ownership、memory/descriptor budget、projection equality、reconciliation truth、backup integrity；
- `alphabrief operations recovery-drill --scenario all --compact` 与 `alphabrief operations soak --cycles 1000 --compact` 为可脚本化 runtime drill。

## Security Gates and Runbook Rehearsal

M15-W06 起，真实观察窗口开始前必须通过 7 项 security gates（dependency
integrity、supply-chain、secret scan、artifact scrub、network allowlist（仅
OANDA practice 两 host）、reference boundary、static rules），无 waiver；
prompt-injection fixtures 不得改变 system instructions/risk limits/broker
tools/provider routing/execution state/evidence citations；非生产彩排
（`alphabrief observation rehearse --all-drills --compact`）完成 8 步流程但
绝不计为真实观察日。

## Engineering Readiness Gate

M15-W07 通过 Engineering Readiness Gate：M01-M15 全部 DONE、tree clean、
frozen build practice-only；`alphabrief acceptance preflight --scope
oanda-observation --compact`、`acceptance practice-e2e --scenario
commissioning --compact`、`operations restore-drill --latest --isolated
--compact` 为可脚本化 runtime 命令。真实 practice E2E 与 T7 外部证据
pending（记录 blocker，绝不伪造）；真实 30 日观察待 M16 commissioning。

## Day 0 Commissioning (M16-W01)

- Day 0 manifest（`observation_id`、commit/tree hash、schema/config/dependency
  hash、provider profile、account hash、catalog version、timezone、start
  timestamp）只在 engineering readiness + full observation preflight +
  formal-path practice E2E + clean reconciliation + isolated restore 全部通过后
  冻结；任何缺失 → 全部 BLOCKED_EXTERNAL blocker，绝不 manufacture manifest。
- 合格时钟绝不从彩排或历史日期启动（`qualified_start_date`）；Day 0 为真实
  UTC 日历首日。
- `alphabrief observation start --runbook docs/oanda_30_day_runbook.md --compact`
  与 `alphabrief observation verify-day --day 0 --compact` 为可脚本化命令。
