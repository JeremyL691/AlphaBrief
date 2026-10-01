# AlphaBrief 项目指导文件（v1.0 重构）

> 本文件是 AlphaBrief 唯一的产品与构建权威。它回答三件事：项目最终应该是什么样子、从哪里开始、怎么一步步构建到可以发布。
> 可变状态只写在 [`docs/STATUS.md`](STATUS.md)；Agent 行为契约见 [`AGENTS.md`](../AGENTS.md)；交给 Agent 的提示词见 [`docs/AGENT_PROMPT.md`](AGENT_PROMPT.md)。
> 编写日期：2026-09-30。本文件中的所有"现状"均为当天实测结果，不是推测。

---

## 0. 怎么使用这份文件

### 0.1 给 Agent 的工作循环

每次启动（包括中断后恢复）都按以下顺序：

1. 读 `AGENTS.md` → 本文件 → `docs/STATUS.md`。
2. 在 STATUS 里找到当前阶段（`Sx`）和下一项未完成任务。
3. 只做这一项任务：实现 → 测试 → 用本文件第 7 节的退出标准命令验证 → 更新 STATUS → 提交一次。
4. 回到第 2 步。阶段的全部任务和退出标准都通过后，STATUS 进入下一阶段。

规则：
- **以 STATUS 和真实证据为准**，不依赖记忆、聊天摘要或旧提交信息。
- 本文件中写明的默认值直接采用，不向用户提问。
- 遇到本文件没覆盖的情况：选择更安全的做法（不交易、冻结、失败即停），把决定写进 STATUS 的"决策记录"，继续推进。

### 0.2 本文件的结构

| 节 | 内容 |
|---|---|
| 1 | 一句话目标 |
| 2 | 真实基线：现在有什么、坏在哪里 |
| 3 | 最终产品：用户看到什么 |
| 4 | 目标架构 |
| 5 | 交易循环的精确规格（时间表、风控数值、下单规则） |
| 6 | 代码处置清单：删、接、合并、保留 |
| 7 | 构建阶段 S0–S11，每阶段的任务和退出标准 |
| 8 | Agent 自主协议 |
| 9 | 安全不变量 |
| 10 | v1.0.0 完成定义 |
| 11 | 附录 |

---

## 1. 一句话目标

把 AlphaBrief 做成一个**真正在 OANDA 模拟盘上无人值守运行的 AI 外汇交易工作站**：

- 每个交易日自动读取新闻、宏观数据和行情；
- 5 个 AI 角色组成的委员会讨论后给出结构化决策；
- 经过确定性风控后，向 OANDA 模拟盘下带止损止盈的真实订单，并完成对账；
- 连续 14 天真实运行，留下可复核的证据；
- 以 GitHub 开源项目 + Mac 安装包（`.dmg`）的形式发布 v1.0.0。

实盘交易永远不在范围内。

---

## 2. 真实基线（2026-09-30 实测）

### 2.1 总体

| 项目 | 实测结果 |
|---|---|
| 代码规模 | 13 个包 + 2 个 app，源码约 7.8 万行 Python；测试约 6.4 万行，3325 个用例 |
| 静态检查 | `ruff check .` 通过；`mypy`（strict，523 个文件）通过 |
| 测试 | 删除旧文档前：3304 通过 / 21 失败（全部是写死日期的测试，见 2.3）。删除旧文档后：3255 通过 / 41 失败 / 29 错误，新增的 49 个全部属于 S1 要删除或改写的测试，明细见 STATUS 基线 |
| OANDA 模拟账户 | 2026-06-29 开户，**有史以来只有 3 笔交易记录**（开户、配置、入金），余额 100000 USD 未动，**从未下过一单** |
| 账户可交易品种 | 68 个，全部是外汇（`CURRENCY`）。`XAU_USD`、`SPX500_USD` 在 `/v3/accounts/{id}/instruments` 返回 404，但报价和 K 线可读。`hedgingEnabled=false`，`marginRate=0.02`（50 倍杠杆上限），与 OANDA 美国主体的规则一致 |
| 真实运行记录 | 旧版调度器 8/12–8/30 每天有 39–44 张票、10–11 个计划，但所有计划的目标仓位都是 0；9/14 起模型调用全部失败；9/16 起对账冻结，调度器跳过 AI 任务 |
| 模型服务 | `.env` 指向 OpenCode Go（`opencode.ai/zen/go`），请求返回 `400 MissingSessionID`。官方文档写明它只服务编程 Agent 的流量，**不能作为产品后端** |
| GitHub | 仓库 `JeremyL691/AlphaBrief` 已公开；`gh` 已登录（scope 含 `repo`、`workflow`）；完整 git 历史中**没有出现过**真实的 OANDA token、账户 ID 或模型 key |
| 本机 | macOS 27，arm64；Amphetamine 等进程持有防休眠断言 |
| 可选数据 key | `FRED_API_KEY`、`ALPHAVANTAGE_API_KEY` 均为空 |

### 2.2 旧部署（正在运行，必须在 S0 清场）

- launchd 服务 `com.alphabrief.api`（端口 8000）和 `com.alphabrief.scheduler` 正在运行。
- 它们跑的是 `~/.alphabrief/alphabrief-src`：一个**不是 git 仓库的旧代码快照**（例如 `daily_cycle.py` 459 行，而 HEAD 是 1224 行）。
- 数据：`~/.alphabrief/data/alphabrief.db`（22MB，含 8 月的投票记录）、`~/.alphabrief/api-data/`、`~/.alphabrief/ai-data/`，以及 228MB 的 `alphabrief.db.bak-1.3m-alerts`。
- 包装脚本：`~/.alphabrief/run_api.sh`、`run_scheduler.sh`；plist 在 `~/Library/LaunchAgents/com.alphabrief.{api,scheduler}.plist`。
- 这套服务和新系统共用同一个 OANDA 账户。**同一账户同一时间只能有一个交易运行时**，所以 S0 必须先停掉它。

### 2.3 真实下单链路上的缺陷（逐条有出处）

唯一真正会走到 OANDA 的路径是：`alphabrief scheduler run` → `scheduler_commands.py` 的 `_ai_cycle_factory` → `DailyTradingCycle` → `ExternalPaperExecutionBackend` → `OandaPaperAdapter.submit`。

| 位置 | 问题 | 后果 |
|---|---|---|
| `packages/alphabrief-execution/src/alphabrief_execution/broker/oanda/adapter.py:181-192` | 订单体发送无符号 `units` 加一个 v20 不存在的 `side` 字段；没有止损和止盈 | 卖单会作为买单发出；没有保护性止损 |
| `adapter.py:485-490` + `execution_backend.py` 的数量钳制 | 要求整数 units，但仓位计算总是产生小数 | 第一笔真实下单就会被拒 |
| `adapter.py:500-505` | DAY 被映射为 FOK/GTC | 订单时效语义被悄悄改变 |
| `packages/alphabrief-execution/src/alphabrief_execution/broker/port.py:67-77` | `SubmitRequest` 没有止损止盈字段 | 整条链路无法表达保护单 |
| `broker/reconciliation.py:213-216`、`:234-238` | 任何远端持仓、任何未登记的订单都算差异 | 一旦真的成交，下一次对账就会冻结调度器 |
| `broker/risk_context.py:140-149`、`:184-199` | 伪造账户状态（`margin_used=0`），价格、持仓、换算永远为空，对账状态永远 `unknown` | 风控看不到真实账户；有持仓后后续下单全部失败 |
| `packages/alphabrief-trader/src/alphabrief_trader/daily_cycle.py:364`、`:818`、`:896` | `data_quality_passed=True` 写死；不传 `risk_context`、`account_context` | 数据质量、新闻、账户敞口相关风控规则全部不生效 |
| `packages/alphabrief-trader/src/alphabrief_trader/execution_backend.py:313-321` | `policy_hash` 哈希的是常量；`snapshot_hash` 用时间戳冒充；`context_freshness=True` 写死 | 风控决策的证据字段是空壳 |
| `execution_backend.py:350-355` | `fill_price=None`，成交数量用请求数量代替 | 成交记录不可信 |
| `packages/alphabrief-risk/src/alphabrief_risk/gate.py:136` | `KillSwitch` 每次新建，从不生效 | 没有真正的紧急停止 |
| `gate.py:475-480` 等 | AI 意图没有 quantity，敞口、集中度、杠杆检查全部跳过 | 风控实际只有约 3 条检查生效 |
| `apps/cli/src/alphabrief_cli/scheduler_commands.py:415-430` | 默认品种混有 BTC、AAPL、SPY 等，注释还写着 Alpaca | 其中 8 个不是合法的 OANDA 品种名 |
| `scheduler_commands.py:552-600` | 行情默认来自 Yahoo，失败被吞掉 | 没有使用 OANDA 原生 K 线和报价 |
| `scheduler_commands.py:698-703` | 每条新闻都被打上全部品种的标签 | 所有品种看到同样的新闻 |
| `scheduler_commands.py:828-844` | 用 `MockMacroProvider` 往生产库写假宏观数据 | 生产数据被污染 |
| `scheduler_commands.py:980-1055` | async 处理函数里全是同步阻塞调用 | 卡住事件循环，超时和对账都会停摆 |
| `scheduler_commands.py:1008-1026` | 每轮新建 $100k 的内存 `PaperBroker`；RiskGate 只配了 3 个参数 | 风控配置几乎为空 |
| `scheduler_commands.py:409-412` | 委员会构建时没有传 `record_sink` | 模型调用失败的原因从不落库，无法诊断 |
| `packages/alphabrief-models/src/alphabrief_models/gateway.py:351-368` | 吞掉异常，只保留异常类型名 | 401、超时等真实原因丢失 |
| `packages/alphabrief-execution/src/alphabrief_execution/operations/scheduler.py:568-582` | AI 任务每 86400 秒跑一次，从进程启动时间算起 | 没有对齐交易时段 |
| `packages/alphabrief-news/src/alphabrief_news/providers/rss.py:44` | `reuters-rss` 实际指向 Bloomberg | 新闻来源标签错误 |
| `apps/api/src/alphabrief_api/routes/paper.py:98-103` | 看板的组合和持仓来自进程内 `PaperBroker(cash=100000)` | **看板从不显示真实 OANDA 账户** |
| 全仓库 17 处 `def _default_db_path` | 数据库路径各自计算 | 实际存在 3–5 个 DuckDB 文件；多进程以读写方式打开同一文件，导致 `Could not set lock on file` |
| `.env` 中 `ALPHABRIEF_DATA_DIR=data/local` | 相对路径，随当前目录变化 | 不同入口写进不同的数据库 |
| 委员会决策 | 没有当前持仓输入，卖出意图在仓位计算时报错 | 系统只能开多仓，从不平仓 |
| 新闻路径 | `CommitteeInput.evidence_ids` 从不填充 | "证据约束"逻辑实际没有运行 |

失败的测试（共 21 个，全部是时间相关）：

- `tests/test_risk_currency_aggregation.py`、`tests/test_risk_exposure_matrix.py`：测试固定 `NOW=2026-08-13`，但 `_snapshot()` 调用 `compute_exposure` 时没传时钟，代码回落到 `datetime.now(UTC)`，于是数据被判"过期"。修法：在两个 `_snapshot()` 里传 `clock=lambda: NOW`（函数已支持 `clock` 参数）。
- `tests/test_macro_api.py`、`tests/test_macro_commands.py`：路由（`apps/api/src/alphabrief_api/routes/macro.py:288`）、CLI（`apps/cli/src/alphabrief_cli/macro_commands.py:146`）和 `release_state` 默认值（`packages/alphabrief-news/src/alphabrief_news/macro_release.py:110`）直接读墙钟。修法：注入时钟（FastAPI 依赖 / 可替换的 `_now()`），测试里所有时间都从同一个 `NOW` 推导。
- 同样的隐患：`tests/test_risk_execution_paths.py:52` 固定 `NOW`，但第 109 行用了 `datetime.now(UTC)`；仓库里有 53 个测试文件定义了固定 `NOW`。S1 要一并排查。

### 2.4 已经写好但从未接上的代码（优先复用，不要重写）

这些模块质量不错，但只有测试在调用。重构时应**接入**它们，而不是另起炉灶：

| 模块 | 位置 | 能力 |
|---|---|---|
| `orders.py`（264 行） | `packages/alphabrief-execution/src/alphabrief_execution/broker/oanda/` | 带符号 units、精度归一化、`takeProfitOnFill`/`stopLossOnFill`（`orders.py:82-85`） |
| `order_ops.py`、`trade_ops.py`、`position_ops.py`、`account_ops.py` | 同上 | 订单创建、查询、撤单、改单；交易、持仓、账户操作 |
| `transaction_cursor.py`、`transaction_ops.py` | 同上 | 基于 TransactionID 的可恢复游标 |
| `reconcile.py`、`account_projection.py`、`order_ledger.py` | 同上 | 对账与账户投影 |
| `submit_recovery.py`、`unknown_outcome.py` | 同上 | 下单结果未知时先查询、不重发 |
| `pricing.py`、`candles.py`、`instruments.py`、`taxonomy.py`、`sessions.py` | 同上 | 原生报价、K 线、品种目录、分类、交易时段 |
| `freeze_policy.py` | 同上 | 冻结策略 |
| `exposure_aggregation.py`、`loss_state.py`、`margin_loss_rules.py`、`market_conditions.py`、`operational_blocks.py`、`reduce_only.py` | `packages/alphabrief-risk/src/alphabrief_risk/` | 本币敞口、日内亏损、保证金、点差和过期报价、减仓模式 |
| `ingestion.py`、`dedup.py`、`macro_release.py`、`sentiment_aggregate.py`、`untrusted.py` | `packages/alphabrief-news/src/alphabrief_news/` | 新闻入库、去重、宏观日历状态、情绪聚合、不可信内容清洗 |
| `cycle_state.py` | `packages/alphabrief-trader/src/alphabrief_trader/` | 持久化的阶段状态（compare-and-set） |
| `repair.py` | `packages/alphabrief-models/src/alphabrief_models/` | 结构化输出修复（目前默认关闭） |
| `design-tokens.css` | `apps/api/src/alphabrief_api/static/` | Soft 设计令牌（亮色 + 暗色） |

### 2.5 仪式代码（为"验证流程"而写，从不在运行时执行）

前一轮自主开发用约 880KB 的流程文档和以下代码，去"验证"从未产生过的证据。例如 `alphabrief acceptance preflight --scope oanda-observation` 在 4 处调用里都把证据参数传成空字典 `{}`，因此永远返回 `no truth supplied`。这些代码在 S1 删除，清单见第 6 节。

### 2.6 产品外壳现状

- **看板**：`apps/api/src/alphabrief_api/routes/dashboard.py`（2976 行），所有 HTML/CSS/JS 都是 Python 字符串；只有暗色；9 个页面。资金曲线卡片标着"Simulated sample"，且从不绘制。
- **未挂载的 Soft 看板**：`apps/api/src/alphabrief_api/dashboard/`（1987 行 Python），只有测试在导入它。
- **Electron**：`electron/main.js` 直接启动源码目录里的 `.venv/bin/alphabrief serve`（`main.js:26-29`）；`scripts/package.js` 只复制 4 个文件；引用的 `icon.png` 不存在；没有 `.dmg`，没有打包好的 Python。
- **CI**：没有 `.github/workflows`，没有 pre-commit。
- **部署脚本**：`scripts/deployment/run_api.sh` 写死了 `/Users/jeremyliu` 和 OpenCode 地址；`run_scheduler.sh` 的品种列表过时。

---

## 3. 最终产品

### 3.1 用户旅程（v1.0.0）

1. 用户从 GitHub Release 下载 `AlphaBrief-1.0.0-arm64.dmg`，拖进"应用程序"。应用未签名，README 写明首次打开的方法：右键 → 打开。
2. 首次启动进入**引导页**：
   - 填写 OANDA practice token 和账户 ID，应用立即做一次只读校验，显示账户币种和可交易品种数；
   - 点击 **Sign in with ChatGPT**，在浏览器完成授权（使用 ChatGPT 订阅额度）；
   - 可选：填写一个 OpenAI 兼容 API 的地址、key 和模型名作为备用通道，并明确勾选"主通道不可用时使用备用通道"；
   - 选择"后台常驻运行"，应用安装一个 LaunchAgent。
3. 之后无需任何操作：
   - 后台进程每个交易日跑 3 轮决策；
   - 委员会给出开仓、平仓或不交易的结构化决策；
   - 风控通过后向 OANDA 模拟盘下单（止损止盈随成交挂上）；
   - 持续对账；每天生成日报。
4. 用户随时打开应用看板，看到：
   - 真实账户、持仓、订单；
   - 每轮委员会的逐角色发言；
   - 新闻、风控状态；
   - 委员会对比基准的表现；
   - 回测、策略、复盘。
5. 出现安全问题时，系统自动冻结新开仓并发出 macOS 通知；满足自动解冻条件后自动恢复（见 5.9）。

### 3.2 功能清单（v1.0.0 必须具备）

| 领域 | 必须具备 |
|---|---|
| 账户 | 从 OANDA 发现品种；账户摘要、持仓、订单、交易、流水；用 TransactionID 游标增量同步 |
| 行情 | OANDA K 线（M15/H1/H4/D）和实时报价（轮询即可，不强制流式）；本币换算因子 |
| 新闻 | 至少 3 个独立来源家族的 RSS；去重；按品种相关性打标签；不可信内容清洗；只存元数据、哈希和短摘要 |
| 宏观 | 可选 FRED 数据；没有 key 时降级为"新闻冲击过滤"（见 5.7） |
| 委员会 | 5 个角色、有调用上限、结构化 JSON 决策、逐角色发言完整落库 |
| 风控 | 第 5.7 节全部规则；每个决策都持久化；kill switch |
| 执行 | MARKET + FOK + `stopLossOnFill` + `takeProfitOnFill`；带符号整数 units；结果未知时先查询；幂等 |
| 对账 | 每 60 秒一次，每次下单后立即一次；只有无法解释的差异才冻结；按条件自动解冻 |
| 平仓 | 委员会平仓决策、最长持仓时间、周末前平仓、止损止盈 |
| 评估 | 影子基准（5.11），4 小时 / 24 小时远期收益统计 |
| 报告 | 日报（Markdown + JSON）；14 天试运行报告 |
| 保留模块 | 回测（跑基准和策略）、策略注册表（信号作为委员会可选证据）、gym（OANDA K 线环境）、复盘（并入日报和复盘页） |
| 运维 | 单进程后台；LaunchAgent；结构化 JSON 日志；macOS 通知；`alphabrief doctor` 自检 |
| 界面 | 第 3.3 节的页面；亮/暗色；中英文切换（默认跟随系统）；320/768/1024/1440 响应式；键盘可达 |
| 发布 | `.dmg`、校验和、CHANGELOG、中英 README、截图、试运行报告、CI 全绿 |

### 3.3 看板页面

| 页面 | 内容 |
|---|---|
| 总览 | NAV、当日和累计盈亏、保证金占用、持仓、今日各轮决策、下一轮时间、系统健康（数据新鲜度、模型通道、冻结状态） |
| 委员会 | 每轮列表；详情页展示 5 个角色的发言、投票、置信度、最终决策、引用的证据、模型通道和耗时、调用次数 |
| 订单与交易 | 订单、成交、止损止盈、平仓原因、对应的风控决策 ID 和委员会轮次 ID |
| 新闻与宏观 | 新闻列表（来源、时间、相关品种）、宏观事件、信号品种走势（金价、标普、原油） |
| 风控 | 当前限额和占用、冻结历史、kill switch 开关（需二次确认）、被拒原因统计 |
| 评估 | 委员会与 4 个基准的远期收益对比；样本数；置信区间；明确提示"样本太小，不代表未来" |
| 回测 | 运行基准和已注册策略的回测，展示指标 |
| 策略 | 策略注册表的增删改查和信号 |
| 复盘 | 日报列表、交易日志 |
| 设置 | 凭证状态（只显示是否已配置和脱敏 ID）、模型通道、预算、后台服务、数据目录、日志位置、"关于"页 |

所有页面都要有加载、空、错误、数据过期、后端离线五种状态。**界面上永远不显示模拟数据或样例数据**；没有数据就显示空状态。

### 3.4 明确不做

- 实盘交易、实盘 URL、实盘开关或"以后接实盘"的占位代码。
- OANDA 以外的任何券商；产品代码里的模拟成交回退。
- 多用户、账号体系、云端托管、SaaS、付费、遥测上报。
- Mac App Store 上架、代码签名和公证（流程留开关，默认关闭）。
- 高频或低延迟交易；流式行情不是 v1 的必需项。
- 为凑交易次数而下单（`no_trade` 是合法结果）。
- 让模型修改风控阈值、提示词、凭证或调度策略。
- 复制 `_reference_sources/` 下任何项目的代码、提示词或结构。

### 3.5 "可以上架"的定义

满足第 10 节的全部检查项，并且：

- GitHub Release `v1.0.0` 已创建，附件包括 `AlphaBrief-1.0.0-arm64.dmg`、`SHA256SUMS.txt`、`soak-report-v1.0.0.md`；
- 仓库 `main` 已推送，CI 全绿；
- README（英文，附中文节）包含截图、安装步骤、首次打开未签名应用的方法、架构图、试运行结果摘要、已知限制和免责声明。

---

## 4. 目标架构

### 4.1 运行拓扑

```
┌──────────────── AlphaBrief.app (Electron) ────────────────┐
│  窗口 = 加载 http://127.0.0.1:<port>/ 的看板               │
│  首次运行：安装/卸载 LaunchAgent；检测后台是否在线         │
└───────────────────────────┬───────────────────────────────┘
                            │ HTTP (127.0.0.1 only)
┌───────────────────────────▼───────────────────────────────┐
│ 后台进程 `alphabrief run`（LaunchAgent 常驻，单实例锁）     │
│  ├─ FastAPI：JSON API + 静态看板                            │
│  ├─ 调度器：asyncio 任务；阻塞工作用 asyncio.to_thread      │
│  │   ├─ 账户/流水同步（30s）  ├─ 对账（60s + 每次下单后）    │
│  │   ├─ 报价轮询（5s，仅交易时段）├─ K 线增量（5min）        │
│  │   ├─ 新闻（30min）          ├─ 宏观（60min，可选）        │
│  │   ├─ 决策轮（UTC 00:30/07:30/13:00，周一至周五）         │
│  │   ├─ 周五平仓（UTC 19:00）  ├─ 远期收益结算（每小时）    │
│  │   └─ 日报（UTC 21:30）      └─ 备份（UTC 22:00）          │
│  └─ 唯一 DuckDB 写入者：<data_dir>/alphabrief.duckdb         │
└──────┬──────────────────┬──────────────────┬──────────────┘
       │                  │                  │
  OANDA practice     模型通道            RSS / FRED
  api-fxpractice     ChatGPT 订阅（主）   (只读)
  (唯一执行地址)     OpenAI 兼容 key（备用）
```

关键约束：
- **单实例**：后台进程启动时在数据目录取得文件锁（`fcntl.flock`）。拿不到锁就退出，并提示已有实例在运行。
- **唯一写入者**：DuckDB 只由后台进程以读写方式打开。CLI 一律通过 HTTP 调用后台；后台未运行时，CLI 只能以 `read_only=True` 打开数据库做查询，写操作直接报错。
- **一个账户一个交易运行时**：数据库里记录 `runtime_id`。启动时检查 OANDA 账户最近 10 分钟的流水，如果有来自其他 `clientExtensions.tag` 的订单，就拒绝进入交易模式。
- **交易开关**：`trading_mode = off | on`。冒烟测试、开发调试、CI 一律 `off`：照常跑决策，但在下单前停下，并记录 `NO_TRADE_TRADING_OFF`。

### 4.2 最终包结构

保留 11 个包 + 2 个 app：

```
apps/api        FastAPI 应用、路由、静态看板 (static/)
apps/cli        Typer CLI（通过 HTTP 调用后台；`run` 子命令启动后台本身）
packages/
  alphabrief-core        领域模型、配置、路径、时钟、日志、通知
  alphabrief-data        K 线存储、质量检查、特征、CSV/Parquet 导入（回测用）
  alphabrief-news        RSS、宏观、去重、相关性、情绪、不可信内容清洗
  alphabrief-models      ModelGateway、chatgpt_plan 适配器、openai_compatible 适配器、结构化输出与修复
  alphabrief-risk        RiskGate 与全部规则
  alphabrief-execution   OANDA 客户端与生命周期、对账、冻结策略
  alphabrief-trader      委员会、交易轮次（TradingCycle）、仓位计算、评估、日报
  alphabrief-strategy    策略注册表与信号
  alphabrief-backtest    回测引擎（OANDA 语义：点差、隔夜利息、整数 units）
  alphabrief-gym         基于 OANDA K 线的训练环境
  alphabrief-review      交易日志与复盘
electron/       桌面外壳与打包配置
```

删除 `alphabrief-acceptance` 和 `alphabrief-research` 两个包（第 6 节）。

### 4.3 数据与存储

- **数据目录**：`~/Library/Application Support/AlphaBrief/`。环境变量 `ALPHABRIEF_HOME` 可以覆盖，用于开发和测试；**必须是绝对路径**，相对路径直接报错。
- 目录结构见附录 B。全仓库只保留一个路径模块（`alphabrief_core.paths`），删除 17 处 `_default_db_path`。
- 只有一个数据库文件 `alphabrief.duckdb`，迁移带版本号、只能前进，复用现有 `apps/api/src/alphabrief_api/db/migrations.py`。
- **事实表只追加不改写**：订单、成交、流水、决策、模型调用、新闻；当前状态用投影表表示。
- 所有时间以 UTC 存储；界面展示本地时间并在悬停时显示 UTC。
- 所有金额、价格、数量使用 `Decimal`。
- 每天备份一份到 `backups/`，保留 14 份日备份和 8 份周备份；从备份恢复要有一条命令和一个测试。

### 4.4 配置与密钥

- **非密钥配置**：`config/alphabrief.yaml`，带 schema 版本号、严格校验、未知字段报错。它合并取代现有的 `config/oanda_paper.yaml` 和 `config/paper_execution_policy.yaml`。第 5 节的所有数值都放在这里，默认值写在代码里。
- **密钥**：OANDA token、账户 ID、备用模型 key、ChatGPT OAuth 凭证，存在 `<data_dir>/secrets/` 下，文件权限 0600，原子写入。这是 OpenAI SIWC 文档对本地应用的要求，同时也适合无人值守运行。
  - 开发时也可以从 `.env` 读取（变量名见附录 A）。
  - 已知限制：可以升级为 macOS Keychain，v1 不做。
- **任何日志、报告、截图、提交里都不能出现密钥**。账户 ID 只显示脱敏形式（如 `101-***-***-001`）。

### 4.5 模型网关

所有模型调用只经过 `ModelGateway`。业务代码不得直接调用任何模型 SDK 或 HTTP 接口。

**主通道 `chatgpt_plan`**：严格按 OpenAI 官方"Sign in with ChatGPT"开源应用文档实现（链接见附录 E）。

| 要点 | 实现 |
|---|---|
| 授权地址 | `https://auth.openai.com/api/accounts/authorize`；token 端点 `https://auth.openai.com/api/accounts/oauth/token` |
| 首次注册 | `client_id=dynamic_agent_client`；`agent_name_hint=AlphaBrief`；持久化并复用 `ext_agent_host_id`（推荐 `urn:uuid:` 形式，首次生成后永不改变）；保存签发的 client ID |
| 回调 | `http://127.0.0.1:1455/auth/callback`（端口被占用时按文档顺延）；每次授权都生成新的 `state`、`nonce`、PKCE（S256） |
| scope | `openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`；`resource=https://api.openai.com/v1` |
| 校验 | 用 JWKS 验证 ID token 的签名、issuer、audience、过期时间、nonce；**确认授予的 scope 包含 `chatgpt.tokens.use.direct`** |
| 推理 | 只用公开的 Responses API；每个请求 `store=false`、`stream=true`；指令用 `instructions` 或 developer 消息，**不发 system role**；不用 `background`、`max_output_tokens`、`metadata` 等不支持的参数；等收到 `response.completed` 才算成功 |
| 模型 | 用同一个 access token 获取该账户的模型目录，选择列表中可见的默认对话模型，写进配置；切换账户时重新获取 |
| 刷新 | 过期前用 refresh token 续期；所有 token 字段一起原子更新 |
| 结构化输出 | 文档没有承诺支持 JSON schema，所以用"提示词约定 JSON + 本地严格解析 + `repair.py` 最多修复 2 次" |
| 错误 | `subscription_sharing_usage_limit_exceeded`（429）：当天停用该通道；`subscription_sharing_usage_unavailable`（503）：有限次数退避；`subscription_sharing_unsupported_capability`（400）：去掉不支持的特性，不原样重发；`subscription_sharing_user_not_eligible`（403）和 `subscription_sharing_invalid_user`（401）：标记"需要重新登录"并发通知；`refresh_token_expired`/`token_expired`：清除凭证并要求重新登录 |
| User-Agent | `AlphaBrief/<version>`。不伪装成任何 SDK 或其他工具 |

**备用通道 `openai_compatible`**：

- 配置项：`ALPHABRIEF_LLM_BASE_URL`、`ALPHABRIEF_LLM_API_KEY`、`ALPHABRIEF_LLM_MODEL`；可以是 DeepSeek 官方、OpenAI API、OpenRouter 等任何按量付费的 OpenAI 兼容接口。
- **只有在用户明确开启 `model.fallback_enabled: true` 时才使用。** OpenAI 文档要求"不要静默切换计费方式"，所以每次切换都写进模型调用记录，并在看板和日报中显示。
- 拒绝主机名包含 `opencode.ai` 的地址（服务条款不允许），启动时报错并说明原因。
- 旧变量 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`ALPHABRIEF_AI_MODEL_*` 不再被产品读取。

**调用记录**：每次调用都持久化，包括通道、模型、角色、轮次 ID、耗时、token 用量、估算成本、结果状态、错误码和错误信息（脱敏后）。不再只记录异常类型名。

**两个通道都不可用时**：该轮记录 `NO_TRADE_MODEL_UNAVAILABLE`，绝不用假模型兜底。

### 4.6 OANDA 集成

- 只允许以下主机：`api-fxpractice.oanda.com`（必需）和 `stream-fxpractice.oanda.com`（可选）。HTTP 客户端在构造时校验主机白名单，其他主机（包括 `api-fxtrade.oanda.com`）直接抛异常。保留并测试这条约束。
- 复用现有的 urllib 客户端 `broker/oanda/client.py`：只对 GET 自动重试，非幂等请求从不盲目重试。补上 `User-Agent: AlphaBrief/<version>`。
- 下单走 `order_ops.py` + `orders.py`，删除 `adapter.py` 里的旧下单路径。
- 每个订单带 `clientExtensions`：`id` = 意图 ID（幂等键），`tag` = `alphabrief`，`comment` = 轮次 ID。
- 账户同步用 `/v3/accounts/{id}/changes?sinceTransactionID=` 加流水游标；游标落库，重启后从断点继续。
- 换算：报价请求带 `includeHomeConversions=true`，用返回的换算因子把报价货币金额折算成账户本币。

### 4.7 前端

- 删除 `routes/dashboard.py` 和未挂载的 `dashboard/` Python 包。新看板放在 `apps/api/src/alphabrief_api/static/`，由 FastAPI 的 `StaticFiles` 提供。
- 技术：原生 HTML + CSS + ES Modules，不引入框架，不需要构建步骤。复用并扩展 `design-tokens.css`。图标使用本地的 SVG sprite（例如 Lucide，ISC 许可证），**不用 emoji 当图标**。
- 风格采用 Soft：温和的底色、圆角、柔和阴影、克制的过渡动画。按钮不用渐变；界面文案不用破折号（em dash）；浅色背景上正文颜色不浅于 `#666`；尊重 `prefers-reduced-motion`。
- 主题：亮色、暗色、跟随系统。
- 语言：中文、English 两套文案字典，默认跟随系统。
- 安全：API 只绑定 `127.0.0.1`；写操作需要 CSRF token 和幂等键；不开放通配 CORS。

### 4.8 打包与后台运行

- **后端**：用 PyInstaller（加入 dev 依赖）以 onedir 模式打包 `alphabrief` 入口，产物放进 `.app` 的 `Contents/Resources/backend/`。
- **桌面**：用 electron-builder（npm devDependency），目标 `dmg`、架构 `arm64`、`mac.identity: null`（不签名）。签名和公证配置留好，默认关闭，只有检测到对应环境变量时才启用。
- **后台服务**：`alphabrief service install|uninstall|status` 生成和管理 `~/Library/LaunchAgents/ai.alphabrief.backend.plist`。设置 `KeepAlive=true`、`RunAtLoad=true`，日志写到数据目录。Electron 的设置页调用这些命令。
- **Electron 启动流程**：先探测 `http://127.0.0.1:<port>/health`；在线就直接连接；不在线就提示"安装后台服务"或"仅本次启动"。
- **防休眠**：后台进程在交易时段持有 `caffeinate -i` 断言（以子进程方式运行，进程退出时随之释放）。**不修改任何系统设置**；`pmset` 只读检查，结果写进 `doctor` 输出。

### 4.9 可观测性

- 结构化 JSON 日志，按天轮转，保留 30 天。
- 告警渠道：macOS 通知（`osascript`）、看板横幅、日报。
- `alphabrief doctor` 一次性检查以下各项，并给出明确结论（PASS / WARN / FAIL + 原因）：
  - 数据目录可写、单实例锁；
  - OANDA 只读连通、账户币种和可交易品种数；
  - 模型主通道 token 有效、备用通道配置；
  - 新闻源可用性；
  - 防休眠断言；
  - 磁盘空间；
  - 最近一次对账结果。

---

## 5. 交易循环规格

本节的数值都是默认值，全部写进 `config/alphabrief.yaml`。模型和新闻内容不能修改它们。

### 5.1 时间表（UTC，周一至周五）

| 时间 | 任务 |
|---|---|
| 00:30 | 决策轮 A（东京时段） |
| 07:30 | 决策轮 B（伦敦开盘） |
| 13:00 | 决策轮 C（纽约开盘） |
| 周五 13:00 | 只允许平仓，不新开仓 |
| 周五 19:00 | 平掉所有持仓（周末跳空保护） |
| 每天 21:30 | 生成日报 |
| 每天 22:00 | 备份 |

规则：
- 周六、周日不跑决策轮；同步、对账、日报照常进行，日报标注"休市"。
- **补跑**：错过的轮次在计划时间后 90 分钟内可以补跑，超过 90 分钟记录 `MISSED_WINDOW`，绝不在错误的时段补下单。
- 下单前最终判断以 OANDA 报价里的 `tradeable` 状态为准。

### 5.2 品种

- **交易品种** = 账户可交易列表 ∩ 配置列表。默认配置：`EUR_USD`、`GBP_USD`、`USD_JPY`、`AUD_USD`、`USD_CAD`。
- **信号品种**（只读 K 线，作为委员会输入，不交易）：`XAU_USD`、`SPX500_USD`、`BCO_USD`。如果账户读不到某个信号品种，就从输入中去掉，并在轮次记录里注明。
- 换成能交易 CFD 的账户后，`XAU_USD` 等会自动出现在可交易列表里。是否把它们加入交易品种由配置决定，默认不加。未识别的品种分类一律禁止下单。

### 5.3 每轮每个品种的输入

| 输入 | 来源 | 新鲜度要求 |
|---|---|---|
| K 线 | OANDA：M15 最近 96 根、H1 最近 120 根、H4 最近 60 根、D 最近 60 根 | 最新一根 H1 的结束时间距今不超过 2 小时（交易时段内） |
| 报价 | OANDA pricing：bid、ask、点差、本币换算因子 | 不超过 15 秒 |
| 派生特征 | ATR(14, H1)、近 20 日收益与波动、与信号品种的 20 日相关性 | 由 K 线计算 |
| 新闻 | 过去 24 小时内与该品种两个货币相关的条目，最多 20 条，按时间倒序 | 至少 2 个来源家族成功；最新的相关条目不超过 6 小时 |
| 宏观 | FRED（如已配置）：近期数据与即将发布的数据 | 可选 |
| 信号品种 | 金价、标普、原油的 H1/D 涨跌 | 同 K 线 |
| 账户 | NAV、可用保证金、该品种当前持仓及未实现盈亏、今日已开仓数 | 不超过 60 秒（对账结果） |
| 策略信号 | 已启用的注册策略在该品种上的最新信号（可选证据） | 同 K 线 |

任何关键输入缺失或过期：该品种本轮直接记录 `NO_TRADE_DATA_STALE`，不调用模型去"猜"。

### 5.4 委员会协议

- **角色**：`technical`（技术面）、`macro_news`（宏观与新闻）、`intermarket`（跨市场信号，如金价、股指、原油）、`risk`（风险视角）、`manager`（主持人，最终决策）。
- **流程**：
  1. 4 个分析角色各自给出开场意见；
  2. manager 读完 4 份意见后做最终决策。
  - 质询轮次可以配置，默认 0 轮，以控制预算。
- **调用上限**：每个品种最多 5 次正常调用 + 最多 2 次修复调用；每轮最多 35 次。
- **每个分析角色的输出 schema**：
  ```json
  {"stance": "long|short|flat", "confidence": 0.0, "horizon_hours": 24,
   "key_points": ["..."], "evidence_ids": ["news:...", "candle:..."], "veto": false}
  ```
- **manager 的输出 schema**：
  ```json
  {"action": "open_long|open_short|close|hold|no_trade", "confidence": 0.0,
   "stop_atr_multiple": 1.5, "take_profit_r_multiple": 2.0,
   "rationale": "...", "evidence_ids": ["..."]}
  ```
- **决策规则**（确定性）：
  - `confidence < 0.55` → `no_trade`；
  - `risk` 角色 `veto=true` → `no_trade`；
  - 开仓方向至少要有 2 个分析角色支持；
  - 已有同向持仓时 `open_*` 视为 `hold`；
  - 已有反向持仓时 `open_*` 先平仓，下一轮再考虑新开仓（不在同一轮反手）。
- **证据约束**：`evidence_ids` 必须引用本轮实际提供的输入 ID。引用不存在的 ID 时，该份意见作废。
- **不可信内容**：新闻正文先经 `untrusted.py` 清洗；检测到提示词注入的条目不送进模型，但保留哈希记录。
- **全量落库**：完整的提示词版本号、输入摘要哈希、每个角色的原始输出、解析结果、最终决策都要落库。

### 5.5 决策 → 意图

`TradingCycle` 把 manager 的决策转换成 `OrderIntent`：

| 字段 | 取值 |
|---|---|
| `intent_id` | 确定性生成：`hash(cycle_id, instrument, action)`；同一轮重跑会得到同一个 ID |
| 方向 | 由 action 决定 |
| 数量 | 由 5.6 的仓位计算得出（带符号的整数 units） |
| 止损、止盈价格 | 由 5.6 计算 |

`close` → 生成减仓意图，数量等于当前持仓的反向（reduce-only）。

### 5.6 仓位与止损

| 参数 | 默认值 |
|---|---|
| 单笔风险 | NAV 的 0.25% |
| 止损距离 | `stop_atr_multiple × ATR(14, H1)`。模型只能在 [1.0, 3.0] 内建议，超出范围就截断到边界；没给就用 1.5 |
| 止盈距离 | `take_profit_r_multiple × 止损距离`，限制在 [1.0, 3.0]，默认 2.0 |
| units | `floor(风险金额(本币) / (止损距离 × 报价货币对本币的换算因子))`，再按品种的 `tradeUnitsPrecision` 和 `minimumTradeSize` 规整；结果为 0 则 `no_trade` |
| 单笔名义价值上限 | NAV 的 50% |
| 总名义敞口上限 | NAV 的 150% |
| 最多同时持仓 | 3 个品种 |
| 保证金占用 | 超过 20% 告警；超过 30% 禁止新开仓 |
| 试运行前 3 天 | 风险金额减半 |
| S9 预跑 | 固定 1000 units，不按风险计算 |

### 5.7 风控规则（RiskGate，按顺序执行，任何一条拒绝即结束）

| # | 规则 | 拒绝代码 |
|---|---|---|
| 1 | `trading_mode` 必须为 `on`，kill switch 未触发，没有冻结 | `TRADING_OFF` / `KILL_SWITCH` / `FROZEN` |
| 2 | 品种在交易白名单内，分类为 `CURRENCY` | `INSTRUMENT_NOT_ALLOWED` |
| 3 | 报价新鲜（≤15s），且 `tradeable=true` | `QUOTE_STALE` / `NOT_TRADEABLE` |
| 4 | 点差 ≤ 同品种同时段最近 20 个样本中位数的 2 倍 | `SPREAD_WIDE` |
| 5 | 数据质量通过（5.3 的新鲜度和完整性检查）。**由真实检查结果传入，禁止写死** | `DATA_QUALITY` |
| 6 | 宏观或新闻冲击：如果配置了 FRED，相关货币的高影响发布前后 30 分钟内不开仓；如果没有配置，则当该货币相关新闻在过去 30 分钟内出现高影响关键词（CPI、NFP/nonfarm、FOMC、rate decision、ECB、BoE、BoJ、RBA、BoC、SNB）时不开仓 | `EVENT_WINDOW` |
| 7 | 今日新开仓 < 5，该品种今日新方向意图 < 1 | `DAILY_INTENT_CAP` |
| 8 | 持仓品种数 < 3（仅开仓） | `MAX_POSITIONS` |
| 9 | 单笔名义价值、总名义敞口、保证金占用不超过 5.6 的上限（用真实账户上下文和本币换算计算） | `EXPOSURE` / `MARGIN` |
| 10 | 当日已实现加未实现亏损 < NAV 的 1%，否则当天剩余时间禁止开仓 | `DAILY_LOSS` |
| 11 | 相对试运行期内最高 NAV 的回撤 < 3%，否则 48 小时内禁止开仓，之后恢复为半仓；回撤 ≥ 5% 时试运行剩余期间禁止开仓（平仓和对账照常） | `DRAWDOWN` |
| 12 | 同一品种连续 3 笔亏损平仓后，该品种冻结 24 小时 | `LOSS_STREAK` |
| 13 | 周五 13:00 后、周末，禁止开仓 | `WEEKEND` |
| 14 | 止损、止盈、units 都已确定且合法 | `ORDER_INVALID` |

规则执行要求：
- 平仓（reduce-only）意图只检查规则 1 中的 kill switch 和规则 3；**冻结状态下也允许平仓**。
- 每个决策都持久化：规则结果、输入哈希（基于真实快照内容）、策略版本哈希（基于配置文件内容）。下单前必须校验持久化的决策与将要提交的订单一致。

### 5.8 下单与结果未知

- 订单：`MARKET` + `timeInForce=FOK` + `positionFill=DEFAULT` + `stopLossOnFill` + `takeProfitOnFill` + `clientExtensions`。
- 提交前把意图和决策落库；提交后无论成功、拒绝还是超时，都落库。
- **超时或连接中断 → 状态 `SUBMIT_UNKNOWN`**：按 `clientExtensions.id` 查询订单，并扫描流水。找到就按真实结果记账；查询窗口（默认 120 秒）内找不到，就标记为未成交并告警。**绝不直接重发。**
- 重启后，先处理所有 `SUBMIT_UNKNOWN`，再允许新的下单。

### 5.9 对账、冻结与自动解冻

- 对账频率：每 60 秒一次、每次下单后立即一次、启动时和停止前各一次。
- **可以解释的差异**不冻结：
  - 自己下的订单（`clientExtensions.tag=alphabrief`）；
  - 止损止盈触发的成交；
  - 隔夜利息和手续费流水。
- **以下情况冻结新开仓**：
  - 出现不是本系统产生的订单或持仓；
  - 持仓数量与本地记录不一致且无法用流水解释；
  - 流水游标出现缺口；
  - 连续 5 次对账请求失败。
- **自动解冻**：冻结原因消失，且之后连续 3 次对账干净 → 自动解冻并发通知。"非本系统订单"类冻结**不自动解冻**，必须由 Agent 调查后执行 `alphabrief unfreeze --reason ...`，并写进 STATUS。
- 冻结期间照常同步、对账、跑委员会（记录 `NO_TRADE_FROZEN`），平仓类意图照常执行。

### 5.10 平仓

以下任一情况触发平仓：

- manager 给出 `close`；
- 持仓达到 48 小时；
- 周五 19:00 UTC；
- 止损或止盈在 OANDA 侧触发；
- kill switch 触发时执行"全部平仓"（用户在看板上二次确认，或由 5.7 规则 11 的 5% 回撤自动触发）。

### 5.11 影子评估（只记录，不下单）

每轮每个品种，同时记录 5 个决策：

1. 委员会；
2. 单次调用：同样的输入，只让 manager 调用一次模型；
3. 动量：20 日收益为正就做多，为负就做空；
4. 随机：用固定种子，种子 = 轮次 ID 的哈希；
5. 不交易。

规则：
- 单次调用只在当轮预算剩余时执行，否则记录为跳过。
- 每个决策在 4 小时和 24 小时后，用 OANDA 中间价计算方向收益（扣除当时的点差）。
- 评估页和试运行报告展示：每个基准的样本数、平均收益、胜率、95% bootstrap 置信区间。
- 明确写出"14 天样本不足以判断是否有效"。

### 5.12 日报（UTC 21:30）

日报同时生成 `reports/daily/YYYY-MM-DD.md` 和 `.json`（写在数据目录里），内容全部来自数据库：

- 当日各轮决策汇总；
- 订单、成交和平仓；
- 盈亏、NAV、回撤；
- 风控拒绝统计、冻结事件；
- 模型调用次数、通道和估算成本；
- 数据新鲜度事件；
- 影子评估的增量；
- 当日的 `doctor` 摘要。

复盘模块读取日报和交易日志，生成复盘页。

### 5.13 模型预算

| 通道 | 限制 | 超出后 |
|---|---|---|
| `chatgpt_plan` | 每天最多 150 次调用（可配置）；另外建议用户在 ChatGPT 设置里给 AlphaBrief 设置每周上限 | 当轮剩余品种记录 `NO_TRADE_MODEL_BUDGET` |
| `openai_compatible` | 按配置的单价（每百万 input/output token）估算，每天 $2 | 同上 |
| 两者 | 收到 429 或额度错误 → 当天停用该通道 | 有备用通道且已明确开启时切换，否则 `NO_TRADE_MODEL_UNAVAILABLE` |

---

## 6. 代码处置清单

原则：**能接上就接上，重复的只留一份，仪式代码全部删除。** 删除代码时同时删除只测试它的测试。保留下来的代码，其测试必须保留并保持通过。

### 6.1 删除（S1 完成，括号内为行数）

| 对象 | 位置 |
|---|---|
| 验收与自主循环包（2512） | `packages/alphabrief-acceptance/` 整个包，以及 `pyproject.toml` 中的对应路径 |
| 研究辩论包（927） | `packages/alphabrief-research/` 整个包（与委员会重复） |
| 观察期仪式代码 | `packages/alphabrief-core/src/alphabrief_core/` 下的 `observation_controller.py`（1571）、`runbook_rehearsal.py`（132）、`recovery.py`（388）、`preflight.py`（182）、`security_gates.py`（124，由 CI 密钥扫描取代）、`request_policy.py`（259，无调用方） |
| CLI 命令组 | `apps/cli/src/alphabrief_cli/` 下的 `observation_commands.py`（605）、`acceptance_commands.py`（231）、`operations_commands.py`（152）、`paper_commands.py`（254）、`research_commands.py`、`brief_commands.py`（日报取代）、`bootstrap_commands.py`（含过时品种） |
| API 路由 | `apps/api/src/alphabrief_api/routes/` 下的 `acceptance.py`（62）、`paper.py`（701）、`research.py`、`brief.py`、`models.py`（评估、对比、Kronos）；`ai_trading.py` 里的 observation 目录分支（`ALPHABRIEF_AI_OBSERVATION_DIR`） |
| 写入租约 | `apps/api/src/alphabrief_api/db/writer_lease.py`（215）、`packages/alphabrief-trader/src/alphabrief_trader/scheduler_leader.py`（194），由单实例锁取代；`alphabrief_risk/operational_blocks.py` 中的 `writer_lease` 证据字段改为单实例锁状态 |
| 模型杂项 | `packages/alphabrief-models/src/alphabrief_models/` 下的 `kronos.py`（500）、`router.py`（309）、`registry.py`（129）、`quality_gate.py`（112），以及 `research_content` 用到的 briefs/daily/evaluation 提示词模块；`pyproject.toml` 的 `kronos` 可选依赖 |
| 数据源 | `packages/alphabrief-data/src/alphabrief_data/providers/` 下的 `yahoo.py`（450）、`binance.py`（412）、`alphavantage.py`（OANDA K 线取代） |
| 新闻杂项 | `packages/alphabrief-news/src/alphabrief_news/providers/` 下的 `sec_edgar.py`、`social_sentiment.py`；`mock.py` 移到 `tests/` |
| 调度器杂项 | `scheduler_commands.py` 里的 `research_content` 任务（会往生产库写假宏观数据）、过时的默认品种、Yahoo 摄取逻辑 |
| 产品里的模拟成交 | `broker/legacy.py` 的 `PaperBroker`，以及 `router.py`、`fills.py`、`portfolio.py` 中只为它服务的部分。只有 backtest/gym 确实依赖时，才在它们自己的包里保留一个最小模拟器，并且禁止被运行时导入（加一个导入约束测试） |
| 旧看板 | 未挂载的 `apps/api/src/alphabrief_api/dashboard/` Python 包（S1 删除；先把 `static/design-tokens.css` 保留下来）；`routes/dashboard.py`（S6 新看板上线后删除） |
| 旧部署脚本 | `scripts/deployment/`（由 `alphabrief service` 取代） |
| 占位目录 | `notebooks/`、`strategies/`，以及对应的 scaffold 测试断言 |
| 过时测试 | 只测试上述对象的测试文件；依赖已删除文档的测试（见 STATUS 基线）。`test_project_scaffold.py` 改成检查新的文档集合（`AGENTS.md`、`docs/PROJECT_GUIDE.md`、`docs/STATUS.md`、`docs/AGENT_PROMPT.md`），以及已删除的旧文档确实不存在 |

### 6.2 接入（第 2.4 节列出的模块，在 S3–S5 接上）

接上以后，用对应的旧实现做对照，然后删掉旧实现：
- `adapter.py` 中的旧下单和转换逻辑；
- `risk_context.py` 中的伪造数据源；
- `reconciliation.py` 中把所有持仓都当差异的旧逻辑。

### 6.3 合并去重

| 现状 | 合并为 |
|---|---|
| `DailyTradingCycle` 和从未构造过的 `DurableDailyCycle`（`daily_cycle.py`），加上 `cycle_execution.py`、`cycle_report.py`、`cycle_schedule.py`、`runtime_truth.py`、`execution_gate.py`、`candidate_selection.py`、`proposal.py`、`security_eval.py` | 一个 `TradingCycle`：阶段持久化（用 `cycle_state.py`），流程为准备 → 输入 → 委员会 → 决策 → 风控 → 执行或不交易 → 对账 → 记录。其余文件中有用的部分并入，没用的删除。**最终每个关注点只有一份实现** |
| 17 处 `_default_db_path` | `alphabrief_core.paths` |
| `config/oanda_paper.yaml` + `config/paper_execution_policy.yaml` | `config/alphabrief.yaml` |
| 多个 DuckDB 文件和 `apps/api/src/alphabrief_api/db/merged.py` 的快照复制 | 一个数据库、一个写入者；删除 `merged.py` |

### 6.4 保留并接上真实数据（S7）

| 模块 | v1 要求 |
|---|---|
| 回测 `alphabrief-backtest` | 数据来源改为 OANDA K 线（从数据库读取，可用 CLI 回填历史）；能对动量和随机基准以及已注册策略运行回测；成本模型包含点差、整数 units 和隔夜利息（无法获取时注明为估算）；结果落库并在回测页展示 |
| 策略注册表 `alphabrief-strategy` | 保留 DSL 和增删改查；信号基于 OANDA K 线计算；启用的策略信号作为委员会的可选证据（`evidence_ids` 可以引用 `strategy:<id>`） |
| gym `alphabrief-gym` | 环境数据来自 OANDA K 线；提供一个可运行的示例（CLI `alphabrief gym demo`）和测试；不接入实时交易 |
| 复盘 `alphabrief-review` | 读取日报和交易日志；提供复盘页和 `alphabrief review daily` |

---

## 7. 构建阶段（S0–S11）

每个阶段格式统一：**目标 / 任务 / 退出标准 / 产物**。退出标准中的命令必须真实执行并通过，并把输出摘要（不含密钥）写进 STATUS 的证据栏。

需要真实网络、凭证的测试统一用 pytest 标记 `@pytest.mark.practice`，CI 中运行 `-m "not practice"`。这是用标记选择测试，不是跳过测试。退出标准里要求运行的 practice 测试必须在本机实际运行通过。

### S0 环境与清场

**目标**：确认外部前提真实可用，并清掉旧部署。

**任务**：
1. 停掉旧服务：`launchctl bootout gui/$(id -u)/com.alphabrief.scheduler` 和 `.../com.alphabrief.api`；把两个 plist 移到 `~/.alphabrief-legacy-20260930/LaunchAgents/`。
2. 把 `~/.alphabrief` 整体移到 `~/.alphabrief-legacy-20260930/`，不删除，8 月的投票数据留作参考。
3. 用仓库现有代码做一次 OANDA 只读探测：账户摘要、可交易品种数、最近流水 ID。输出脱敏。
4. 检查 `gh auth status`、`git remote -v`、`pmset -g assertions`（只读）、可用磁盘空间。
5. 确认本地 `main` 与 `origin/main` 同步，工作区干净。
6. 在 STATUS 中记录以上结果。

**退出标准**：
- `launchctl list | grep -cE "com\.alphabrief\.(api|scheduler)"` 输出 0（不要动 `dev.alphabrief-agent.*`，那是用户用来唤醒 Agent 的服务）；
- `pgrep -f "alphabrief (scheduler|serve)"` 没有输出；
- OANDA 探测返回 HTTP 200；
- 网络不通或凭证无效时，STATUS 置为 `BLOCKED`，写明需要用户做的事，然后停止。**禁止编写模拟代码绕过。**

**产物**：STATUS 的 S0 证据。

### S1 做减法与恢复全绿

**目标**：删掉仪式代码，让测试、类型检查、lint 全部真实通过，并建立 CI。

**任务**：
1. 按 6.1 删除代码和对应测试；更新 `pyproject.toml` 的包路径。
2. 修好时间相关测试：用注入时钟，不改断言、不删测试（见 2.3）；排查其他 52 个固定 `NOW` 的测试文件中直接读墙钟的地方。
3. 改写 `test_project_scaffold.py`，让它检查新的文档集合。
4. 清理 Alpaca 和多资产残留：
   - 注释：`broker/__init__.py`、`port.py`、`exposure.py`、`routes/broker.py`、`scheduler_commands.py`；
   - 删除空的 `broker/alpaca/` 目录；
   - 重写 `.env.example`：只保留附录 A 中的变量，删掉 `ALPHABRIEF_LIVE_TRADING_ENABLED`。
5. 新建 `alphabrief_core.paths`；`ALPHABRIEF_HOME` 必须是绝对路径。
6. 新建 `scripts/secret_scan.py`：扫描已跟踪文件中的 OANDA token、`sk-` key、账户 ID 等形态的字符串（测试夹具中的假值需在白名单里明确列出）；本地存在 `.env` 时，额外确认真实值不在任何已跟踪文件中。
7. 新建 `.github/workflows/ci.yml`（ubuntu-latest，Python 3.12）：`pip install -e '.[dev]'` → `ruff check .` → `mypy` → `pytest -q -m "not practice"` → `python scripts/secret_scan.py`。

**退出标准**：
- `ruff check .`、`mypy` 通过；
- `pytest -q -m "not practice"` 0 失败；
- `python scripts/secret_scan.py` 退出码 0；
- `grep -rn -i "alpaca" packages apps tests config .env.example` 只剩下"禁止 Alpaca"的约束测试；
- 推送前 CI 配置已在本地用相同命令验证；
- 记录删除前后的源码行数（`find packages apps -name '*.py' | xargs cat | wc -l`）。

**产物**：更精简的代码库；CI 配置。

### S2 模型通道

**目标**：两个模型通道都真实可用，调用全量记录。

**任务**：
1. 实现 `chatgpt_plan` 适配器和 OAuth 流程（4.5），提供 `alphabrief model login | status | logout | test`。
2. 实现 `openai_compatible` 适配器、`opencode.ai` 拒绝规则、`fallback_enabled` 开关。
3. 让 `ModelGateway` 记录完整的调用信息（4.5 的"调用记录"）；委员会构建时必须传入记录器。
4. 用 `httpx.MockTransport` 或本地假服务器为 OAuth 和 Responses 流式解析写确定性测试（覆盖成功、过期刷新、429、503、401、unsupported_capability），再加一个 `practice` 标记的真实调用测试。
5. 完成登录命令后，如果还没有凭证，把 STATUS 置为 `WAITING_OWNER_LOGIN`，在"需要用户做的事"中写明：在终端运行 `alphabrief model login` 并在浏览器点授权。**这是整个项目唯一的一次人工操作。** 等待期间继续做 S1 遗留项或 S6 前端等不依赖模型的任务。

**退出标准**：
- `alphabrief model status` 显示主通道已授权、`chatgpt.tokens.use.direct` 已授予、默认模型已从目录中选定；
- `alphabrief model test --json` 真实返回一个通过本地严格解析的 JSON 对象，调用记录已落库（通道、模型、耗时、用量）；
- 备用通道：配置了就做同样的验证；没配置就在 STATUS 记录"未配置"，不算失败。

### S3 打通一单（垂直切片）

**目标**：EUR_USD 上跑通一轮真实委员会 → 一笔真实的 OANDA 模拟单 → 对账干净。

**任务**：
1. 接入 OANDA K 线和报价（`candles.py`、`pricing.py`），写进单一数据库。
2. 接入 `order_ops.py` + `orders.py` 下单（带符号整数 units、`stopLossOnFill`、`takeProfitOnFill`、`clientExtensions`）；删除 `adapter.py` 的旧下单路径。
3. 接入 `transaction_cursor.py` 和新的对账逻辑（5.9 的可解释差异）。
4. 提供 `alphabrief cycle run --once --instrument EUR_USD --units 1000 --trading on`。它跑完整的委员会，但用固定的 1000 units 覆盖仓位计算，作为首单安全措施。
5. 如果委员会给出 `no_trade`，允许用 `--force-direction long --reason "S3 vertical slice"` 跑一次。这笔订单仍然必须经过 RiskGate 并持久化决策，只有方向由命令行指定，委员会的真实输出照常落库。这是验证管道的唯一例外，不得在其他地方使用。
6. 成交后立即运行对账；然后用 `alphabrief cycle close --instrument EUR_USD` 平仓，再对账。

**退出标准**：
- OANDA 账户的 `lastTransactionID` 增加，新增流水中包含 `ORDER_FILL` 以及挂上的止损单和止盈单；
- 数据库里能从轮次 ID 一路追到：委员会发言 → 决策 → 风控决策 → 意图 → OANDA 订单 ID → 成交流水 ID → 平仓流水 ID；
- 平仓后对账干净、没有冻结；
- `pytest -m practice -k vertical_slice` 通过。

### S4 风控与决策补全

**目标**：第 5 节的规则全部真实生效。

**任务**：
1. 风控上下文改用真实账户、持仓、报价、本币换算（接入 `exposure_aggregation.py` 等）；删除伪造上下文的代码和全部 `data_quality_passed=True` 写死。
2. 实现 5.4 委员会协议、5.5 意图、5.6 仓位、5.7 全部规则、5.8 结果未知处理、5.10 平仓、kill switch（持久化状态，看板和 CLI 都能操作）。
3. 决策持久化改用真实哈希（配置文件内容、输入快照内容）。
4. 实现 5.11 影子评估、5.12 日报、5.13 预算。
5. 新闻：
   - 修正 `rss.py` 的来源标签；
   - 至少接入 3 个独立来源家族（建议 MarketWatch、FXStreet、ForexLive，以及 Fed、ECB、BoE 的官方新闻 RSS），只存元数据、哈希和短摘要；
   - 按货币相关性给新闻打标签，替代"每条新闻打全部品种"；
   - 接入 `ingestion.py`、`dedup.py`、`untrusted.py`。
6. 每条风控规则至少有一个通过用例和一个拒绝用例的确定性测试；仓位计算对 EUR_USD（报价货币为 USD）和 USD_JPY（报价货币为 JPY，需要换算）各有测试。

**退出标准**：
- `pytest -q -m "not practice"` 全绿；
- 在 `trading_mode=off` 下对 5 个品种跑一轮：`alphabrief cycle run --once --trading off`，产出 5 个品种的完整决策记录；风控结果中能看到真实的数据质量、敞口和点差数值；日报生成成功；
- `grep -rn "data_quality_passed=True" packages apps` 无输出（测试中显式构造的除外）。

### S5 常驻运行时

**目标**：单进程后台按时间表稳定运行，可安全重启。

**任务**：
1. 实现 `alphabrief run`：FastAPI 与调度器同进程；单实例文件锁；阻塞工作放进 `asyncio.to_thread`；每个任务都有超时。
2. 按 5.1 实现基于时钟的时间表，含补跑窗口；轮次阶段持久化，重启后从中断的阶段继续。
3. CLI 改为通过 HTTP 访问后台；后台不在线时只读。
4. 实现 `alphabrief service install|uninstall|status`（LaunchAgent `ai.alphabrief.backend`，开发模式下指向仓库 venv）。
5. 实现 `alphabrief doctor`（4.9）和 macOS 通知。
6. 实现备份和恢复命令（复用 `apps/api/src/alphabrief_api/db/backup.py` 已有的 `create_backup`、`verify_backup`、`restore_backup`、`apply_retention`），并为恢复写测试。

**退出标准**：
- 后台运行时，第二个 `alphabrief run` 立即以明确的错误退出；
- **重启实测**：在 `trading_mode=on`、固定 1000 units 的条件下，在"已提交、未对账"这个阶段注入 `kill -9`（用测试钩子 `ALPHABRIEF_TEST_CRASH_AT=after_submit`，仅限 practice 测试）。重启后：订单只存在一笔，`SUBMIT_UNKNOWN` 被正确解析，对账干净。记录 OANDA 流水 ID 作为证据，事后平仓；
- `alphabrief service install` 安装后，后台能完整跑完至少 1 个决策轮，期间同时使用 CLI 和看板，日志中没有 `Could not set lock`；
- `alphabrief doctor` 全部 PASS（防休眠项允许 WARN，并写进 STATUS）。

### S6 前端重写

**目标**：看板只展示真实数据，体验达到可发布水准。

**任务**：
1. 按 3.3 和 4.7 实现静态看板；补齐对应的 JSON API，包括轮次详情（含逐角色发言）、评估、风控状态、设置和引导页。
2. 实现引导页：凭证录入（写入 `secrets/`，只回显脱敏值）、ChatGPT 登录按钮（启动 4.5 的流程）、后台服务安装。
3. 删除 `routes/dashboard.py`。
4. 测试：
   - API 合约测试；
   - 用 Playwright（dev 依赖）做端到端冒烟：后端以 `trading_mode=off` 和临时数据目录启动，覆盖每个页面的 5 种状态、亮/暗色、4 个断点，并截图；
   - 用 axe-core 的可访问性检查，0 个 serious 或 critical 问题。

**退出标准**：
- Playwright 冒烟全绿；
- 生成 `docs/images/` 下的截图：每个主要页面亮色、暗色各一张，用于 README；
- 看板总览显示的 NAV 与 OANDA 账户摘要一致（practice 测试比对）；
- `grep -rn "Simulated sample\|100000" apps/api/src/alphabrief_api/static` 无输出。

### S7 保留模块接入真实数据

**目标**：回测、策略注册表、gym、复盘按 6.4 可用。

**退出标准**：
- `alphabrief backtest run --strategy momentum --instrument EUR_USD --from <90 天前>` 用数据库中的 OANDA K 线跑完，结果落库并在回测页可见；
- 已启用的一个示例策略的信号出现在委员会输入证据里；
- `alphabrief gym demo` 用 OANDA K 线跑完一个回合；
- 复盘页显示最近的日报；
- 以上都有测试。

### S8 打包

**目标**：生成可安装的 `.dmg`，安装后能完成引导并连上后台。

**任务**：
1. 加入 PyInstaller（dev 依赖）和 electron-builder（npm devDependency）；新建 `scripts/build_release.sh`：构建后端 → 构建 dmg → 生成 `SHA256SUMS.txt`。
2. 改造 `electron/main.js`：不再依赖源码目录；探测后台；托盘图标；设置页调用 `alphabrief service`。补上应用图标（`electron/build/icon.icns`，用项目自己的简单几何图形生成，不使用第三方商标）。
3. 冒烟测试：把 dmg 挂载到临时目录，**用临时数据目录、`trading_mode=off`、不安装 LaunchAgent** 启动打包好的后端，跑 `doctor` 和 API 健康检查，确认静态看板可以访问。冒烟测试绝不能和试运行的后台抢同一个账户的交易权。
4. 版本号统一为 `1.0.0-rc.N`（`pyproject.toml` 和 `electron/package.json`）。

**退出标准**：
- `scripts/build_release.sh` 产出 `dist/AlphaBrief-1.0.0-rc.N-arm64.dmg` 和校验和；
- 冒烟测试通过；
- 打包后端的 `alphabrief --version` 输出正确版本。

**兜底**：如果同一个打包问题修了 3 次还不行，就在 STATUS 记录阻塞，试运行改用 wheel + 独立 venv 的 LaunchAgent 方式（`alphabrief service install --runtime venv`），打包在试运行期间继续推进。打包问题不阻塞试运行开始。

### S9 试运行前门禁

**目标**：确认可以无人值守连续运行。

**任务**：
1. 以 RC 版本的后台（优先打包版本，兜底用 venv 版本）安装 LaunchAgent，`trading_mode=on`，**固定 1000 units**，连续运行 24 小时（至少覆盖 2 个决策轮）。
2. 期间至少发生 1 次真实开仓和平仓，或者在每一轮都有明确的 `no_trade` 原因。
3. 逐项检查第 9 节安全不变量和以下门禁清单。

**门禁清单**（全部满足才能进入 Day 0）：
- [ ] 24 小时内后台进程没有意外退出（LaunchAgent 重启计数为 0）
- [ ] 每个计划轮次都有记录（执行、`no_trade` 或 `MISSED_WINDOW`，并有原因）
- [ ] 对账全部干净，或冻结已按 5.9 自动解除
- [ ] 没有重复订单（`clientExtensions.id` 唯一）
- [ ] 每笔订单都能追到持久化的 RiskDecision
- [ ] 出站请求只访问 `api-fxpractice.oanda.com`、模型通道主机和配置的新闻/数据源（以请求日志为证）
- [ ] 日报生成成功，`doctor` 全部 PASS
- [ ] 模型调用成本或次数在预算内
- [ ] CI 全绿（最新提交已推送到 `origin/main`；S9 起允许推送 `main`，不允许创建 Release）

**退出标准**：门禁清单全部勾选 → 打 tag `v1.0.0-rc.<N>` 并推送 → 切换为按风险计算的仓位（前 3 天减半）→ 在数据库 `soak_runs` 表写入 Day 0 起始时间（UTC），STATUS 记录 Day 0。

### S10 14 天试运行

**目标**：连续 14 个合格自然日的真实无人值守运行。

**计日规则**（由 `alphabrief soak status` 从数据库事实计算，不能手写）：

- **合格日**（UTC 自然日）满足以下全部条件：
  - 后台累计停机 ≤ 6 小时；
  - 每个计划轮次都有记录；
  - 日终对账干净或冻结已按规则解除；
  - 日报已生成；
  - 没有发生重置事件。
- 周末不跑决策轮，只要求同步、对账、日报正常。
- **不合格日但没有安全问题**（例如新闻源全天失败导致全部 `no_trade` 但记录完整，或停机 6–12 小时）：试运行顺延 1 天，最多顺延 3 次，超过 3 次就重置。
- **重置事件**（试运行从新的 Day 0 开始，并在 STATUS 写明原因）：
  - 出现重复订单；
  - 有订单没有对应的持久化 RiskDecision；
  - 向白名单以外的主机发出请求，或访问 live 主机；
  - 无法解释的对账差异持续超过 1 个对账周期仍未冻结；
  - 单日停机超过 12 小时；
  - 修改了安全或执行语义（第 9 节相关代码、RiskGate、下单、对账）并部署到运行中的后台。

**Agent 在试运行期间的工作**：
1. 大约每 24 小时巡检一次（建议 UTC 22:30，日报之后）：
   - 运行 `alphabrief soak status` 和 `alphabrief doctor`；
   - 阅读当天日报；
   - 把一行摘要写进 STATUS 的试运行日志（日期、合格与否、订单数、盈亏、异常）。
2. **不影响安全的问题**（界面、日报格式、新闻源适配、日志等）：
   - 在 `main` 上修复、测试、提交；
   - 需要部署到运行中后台的，构建新 RC → `alphabrief service install` 重新部署 → 记录"热修复 rcN→rcN+1，原因，停机 X 分钟"；天数继续计算。
3. **安全问题**：系统应已自动冻结。Agent 调查原因、修复、按重置规则重新开始，并写清楚经过。
4. 试运行期间并行完成发布材料：README 草稿、截图、CHANGELOG、试运行报告生成器（`alphabrief report soak`）。

**等待方式**：每次巡检后，在 STATUS 写好"下次巡检时间"，然后：
- 工具支持定时唤醒就设置约 24 小时后唤醒；
- 不支持就结束本次会话，等待下一次以同一提示词启动。

**禁止**：忙等、循环 `sleep` 占住会话、修改系统时间、伪造或回填任何一天。

**退出标准**：`alphabrief soak status` 显示 `qualified_days=14`，且没有未解决的冻结或阻塞。

### S11 发布

**目标**：发布 v1.0.0。

**任务**：
1. `alphabrief report soak --final` 从数据库生成 `reports/soak-report-v1.0.0.md`（仓库内）。内容包括：
   - 时间范围、合格日、顺延和重置记录；
   - 订单、成交、盈亏、回撤；
   - 风控拒绝分布、冻结事件；
   - 模型调用和成本；
   - 影子评估结果（含置信区间和"样本不足"声明）；
   - 热修复列表；
   - 已知限制。

   账户 ID 必须脱敏。
2. 确认发布代码与试运行最后一个 RC 的运行时代码一致：`git diff --stat v1.0.0-rc.<last>..HEAD -- packages apps/cli apps/api/src/alphabrief_api/*.py apps/api/src/alphabrief_api/routes apps/api/src/alphabrief_api/db` 必须为空。只允许修改文档、README、截图、CHANGELOG、静态前端文案和版本号。
3. 版本号改为 `1.0.0`；新建 `CHANGELOG.md`；重写 README：
   - 英文为主，附中文节；
   - 截图、安装方法、首次打开未签名应用的方法；
   - 架构图、试运行结果摘要、已知限制、免责声明；
   - 不要写夸大或无法证实的说法。
4. 运行 `scripts/build_release.sh` 生成正式 dmg 和校验和；做一次 S8 同样的冒烟测试。
5. 发布前安全检查：
   - `python scripts/secret_scan.py --history`（扫描完整 git 历史，并与本地真实密钥值比对）通过；
   - `git status` 干净；
   - CI 全绿。
6. 打 tag `v1.0.0` → `git push origin main --tags` → `gh release create v1.0.0 dist/AlphaBrief-1.0.0-arm64.dmg dist/SHA256SUMS.txt reports/soak-report-v1.0.0.md --title "AlphaBrief v1.0.0" --notes-file <从 CHANGELOG 生成的说明>`。
7. STATUS 置为 `RELEASED`，附 Release 链接。

**退出标准**：`gh release view v1.0.0` 能看到 3 个附件；CI 全绿；第 10 节全部勾选。

---

## 8. Agent 自主协议

### 8.1 每一步

- 一次只做一项任务。完成后运行与改动相关的测试，阶段收尾时运行全量测试；更新 STATUS；提交一次。
- 提交信息格式：`S<阶段>: <做了什么>`；正文写验证命令和结果摘要。
- 只在 `main` 上工作，不创建其他分支。不 force-push，不改写已推送的历史，不使用 `git reset --hard`，不使用 `git clean`。
- **推送**：S1 至 S8 只在本地提交；S9 起允许推送 `main` 和 RC tag；只有 S11 允许创建 GitHub Release。

### 8.2 决策与歧义

- 本文件有默认值就用默认值。
- 本文件没覆盖的情况：选择更安全的方案（不交易、冻结、失败即停、缩小权限），在 STATUS"决策记录"中写下一行"日期 / 问题 / 选择 / 理由"，然后继续。
- 不向用户提问。唯一的例外是第 8.4 节列出的外部前提。

### 8.3 失败与重试

- 外部请求：GET 最多自动重试 2 次；非幂等请求从不盲目重试。
- 同一个失败特征最多修复 3 轮。仍然失败时，在 STATUS"阻塞"中记录（现象、尝试过的方法、怀疑的原因），转去做同阶段或后续阶段中不依赖它的任务。
- 所有剩余任务都依赖阻塞项时，STATUS 置为 `BLOCKED` 并结束。

### 8.4 只有这几种情况需要用户

1. `WAITING_OWNER_LOGIN`：ChatGPT 授权（S2，一次）。
2. OANDA 凭证缺失或失效。
3. 网络完全不可用。
4. `gh` 未登录或没有推送权限（只阻塞 S9 之后的推送和 S11）。
5. 本机长时间休眠导致试运行反复重置（需要用户保持接电源、不休眠）。

遇到时，在 STATUS"需要用户做的事"中写一行明确的指令，继续做其他不依赖它的任务；全部被阻塞时结束会话。

### 8.5 绝对禁止

- 伪造日期、成交、订单、证据、天数；把模拟或回放结果说成真实运行结果。
- 为了让测试变绿而删除测试、加 `skip`/`xfail`、放宽断言、缩小测试命令范围、禁用 lint 或类型规则。新增 `# noqa` 或 `type: ignore` 时必须在同一行写明理由。
- 引入实盘 URL、实盘开关、其他券商。
- 打印、提交、截图任何密钥或完整账户 ID。
- 修改系统设置（`pmset`、防火墙、系统时间等），或操作与 AlphaBrief 无关的服务和文件。
- 直接从 `_reference_sources/` 复制代码、提示词或结构。
- 再创建新的路线图、阶段计划、开发日志类文档。所有进度只写 STATUS；所有规格只改本文件。

### 8.6 本文件的修改

- 实现过程中发现本文件有错误（例如某个 API 行为与官方文档或实测不符），可以修改本文件，但必须在同一个提交里更新 STATUS 的决策记录，并写明证据。
- 第 9 节安全不变量和第 5.7 节风控数值**只能收紧，不能放宽**。

---

## 9. 安全不变量

1. **只用 OANDA 模拟盘**：执行代码只能访问 `api-fxpractice.oanda.com` 和 `stream-fxpractice.oanda.com`。
2. **没有实盘路径**：没有实盘 URL、实盘模式、账户环境切换开关，也没有"以后接实盘"的占位代码。
3. **只用 OANDA**：没有 Alpaca、没有券商路由；确定性的假券商只能存在于测试中。
4. **没有静默模拟回退**：凭证缺失时失败即停；产品绝不把内存成交当作 OANDA 成交展示。
5. **先风控后执行**：每笔订单必须经过 `决策 → OrderIntent → RiskGate → 持久化的 RiskDecision → OANDA`。平仓也必须经过精简检查并持久化。
6. **模型没有权限**：模型、提示词、新闻、网页内容都是不可信输入，不能修改风控阈值、提示词、凭证、调度，也不能直接调用券商。
7. **只经过 ModelGateway**：业务模块不得直接调用模型接口；不静默切换计费通道。
8. **密钥不外泄**：密钥只来自 `secrets/` 或环境变量，不打印、不持久化到日志或报告、不截图、不提交。
9. **幂等与对账**：重试、重启、补跑都不能产生重复订单；对账以券商状态为准；无法解释的差异立即冻结新开仓。
10. **不强制交易**：`no_trade` 是合法结果，不为凑活跃度而下单。
11. **时间是真实的**：试运行天数只能来自真实时间流逝，不能伪造、回填或加速。
12. **单一交易运行时**：同一 OANDA 账户同一时间只有一个后台处于 `trading_mode=on`。

---

## 10. v1.0.0 完成定义

以下全部满足，STATUS 才能置为 `RELEASED`：

**代码与质量**
- [ ] 第 6 节删除项全部删除；第 6.3 节每个关注点只有一份实现
- [ ] `ruff check .`、`mypy`、`pytest -q -m "not practice"` 全部通过；GitHub Actions 在 `main` 上为绿
- [ ] `pytest -m practice` 在本机全部通过（含 S3 垂直切片、S5 重启实测、S6 NAV 比对）
- [ ] `scripts/secret_scan.py --history` 通过

**功能**
- [ ] 第 3.2 节功能清单全部可用，第 3.3 节页面全部显示真实数据
- [ ] 第 5.7 节 14 条风控规则都有通过和拒绝两类测试
- [ ] 主模型通道可用；备用通道行为符合 4.5（未开启时绝不使用）

**真实运行**
- [ ] S9 门禁清单全部勾选
- [ ] `alphabrief soak status` 显示 14 个合格日；重置和顺延都有记录和原因
- [ ] 试运行期间：重复订单 0、没有 RiskDecision 的订单 0、白名单外出站请求 0、live 访问 0
- [ ] 试运行报告已生成并提交，数字可以从数据库复算

**发布**
- [ ] `v1.0.0` tag 和 GitHub Release 已创建，附 dmg、校验和、试运行报告
- [ ] README（英文 + 中文节）包含截图、安装、首次打开方法、架构、试运行摘要、已知限制、免责声明
- [ ] `CHANGELOG.md` 存在；`pyproject.toml` 和 `electron/package.json` 版本为 `1.0.0`
- [ ] STATUS 记录 Release 链接，状态为 `RELEASED`

---

## 11. 附录

### A. 环境变量（`.env.example` 的最终内容）

| 变量 | 必需 | 说明 |
|---|---|---|
| `ALPHABRIEF_HOME` | 否 | 数据目录绝对路径；默认 `~/Library/Application Support/AlphaBrief` |
| `ALPHABRIEF_OANDA_TOKEN` | 是（也可以通过引导页写入 `secrets/`） | OANDA practice token |
| `ALPHABRIEF_OANDA_ACCOUNT_ID` | 是（同上） | OANDA practice 账户 ID |
| `ALPHABRIEF_TRADING_MODE` | 否 | `off`（默认）或 `on` |
| `ALPHABRIEF_PORT` | 否 | 后台端口，默认 8765 |
| `ALPHABRIEF_LLM_BASE_URL` | 否 | 备用通道地址（OpenAI 兼容），不能是 `opencode.ai` |
| `ALPHABRIEF_LLM_API_KEY` | 否 | 备用通道 key |
| `ALPHABRIEF_LLM_MODEL` | 否 | 备用通道模型名 |
| `FRED_API_KEY` | 否 | 宏观数据；没有时用新闻冲击过滤 |
| `ALPHABRIEF_LOG_LEVEL` | 否 | 默认 `INFO` |

ChatGPT 订阅凭证不走环境变量，只通过 `alphabrief model login` 写入 `secrets/`。

### B. 数据目录布局

```
~/Library/Application Support/AlphaBrief/
  alphabrief.duckdb          唯一数据库
  runtime.lock               数据目录单实例锁
  account-locks/             账户哈希锁，固定在默认应用支持目录，不随 ALPHABRIEF_HOME/ALPHABRIEF_DATA_DIR 覆盖迁移
  secrets/                   0600：oanda.json、llm_fallback.json、chatgpt_oauth.json
  logs/                      结构化 JSON 日志（按天）
  reports/daily/             日报 .md / .json
  backups/                   日备份 14 份 + 周备份 8 份
  cache/                     可删除的缓存
```

### C. STATUS.md 规则

- 只有一个"当前阶段"和一个"状态"：`READY | IN_PROGRESS | WAITING_OWNER_LOGIN | BLOCKED | SOAKING | RELEASED`。
- 各阶段的检查表来自第 7 节的任务和退出标准；勾选时写日期、提交哈希、证据摘要。
- 证据摘要必须是命令加结果（例如 `lastTransactionID 3→11, ORDER_FILL id=7`），不能只写"已完成"。
- 决策记录、阻塞、需要用户做的事、试运行日志，各自是一个列表，只追加不改写。

### D. 试运行报告模板（`alphabrief report soak --final` 生成）

```
# AlphaBrief v1.0.0 Soak Report
Period (UTC) / Qualified days / Extensions / Resets (with reasons)
Runtime: versions (rc tags), hotfixes, total downtime
Account: start NAV, end NAV, max drawdown, realized P&L, trades, win rate
Orders: submitted / filled / rejected / SUBMIT_UNKNOWN resolved
Risk: rejections by rule, freezes and resolutions
Models: calls by channel, failures by code, estimated cost
Shadow evaluation: per baseline n / mean 4h & 24h return / 95% CI
Safety invariants: duplicate orders 0, orders without RiskDecision 0, off-allowlist requests 0
Known limitations
Disclaimer: practice account only, not financial advice, sample too small to infer edge
```

### E. 外部权威文档

- OANDA v20：
  - [账户与品种](https://developer.oanda.com/rest-live-v20/account-ep/)
  - [订单定义](https://developer.oanda.com/rest-live-v20/order-df/)
  - [订单接口](https://developer.oanda.com/rest-live-v20/order-ep/)
  - [交易](https://developer.oanda.com/rest-live-v20/trade-ep/)
  - [持仓](https://developer.oanda.com/rest-live-v20/position-ep/)
  - [流水](https://developer.oanda.com/rest-live-v20/transaction-ep/)
  - [报价](https://developer.oanda.com/rest-live-v20/pricing-ep/)
  - [基础类型](https://developer.oanda.com/rest-live-v20/primitives-df/)
  - [账户同步最佳实践](https://developer.oanda.com/rest-live-v20/best-practices/)
  - [开发指南与限流](https://developer.oanda.com/rest-live-v20/development-guide/)
- OpenAI "Sign in with ChatGPT"（开源应用使用订阅额度）：
  - [概览](https://developers.openai.com/siwc/token-sharing-open-source)
  - [注册与登录](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
  - [模型与推理](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
  - [错误与恢复](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery)
  - [预览限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
  - [UI/UX 指南](https://developers.openai.com/siwc/ui-ux-guidelines)
- OpenCode Go 的使用范围说明（为什么不能作为产品后端）：[文档](https://opencode.ai/docs/go/)

实现时以官方文档和真实响应为准。发现与本文件不一致时，按 8.6 修改本文件。

### F. 已删除的旧文档

以下文档已于 2026-09-30 删除，内容如需查阅请看 git 历史：

- `ALPHABRIEF_PRODUCT_BLUEPRINT.md`
- `docs/architecture.md`
- `docs/acceptance.md`
- `docs/autonomous_loop.md`
- `docs/oanda_30_day_runbook.md`
- `docs/progress.yaml`
- `docs/work_items.yaml`
- `docs/development_ledger.ndjson`

它们描述的里程碑 M00–M17 中，标记为 DONE 的工作大多只是"合同代码"，没有对应的真实运行证据。**不要把这些里程碑当成已完成的事实。**
