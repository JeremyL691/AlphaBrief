# AlphaBrief 状态

> 这是全项目唯一的可变状态文件。规则见 [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md) 附录 C。
> 勾选任务时写明日期、提交哈希和证据摘要（命令加结果，不含密钥或完整账户 ID）。
> 决策记录、阻塞、需要用户做的事、试运行日志都只追加，不改写。

## 当前

| 字段 | 值 |
|---|---|
| 当前阶段 | **S5 常驻运行时** |
| 状态 | `IN_PROGRESS` |
| 下一项任务 | 接管整改：统一后台与单轮 CLI 的交易构建、阶段持久化与恢复；补齐账户级单实例、practice 主机白名单、HTTP 写路径，再完成 S5 余项和真实退出验证 |
| 下次巡检时间（UTC） | 不适用（尚未进入试运行） |
| 试运行 | 未开始；合格日 0 / 14；顺延 0；重置 0 |
| 最近更新 | 2026-10-01，用户授权新 Agent 接手完成整个项目；恢复开发，先修复接管审查发现的质量与安全缺口。14 天试运行尚未开始，历史记录保留，未验证的完成项撤回 |

可选状态：`READY | IN_PROGRESS | WAITING_OWNER_LOGIN | BLOCKED | SOAKING | RELEASED`

## 基线（2026-09-30 实测，文档重建后）

- 测试：`pytest -q` → **3255 passed / 41 failed / 29 errors**，共 70 个未通过，分两类：
  - **21 个是时间相关的老问题**：
    - `test_risk_currency_aggregation.py` 11 个
    - `test_risk_exposure_matrix.py` 8 个
    - `test_macro_api.py` 1 个
    - `test_macro_commands.py` 1 个
  - **49 个依赖已删除的旧文档**：
    - `test_autonomous_loop_state_machine.py` 12 个
    - `test_autonomous_loop_schemas.py` 10 个
    - `test_autonomous_loop_recovery.py` 7 个
    - `test_project_scaffold.py` 6 个
    - `test_autonomous_loop_meta_gate.py` 5 个
    - `test_acceptance_api_cli.py` 4 个
    - `test_autonomous_loop_scope_gate.py` 3 个
    - `test_acceptance_verifier.py` 2 个

    这些属于 S1 删除对象（`alphabrief-acceptance` 包及其测试），或需要改写（scaffold 测试）。
- `ruff check .` 通过；`mypy` 通过。
- OANDA 模拟账户：可连通；`lastTransactionID=3`；从未下单；余额 100000 USD；可交易品种 68 个，全部是外汇。
- 旧服务 `com.alphabrief.api`、`com.alphabrief.scheduler` **仍在运行**（`~/.alphabrief/`，旧代码快照，自 9/16 起对账冻结），S0 负责清场。
- 模型：`.env` 指向的 OpenCode Go 返回 `400 MissingSessionID`，且不允许作为产品后端；产品改用 ChatGPT 订阅登录（主）和可选的 OpenAI 兼容 key（备用）。
- GitHub：仓库公开；`gh` 已登录（scope 含 `repo`、`workflow`）；完整 git 历史中没有真实密钥。
- 本机：macOS 27 arm64；Amphetamine 持有防休眠断言。
- `FRED_API_KEY`、`ALPHAVANTAGE_API_KEY` 均为空。

## 阶段检查表

### S0 环境与清场
- [x] S0-1 停掉并卸载 `com.alphabrief.api`、`com.alphabrief.scheduler`，plist 移到 `~/.alphabrief-legacy-20260930/LaunchAgents/`
- [x] S0-2 `~/.alphabrief` 整体移到 `~/.alphabrief-legacy-20260930/`
- [x] S0-3 OANDA 只读探测（摘要、品种数、`lastTransactionID`）
- [x] S0-4 `gh auth status`、`git remote -v`、`pmset -g assertions`、磁盘空间
- [x] S0-5 工作区干净；`main` 领先 `origin/main` 1 个提交（推送规则见决策记录）
- [x] 退出标准：旧服务数为 0；无旧进程；OANDA 返回 200

#### S0 证据（2026-09-30 实测）

- S0-1：`launchctl bootout gui/$(id -u)/com.alphabrief.scheduler` 与 `.../com.alphabrief.api` 各返回 rc=0；`launchctl list | grep -i alphabrief` 无输出；`~/Library/LaunchAgents/` 中已无 `com.alphabrief.*`；两个 plist 位于 `~/.alphabrief-legacy-20260930/LaunchAgents/`。
- S0-2：`mv ~/.alphabrief ~/.alphabrief-legacy-20260930/alphabrief`；移动前 `du -sh` = 830M，移动前 `lsof +D` 无占用；移动后 `ls ~/.alphabrief` → `No such file or directory`。
- S0-3：用仓库现有代码（`OandaHttpClient`、`AccountOpsClient`、`fetch_instruments`）做只读探测，临时脚本放在 `/tmp`（未进仓库）：`GET /v3/accounts/{id}/summary` → HTTP 200；`GET /v3/accounts/{id}/instruments` → HTTP 200；`GET /v3/accounts/{id}/transactions?pageSize=5` → HTTP 200。结果：币种 USD，balance=NAV=100000.0000，unrealizedPL=0，marginUsed=0，订单/成交/持仓计数均为 0，`lastTransactionID=3`；可交易品种 68 个且全部为 `CURRENCY`；`XAU_USD`、`SPX500_USD`、`BCO_USD` 均不在可交易列表（与基线一致）；账户 ID 只以 `101-***-***-001` 形式出现。
- S0-4：`gh auth status` → 已登录 `JeremyL691`，scopes 为 `gist, read:org, repo, workflow`；`git remote -v` → `origin https://github.com/JeremyL691/AlphaBrief.git`（fetch/push）；`pmset -g assertions` → Amphetamine（pid 1375）持有 `PreventUserIdleSystemSleep` 与 `PreventUserIdleDisplaySleep`；`df -h` → `/System/Volumes/Data` 可用 79Gi。
- S0-5：`git status --porcelain` 无输出（工作区干净）；`git rev-list --left-right --count origin/main...main` → `0 1`，唯一的领先提交是 `72bea02`（文档重建，本地提交，尚未推送）。
- 退出标准：`launchctl list | grep -cE "com\.alphabrief\.(api|scheduler)"` → `0`；`pgrep -f "alphabrief (scheduler|serve)"` → 无输出；OANDA 探测 HTTP 200。

### S1 做减法与恢复全绿
- [x] S1-1 按 GUIDE 6.1 删除代码和对应测试；更新 `pyproject.toml`
- [x] S1-2 时间相关测试改为注入时钟（21 个，外加排查其他固定 `NOW` 的测试）
- [x] S1-3 改写 `test_project_scaffold.py` 以检查新的文档集合
- [x] S1-4 清理 Alpaca 和多资产残留；重写 `.env.example`
- [x] S1-5 `alphabrief_core.paths`（只接受绝对路径）
- [x] S1-6 `scripts/secret_scan.py`
- [x] S1-7 `.github/workflows/ci.yml`
- [x] 退出标准：ruff、mypy、`pytest -m "not practice"` 全绿；密钥扫描通过；记录删除前后的行数

#### S4 证据（进行中）

- 接管质量整改（2026-10-01，本提交）：修复 3 个数据库 fixture 的生成器返回类型、风控矩阵的真实 RiskDecision/Callable 类型、事件窗口测试中未使用的宽泛 kwargs；删除随正确类型变得无效的 ignore，保留所有用例和原断言。恢复 STATUS 的唯一状态格式，记录用户的新接管授权；S2 授权遗漏勾选纠正，S5 不符合当前代码的完成标记撤回。
  - 验证：`.venv/bin/mypy --no-incremental` → exit 0，446 个文件无错误；`.venv/bin/ruff check .` → exit 0；`.venv/bin/python -m pytest -q -m "not practice"`（允许本地回环端口）→ exit 0，2709 passed / 5 deselected；`.venv/bin/python scripts/secret_scan.py` → exit 0；`git diff --check` → exit 0。没有缩小验证范围或修改断言。
  - 当前缺口仍未宣称完成：后台工厂缺账户上下文/完整入场规则/风险仓位/模型预算/影子记录；提交后未落库中断的隔离复现产生两个意图；practice 主机校验及账户级互斥未落实；S3 指定的 vertical_slice practice 选择器没有测试；S4/S5 真实退出门禁待补验。OANDA 只读复核与历史首单证据一致（流水 4–11，空仓，NAV 99999.92 USD），未追加交易。

- S5 第三批（本提交）：**CLI-over-HTTP（5.3）**：后台在线时 CLI 不再直连数据库，只读走 HTTP。
  - 新增 `api_client.require_local_write(command)`：后台在线时，会直写数据库的命令立即以退出码 3 拒绝并说明原因（DuckDB 单进程独占文件，第二个写者会与常驻进程竞争）。已接入 `cycle run` / `cycle close` / `cycle close-due` / `broker reconcile` / `broker freeze` / `broker unfreeze` / `risk kill-switch` / `data sync-oanda`；后台不在线时照常本地执行（无旁路开关，安全不变量 12 不允许第二个写者）。
  - **修掉一个真实缺陷**：`is_api_running()` 原先在设置 `ALPHABRIEF_DATA_DIR` 时直接返回 False（本意是测试隔离），但生产 `.env` 也设这个变量，导致后台在线时 CLI 仍走本地连接并在 DuckDB 锁上抛 traceback。现在探测 `/health` 是唯一权威；测试改由 `tests/conftest.py` 的 autouse fixture 把 `ALPHABRIEF_API_URL` 指向 discard 端口，保证开发者本机跑着后台也不会改变测试行为。
  - **doctor 适配单进程约束**：DuckDB 只允许一个进程持有文件（连只读连接也会被写者挡住），所以后台在线时 doctor 从后台的 HTTP 端点取对账事实（`/api/v1/broker/status` → 真实快照与冻结列表），行情新鲜度与点差样本深度因尚无 HTTP 端点而如实记 WARN 并写明"dashboard endpoint pending"，模型通道的调用历史/预算同样如此；数据库文件不存在（全新安装）时三项检查给出"no data yet"而不是崩溃。四个 store（recon / quote samples / model call / market data）新增 `read_only=True` 连接支持（只读时不建表），供后台不在线时的只读路径使用。
  - 真实实测（本机 practice）：后台在线（`:8000`）时 `alphabrief cycle run` → `exit=3`、`error: the backend is running ... would race the daemon`；`alphabrief broker reconcile` → `exit=3` 同样拒绝；只读命令正常走 HTTP：`scheduler status` 返回真实 heartbeat/冻结计数、`broker account` 返回真实账户、`doctor run` → `5 PASS, 5 WARN, 0 FAIL`（对账经后台 HTTP 得到 `all_match=True`，锁报出持锁 pid）。停止后台后 `broker reconcile` 本地执行恢复 `clean/all_match=true`，锁回到空闲。
  - 测试：`tests/test_runtime_lock_and_doctor.py` 更新为"全新安装无数据库"的语义；新增 conftest 的 API 隔离 fixture。命令与结果：`pytest -q -m "not practice"` → 2709 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (237 source files)；`secret_scan` → OK。
  - S5 余下：LaunchAgent `ai.alphabrief.backend`（`service install|uninstall|status`）、macOS 通知、备份/恢复 CLI 命令、行情与点差样本的 HTTP 端点（S6 看板需要）、`kill -9` 重启实测（需 practice 环境）。

- S5 第二批（本提交）：**`alphabrief run` 单进程运行时 + 时钟时间表（5.1）**。
  - 新增 `alphabrief_core.schedule_plan`（纯函数）：5.1 的时钟表（决策轮 00:30/07:30/13:00、周五 19:00 全平、21:30 日报、22:00 备份）+ 补跑规则（**90 分钟内可补跑**；超过即 `missed_window`，"never run late"；周末决策轮记 `market_closed` 而日报/备份照常；已跑过的事件不再触发）。`cycle_key_for()` 给出"事件+UTC 日期"的幂等键。
  - 新增 CLI `alphabrief run run [--host --port --catch-up-minutes]`：一个进程里跑 **uvicorn（FastAPI）+ OperationsScheduler + 时钟规划器**；启动即取单实例锁（第二个进程退出码 2 且打印 `Could not set lock ... (held by pid N)`）；SIGINT/SIGTERM 优雅停止并释放锁；拒绝 live-trading 解锁。任务都带超时：对账 60s/60s、报价轮询 60s/60s、影子计分 900s/300s、日报 300s、备份 600s、周五全平 600s。阻塞工作走 `asyncio.to_thread`（对账、报价、计分、日报、备份、全平）。
  - **重启安全的"已跑过"判定来自持久化产物**（不是内存）：决策轮看 cycle store 里当天该轮 cycle key 的轮次、日报看当天报告文件、备份看当天 manifest；`scheduler_commands._ai_cycle_factory` 改为接受 `cycle_key` 并把键传给 `DailyTradingCycle.run(cycle_key=...)`（同一轮重跑返回已持久化记录，不重复跑委员会）；对账 runner 抽成模块级 `_reconcile_runner(store)`，`scheduler run` 与 `alphabrief run` 共用一份实现。
  - 任务实现：报价轮询把真实 bid/ask 写成规则 4 的样本；影子计分对到期的 4h/24h 决策用真实中间价与点差计分（无报价的品种跳过而不是编造价格）；日报与备份在进程内直接生成（复用 S4-4 的渲染与 `db/backup.py`）；周五全平走 `cycle close` 的同一条 reduce-only 风控链。
  - 真实实测（本机 practice，trading_mode=off）：`alphabrief run run --port 8123` → uvicorn 起在 8123、`/health` 返回 `{"status":"healthy","version":"0.0.0"}`、规划器记录三个真实错过的决策轮（"missed by 1240m/820m/490m (window 90m); never run late"）、报价轮询写入真实点差样本（累计 11 条，EUR_USD 0.00044 / GBP_USD 0.00132 / USD_JPY 0.086）、heartbeat 出现 reconcile/quote_poll/shadow_score 三行；第二个实例 `exit=2` 且明确报出持锁 pid；`kill -TERM` → `{"status": "stopped"}`，`lock_status()` 回到 None，无残留进程。
  - 测试：新增 `tests/test_runtime_schedule.py` 15 个（准点触发、补跑窗口内/外、90 分钟边界含端点、已跑过不再触发、周末只跑日报备份、周五全平仅周五、日报/备份每日、非法窗口拒绝、cycle key 按轮次与日期、规划器派发决策轮/日报/备份、错过不派发、停止事件结束循环）。命令与结果：`pytest -q -m "not practice"` → 2709 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (237 source files)；`secret_scan` → OK。
  - S5 余下：CLI-over-HTTP（后台不在线时只读）、LaunchAgent `ai.alphabrief.backend`（`service install|uninstall|status`）、备份/恢复的 CLI 命令、macOS 通知；S5 退出标准里的 `kill -9` 重启实测（`ALPHABRIEF_TEST_CRASH_AT=after_submit`，仅 practice）留待进入试运行前做。

- S5 第一批（本提交）：**单实例锁 + `alphabrief doctor` + 日报接入 doctor 摘要**。
  - 新增 `alphabrief_core.runtime_lock`：`RuntimeLock` 用 `flock(runtime.lock)` 实现单实例（第二个进程立即 `Could not set lock`，文件里记录 pid 与启动时间；进程退出/崩溃时内核自动释放，陈旧锁文件不会挡住重启），`lock_status()` 供 doctor 非阻塞探测持有者。
  - 新增 CLI `alphabrief doctor run [--expect-daemon] [--offline]`（GUIDE 4.9）：数据目录可写、单实例锁（`--expect-daemon` 时"无人运行"记 WARN）、最近对账快照与冻结状态、行情新鲜度（>6h 记 WARN）、规则 4 的同小时样本厚度、磁盘空间（<512MiB FAIL / <2GiB WARN）、防休眠断言（**只读 pmset，绝不修改系统设置**，开启睡眠记 WARN）、OANDA 只读连通（账户币种/可交易品种数/NAV）、模型通道（凭证 + 24h 调用记录 + 每日预算是否允许，**不发真实调用**以免消耗额度）、新闻源可用性（逐 feed 真实 HTTP 且校验 RSS/Atom 根元素）。输出 JSON + 一行摘要，仅 FAIL 时退出非零。
  - 真实实测（本机 practice）：`alphabrief doctor run` → `7 PASS, 3 WARN, 0 FAIL`：数据目录可写、锁空闲、对账 `all_match=True`（清理冻结后）、行情最新 2026-10-01T20:15Z、磁盘 36 GiB、OANDA 只读 PASS（USD、68 个可交易品种、NAV 99999.92）、新闻 6/6 feed 可达；WARN 为 quote_samples（4 个品种同小时样本不足，规则 4 因此失败闭合——真实状态）、sleep_assertion（本机睡眠未禁用，属用户控制项）、model_channel（额度窗口用尽，见阻塞）。
  - 日报接入：`alphabrief report daily` 现在嵌入 doctor 的离线摘要（`doctor: 5 PASS, 2 WARN, 0 FAIL; warn=[...] (offline checks; network checks skipped)`），不再写"要等 S5"。
  - 测试：新增 `tests/test_runtime_lock_and_doctor.py` 14 个（第二个进程立即被拒、持有者元数据、释放后可再取、缺文件视为空闲、数据目录可写、锁状态与 `--expect-daemon` 语义、磁盘/睡眠/行情/样本/对账各检查的判定与失败闭合、报告摘要与"仅 FAIL 不健康"、离线运行不含网络检查）。命令与结果：`pytest -q -m "not practice"` → 2694 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (235 source files)；`secret_scan` → OK。
  - S5 余下：单进程 FastAPI+调度器（`alphabrief run`，含报价轮询与影子 T+4h/24h 计分任务）、时间表与补跑、CLI-over-HTTP、LaunchAgent `ai.alphabrief.backend`、备份/恢复命令（复用 `apps/api` 的 `create_backup`/`verify_backup`/`restore_backup`/`apply_retention`）。

- S4-6（本提交）：**规则矩阵 + 补齐规则 1 冻结与规则 2 分类，并清理过期冻结**。
  - 补齐两处此前未被 gate 强制的规则半边：① **规则 1 的冻结**（`EntryRulePolicy.require_unfrozen`）——`AccountExposureContext.reconciliation_state`（clean/frozen/unknown，来自持久化对账状态），frozen 时拒绝新开仓（`FROZEN`），缺上下文失败闭合，平仓照常；② **规则 2 的品种分类**（`require_currency_type`）——`AccountExposureContext.symbol_types`（来自券商 instrument catalog 的 `raw_type`），非 `CURRENCY` 或未知即 `INSTRUMENT_NOT_ALLOWED`。CLI 的受审 policy 两项都开启，账户上下文提供者填入真实对账状态与真实品种分类。
  - 新增 `tests/test_risk_rule_matrix.py`（表驱动矩阵，29 个）：14 条规则每条都有"违规 → 期望拒绝码"与"健康上下文 → 放行"的用例（规则 1 三个子项 trading-off/kill-switch/frozen，规则 2 两个子项 分类/白名单，规则 3 两个子项 过期/不可交易，规则 7 两个子项 总量/单品种，规则 9 两个子项 单笔/总敞口），并单独钉住"平仓豁免除规则 1 kill switch 与规则 3 之外的全部入场规则"与"平仓仍需新鲜报价"；仓位矩阵覆盖 EUR_USD（本币报价，无换算）与 USD_JPY（JPY 报价，需换算 + 名义价值上限生效与不生效两种情形）。
  - **过期冻结清理（GUIDE 5.9 要求的人工调查）**：实测发现账户上仍挂着 3 个 2026-10-01 00:15–00:17 的 open freeze（原因串为 `position is not from this system` / `trade state mismatch` / NAV 与 margin 差异），它们是 S3 已修的三个缺陷（依赖单解析、`tradesClosed` 关联、投影重建）在当时造成的。调查证据：账户真实状态为 EUR_USD 持仓 0/0、唯一一笔交易 `CLOSED`、NAV 99999.92 与本地投影一致、修复后连续 3 次对账 `all_match=true`。按 5.9 由 Agent 执行 `alphabrief broker unfreeze <event_id> --reason "S4-2 investigation: ..."`（3 个事件全部清理，理由写入事件记录），随后 `alphabrief broker reconcile --scope cycle` → `clean: true, all_match: true, freeze_raised: false`，仅剩两条 INFO（保护单无 client identity）；风控上下文的对账状态已从 `frozen` 变为 `clean`。
  - 命令与结果：`pytest -q -m "not practice"` → 2680 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (233 source files)；`secret_scan` → OK。
  - S4-6 剩余：S4 退出标准里的"trading off 跑完 5 个品种 + 日报"需要模型额度（当前通道 `usage_limit_exceeded`，见阻塞）；日报本身已可用（S4-4 第三批）。S4 其余任务全部完成。

- S4-2 第八批（本提交）：**规则 4 点差（5.7）——14 条规则全部实现**。
  - 新增 `alphabrief_data.quote_samples`（数据层，自带 DDL）：`quote_spread_samples`（symbol/captured_at/bid/ask/spread/mid/source，按 `(symbol, captured_at)` 幂等），`recent_spreads(symbol, hour, limit=20)` 取**同一 UTC 小时**内最近 20 个样本（"同时段"的操作化定义：02:00 的点差不该拿伦敦开盘时段当基准），`QuoteSample` 校验 ask ≥ bid、spread ≥ 0。
  - 新增 `alphabrief_risk.spread_policy`（纯规则）：`median`（偶数取中间两值均值）、`evaluate_spread`——当前点差 > 2 × 同品种同时段最近样本中位数即 `SPREAD_WIDE`；**历史不足 `min_samples`（默认 5）或无样本时失败闭合**（没有基准可比较时不假设安全，理由串写明样本数）；用中位数而非均值，单个尖峰不会放宽所有人的容忍度。
  - 接入：`AccountExposureContext.current_spread/recent_spreads`（调用方读样本，gate 只应用规则）；`EntryRulePolicy.max_spread_median_multiplier/min_spread_samples`（未配置不启用），仅约束入场、平仓豁免；`OandaRiskContextSources` 新增 `live_spread`/`live_quote`；CLI 的账户上下文提供者在每次评估时把当前报价写入样本表（幂等）并读取同时段历史，受审 policy 设 2 倍/最少 5 个样本；`alphabrief data sync-oanda` 每次同步也记录样本（输出新增 `spread_samples_recorded`）。
  - 真实实测（practice 账户，真实报价）：`data sync-oanda --instrument EUR_USD --instrument USD_JPY` → 写入 2 个样本；再连续同步 6 次后，当前 UTC 小时内有 7 个真实 EUR_USD 样本（0.00016–0.00017，即 1.6–1.7 pips）。规则判定：真实点差 → 允许（"within 2 x the median 0.00017 of the last 7 samples"）；把点差放大 5 倍（0.00080）→ `SPREAD_WIDE` 拒绝；空历史 → `SPREAD_WIDE` 失败闭合。
  - 测试：新增 `tests/test_spread_rule.py` 21 个（中位数奇偶与空序列、恰好 2 倍放行、超过 2 倍拒绝、单个尖峰不抬高容忍度、样本不足/无样本失败闭合、参数校验、verdict 序列化、样本表幂等、同时段过滤、按品种与 limit 过滤、ask<bid 拒绝、非法小时拒绝、规则拒绝/放行/缺样本失败闭合/默认不启用/平仓豁免、gate 报 `SPREAD_WIDE`）。命令与结果：`pytest -q -m "not practice"` → 2651 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (233 source files)；`secret_scan` → OK。
  - 至此 GUIDE 5.7 的 14 条规则全部有实现与确定性测试；S4-2 可勾选。下一批 S4-6：把 14 条规则整理成显式的"通过+拒绝"矩阵测试（防止后续改动悄悄漏掉某条规则），并补 EUR_USD/USD_JPY 仓位测试的矩阵断言。

- S4-2 第七批（本提交）：**规则 11 回撤状态机（5.7）**。
  - 新增 `alphabrief_risk.drawdown_policy`（纯状态机 + DuckDB 持久化）：以**试运行期最高 NAV** 为基准，回撤 <3% 正常全仓；≥3% 立即禁止新开仓 48 小时，48 小时后自动恢复为**半仓**（风险 ×0.5）直到回撤回到 3% 以下；≥5% 直接 `soak_halted`，试运行剩余期间禁止新开仓且**不会**因 NAV 回升而解除（状态只会收紧）。高水位只升不降；平仓与对账不受影响。`DrawdownStateStore`（表 `ai_drawdown_state`，按账户单行）保证重启不会重置封禁。
  - 接入：`AccountExposureContext.drawdown_block_reason`（由调用方推进状态，gate 只读结论）；`EntryRulePolicy.block_on_drawdown`（未配置不启用），规则 11 只约束入场、缺上下文失败闭合、平仓豁免；`SizingInputs.risk_multiplier` 让半仓状态真实减半风险（`size_entry` 里 `risk_pct × multiplier`）。CLI 的账户上下文提供者与 sizing 提供者都用真实 NAV 推进并读取该状态（账户 ID 仅作状态键，不打印），受审 policy 设 `block_on_drawdown=True`。
  - 真实实测（practice 账户）：真实 NAV 99999.9200（S3 那笔交易后）→ 高水位以 NAV 播种，状态 `normal`、回撤 0.00%、倍数 1；对同一高水位做一次**未落库**的合成 −3.5% 评估 → `blocked`、48 小时封禁至 2026-10-03T20:35Z、拒绝码 `DRAWDOWN`（探针只打印不写入，随后以真实 NAV 复评仍为 `normal`，持久化状态与事实一致）。
  - 测试：新增 `tests/test_drawdown_state.py` 17 个（3% 边界封禁 48h、到期转半仓、回到 3% 以下清除、5% 熔断且粘滞、高水位只升、跨进程持久、未知账户无状态、规则拒绝/放行/缺上下文失败闭合/默认不启用/平仓豁免、半仓 sizing 精确减半与非法倍数拒绝）。命令与结果：`pytest -q -m "not practice"` → 2630 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (231 source files)；`secret_scan` → OK。

- S4-2 第六批（本提交）：**规则 6 事件窗口（5.7）**。
  - 规则放在 risk（`alphabrief_risk.event_window`，无 news 依赖，延续 `NewsMacroSource` 协议约定）：`HIGH_IMPACT_KEYWORDS`（CPI、consumer price、inflation report、NFP/nonfarm/non-farm、payrolls、FOMC、rate decision、interest rate decision、ECB、BoE、BoJ、RBA、BoC、SNB）、`KEYWORD_CURRENCIES`（FOMC→USD、ECB→EUR、BoE→GBP、BoJ→JPY、RBA→AUD、BoC→CAD、SNB→CHF）、`events_within_window`（窗口边界含端点，未来时间戳丢弃）、`window_reason_map`、`event_window_reason`。
  - 分类放在 news（`alphabrief_news.high_impact.high_impact_events`）：关键词命中标题或摘要；命名央行的关键词按货币定品种（即使条目本身无标签）；通用关键词（CPI/NFP/rate decision）用条目自带的货币标签；无标签的通用关键词对全部品种失败闭合（不假设无关）。GENERAL 条目不会因此被当成"无事件"。
  - 接入：`AccountExposureContext` 新增 `recent_high_impact_events: dict[symbol, reason]`，`EntryRulePolicy.event_window_minutes`（未配置则不启用）；规则 6 在入场规则里执行、**平仓照常豁免**；缺上下文时失败闭合（`EVENT_WINDOW`）。`OandaRiskContextSources.account_exposure_context` 透传该 map；CLI 的账户上下文提供者从**真实新闻库**取最近 30 分钟条目并用 news 分类（读新闻失败返回空 map 而不是编造事件），受审 policy 设 `event_window_minutes=30`。FRED 日历分支未启用（本机未配置 `FRED_API_KEY`），按规格走关键词分支。
  - 真实实测（practice 库里的真实新闻，37 条已入库）：24 小时内命中 6 条高影响新闻并分类正确——`boe/GBP`（BoE's Mann 谈加息）、`boj/JPY`×2（USD/JPY 与 BoJ 相关）、`nfp/MULTI`、`cpi/MULTI`×2；以最新高影响条目时间为"现在"评估时，恰好 1 条落在 30 分钟窗口内 → `GBP_USD` 被 `EVENT_WINDOW` 拦截（reason 含关键词、来源与时间）；按本机当前时刻评估为 0 条（最新高影响条目已 59 分钟前，属真实"无事件"状态而非漏判）。
  - 测试：新增 `tests/test_event_window.py` 18 个（关键词表覆盖、央行关键词货币映射、通用关键词用条目标签、无标签失败闭合、窗口边界含端点、未来时间戳丢弃、窗口参数校验、reason 含来源与时间、规则拒绝/放行/缺上下文失败闭合/默认不启用/它品种不误伤、gate 集成拒绝且平仓豁免）。命令与结果：`pytest -q -m "not practice"` → 2613 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (230 source files)；`secret_scan` → OK。

- S4-5（本提交）：**新闻来源家族、按货币打标签、去重与清洗**。
  - **来源标签修正**：`rss.py` 原先的 `reuters-rss` 键实际指向 Bloomberg URL（来源标签与实际发布方不符），Bloomberg 的 feed 现在也不再返回 RSS；两处误导性键已删除。feed 表改为 `FeedSource`（key / url / publisher / family / default_currency），`source` 一律取表里配置的**真实发布方**，不再用 feed 自己的 `<channel><title>`（可能写着别的媒体名）。六个 feed 均已用真实 HTTP 校验（2026-10-01，本机）：MarketWatch、FXStreet、ForexLive、Federal Reserve、European Central Bank、Bank of England，覆盖 6 个独立来源家族（规格要求 ≥3）。
  - **按货币相关性打标签**：新增 `alphabrief_news.currency_tags`，用确定性词典把标题+摘要映射到货币（USD/EUR/GBP/JPY/AUD/CAD）再映射到受交易品种；短代码按词边界匹配（`cad` 不会命中 "decade"、`aud` 不会命中 "fraud"），通用 "dollar" 仅在无其它货币命中时算 USD（避免把 "Australian dollar" 误标成 USD）。无信号的条目标 `GENERAL`（记录但不声称与任何品种相关），央行官方 feed 自带默认货币（Fed→USD、ECB→EUR、BoE→GBP），且文本信号优先于来源默认。调度器的旧行为（每条新闻 `symbols=list(universe)`）已删除。
  - **去重与清洗接入**：新增 `alphabrief_news.pipeline.prepare_headlines()`，一次确定性通过：`untrusted.py` 清洗（标记不可信、限长、中和指令式内容；检测到提示词注入的条目**不进入后续环节**，只保留 64 位内容哈希与中和计数）→ `ingestion.py` 记录溯源（`ingested_item_from_headline()`：规范化 URL、内容哈希、fetch outcome、metadata-only 保留策略，不落授权全文）→ `dedup.py` 聚类去重（URL 规范化、跟踪参数、内容哈希、标题相似度，同一批内折叠为一条）。调度器 `_ingest_ai_news` 改为走该管道，并把溯源记录写入 `news_ingestion_records`；被扣留的条目在 stderr 打印条数（只有哈希，不含正文）。
  - 真实实测：直接用真实网络跑六个 feed（加载 `.env` 后，本机时钟比 feed 时间戳慢约 6 小时，MarketWatch 的条目落在 `end` 之后被窗口过滤，属环境时钟偏差不是代码缺陷）→ FXStreet 17 条、ForexLive 24 条、Fed 5 条、ECB 7 条、BoE 3 条，货币标签分布真实（ECB 全为 `EUR_USD`、BoE 全为 `GBP_USD`、Fed 全为 USD 对）。真实入库：`_ingest_ai_news`（六 feed，24h 窗口）→ 入库 37 条，发布方 FXStreet 13 / ForexLive 21 / ECB 2 / BoE 1；标签分布 16 条 USD 对（USD 在全部五个品种里，属货币相关性而非"打全部品种"）、8 条 `GENERAL`、13 条窄标签（EUR_USD 5、GBP_USD 4、EUR+GBP 1、EUR+CAD 1、AUD 1、JPY 1）；`news_ingestion_records` 落 37 条溯源（`metadata_only=True`、64 位内容哈希、真实 correlation id）。
  - 测试：新增 `tests/test_news_source_families.py` 15 个（家族数量与发布方唯一性、误导键已删除、央行默认货币、货币标签窄化/USD 全对/双货币/无信号 GENERAL、通用 dollar 不抢别国货币、词边界防误命中、来源默认与文本信号优先级、provider 真实应用标签）、`tests/test_news_pipeline.py` 10 个（正常条目限长、注入条目只留哈希、摘要注入、URL/跟踪参数重复折叠、不同新闻保留、metadata-only 溯源、空批次、空来源拒绝、全文不落库）；`tests/test_news.py` 的 RSS/Atom 用例更新为"发布方来自白名单"与"ECB 默认欧元标签"；`tests/test_ai_trader_scheduler.py` 的预摄取用例扩展为 3 条抓取 → 1 条去重后入库 + 1 条注入扣留 + 溯源记录校验。
  - 本机 `.env`（未跟踪）的 `ALPHABRIEF_AI_NEWS_FEEDS` 原先仍列旧键（`reuters-rss,bloomberg-atom`），已改为六个真实 feed（备份在 /tmp）。
  - 命令与结果：`pytest -q -m "not practice"` → 2595 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (228 source files)；`secret_scan` → OK。
  - 遗留（转 S4-2 余项）：规则 6 事件窗口（高影响新闻关键词 30 分钟窗口）现在具备真实新闻输入与货币标签，可在下一批实现。

- S4-4 第三批（本提交）：**日报生成器（5.12）**。
  - 新增 `alphabrief_trader.daily_report`（纯渲染）：`DailyReportData`（全部字段来自存储查询）+ `render_markdown` + `to_payload` + `write_daily_report`，同时写出 `reports/daily/YYYY-MM-DD.md` 与 `.json`（写在数据目录，可用 `--out-dir` 覆盖）。段落：当日各轮决策、订单/成交/平仓、风控拒绝统计（按 tag 计数，已成交不计）、P&L/NAV/回撤、对账与冻结事件、模型调用（通道/失败数/token/估算成本）、数据新鲜度、影子评估增量、doctor 摘要。没有证据的段落写"no rows"/明确说明，不编造数字；doctor 段写明"要到 S5 实现 `alphabrief doctor` 才有"。
  - 新增 CLI `alphabrief report daily [--date YYYY-MM-DD] [--out-dir DIR]`：从 `AiTradingStore`（轮次与 attempt）、`ModelCallStore`（当日调用）、`ShadowStore`（当日决策与 scoreboard）、`BrokerReconStore`（快照与冻结事件）、`PaperStore`（日内起始/最新 NAV 与 HWM，凭证缺失或无快照时写明原因）、`MarketDataStore`（各品种最新 K 线与版本）汇总；账户 ID 只用于本地查询，从不打印。
  - 真实实测（practice 账户，2026-10-01）：`alphabrief report daily --date 2026-10-01` → 写出 `~/Library/Application Support/AlphaBrief/reports/daily/2026-10-01.md` 与 `.json`；内容为真实数据：16 轮（含 `executed` 1 轮、`blocked_risk_gate` 5 轮、`skipped_model_unavailable` 4 轮、`provider_error` 2 轮、`skipped_no_intent` 4 轮）、6 条 attempt（含真实 broker order 4）、风控拒绝统计 `DAILY_INTENT_CAP 5 / data_quality 2 / max_order_value 2 / max_total_exposure 2 / kill_switch 1`、当日对账快照 6 个（clean 3 / unclean 3，最后一次 all_match=true）、当日冻结事件 3 条（真实原因字符串）、模型调用 1 条、5 条影子决策、5 个品种的最新 K 线时间与 `data_version`。
  - 测试：新增 `tests/test_daily_report.py` 7 个（拒绝统计跳过已成交、执行结果统计、模型用量汇总、Markdown 含全部段落、空段落如实标注、payload 可 JSON 序列化、双文件写入）。命令与结果：`pytest -q -m "not practice"` → 2570 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (226 source files)；`secret_scan` → OK。 本批结束前另跑真实 practice 回归：`pytest -m practice tests/test_oanda_order_path_practice.py tests/test_live_reconciliation_practice.py tests/test_market_sync_practice.py` → 3 passed（下单序列化用真实 instrument 元数据、真实对账、真实 K 线入库），`tests/test_risk_oanda_practice_e2e.py` → 7 passed（含受控 practice 风控链）；模型通道的 practice 测试受额度阻塞未跑。
  - S4-4 完成；S4-4 遗留：影子评估的 T+4h/T+24h 自动计分任务（需要调度器，S5）、单次调用基准的真实模型调用（需要额度）。

- S4-4 第二批（本提交）：**影子评估（5.11）**。
  - 新增 `alphabrief_trader.shadow`（纯函数）：五个基准 `committee` / `single_call` / `momentum` / `random` / `no_trade`；`momentum_side` 用真实 20 日收益（不足 21 根收盘价则记 skipped，不猜方向）；`random_side` 种子 = `hash(cycle_id)`（同一轮可复现）；`committee_side` 读委员会 plan（target=0 或 side 非买卖即 flat）；`directional_return_pct` 用中间价计方向收益并扣除计分时点差（flat 恒为 0，点差大于波动时正确方向也会为负）；`summarize` 给出样本数、均值、胜率、95% bootstrap 置信区间，bootstrap 用样本内容的哈希做种子（同一份证据永远得到同一个区间），并强制带上"14 天样本不足以判断有效性"的 caveat。
  - 新增 `alphabrief_trader.shadow_store.ShadowStore`（DuckDB，自带 DDL）：`ai_shadow_decisions`（按 `(cycle_id, symbol, benchmark)` 幂等）、`ai_shadow_scores`（按 `(cycle_id, symbol, benchmark, horizon)` 只写一次）、`due_for_scoring(now)`（4h/24h 到期且未计分）、`stats` / `scoreboard`。
  - cycle 接入：`DailyTradingCycle` 新增 `shadow_recorder`；每轮每个品种记录 5 条，**模型通道不可用时也照常记录**（committee 记为 skipped + 原因，momentum/random/no_trade 仍用真实数据），影子序列不留空洞。`MarketSnapshot` 新增 `momentum_20d_pct`，CLI 的快照加载器用存储的 D 线真实计算 20 日收益。记录路径不可能下单。
  - 真实实测（practice 账户）：`data sync-oanda --instrument EUR_USD` → 成功；`cycle run --once --instrument EUR_USD --trading off` → 数据库 `ai_shadow_decisions` 落 5 条：committee=flat（`skipped: NO_TRADE_MODEL_UNAVAILABLE...`）、momentum=short（20 日收益 −1.7348%）、random=long（hash 种子）、no_trade=flat、single_call=skipped（需要预算内的单次调用）；`scoreboard()["4h"]` 五个基准 samples 均为 0（尚未到 4h，未计分——不编造分数）。
  - 测试：新增 `tests/test_shadow_evaluation.py` 17 个（20 日动量边界、随机可复现、委员会方向、五基准组成、点差扣减、flat 恒零、宽点差转负、bootstrap 确定性与区间包夹、空样本、存储幂等、到期判定、只计分一次、聚合含 caveat），`tests/test_ai_trader_daily_cycle.py` 新增 3 个（每品种 5 条、hold plan 记 flat、20 日收益驱动 momentum）。
  - 尚未做：单次调用基准的真实模型调用（需要额度，已记阻塞）；T+4h/T+24h 的自动计分任务（属于 S5 调度器，届时用 `due_for_scoring` + OANDA 中间价与点差写入 `ai_shadow_scores`）。

- S4-4 第一批（本提交）：**模型每日预算（5.13）**。
  - 新增 `alphabrief_models.model_budget`：`ModelBudgetPolicy`（`chatgpt_plan` 每日调用上限，默认 150；`openai_compatible` 每日成本上限，默认 $2.00）、`ModelBudgetGuard.admit(channel)` 按**已记录的真实调用**判定，`record_channel_unavailable()` 在收到 429/额度错误时把该通道禁用当天。理由码用规格原文 `NO_TRADE_MODEL_BUDGET` / `NO_TRADE_MODEL_UNAVAILABLE`。
  - 持久化在 `ModelCallStore`：新增 `daily_usage(since)`（按通道汇总调用数与估算成本）与 `model_channel_day_state` 表（`disabled_channel_reason` / `disable_channel`），跨进程、跨重启生效。
  - 委员会把失败分类为 `provider_unavailable:<code>`（rate_limit / budget_exhausted / usage_limit_exceeded / quota_exceeded / rate_limit_exceeded），其它失败仍是 `provider_call_failed`，既有消费者不受影响。
  - cycle 接入：新增 `skipped_model_budget` / `skipped_model_unavailable` 两个 `CycleOutcome`，summary 里带 `reasons=[...]`；预算判定优先于通用 provider_error，不会把"额度用尽"混成"模型故障"。CLI 的 `cycle run` 现在把 `ModelCallStore` 接到委员会的 `record_sink`（此前委员会调用根本不落库，预算和日报都会少算），并用 `config/alphabrief.yaml` 的 `model.daily_call_limit` / `model.daily_cost_limit_usd` 配置上限。
  - 真实实测（当前通道额度确实已用尽）：`alphabrief cycle run --once --trading off`（全 universe）→ 第 1 个品种 5 次真实调用全部 `usage_limit_exceeded`，被分类为 `provider_unavailable:usage_limit_exceeded` 并禁用当天；其余 4 个品种**一次调用都没发**，记录 `NO_TRADE_MODEL_UNAVAILABLE: chatgpt_plan is disabled for 2026-10-01: usage_limit_exceeded`（此前同类运行会烧掉 25 次调用）。随后单独再跑一次 `--instrument EUR_USD`：`outcome=skipped_model_unavailable`，落库调用数仍为 2（未新增），证明禁用状态跨进程持久。
  - 测试：新增 `tests/test_model_budget.py` 9 个（阈值边界、成本上限、无限制通道、按天禁用、策略参数校验、真实存储汇总只算当天、跨实例持久、真实记录触发上限），`tests/test_ai_trader_daily_cycle.py` 新增 3 个（预算用尽记 `skipped_model_budget` 且不发模型调用、通道禁用记 `skipped_model_unavailable`、无预算时行为不变）。命令与结果：`pytest -q -m "not practice"` → 2543 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (222 source files)；`secret_scan` → OK。
  - 本批未做（S4-4 余下）：5.11 影子评估（委员会/单次调用/动量/随机/不交易五个基准 + 4h/24h 计分 + bootstrap 置信区间）与 5.12 日报生成器。

- S4-3（本提交）：**决策持久化改用真实哈希**（PROJECT_GUIDE 5.7）。此前 `ExternalPaperExecutionBackend` 落库的 `policy_hash` 是常量 `DEFAULT_POLICY_VERSION` 的哈希、`snapshot_hash` 是 `captured_at` 时间戳，两者都不是"配置内容/快照内容"的哈希，配置改动后旧决策仍会被认为合法。现在：
  - 新增 `alphabrief_core.policy_version`：`policy_version_hash()` 对受审配置文件（`config/paper_execution_policy.yaml`、`config/alphabrief.yaml`）的真实字节按路径排序后逐条 `路径:sha256` 再哈希；文件缺失或为空时抛 `PolicyVersionError` 失败闭合，绝不悄悄少算一个文件。`policy_version_label()` 给出 `policy:<12 位>` 短标签。
  - `ExternalPaperExecutionBackend` 构造时算一次 policy 哈希；读不到配置时 submit 直接失败（不落占位值）。
  - 新增 `snapshot_content_hash(context)`：对真实券商快照（账户资金、持仓、挂单、交易、报价、换算、采集时间）做规范化 JSON 哈希，落库到决策记录的 `snapshot_hash`；时间戳不再是哈希。
  - 测试：新增 `tests/test_policy_version_hash.py` 7 个（哈希覆盖真实文件、内容变则哈希变、缺文件/空文件失败闭合、项目根发现、快照哈希随资金与采集时间变化、哈希不是时间戳），`tests/test_ai_trader_execution_backend.py` 新增 1 个端到端断言（落库记录的 `policy_hash` 等于真实配置哈希、`snapshot_hash` 为 64 位内容哈希）。命令与结果：`pytest -q -m "not practice"` → 2531 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (221 source files)；`secret_scan` → OK。
  - 当前真实哈希标签：`policy:e54ca5bfb209`（随配置内容变化）。

- S4-2 第五批（本提交）：**决策→意图（5.5）、风险仓位（5.6）与平仓走完整风控链**。
  - 新增 `alphabrief_trader.intents`：`intent_id = hash(cycle_id, instrument, action)`（`ai_` + 12 位十六进制，同一轮重跑得到同一个 ID），action 区分 `entry:*` 与 `close:*`；`close` 生成 reduce-only 意图（数量等于当前持仓的反向：多仓卖出、空仓买回）。cycle 与 durable cycle 都改用该确定性 ID，不再用随机 UUID。
  - 新增 `alphabrief_trader.sizing`（5.6）：`units = floor(NAV × 风险比例 / (止损距离 × 报价货币对本币换算因子))`，再按品种 `tradeUnitsPrecision`/`minimumTradeSize` 规整，结果 ≤0 即 `no_trade`；单笔名义价值上限 NAV 的 50%；试运行前 3 天风险减半（`soak_risk_pct`）。`SizingResult` 同时给出风险预算与实际风险（被名义价值上限截断后 `actual_risk = units × 每单位风险`），意图 rationale 里两者都写，避免审计时把预算当成真实风险。
  - 接入 cycle：`DailyTradingCycle` 新增 `sizing_provider`（按品种提供 NAV、换算因子、精度、最小下单量，全部来自券商真实数据）；已配置 sizing 但缺 ATR 或算不出数量时记 `skipped_no_intent`（`sizing_no_trade`，不产生 RiskDecision、不下单），绝不退回估算数量。`--units` 仍固定 S9 预跑尺寸。
  - **平仓豁免（5.7）**：`RiskGate` 对 `reduce_only`（或 `target_position_pct=0`）意图只检查规则 1 的 kill switch 与规则 3（报价新鲜且 `tradeable`）；`trading_enabled=False`、品种冻结、当日上限、周五/周末、敞口与单笔名义价值上限都不拦平仓。此前 `trading_enabled=False` 会连平仓一起拦（实现缺陷，已修）。
  - **平仓路径（5.5）**：`cycle close` / `cycle close-due` 不再直接调用 `OrderOpsClient`（原先完全绕过 RiskGate、不落 RiskDecision），改为走 `DailyTradingCycle.close_position`：意图 → RiskGate → 持久化 RiskDecision → OANDA，client order id 取自确定性意图 ID。
  - 敞口上限按阶段切换（见决策记录）：风险仓位路径用 5.6 的 NAV 比例（单笔 50%、总敞口 150%）；`--units` 固定尺寸预跑仍用受审 policy 的绝对值（2000/20000）。
  - 真实实测（practice 账户，NAV≈100k）：`alphabrief data sync-oanda` → 315 根 K 线 + 5 个报价、0 错误；`alphabrief cycle run --once --instrument EUR_USD --force-direction long --reason "S4-2 sizing evidence" --trading off` → ATR(H1)=0.00118357、stop 1.12882 / TP 1.13415、units=44224（被 50% NAV 名义价值上限截断）、risk_budget=250.00、actual_risk=78.72、notional=49999.65；gate 结论 `blocked_risk_gate`，真实拒绝标签 `data_quality / max_order_value / max_total_exposure / DAILY_INTENT_CAP`（轮次 aic_f2b393738913，意图 ai_13ee658d828e，决策 risk_39a1d1387ea94496bbfe593ac51745e3）。
  - 测试：新增 `tests/test_intents.py` 11 个、`tests/test_sizing.py` 14 个、`tests/test_cycle_sizing_and_close.py` 11 个、`tests/test_risk_gate_close_path.py` 7 个；`tests/test_entry_rules.py` 的平仓用例改为"只豁免到规则 3"；`tests/test_cycle_commands.py` 新增敞口上限制度 2 个。命令与结果：`pytest -q -m "not practice"` → 2523 passed / 5 deselected；`ruff check .` → All checks passed；`mypy` → Success (220 source files)；`scripts/secret_scan.py` → OK。
  - 待复验：模型通道当前返回 `usage_limit_exceeded`（ChatGPT 计划额度窗口用尽，见"阻塞"），NAV 比例上限改动的真实复验跑（`cycle run --once --instrument GBP_USD --force-direction long --trading off`）在额度恢复后补做。

- S4-2 第四批（本提交）：**委员会协议对齐 GUIDE 5.4**。发现并修正三处与规格不符的确定性规则：① `no_trade_below_confidence` 原为 0.45，规格要求 0.55（已收紧到 0.55）；② `risk` 角色的 `veto` 原先只置 `needs_human_review`，规格要求直接 `no_trade`（现已硬阻断新开仓，可用 `honour_risk_role_veto=False` 显式关闭）；③ 缺少"开仓方向至少 2 个分析角色支持"的规则（新增 `min_analysts_supporting_direction=2`，仅对 `buy`/`sell` 开仓生效，低置信度门槛优先）。测试新增 6 个（risk 否决阻断/可配置关闭/无否决放行；两个分析师放行、单个支持者不算授权、低置信度优先拦截）。命令与结果：`pytest -q -m "not practice"` → 2477 passed / 5 deselected；`ruff` → All checks passed；`mypy` → Success (414 files)；`secret_scan` → exit 0。

- S4-2 第三批（本提交）：**平仓触发条件**（PROJECT_GUIDE 5.10）新增 `alphabrief_trader.close_policy`（纯函数）：周五 19:00 UTC 起至整个周末必须平仓、持仓达到 48 小时必须平仓、开仓时间未知时失败闭合（不把无限期持仓带过周末缺口）。新增 `alphabrief cycle close-due`：只对**未平仓**交易判定（券商的 `state=ALL` 也返回已平仓交易，已过滤），`--trading off` 时只报告不下单。真实实测：`alphabrief cycle close-due --compact` → `{"due": [], "detail": "no position is due for close", "checked": 0}`（账户当前空仓）。测试 `tests/test_close_policy.py` 10 个（周五 18:59/19:00 边界、周六周日、48 小时边界、未知开仓时间、批量排序）。命令与结果：`pytest -q -m "not practice"` → 2471 passed / 5 deselected；`ruff` → All checks passed；`mypy` → Success (414 files)；`secret_scan` → exit 0。

- S4-2 第二批（本提交）：**结果未知处理接入真实提交路径**（PROJECT_GUIDE 5.8）。此前 `UnknownOutcomeResolver`/`UnknownOutcomeFailure` 只存在于 oanda 包内、没有任何运行时调用者，即"超时/断连绝不重发"实际上没有生效。现在 `ExternalPaperExecutionBackend.submit` 捕获 `UnknownOutcomeFailure` 并按持久化的 `clientExtensions.id` 查询券商：`RESOLVED_ACCEPTED` → 记为已接受（不再发送）、`RESOLVED_NOT_SUBMITTED` → 抛 `SUBMIT_NOT_ACCEPTED`（订单从未到达）、`UNRESOLVED` → 抛 `SUBMIT_UNKNOWN`（明确暴露，等待人工/后续处理）。测试 `tests/test_ai_trader_execution_backend.py` 新增 3 个用例（已接受且只提交一次、未提交与未决分别区分）。命令与结果：`pytest -q -m "not practice"` → 2461 passed / 5 deselected；`ruff` → All checks passed；`mypy` → Success (412 files)。

- S4-2 第一批（本提交）：
  - **补齐 6 条缺口风控规则**（新增 `alphabrief_risk.entry_rules`，纯函数 + 稳定拒绝码）：规则 3 报价新鲜/可交易（`QUOTE_STALE`/`NOT_TRADEABLE`）、规则 7 当日开仓上限（`DAILY_INTENT_CAP`，计数来自持久化的 attempt 历史 `AiTradingStore.count_daily_opens`，不是内存计数）、规则 8 最多同时持仓（`MAX_POSITIONS`，仅开仓、已持有同品种时允许加仓）、规则 12 连亏冻结品种（`LOSS_STREAK`）、规则 13 周五 13:00 UTC 后与周末只许平仓（`WEEKEND`）、规则 14 保护单与合法 units（`ORDER_INVALID`，多空方向与止损止盈相对位置都校验）。**平仓豁免**：`reduce_only` 或 `target_position_pct=0` 的意图不受任何入场规则约束（只有规则 1 的 kill switch 能拦平仓）。
  - **接入运行时**：`RiskGate` 新增 `entry_rules` 策略（未配置时保持旧行为）；cycle CLI 的 gate 现在带受审 policy（报价 15s、每日 5 笔/单品种 1 笔、最多 3 个持仓、周五与周末只平仓、必须有保护单），并在每次评估时传入真实账户上下文（新增 `OandaRiskContextSources.account_exposure_context`：真实 NAV/现金/持仓敞口按券商换算因子折算、报价时间与 tradeable、持仓数、当日开仓计数）。
  - **kill switch 持久化**：新增 `KillSwitchStore`（DuckDB，单行状态），新增 `alphabrief risk kill-switch --activate/--deactivate/--reason`；cycle 与 scheduler 的 gate 都从持久化状态加载，重启后仍然生效。真实实测：激活后 `cycle run --once --instrument EUR_USD --trading off --force-direction long` → `blocked_risk_gate`，拒绝原因含 `verify runtime blocks`（kill switch 理由）。
  - 真实 dry run：`alphabrief cycle run --once --trading off`（全 universe）→ 5 个品种各 5 个角色共 25 次真实模型调用、5 份 plan、`skipped_no_intent`（委员会全员 uncertain，属合法 no_trade）；`data sync-oanda`（全 universe）→ 1330 根 K 线 + 5 个报价、0 错误。
  - 测试：`tests/test_entry_rules.py` 29 个（每条规则通过+拒绝、平仓豁免、gate 集成）、`tests/test_kill_switch_store.py` 7 个（持久化跨进程、空白理由拒绝、激活拦所有单含平仓）。命令与结果：`pytest -q -m "not practice"` → 2458 passed / 5 deselected；`ruff` → All checks passed；`mypy` → Success (412 files)；`secret_scan` → exit 0。
  - 尚未完成（下一步）：规则 4 点差（需要最近 20 个报价样本，随 S5 报价轮询落库）、规则 6 事件窗口（需要 S4-5 新闻/宏观）、规则 11 回撤状态机（48 小时禁开/半仓，需要持久化窗口状态）、规则 2 的品种分类白名单（instrument_rules 已存在，待接入）、5.8 结果未知处理与 5.10 平仓触发条件（委员会平仓、48 小时最长持仓、周五 19:00 全平）。

#### S3 退出标准证据（2026-10-01，真实 practice 账户）

- 下单前账户：`lastTransactionID=3`，balance=NAV=100000.0000，marginUsed=0，持仓/交易/订单均为 0。
- `alphabrief data sync-oanda --instrument EUR_USD` → 332 根 K 线 + 1 报价入库；快照由真实 H1 K 线计算 ATR(14)=0.0011836，价格 1.1318。
- 委员会真实运行（5 个角色各一次真实模型调用）→ 全员 view=uncertain、manager 给出不持仓，cycle 记录 `skipped_no_intent`（这是合法结果，未凑单）。
- 按 GUIDE S3-5 的一次性例外执行：`alphabrief cycle run --once --instrument EUR_USD --units 1000 --trading on --force-direction long --reason "S3 vertical slice"` → `{"outcome": "executed", "attempt_count": 1, "attempts": [{"intent_id": "ai_e482fc8865b9", "risk_decision_id": "risk_0f29f0ff42d54440ab6e34bf7a631015", "approved": true, "outcome": "executed", "order_id": "4", "broker_order_id": "4", "filled": true}]}`（委员会原始输出照常落库，reason 写进 intent rationale）。
- OANDA 流水（`lastTransactionID` 3 → 11）：tx4 `MARKET_ORDER` EUR_USD +1000；tx5 `ORDER_FILL` 1000 @ 1.13173；tx6 `TAKE_PROFIT_ORDER` @ 1.13535；tx7 `STOP_LOSS_ORDER` @ 1.13002（止损止盈价由 ATR×1.5 / ×2.0 计算并随成交挂上，当时均 PENDING）；tx8 `MARKET_ORDER` EUR_USD −1000（`alphabrief cycle close --instrument EUR_USD`，order id 8）；tx9 `ORDER_FILL` −1000 @ 1.13165，pl −0.0800；tx10/tx11 `ORDER_CANCEL`（持仓平掉后保护单自动撤销）。最终 balance 99999.9200、NAV 99999.9200、持仓/交易/订单 0。
- 全链路可追溯：轮次 ID `aic_d22761752a0a` → 意图 `ai_e482fc8865b9` → 风控决策 `risk_0f29f0ff42d54440ab6e34bf7a631015` → OANDA 订单 4（`clientExtensions={id: ai_e482fc8865b9, tag: alphabrief, comment: 轮次}`）→ 成交 tx5 → 平仓 tx9。
- 对账：下单后与平仓后各跑一次 `alphabrief broker reconcile --scope cycle` → 均 `clean: true`、`freeze_raised: false`、`gap_count: 0`，剩余差异全部为 INFO（止损止盈挂单无 client identity、NAV/margin 为券商计算标记）。
- 过程中发现并修复 4 个真实缺陷：模型目录返回形状（`models[].slug`）、流解析重复文本、依赖单（止损/止盈）行没有 instrument/units 导致解析失败、平仓成交缺少 `tradesClosed` 关联导致投影认为持仓"非本系统"；另修投影重建的期初余额算法（原先用当前余额播种会重复计入历史盈亏）。新增回归测试覆盖依赖单解析、`tradesOpened/tradesClosed` 关联、平仓成交关仓投影。

#### S2 完成证据（2026-10-01）

- S2-5 用户完成授权后实测：`alphabrief model status --compact` → `{"primary": {"authorized": true, "inference_scope": true, "refresh_token_present": true, "expires_at": "2026-10-01T07:50:35Z", "scopes": ["chatgpt.tokens.use.direct","email","offline_access","openid","profile","resource.invoke"], "default_model": "gpt-6-astra", ...}}`；`alphabrief model test --compact` → `{"ok": true, "channel": "chatgpt_plan", "model": "gpt-6-astra", "text": "{\"ok\": true}", "parsed_ok": true, "parsed": {"ok": true}, "input_tokens": 18, "output_tokens": 9, "latency_ms": 2297}`，调用记录已落库（`ModelCallStore.list_calls` → 1 条，provider=chatgpt_plan、model=gpt-6-astra、status=succeeded、latency_ms=3270、tokens 18/9）。`pytest -m practice` → 5 passed（行情入库、下单序列化、对账、通道登录态、通道真实调用）。
- 真实响应与文档不一致处（按 GUIDE 8.6 以真实响应为准）：订阅通道的模型目录实际返回 `{"models": [{"slug", "visibility", "display_name", ...}]}`（`visibility` 取值 `list`/`hide`），而公开文档描述的是 OpenAI 风格的 `data[].id` + `visibility == "list"`。`fetch_model_slugs` 现在同时接受两种形状并仍按 `visibility == "list"` 过滤；实测该账号可见模型 5 个（gpt-6-astra、gpt-5.6-sol、gpt-5.6-terra、gpt-5.6-luna、gpt-5.5），逐个用文档化的 Responses 调用（`store=false`、`stream=true`）探测均返回 HTTP 200 且含 `response.completed`；默认模型取目录中第一个可见项 `gpt-6-astra`（可用 `config/alphabrief.yaml: model.primary_model` 覆盖）。
- 同时修掉一个真实流解析缺陷：真实流会同时发送 `response.output_text.delta` 与 `response.output_item.done`，旧实现把两者都拼接导致文本重复（`{"ok": true}{"ok": true}`），现已改为"优先 deltas，仅在无 deltas 时用完成项/完成响应的文本"，并补了回归测试。`model test` 现在把调用记录持久化到 `ModelCallStore`（此前只留在内存）。

#### S4-1 证据（进行中）

- S4-1 第二部分（本提交）：新增 `alphabrief_execution.broker.oanda.risk_sources.OandaRiskContextSources`，从真实 practice 端点取风控上下文所需事实：`/summary`（balance/NAV/marginUsed/marginAvailable/币种）、`/positions`（多空分开 + 均价）、`/orders?state=PENDING`、`/trades`、`/pricing`（bid/ask + 本币换算因子）、`/instruments`（目录版本）、对账状态改读持久化 recon store（frozen/clean/unknown，不再恒为 unknown）、健康状态由账户摘要探测；报价覆盖"配置品种 ∪ 当前持仓 ∪ 挂单品种"。`OandaPaperAdapter` 增加只读 `client` 访问器以便构造这些来源。接入已完成：`ExternalPaperExecutionBackend` 在适配器为 `OandaPaperAdapter` 时默认使用这些真实来源（并接收 `risk_symbols` 以覆盖配置品种；cycle CLI 传当前品种、scheduler 传配置 universe），其它适配器仍走端口组合；对账状态来自持久化 recon store，健康状态来自账户摘要探测。命令与结果：`pytest -q -m "not practice"` → 2418 passed / 5 deselected；`ruff` → All checks passed；`mypy` → Success (408 files)。

- S4-1 第一部分（本提交）：新增 `alphabrief_trader.data_quality`（版本化规则：报价必须为正、`data_version` 非空、`captured_at` 必须带时区且不晚于当前时间、年龄超过 2 小时判为过期；任何缺陷都失败闭合并给出稳定原因串），`DailyTradingCycle` 的三处风控调用不再写死 `data_quality_passed=True`，改为传入真实判定结果（过期/不完整输入会被 RiskGate 规则 5 拒绝并记录原因，绝不假定通过）。同时删除两处冗余的 `require_data_quality_passed=True`（`RiskLimitConfig` 的字段默认值本就是 True，策略只保留在一处）。命令与结果：`grep -rn "data_quality_passed=True" packages apps` → 无输出；`pytest -q -m "not practice"` → 2417 passed / 5 deselected；`ruff` → All checks passed；`mypy` → Success (407 files)；新增 `tests/test_data_quality.py` 7 个用例（新鲜通过、过期带年龄、临界值通过、未来时间失败、verdict JSON 安全、过期输入被风控拒绝且不下单、新鲜输入成交）。为保持既有用例语义，`tests/test_ai_trader_daily_cycle.py` 与 `tests/test_ai_trader_idempotency.py` 注入与快照时间一致的时钟（它们验证的是执行路径，不是新鲜度）。

#### 环境修复（2026-09-30，S3 期间）

- 本地 `.env`（未跟踪）里的 `ALPHABRIEF_DATA_DIR=data/local` 是相对路径，S1-5 之后 `alphabrief_core.paths` 按 GUIDE 4.3 对相对路径直接报错，导致所有 CLI 命令都会抛 traceback。已把该行改成绝对路径 `/Users/jeremyliu/Library/Application Support/AlphaBrief`（备份在 /tmp），并在 CLI 增加环境守卫：`--help` 不受影响，路径不合法时输出一行 `error: ... must be an absolute path` 并退出码 2（不再打印 traceback）。新增 `tests/test_cli_environment_guard.py` 4 个用例（相对路径退出码 2 且无 traceback、绝对路径可用、`--help` 可用、`ALPHABRIEF_HOME` 同样要求绝对路径）。命令与结果：`pytest -q -m "not practice"` → 2410 passed / 5 deselected；`ruff` → All checks passed；`mypy` → Success (405 files)。

#### S3 证据（进行中）

- S3-4/S3-5 命令面（本提交）：新增 `alphabrief cycle run --once --instrument --units --trading on|off [--force-direction long|short --reason TEXT]` 与 `alphabrief cycle close --instrument [--trading]`。`DailyTradingCycle` 新增三项安全机制：`trading_mode`（默认 off，off 时跑完委员会与风控后在下单前停下并记录 `blocked_trading_off` + `NO_TRADE_TRADING_OFF`）、`quantity_override`（首单固定 1000 units，覆盖仓位计算）、`direction_override`（垂直切片例外：必须带 reason，只改方向，委员会原始输出照常落库，reason 写进 intent rationale）。scheduler 的无人值守轮次改读 `ALPHABRIEF_TRADING_MODE`（默认 off）。CLI 拒绝不在受审universe内的品种、拒绝无 reason 的 `--force-direction`。测试 `tests/test_cycle_commands.py` 15 个：trading off 不下单、trading on 下单、固定 units 覆盖仓位、无覆盖时用委员会仓位、方向覆盖需 reason、方向覆盖只改方向且委员会输出不变、CLI 参数校验。命令与结果：`pytest -q -m "not practice"` → 2406 passed / 5 deselected；`mypy` → Success (404 files)；`ruff` → All checks passed；`secret_scan` → exit 0。真实下单与平仓仍待 S2-5 授权后执行（S3-4/S3-5 未勾选）。

- S3-3（本提交）：删除旧的 `broker/reconciliation.py`（它把"任何远端持仓、任何未登记订单"都当差异，一旦真成交就会冻结调度器），改为 `broker/oanda/live_reconciliation.py`：一次 pass = 取一次账户摘要 → 用 broker 报告的 account id 作为本地键的权威 → 从持久化游标拉 `transactions/sinceid` 并原子推进（`TransactionCursorStore`）→ 把可投影的流水折叠进账户投影（不可投影类型记录但不折叠）→ 用类型化的 `Reconciler` 比较 → 只有不可解释差异才冻结，快照照常落库。`clientExtensions.tag=alphabrief` 视为本系统订单（GUIDE 5.9），`RemoteOrder`/`OrderStateResult` 增加 `client_tag`；无本地投影的持仓只有在本地有同品种未平仓交易时才视为投影滞后（INFO），否则判为"非本系统持仓"（CRITICAL → 冻结）。scheduler / API `POST /broker/reconcile` / CLI `broker reconcile` 全部改用新实现（无凭证时记录显式 non-matching 快照并按 scope 冻结）。真实 practice 实测：`ALPHABRIEF_HOME=/tmp/ab-recon-check2 .venv/bin/alphabrief broker reconcile --scope cycle --compact` → `{"all_match": true, "clean": true, "cursor": "3", "diffs": [], "facts_applied": 0, "freeze_raised": false, "gap_count": 0, "scope": "cycle", ...}`（cursor 3 与 S0 探测到的 lastTransactionID=3 一致）。测试：`tests/test_reconciliation.py` 14 个（自有成交/止损/融资不冻结、外来持仓冻结、eod 只记录、游标与快照落库、无凭证按 scope 处理、冻结存储语义）、`tests/test_broker_reconciliation_matrix.py` 与 `tests/test_broker_api_live.py` 更新到新契约、practice `tests/test_live_reconciliation_practice.py` → 1 passed。命令与结果：`pytest -q -m "not practice"` → 2391 passed / 5 deselected；`mypy` → Success (403 files)；`ruff` → All checks passed；`secret_scan` → exit 0。

- S3-2（本提交）：下单路径改由 `order_ops.create_order` + `orders.serialize_order` 唯一实现 —— 带符号整数 units（买单正、卖单负，不再发送 v20 不存在的 `side` 字段）、`stopLossOnFill`/`takeProfitOnFill`（来自新增的 `SubmitRequest.stop_loss`/`take_profit`）、`clientExtensions` 带 `id`（幂等键）、`tag=alphabrief`、`comment=<轮次 ID>`；市价单固定 `FOK`，挂单必须显式给 GTC/IOC/FOK，不再把 `DAY` 悄悄改写成别的时效；品种精度与最小下单量取自账户自己的 instrument catalog（未知品种在下单前失败）。删除 `adapter.py` 的旧下单路径与三个失效辅助函数（`_SIDE_MAP`、`_decimal_to_oanda_units`、`_decimal_to_oanda_price`、`_submit_broker_order_id`）。命令与结果：`pytest -q -m "not practice"` → 2391 passed / 4 deselected；`mypy` → Success (402 files)；`ruff` → All checks passed；`secret_scan` → exit 0。确定性测试 `tests/test_oanda_adapter.py`（7 个）覆盖：payload 形状与幂等（同一 client id 只发一单）、卖单负数 units 且无 `side`、止损止盈挂单字段、未知品种失败闭合、挂单缺时效被拒。practice 测试 `tests/test_oanda_order_path_practice.py` 用真实账户的 instrument 元数据校验序列化（不提交订单：安全不变量 5 要求订单必须经过 决策 → RiskGate → 持久化 RiskDecision 链，该链在 S3-4 验证）→ 1 passed。

- S3-1（本提交）：新增 `alphabrief_execution.broker.oanda.market_sync`（K 线与报价同步：M15 96 / H1 120 / H4 60 / D 60 根完整 K 线，`source=oanda_practice`，按 `oanda-candles-v1:M:{granularity}` 分版本入库；报价取 bid/ask 中价并按批次 coverage 报告缺失与失败，不做替代）；新增 CLI `alphabrief data sync-oanda`（只读访问 practice，缺凭证即停并退出非零）。命令与结果（真实 practice 账户）：`alphabrief data sync-oanda --instrument EUR_USD --compact` → `{"bars_by_granularity": {"EUR_USD:M15": 95, "EUR_USD:H1": 119, "EUR_USD:H4": 59, "EUR_USD:D": 59}, "total_bars": 332, "quotes": 1, "errors": {}}`；数据库校验 `MarketDataStore.get_bar_count("EUR_USD")` → 271，`get_bar_models` 返回 4 个 data_version（M15/H1/H4/D），全部 `source=oanda_practice` 且时间带 UTC 时区。未完成的最新一根 K 线被排除（95/119/59/59 而非 96/120/60/60）。测试：`tests/test_market_sync.py`（8 个确定性用例：K 线转换、按品种/周期写入、单品种失败不中断、报价中价、缺失与失败按 coverage 报告、报告汇总）与 `tests/test_market_sync_practice.py`（`@pytest.mark.practice`，真实账户，1 passed）。

#### S2 证据（进行中）

- S2-1/S2-2（提交见下）：新增 `alphabrief_models.chatgpt_plan`（授权 URL 构造、PKCE S256、凭证记录与 0600 原子存储、Responses SSE 解析、错误码映射、模型目录发现、`ChatGptPlanAdapter`）与 `alphabrief_models.chatgpt_oauth`（回环回调服务、code 换 token、JWKS 校验 ID token、refresh、`login()`）；`alphabrief_core.jwt_verify` 用纯标准库实现 RS256/JWKS 校验。实现严格对齐官方文档（授权端点、token 端点、scope、`resource`、`store=false`/`stream=true`、只有 `response.completed` 才算成功），并已用线上 discovery 文档核对 `issuer`/`jwks_uri`/`grant_types`。新增 `openai_compatible` 适配器与 `model.fallback_enabled`（默认 false；只有显式开启才允许切通道，切换逐条记录），主机含 `opencode.ai` 直接报错拒绝。`config/alphabrief.yaml` 首次创建（`model.fallback_enabled: false`）。
- S2-3：`ModelGateway` 支持 opt-in 通道回退（每次尝试各写一条调用记录），调用记录新增 token 用量与 `类型:错误码` 形式的原因；API 与 scheduler 的委员会构建都传入持久化 sink（`ModelCallStore`）。`model test` 会落库并打印记录。
- S2-4：确定性测试 `tests/test_chatgpt_channel.py`（30 个：PKCE、授权 URL、SSE 解析、错误映射、适配器失败闭合、token 解析与 refresh、登录全流程含 state 校验/拒绝授权/client id 不匹配/缺少推理 scope）与 `tests/test_model_channels.py`（21 个：备用通道装载与 `opencode.ai` 拒绝、成本估算、显式切换策略、通道构建）。practice 测试 `tests/test_chatgpt_channel_practice.py`（`@pytest.mark.practice`，CI 用 `-m "not practice"` 排除）在登录前按预期失败（`not_configured`）。
- 命令与结果：`pytest -q -m "not practice"` → 2379 passed / 2 deselected；`mypy` → Success: no issues found in 398 source files；`ruff check .` → All checks passed；`python scripts/secret_scan.py` → exit 0。
- 模型工厂改造：`build_ai_trading_committee` 现在构建在真实通道上，产品不再读取 `OPENAI_API_KEY`/`OPENAI_BASE_URL`（那是用户的编程工具凭证）；`fake` 仅保留给显式测试选择。

#### S1 证据（已完成）

- S1-0（S0 完成提交回填）：S0 的检查表、证据与决策已随提交 `5b56d0e` 落库。
- S1-1（提交 `e58f444`）：
  - 删除：`alphabrief-acceptance`、`alphabrief-research` 两个整包；core 的 6 个观察期模块；8 个 CLI 命令组（`model` 组在 S2 重写）；5 个 API 路由与 `db/writer_lease`；`scheduler_leader`；models 的 kronos/router/registry/quality_gate/briefs/daily/evaluation/prompts/evaluation_datasets；data 的 3 个联网 provider；news 的 sec_edgar/social_sentiment（mock 移到 `tests/news_mock_provider.py`）；运行时的 PaperBroker 与 fills/portfolio/router；未挂载的 `dashboard/` 包；`scripts/deployment`、`notebooks`、`strategies`。
  - 改造：`DailyTradingCycle`/`DurableDailyCycle` 的 `broker` 参数改为必需的 `execution_backend`；scheduler、API `ai_trading`、`ai` CLI 一律走 `ExternalPaperExecutionBackend`（缺凭证即停，无内存兜底）；scheduler 默认品种改为 FX 五大货币对，删除 research_content 任务、Yahoo 行情摄取、observation JSON 导出；news/macro 只保留 `rss` 与 `fred`；`alphabrief_risk.context` 改用 `NewsMacroSource` 协议，摘要构建器迁到 `alphabrief_news.context_summary`。
  - 新增测试替身 `tests/_helpers/fake_execution_backend.py`（确定性假券商只存在于测试中）。
  - 命令与结果：`ruff check .` → All checks passed；`mypy` → Success: no issues found in 386 source files；`pytest -q -m "not practice"` → 2288 passed / 28 failed（当时剩余失败全部属于 S1-2 与 S1-3 的范围）。
  - 行数：`find packages apps -name '*.py' | xargs cat | wc -l` 73915 → 55005；`find tests -name '*.py' | xargs cat | wc -l` 64394 → 48912；`git ls-files | wc -l` 576 → 424。
- S1-2（提交 `2fea812`）：`test_risk_currency_aggregation.py`、`test_risk_exposure_matrix.py` 的 `_snapshot()` 传入 `clock=lambda: NOW`；`routes/macro.py` 与 `macro_commands.py` 增加可替换的 `_now()`；两个 macro 测试注入 `NOW` 并把 stale 样本时间改为由 `NOW` 推导；全仓库扫描后仅 `test_risk_execution_paths.py` 的假券商快照保留墙钟（默认 builder 的实时性语义，已写明原因）。命令与结果：`pytest -q -m "not practice"` → 2309 passed / 7 failed（仅剩 scaffold）；`mypy` → Success。
- S1-6（提交见 S1-7）：新建 `scripts/secret_scan.py`：扫描 git 已跟踪文件中的 OANDA token 形态（32+32 hex）、账户 ID 形态（`NNN-NNN-NNNNNNN-NNN`）、`sk-` key 与凭证名赋值，测试夹具的假值以显式白名单列出；本地存在 `.env` 时，只取凭证名变量（token/key/secret/password/account_id）的真实值并确认不出现在任何已跟踪文件中；`--history` 追加扫描完整 git 历史（S11 门禁用）。新增 `tests/test_secret_scan_tool.py` 覆盖各形态与红acted 输出。命令与结果：`python scripts/secret_scan.py` → exit 0；`python scripts/secret_scan.py --history` → exit 0（历史命中项逐条人工核对，全部为已删除测试/参考快照中的假值，如 `101-004-1234567-001`、`001-002-3456789-001`、`explicit-key`、`adanos_test_key`、`your_password`）。
- S1-7（本提交）：新建 `.github/workflows/ci.yml`（ubuntu-latest + Python 3.12）：`pip install -e '.[dev]'` → `ruff check .` → `mypy` → `pytest -q -m "not practice"` → `python scripts/secret_scan.py`；practice 测试按 GUIDE 第 7 节只在本机运行。YAML 已用 `yaml.safe_load` 校验，五个步骤与本地执行命令一致。
- S1 退出标准（本提交实测）：
  - `ruff check .` → All checks passed
  - `mypy` → Success: no issues found in 389 source files
  - `pytest -q -m "not practice"` → 2330 passed / 0 failed
  - `python scripts/secret_scan.py` → exit 0
  - `grep -rn -i "alpaca" packages apps tests config .env.example` → 5 处，全部是"禁止 Alpaca/其他券商"的约束与负例（`broker/safety.py` 禁止导入段、两条 provider 拒绝用例、electron 安全断言）
  - 行数：`find packages apps -name '*.py' | xargs cat | wc -l` 73915 → 54767；tests 64394 → 49049；`git ls-files` 576 → 428
- S1-5：新建唯一路径模块 `alphabrief_core.paths`（`ALPHABRIEF_HOME` 优先、`ALPHABRIEF_DATA_DIR` 作为开发别名，二者都必须是绝对路径，相对路径抛 `PathConfigError`；默认 `~/Library/Application Support/AlphaBrief`；提供 `data_dir/db_path/secrets_dir/logs_dir/reports_dir/daily_reports_dir/backups_dir/cache_dir/runtime_lock_path`）。删除全部本地路径实现（原 16 个 `_default_db_path`/`_db_dir`/`_db_path` 定义与 `_DEFAULT_DB_DIR` 常量），并把 8 处直接读 `ALPHABRIEF_DATA_DIR` 的入口（scheduler/strategy/review/ai CLI、broker runtime、practice_scenarios、api_client、routes/scheduler、routes/broker）统一接到该模块。数据库文件名统一为 `alphabrief.duckdb`（GUIDE 4.3/附录 B），删除第二套数据目录权威 `ALPHABRIEF_AI_DB_DIR`。新增 `tests/test_paths.py`（默认目录、两个变量优先级、相对路径拒绝、目录布局、各 store 共用同一 resolver）。命令与结果：`pytest -q -m "not practice"` → 2320 passed / 0 failed；`mypy` → Success: no issues found in 388 source files；`ruff check .` → All checks passed。
- S1-4：`.env.example` 重写为附录 A 的变量集合（删除 `ALPHABRIEF_LIVE_TRADING_ENABLED`、`ALPHAVANTAGE_API_KEY`、`OPENAI_*` 与过时的 `ALPHABRIEF_AI_*`）；删除已经不再门控任何行为的 `is_ai_external_paper_enabled`；`config/paper_execution_policy.yaml` 的品种收窄为五个 FX 主要货币对、`market: fx`；清理 `port.py`、`routes/broker.py` 与相关测试里的 Alpaca 注释。`grep -rn -i "alpaca" packages apps tests config .env.example` 只剩 6 处，全部是"禁止 Alpaca/其他券商"的约束测试与安全门（`broker/safety.py` 的禁用导入段、两条 provider 拒绝用例、electron 安全断言）。命令与结果：`pytest -q -m "not practice"` → 2312 passed / 0 failed；`mypy` → Success；`ruff check .` → All checks passed。
- S1-3：重写 `tests/test_project_scaffold.py`，检查 `AGENTS.md`、`docs/PROJECT_GUIDE.md`、`docs/STATUS.md`、`docs/AGENT_PROMPT.md` 存在，`docs/` 只有这四个（含 `images`），已删除的旧文档与旧目录确实不存在，STATUS 只有一个当前阶段与状态，markdown 本地链接可解析。命令与结果：`pytest -q -m "not practice"` → 2315 passed / 0 failed；`mypy` → Success: no issues found in 386 source files；`ruff check .` → All checks passed。

### S2 模型通道
- [x] S2-1 `chatgpt_plan` 适配器与 OAuth（`alphabrief model login|status|logout|test`）
- [x] S2-2 `openai_compatible` 备用适配器、拒绝 `opencode.ai`、`fallback_enabled` 开关
- [x] S2-3 完整的调用记录；委员会构建时传入记录器
- [x] S2-4 确定性测试，加一个 practice 测试（practice 待登录后通过）
- [x] S2-5 用户完成 ChatGPT 授权（2026-10-01，见 S2 完成证据；此项纠正遗漏勾选，通道当前可用性仍需复验）
- [x] 退出标准：`model status` 主通道已授权；`model test --json` 真实通过并落库（2026-10-01 实测）

### S3 打通一单
- [x] S3-1 OANDA K 线和报价入库
- [x] S3-2 `order_ops` + `orders` 下单（止损止盈、带符号整数 units、clientExtensions）；删除旧下单路径
- [x] S3-3 流水游标与新对账逻辑
- [x] S3-4 `alphabrief cycle run --once --instrument EUR_USD --units 1000 --trading on`（真实下单完成，见下）
- [x] S3-5 平仓与对账（真实平仓与对账完成，见下）
- [x] 退出标准：`lastTransactionID` 3→11 并有 `ORDER_FILL` 与止损止盈单；全链路可追溯；对账干净（2026-10-01 实测）

### S4 风控与决策补全
- [x] S4-1 真实风控上下文：写死的 `data_quality_passed=True` 已删除；执行后端默认改用真实 OANDA 风控来源
- [x] S4-2 委员会协议、意图、仓位、14 条规则、结果未知处理、平仓、kill switch（2026-10-01 完成：5.4 委员会协议、5.5 意图、5.6 仓位、5.7 全部 14 条规则、5.8 结果未知、5.10 平仓触发与平仓路径、kill switch 持久化；证据见下方 S4-2 八批记录）
- [x] S4-3 真实的策略版本哈希和输入哈希（2026-10-01，本提交：配置内容哈希 + 券商快照内容哈希）
- [x] S4-4 影子评估、日报、预算（2026-10-01，本提交：5.11 影子评估、5.12 日报、5.13 预算；遗留 T+4h/24h 自动计分待 S5 调度器）
- [x] S4-5 新闻：3 个以上来源家族、按货币打标签、入库、去重、清洗（2026-10-01，本提交：6 个家族、货币标签、pipeline 去重清洗 + 真实 37 条入库溯源）
- [x] S4-6 每条规则都有通过和拒绝测试；EUR_USD 和 USD_JPY 的仓位测试（2026-10-01，本提交：表驱动矩阵 29 个，含 14 条规则的通过/拒绝与两个品种的仓位矩阵）
- [ ] 退出标准：`cycle run --once --trading off` 跑完 5 个品种，日报生成；不再有写死的 `data_quality_passed=True`

### S5 常驻运行时
- [ ] S5-0 账户级单实例锁与 `alphabrief doctor`（数据目录级锁已实现；同账户跨目录互斥未实现，2026-10-01 接管复核撤回完成标记）
- [ ] S5-1 `alphabrief run`（现有后台未接完整风控/预算/仓位；决策轮同步阻塞事件循环，2026-10-01 接管复核撤回完成标记）
- [ ] S5-2 时钟表、补跑窗口与阶段持久化（时钟表已实现；后台实际用普通 DailyTradingCycle，提交后中断重跑能产生新意图，待修复和真实重启验证）
- [ ] S5-3 CLI 走 HTTP；后台不在线时只读（只读 HTTP 已有；写操作只是在线拒绝、离线直写，待实现计划规定的路径）
- [ ] S5-4 `alphabrief service install|uninstall|status`
- [ ] S5-5 macOS 通知（doctor 已完成，见 S5-0）
- [ ] S5-6 备份和恢复（复用 `db/backup.py`）
- [ ] 退出标准：第二个实例被拒；`kill -9` 重启实测没有重复订单；没有锁冲突；`doctor` 通过

### S6 前端重写
- [ ] S6-1 静态看板与 API
- [ ] S6-2 引导页（凭证、ChatGPT 登录、后台服务）
- [ ] S6-3 删除 `routes/dashboard.py`
- [ ] S6-4 Playwright 冒烟测试和 axe 可访问性检查
- [ ] 退出标准：冒烟全绿；生成截图；NAV 与 OANDA 一致；没有任何样例数据

### S7 保留模块接入真实数据
- [ ] S7-1 回测（OANDA K 线，跑基准和策略）
- [ ] S7-2 策略注册表（信号作为委员会证据）
- [ ] S7-3 gym demo
- [ ] S7-4 复盘页
- [ ] 退出标准：见 GUIDE S7

### S8 打包
- [ ] S8-1 `scripts/build_release.sh`（PyInstaller + electron-builder + `SHA256SUMS`）
- [ ] S8-2 改造 Electron（不依赖源码目录、托盘、服务管理、图标）
- [ ] S8-3 冒烟测试（临时数据目录、`trading_mode=off`、不装 LaunchAgent）
- [ ] S8-4 版本号 `1.0.0-rc.N`
- [ ] 退出标准：dmg 和校验和生成；冒烟通过；`--version` 正确

### S9 试运行前门禁
- [ ] S9-1 RC 后台以固定 1000 units 连续运行 24 小时
- [ ] S9-2 门禁清单全部勾选（见 GUIDE S9）
- [ ] 退出标准：打 tag `v1.0.0-rc.N` 并推送；写入 Day 0

### S10 14 天试运行
- [ ] 合格日 14 / 14（由 `alphabrief soak status` 计算）
- [ ] 没有未解决的冻结或阻塞

### S11 发布
- [ ] S11-1 试运行报告
- [ ] S11-2 发布代码与最后一个 RC 的运行时代码一致
- [ ] S11-3 版本 1.0.0、CHANGELOG、README（英文 + 中文节，含截图）
- [ ] S11-4 正式 dmg 构建与冒烟
- [ ] S11-5 完整历史密钥扫描、CI 全绿
- [ ] S11-6 tag、push、`gh release create`
- [ ] S11-7 状态 → `RELEASED`，附 Release 链接

## 需要用户做的事

- 2026-10-01 接管补充：下方历史登录要求已由 S2 完成证据满足，目前不要求重复授权；只有当前凭证被真实判定失效时才重新请求。用户本次授权已恢复开发。

- **（现在需要，只此一次）** 在项目目录下运行 `.venv/bin/alphabrief model login`，浏览器会自动打开 OpenAI 授权页，点一次同意即可。完成后把终端输出贴给我，或直接让我继续（我会用 `alphabrief model status` 自查）。若浏览器没有自动打开，终端会打印授权 URL，手动打开同样可以。
- （长期）试运行期间保持 Mac 接电源、不休眠（目前由 Amphetamine 保证）。
- （可选）如果想启用备用模型通道：提供一个按量付费的 OpenAI 兼容 key（例如 DeepSeek 官方），写入 `.env` 的 `ALPHABRIEF_LLM_BASE_URL`、`ALPHABRIEF_LLM_API_KEY`、`ALPHABRIEF_LLM_MODEL`，并在配置中开启 `model.fallback_enabled`。
- （可选）申请免费的 `FRED_API_KEY` 以启用宏观日历；没有也能运行（会用新闻冲击过滤代替）。

## 决策记录

| 日期 | 问题 | 选择 | 理由 |
|---|---|---|---|
| 2026-10-01 | 接管后是否沿用历史完成勾选 | 当前代码与真实检查优先；撤回 S5 不成立的勾选，先恢复完整质量门禁，再修复交易运行时集成 | 用户要求按项目验收接手完成；审查复现表明阶段持久化、完整风控接线、HTTP 写路径和安全边界尚不满足规格，不能以旧记录替代当前证据 |
| 2026-09-30 | 上架形态 | GitHub 开源发布 + 未签名的 arm64 `.dmg` | 用户决定；不上 App Store，签名流程留开关 |
| 2026-09-30 | 发布权限 | 允许 Agent 在 S11 自动 push 并创建 Release；S9 起允许推送 `main` 和 RC tag | 用户决定 |
| 2026-09-30 | 交易品种 | 只交易外汇（账户实测只开放外汇）；`XAU_USD`、`SPX500_USD`、`BCO_USD` 作为只读信号 | 用户决定 |
| 2026-09-30 | 试运行 | 14 个自然日，全自主运行 | 用户决定 |
| 2026-09-30 | 保留模块 | 回测、策略注册表、gym、复盘全部保留并接上真实数据 | 用户决定 |
| 2026-09-30 | 模型通道 | 主通道 ChatGPT 订阅登录（OpenAI 官方 SIWC 开源方案）；备用通道为可选的 OpenAI 兼容 key；OpenCode Go 不进产品 | 用户决定；OpenCode Go 返回 400，且其文档只允许编程 Agent 流量 |
| 2026-09-30 | 模型预算 | 备用通道每天 $2；订阅通道每天最多 150 次调用 | 用户决定 $2/天；调用上限为默认值 |
| 2026-09-30 | 文档 | 删除旧蓝图和 `docs/` 下 7 个流程文件，由 PROJECT_GUIDE、STATUS、AGENT_PROMPT 取代 | 旧文档描述的是从未产生的证据，且彼此矛盾 |
| 2026-09-30 | 语言 | README 英文（发布时附中文节）；GUIDE、STATUS、AGENT_PROMPT、AGENTS 用中文；界面中英切换 | 求职展示与自用兼顾 |
| 2026-09-30 | S0-5 本地 `main` 领先 `origin/main` 一个提交（`72bea02` 文档重建） | 不在 S0 推送，等 S9 首次推送 | 推送规则只从 S9 起授权（AGENTS"Git 规则"、GUIDE 8.1），S0 不在授权范围内；提前推送没有收益 |
| 2026-10-01 | 风险仓位下单的名义价值上限用哪一套 | 按阶段切换：风险仓位路径（无 `--units`）用 GUIDE 5.6 的 NAV 比例（单笔 50%、总敞口 150%）；`--units` 固定尺寸预跑仍用受审 policy 的绝对值（2000/20000） | GUIDE 5.6 明确规定比例上限，受审 policy 的绝对值是为 S9 固定 1000 units 预跑定的；两套并存会互相矛盾（0.25% 风险的仓位名义价值约 50000，必然撞上 2000 的绝对上限，系统将永远无法按规格开仓）。比例上限同时受单笔风险预算（0.25% NAV）与止损约束，实际风险仍在 250 USD 量级 |
| 2026-09-30 | S0-3 探测脚本放哪里 | 临时脚本放 `/tmp/alphabrief_s0_probe.py`，不进仓库 | 避免为一次性检查新增代码；同类检查在 S5 由 `alphabrief doctor` 正式实现并测试 |

## 阻塞

- 2026-10-01：模型通道返回 `usage_limit_exceeded`（`alphabrief model test` → `ChatGptPlanError:usage_limit_exceeded`）。ChatGPT 计划的本窗口调用额度已用尽（本轮为取 S4-2/S4-3 真实证据跑了多次 5 角色委员会）。S4-4 的每日预算（5.13）已上线并实测：额度错误被分类为 `provider_unavailable:usage_limit_exceeded`，该通道当天被禁用，后续轮次记录 `NO_TRADE_MODEL_UNAVAILABLE` 而不再调用。额度按窗口自动恢复，不需要用户操作；恢复前所有需要委员会的验证（S4-2 余项真实复验、S4-4 影子评估的单次调用基准、S4-6 全 universe 退出标准）暂停，先做不依赖模型的工作（S4-5 新闻、S5 运行时）。额度长期不足时改用"需要用户做的事"里的备用付费通道。

## 试运行日志

| 日期（UTC） | 合格 | 订单 / 成交 | 当日盈亏 | NAV | 异常与处理 | 版本 |
|---|---|---|---|---|---|---|
