# AlphaBrief 状态

> 这是全项目唯一的可变状态文件。规则见 [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md) 附录 C。
> 勾选任务时写明日期、提交哈希和证据摘要（命令加结果，不含密钥或完整账户 ID）。
> 决策记录、阻塞、需要用户做的事、试运行日志都只追加，不改写。

## 当前

| 字段 | 值 |
|---|---|
| 当前阶段 | **S1 做减法与恢复全绿** |
| 状态 | `IN_PROGRESS` |
| 下一项任务 | S1-5 `alphabrief_core.paths`（只接受绝对路径） |
| 下次巡检时间（UTC） | 不适用（尚未进入试运行） |
| 试运行 | 未开始；合格日 0 / 14；顺延 0；重置 0 |
| 最近更新 | 2026-09-30，S1-1 至 S1-3 完成，测试全绿（见"S1 证据"） |

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
- [ ] S1-5 `alphabrief_core.paths`（只接受绝对路径）
- [ ] S1-6 `scripts/secret_scan.py`
- [ ] S1-7 `.github/workflows/ci.yml`
- [ ] 退出标准：ruff、mypy、`pytest -m "not practice"` 全绿；密钥扫描通过；记录删除前后的行数

#### S1 证据（进行中）

- S1-0（S0 完成提交回填）：S0 的检查表、证据与决策已随提交 `5b56d0e` 落库。
- S1-1（提交 `e58f444`）：
  - 删除：`alphabrief-acceptance`、`alphabrief-research` 两个整包；core 的 6 个观察期模块；8 个 CLI 命令组（`model` 组在 S2 重写）；5 个 API 路由与 `db/writer_lease`；`scheduler_leader`；models 的 kronos/router/registry/quality_gate/briefs/daily/evaluation/prompts/evaluation_datasets；data 的 3 个联网 provider；news 的 sec_edgar/social_sentiment（mock 移到 `tests/news_mock_provider.py`）；运行时的 PaperBroker 与 fills/portfolio/router；未挂载的 `dashboard/` 包；`scripts/deployment`、`notebooks`、`strategies`。
  - 改造：`DailyTradingCycle`/`DurableDailyCycle` 的 `broker` 参数改为必需的 `execution_backend`；scheduler、API `ai_trading`、`ai` CLI 一律走 `ExternalPaperExecutionBackend`（缺凭证即停，无内存兜底）；scheduler 默认品种改为 FX 五大货币对，删除 research_content 任务、Yahoo 行情摄取、observation JSON 导出；news/macro 只保留 `rss` 与 `fred`；`alphabrief_risk.context` 改用 `NewsMacroSource` 协议，摘要构建器迁到 `alphabrief_news.context_summary`。
  - 新增测试替身 `tests/_helpers/fake_execution_backend.py`（确定性假券商只存在于测试中）。
  - 命令与结果：`ruff check .` → All checks passed；`mypy` → Success: no issues found in 386 source files；`pytest -q -m "not practice"` → 2288 passed / 28 failed（当时剩余失败全部属于 S1-2 与 S1-3 的范围）。
  - 行数：`find packages apps -name '*.py' | xargs cat | wc -l` 73915 → 55005；`find tests -name '*.py' | xargs cat | wc -l` 64394 → 48912；`git ls-files | wc -l` 576 → 424。
- S1-2（提交 `2fea812`）：`test_risk_currency_aggregation.py`、`test_risk_exposure_matrix.py` 的 `_snapshot()` 传入 `clock=lambda: NOW`；`routes/macro.py` 与 `macro_commands.py` 增加可替换的 `_now()`；两个 macro 测试注入 `NOW` 并把 stale 样本时间改为由 `NOW` 推导；全仓库扫描后仅 `test_risk_execution_paths.py` 的假券商快照保留墙钟（默认 builder 的实时性语义，已写明原因）。命令与结果：`pytest -q -m "not practice"` → 2309 passed / 7 failed（仅剩 scaffold）；`mypy` → Success。
- S1-4（本提交）：`.env.example` 重写为附录 A 的变量集合（删除 `ALPHABRIEF_LIVE_TRADING_ENABLED`、`ALPHAVANTAGE_API_KEY`、`OPENAI_*` 与过时的 `ALPHABRIEF_AI_*`）；删除已经不再门控任何行为的 `is_ai_external_paper_enabled`；`config/paper_execution_policy.yaml` 的品种收窄为五个 FX 主要货币对、`market: fx`；清理 `port.py`、`routes/broker.py` 与相关测试里的 Alpaca 注释。`grep -rn -i "alpaca" packages apps tests config .env.example` 只剩 6 处，全部是"禁止 Alpaca/其他券商"的约束测试与安全门（`broker/safety.py` 的禁用导入段、两条 provider 拒绝用例、electron 安全断言）。命令与结果：`pytest -q -m "not practice"` → 2312 passed / 0 failed；`mypy` → Success；`ruff check .` → All checks passed。
- S1-3：重写 `tests/test_project_scaffold.py`，检查 `AGENTS.md`、`docs/PROJECT_GUIDE.md`、`docs/STATUS.md`、`docs/AGENT_PROMPT.md` 存在，`docs/` 只有这四个（含 `images`），已删除的旧文档与旧目录确实不存在，STATUS 只有一个当前阶段与状态，markdown 本地链接可解析。命令与结果：`pytest -q -m "not practice"` → 2315 passed / 0 failed；`mypy` → Success: no issues found in 386 source files；`ruff check .` → All checks passed。

### S2 模型通道
- [ ] S2-1 `chatgpt_plan` 适配器与 OAuth（`alphabrief model login|status|logout|test`）
- [ ] S2-2 `openai_compatible` 备用适配器、拒绝 `opencode.ai`、`fallback_enabled` 开关
- [ ] S2-3 完整的调用记录；委员会构建时传入记录器
- [ ] S2-4 确定性测试，加一个 practice 测试
- [ ] S2-5 用户完成 ChatGPT 授权
- [ ] 退出标准：`model status` 主通道已授权；`model test --json` 真实通过并落库

### S3 打通一单
- [ ] S3-1 OANDA K 线和报价入库
- [ ] S3-2 `order_ops` + `orders` 下单（止损止盈、带符号整数 units、clientExtensions）；删除旧下单路径
- [ ] S3-3 流水游标与新对账逻辑
- [ ] S3-4 `alphabrief cycle run --once --instrument EUR_USD --units 1000 --trading on`
- [ ] S3-5 平仓与对账
- [ ] 退出标准：`lastTransactionID` 增加并有 `ORDER_FILL` 和止损止盈单；全链路可追溯；对账干净

### S4 风控与决策补全
- [ ] S4-1 真实风控上下文；删除伪造上下文和写死的 `data_quality_passed=True`
- [ ] S4-2 委员会协议、意图、仓位、14 条规则、结果未知处理、平仓、kill switch
- [ ] S4-3 真实的策略版本哈希和输入哈希
- [ ] S4-4 影子评估、日报、预算
- [ ] S4-5 新闻：3 个以上来源家族、按货币打标签、入库、去重、清洗
- [ ] S4-6 每条规则都有通过和拒绝测试；EUR_USD 和 USD_JPY 的仓位测试
- [ ] 退出标准：`cycle run --once --trading off` 跑完 5 个品种，日报生成；不再有写死的 `data_quality_passed=True`

### S5 常驻运行时
- [ ] S5-1 `alphabrief run`（单进程、单实例锁、`to_thread`、超时）
- [ ] S5-2 按时钟的时间表、补跑窗口、阶段持久化
- [ ] S5-3 CLI 走 HTTP；后台不在线时只读
- [ ] S5-4 `alphabrief service install|uninstall|status`
- [ ] S5-5 `alphabrief doctor`、macOS 通知
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

- （S2 到达时）在终端运行 `alphabrief model login`，在浏览器点授权。整个项目只需要这一次。
- （长期）试运行期间保持 Mac 接电源、不休眠（目前由 Amphetamine 保证）。
- （可选）如果想启用备用模型通道：提供一个按量付费的 OpenAI 兼容 key（例如 DeepSeek 官方），写入 `.env` 的 `ALPHABRIEF_LLM_BASE_URL`、`ALPHABRIEF_LLM_API_KEY`、`ALPHABRIEF_LLM_MODEL`，并在配置中开启 `model.fallback_enabled`。
- （可选）申请免费的 `FRED_API_KEY` 以启用宏观日历；没有也能运行（会用新闻冲击过滤代替）。

## 决策记录

| 日期 | 问题 | 选择 | 理由 |
|---|---|---|---|
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
| 2026-09-30 | S0-3 探测脚本放哪里 | 临时脚本放 `/tmp/alphabrief_s0_probe.py`，不进仓库 | 避免为一次性检查新增代码；同类检查在 S5 由 `alphabrief doctor` 正式实现并测试 |

## 阻塞

（无）

## 试运行日志

| 日期（UTC） | 合格 | 订单 / 成交 | 当日盈亏 | NAV | 异常与处理 | 版本 |
|---|---|---|---|---|---|---|
