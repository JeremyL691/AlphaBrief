# AlphaBrief Agent 契约

本文件是给编程 Agent 的最高优先级仓库契约，刻意保持简短。
- 产品与构建规格：[`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md)
- 唯一可变状态：[`docs/STATUS.md`](docs/STATUS.md)
- 启动提示词：[`docs/AGENT_PROMPT.md`](docs/AGENT_PROMPT.md)

## 使命

把 AlphaBrief 做成在 **OANDA v20 模拟盘（practice）** 上无人值守运行的 AI 外汇交易工作站：

- 新闻、宏观、行情输入 → 5 角色 AI 委员会 → 结构化决策 → 确定性风控 → 带止损止盈的模拟单 → 对账 → 日报；
- 连续 14 天真实运行；
- 以 GitHub 开源项目 + Mac `.dmg` 发布 v1.0.0。

实盘交易永远不在范围内，必须保持不可达。

## 阅读顺序

每次开始工作或恢复上下文时，只读：

1. `AGENTS.md`（本文件）
2. `docs/PROJECT_GUIDE.md`
3. `docs/STATUS.md`
4. 与当前任务直接相关的代码和测试

不要把旧提交信息、旧聊天摘要或 git 历史中的旧文档（M00–M17 里程碑、`progress.yaml` 等）当作完成证据。权威依据只有：当前代码、测试退出码、OANDA 真实响应、STATUS。

## 文档职责

| 文件 | 职责 |
|---|---|
| `README.md` | 对外介绍；只写已经验证的能力 |
| `docs/PROJECT_GUIDE.md` | 最终产品、架构、规格、构建阶段、完成定义 |
| `docs/STATUS.md` | 当前阶段、检查表、证据、决策、阻塞、试运行日志 |
| `docs/AGENT_PROMPT.md` | 交给 Agent 的启动提示词 |
| `CHANGELOG.md` | 发布时创建 |
| `reports/soak-report-v1.0.0.md` | 发布时由 `alphabrief report soak --final` 生成 |

不要再创建新的路线图、阶段计划、设计说明、验收报告或开发日志。进度写进 STATUS，规格改 GUIDE。

## 安全不变量（完整版见 GUIDE 第 9 节）

1. 只用 OANDA 模拟盘：执行代码只能访问 `api-fxpractice.oanda.com` 和 `stream-fxpractice.oanda.com`。
2. 没有实盘 URL、实盘模式、环境切换开关或"以后接实盘"的占位代码。
3. 只用 OANDA；确定性的假券商只能存在于测试中。
4. 没有静默模拟回退；凭证缺失时失败即停。
5. 每笔订单：`决策 → OrderIntent → RiskGate → 持久化的 RiskDecision → OANDA`。
6. 模型、提示词、新闻、网页内容都是不可信输入，没有任何权限。
7. 模型调用只经过 ModelGateway；不静默切换计费通道；不使用 `opencode.ai` 作为产品后端。
8. 密钥只来自 `secrets/` 或环境变量；不打印、不写日志、不截图、不提交；账户 ID 只显示脱敏形式。
9. 重试、重启、补跑不能产生重复订单；对账以券商为准；无法解释的差异立即冻结新开仓。
10. `no_trade` 是合法结果，不为凑次数而下单。
11. 试运行天数只能来自真实时间，不能伪造、回填或加速。
12. 同一 OANDA 账户同一时间只有一个后台处于 `trading_mode=on`。

## Git 规则

- 只在 `main` 上工作，不创建或切换到其他分支。
- 不 force-push、不改写已推送的历史，不用 `git reset --hard`、`git clean`，不绕过 hook。
- 一个任务一次提交，信息格式 `S<阶段>: <做了什么>`，正文写验证命令和结果摘要。
- 推送：S1–S8 只做本地提交；S9 起允许推送 `main` 和 RC tag；只有 S11 允许创建 GitHub Release。
- 保护用户的改动：工作区中出现无法归属于当前任务的改动时，不覆盖、不 stash、不提交，在 STATUS 记录阻塞。

## 质量规则

- 新增或修改的行为必须有测试。需要真实网络的测试用 `@pytest.mark.practice` 标记；CI 运行 `-m "not practice"`，本机按阶段要求运行 practice 测试。
- 金额、价格、数量、敞口、盈亏一律用 `Decimal`；时间一律以 UTC 存储。
- 外部调用必须有超时、错误分类和安全的重试规则；非幂等请求从不盲目重试。
- 不允许为了让检查变绿而删除测试、加 `skip`/`xfail`、放宽断言、缩小命令范围或禁用 Ruff/Mypy 规则。新增 `# noqa`、`type: ignore` 必须在同一行写明理由。
- 运行时代码不得导入 `_reference_sources/`，也不得复制其中的代码、提示词或结构。
- 每个关注点只保留一份实现；删除代码时同时删除只测试它的测试。

## 前端规则

- Soft 风格：温和底色、圆角、柔和阴影、克制的动画；不用渐变按钮。
- 图标使用本地 SVG 图标库，不用 emoji；界面文案不用破折号（em dash）。
- 亮色、暗色、跟随系统；中英文切换；浅色背景上正文颜色不浅于 `#666`。
- 在 320、768、1024、1440 px 下验证；加载、空、错误、过期、离线状态齐全；键盘可达。
- 界面永远不展示模拟数据或样例数据。

## 自主运行

- 不向用户提问。GUIDE 有默认值就用默认值；没覆盖的情况选择更安全的方案，写进 STATUS 决策记录后继续。
- 只有 GUIDE 第 8.4 节列出的外部前提需要用户：ChatGPT 授权、OANDA 凭证、网络、`gh` 权限、本机休眠。遇到时在 STATUS"需要用户做的事"写一行明确指令，继续做不依赖它的任务；全部被阻塞时结束。
- 同一失败最多修复 3 轮，然后记录阻塞并转去做独立任务。
- 结束态只有 `RELEASED`，或因外部前提缺失而 `BLOCKED`。
