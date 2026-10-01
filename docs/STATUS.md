# AlphaBrief 状态

> 这是全项目唯一的可变状态文件。规则见 [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md) 附录 C。
> 勾选任务时写明日期、提交哈希和证据摘要（命令加结果，不含密钥或完整账户 ID）。
> 决策记录、阻塞、需要用户做的事、试运行日志都只追加，不改写。

## 当前

| 字段 | 值 |
|---|---|
| 当前阶段 | **S2 模型通道** |
| 状态 | `WAITING_OWNER_LOGIN` |
| 下一项任务 | S3-2 `order_ops` + `orders` 下单路径（S3-4 的委员会垂直切片仍需 S2-5 授权） |
| 下次巡检时间（UTC） | 不适用（尚未进入试运行） |
| 试运行 | 未开始；合格日 0 / 14；顺延 0；重置 0 |
| 最近更新 | 2026-09-30，S2-1 至 S2-4 完成，等待用户完成一次 ChatGPT 授权 |

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

#### S3 证据（进行中）

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
- [ ] S2-5 用户完成 ChatGPT 授权
- [ ] 退出标准：`model status` 主通道已授权；`model test --json` 真实通过并落库（等 S2-5）

### S3 打通一单
- [x] S3-1 OANDA K 线和报价入库
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

- **（现在需要，只此一次）** 在项目目录下运行 `.venv/bin/alphabrief model login`，浏览器会自动打开 OpenAI 授权页，点一次同意即可。完成后把终端输出贴给我，或直接让我继续（我会用 `alphabrief model status` 自查）。若浏览器没有自动打开，终端会打印授权 URL，手动打开同样可以。
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
