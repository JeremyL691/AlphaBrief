# 0023 CLI + OpenAI Provider Adapter

## TL;DR
> **Summary**: 实现 typer CLI（9 个命令）覆盖全部 5 个 MVP 阶段内核功能，同时添加 OpenAI 云 Provider 适配器使 DailyAlphaBrief 生成器可调用真实云端模型。
> **Deliverables**: CLI 入口点 `alphabrief` + 9 个子命令 + OpenAIProviderAdapter + 完整测试
> **Effort**: Medium
> **Parallel**: YES - 2 waves (CLI 命令可并行开发，OpenAI 适配器独立)
> **Critical Path**: CLI scaffold → 各子命令并行 → OpenAI 适配器 → 集成测试

## Context
### Original Request
"计划下一轮的开发" → 选择 CLI 命令行界面 + 一个云 Provider 适配器

### Current State
- 5 个 MVP 阶段全部完成（Core、ModelGateway、Risk+Paper、TradingEnv、ReviewCenter）
- `apps/` 目录完全为空，无 CLI/API/Web 代码
- `strategies/` 目录仅含 `.gitkeep`
- 仅有一个真实 Provider 适配器：`OllamaProviderAdapter`（本地）
- 所有功能仅可通过 Python API 调用，无用户界面
- 205 个测试全部通过，ruff + mypy 严格模式通过

### Constraints
- CLI 是薄封装层，不包含业务逻辑（业务逻辑留在 `packages/`）
- Provider 适配器必须实现 `ProviderAdapter` protocol
- 不导入第三方 SDK（OpenAI 适配器使用 `urllib`，与 Ollama 模式一致）
- 不涉及 DuckDB 持久化、Web Dashboard、live trading

## Work Objectives
### Core Objective
让用户通过 `alphabrief` CLI 命令直接使用所有 5 个 MVP 阶段功能，并通过 OpenAI 适配器让 DailyAlphaBrief 生成器接入真实云端模型。

### Deliverables
1. `apps/cli/` 目录，含 typer CLI 入口和 9 个子命令模块
2. `pyproject.toml` 中的 `[project.scripts]` 入口点
3. `alphabrief_models.openai_adapter.OpenAIProviderAdapter`
4. CLI 集成测试（每命令至少 1 个 happy path）
5. OpenAI 适配器测试（遵循 Ollama 测试模式）

### Definition of Done
```bash
# CLI 命令全部可用且输出合理
alphabrief data import --file data/btc.csv --symbol BTC-USD
alphabrief data check --symbol BTC-USD --source test --data-version v1
alphabrief backtest run --spec strategies/ema_trend_v1.json --data data/btc.csv
alphabrief brief daily --prompt-version daily_brief:v1
alphabrief model test --provider ollama
alphabrief paper run --spec strategies/ema_trend_v1.json
alphabrief paper status
alphabrief risk check --intent intent.json
alphabrief audit list
alphabrief review daily

# 质量门全部通过
python3 -m pytest          # 全部通过
.venv/bin/ruff check .     # 全部通过
.venv/bin/mypy             # 全部通过
```

### Must Have
- typer CLI 框架，9 个蓝图定义命令
- CLI 命令调用现有 `packages/` 库函数（不重复实现逻辑）
- OpenAI Provider 适配器（urllib HTTP，无 SDK 依赖）
- 每命令/每适配器至少 1 个测试
- `pyproject.toml` 入口点 `alphabrief`

### Must NOT Have
- CLI 中包含业务逻辑（仅参数解析 + 调用 library + 格式化输出）
- 导入 `openai` SDK 或其他第三方 AI SDK
- API key 写入代码、日志或 prompt
- DuckDB 持久化
- Web Dashboard / FastAPI / Streamlit
- 其他云 Provider（Anthropic、DeepSeek 等）
- 新策略实现
- 修改现有 packages/ 核心逻辑

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: tests-after（先实现，后补充测试并验证）
- Framework: pytest + typer CliRunner
- QA policy: 每个 CLI 命令至少 1 个集成测试，OpenAI 适配器至少 3 个测试
- Evidence: `.omo/evidence/` 存放测试输出

## Execution Strategy
### Parallel Execution Waves
> Wave 1: CLI scaffold + OpenAI 适配器（无依赖，可并行）
> Wave 2: 9 个 CLI 子命令（依赖 Wave 1 的 scaffold 和库接口）

Wave 1: [foundation] CLI scaffold + main.py 入口 + OpenAI 适配器
Wave 2: [features] 9 个子命令 + 集成测试

### Dependency Matrix
| Task | Blocks | Blocked By |
|------|--------|------------|
| CLI scaffold + main.py | Wave 2 全部 | 无 |
| OpenAIProviderAdapter | 无 | 无 |
| data_commands | 无 | CLI scaffold |
| backtest_commands | 无 | CLI scaffold |
| brief_commands | 无 | CLI scaffold, OpenAI adapter (可选集成) |
| model_commands | 无 | CLI scaffold |
| paper_commands | 无 | CLI scaffold |
| risk_commands | 无 | CLI scaffold |
| audit_commands | 无 | CLI scaffold |
| review_commands | 无 | CLI scaffold |
| CLI 集成测试 | 无 | 全部子命令 |

## TODOs

- [x] 1. CLI Scaffold + Entry Point

  **What to do**: 创建 `apps/cli/` 目录结构，添加 typer 主入口 `main.py`，配置 `pyproject.toml` 入口点
  **Must NOT do**: 实现任何子命令逻辑、添加业务逻辑

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: 纯脚手架 + 配置，改动集中

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: all Wave 2 tasks | Blocked By: none

  **References**:
  - Pattern: typer 官方文档 `typer.Typer()` 应用创建模式
  - Config: `pyproject.toml:37-48` — package discovery 模式
  - Existing: `packages/alphabrief-models/src/alphabrief_models/__init__.py` — 导出模式

  **Acceptance Criteria**:
  - [ ] `apps/cli/__init__.py` 存在
  - [ ] `apps/cli/main.py` 定义 typer app 并注册 9 个子命令
  - [ ] `pyproject.toml` 含 `[project.scripts] alphabrief = "alphabrief_cli.main:app"`
  - [ ] `pip install -e .` 后 `alphabrief --help` 显示命令列表

  **QA Scenarios**:
  ```
  Scenario: CLI help displays all commands
    Tool: Bash
    Steps: pip install -e . && alphabrief --help
    Expected: 显示 9 个子命令（data, backtest, brief, model, paper, risk, audit, review）
    Evidence: .omo/evidence/task-1-cli-scaffold.txt

  Scenario: Each subcommand shows its own --help
    Tool: Bash
    Steps: alphabrief data --help && alphabrief backtest --help && alphabrief brief --help
    Expected: 每个子命令显示自己的参数说明
    Evidence: .omo/evidence/task-1-cli-scaffold-help.txt
  ```

  **Commit**: YES | Message: `feat(cli): add typer scaffold and entry point` | Files: `apps/cli/__init__.py`, `apps/cli/main.py`, `pyproject.toml`

- [x] 2. OpenAIProviderAdapter

  **What to do**: 实现 `OpenAIProviderAdapter`，遵循 `OllamaProviderAdapter` 模式，使用 `urllib` 发 HTTP 请求到 OpenAI Chat Completions API
  **Must NOT do**: 导入 `openai` SDK、硬编码 API key、在日志中记录 API key

  **Recommended Agent Profile**:
  - Category: `deep` — Reason: 涉及 HTTP 适配、错误映射、结构化输出支持

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: brief_commands (可选) | Blocked By: none

  **References**:
  - Pattern: `packages/alphabrief-models/src/alphabrief_models/adapters.py:28-109` — OllamaProviderAdapter 完整实现
  - Protocol: `packages/alphabrief-models/src/alphabrief_models/gateway.py` — ProviderAdapter protocol
  - Test: `tests/test_ollama_provider_adapter.py` — 测试模式
  - External: `https://platform.openai.com/docs/api-reference/chat/create` — Chat Completions API

  **Acceptance Criteria**:
  - [ ] `OpenAIProviderAdapter` 实现 `ProviderAdapter` protocol
  - [ ] 构造时从环境变量 `OPENAI_API_KEY` 读取 key（不存储原文，仅用于请求头）
  - [ ] POST 到 `https://api.openai.com/v1/chat/completions`
  - [ ] 支持 `text_generation` capability
  - [ ] `supports_structured_output` 时设置 `response_format: {"type": "json_object"}`
  - [ ] HTTP 错误映射为 `ModelProviderError`
  - [ ] 导出到 `alphabrief_models.__init__`

  **QA Scenarios**:
  ```
  Scenario: Adapter returns valid ModelResponse for simple text request
    Tool: Bash (pytest)
    Steps: 使用 monkeypatched urllib 模拟 OpenAI 200 响应，调用 adapter.invoke()
    Expected: ModelResponse(status="success", output_text 含回复内容)
    Evidence: .omo/evidence/task-2-openai-success.json

  Scenario: Adapter maps HTTP 401 to ModelProviderError
    Tool: Bash (pytest)
    Steps: 模拟 HTTP 401 响应
    Expected: ModelProviderError，错误消息含 "401"
    Evidence: .omo/evidence/task-2-openai-auth-error.txt

  Scenario: Adapter integrates with ModelGateway
    Tool: Bash (pytest)
    Steps: 创建 ModelGateway(providers=[OpenAIProviderAdapter(...)])，调用 gateway.invoke()
    Expected: ModelGatewayResult(status="success") 含 ModelCallRecord
    Evidence: .omo/evidence/task-2-openai-gateway.json
  ```

  **Commit**: YES | Message: `feat(models): add OpenAIProviderAdapter` | Files: `packages/alphabrief-models/src/alphabrief_models/openai_adapter.py`, `packages/alphabrief-models/src/alphabrief_models/__init__.py`

- [x] 3. Data Commands (import + check)

  **What to do**: 实现 `alphabrief data import` 和 `alphabrief data check`，调用 `load_ohlcv_csv`/`load_ohlcv_parquet` 和 `check_bar_quality`
  **Must NOT do**: 实现新的数据加载逻辑、修改 quality 检查

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: 薄封装，标准库调用

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: task 1

  **References**:
  - API: `alphabrief_data.load_ohlcv_csv`, `alphabrief_data.load_ohlcv_parquet`, `alphabrief_data.check_bar_quality`
  - Types: `alphabrief_core.Bar`

  **Acceptance Criteria**:
  - [ ] `alphabrief data import --file data/btc.csv --symbol BTC-USD` 输出加载的 bar 数量
  - [ ] `alphabrief data import --file data/btc.parquet --symbol BTC-USD` 支持 Parquet
  - [ ] `alphabrief data check --symbol BTC-USD --source test --data-version v1` 输出质量报告
  - [ ] 非法输入时返回非零退出码 + 错误信息

  **QA Scenarios**:
  ```
  Scenario: Import CSV and show bar count
    Tool: Bash
    Steps: alphabrief data import --file /tmp/test.csv --symbol BTC-USD
    Expected: 输出 "Loaded N bars"（N > 0），退出码 0
    Evidence: .omo/evidence/task-3-data-import.txt

  Scenario: Import nonexistent file fails gracefully
    Tool: Bash
    Steps: alphabrief data import --file /tmp/nonexistent.csv --symbol BTC-USD
    Expected: 非零退出码，stderr 含错误信息
    Evidence: .omo/evidence/task-3-data-import-error.txt
  ```

  **Commit**: YES | Message: `feat(cli): add data import and check commands` | Files: `apps/cli/data_commands.py`

- [x] 4. Backtest Command

  **What to do**: 实现 `alphabrief backtest run`，加载 CSV 数据 → 生成特征 → 运行策略 → 输出报告
  **Must NOT do**: 修改回测逻辑、添加新指标

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: 串联现有函数

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: task 1

  **References**:
  - API: `alphabrief_data.load_ohlcv_csv`, `alphabrief_data.generate_basic_features`, `alphabrief_strategy.MovingAverageTrendStrategy`, `alphabrief_backtest.VectorizedBacktester`, `alphabrief_backtest.write_backtest_report`
  - Types: `alphabrief_strategy.StrategySpec`

  **Acceptance Criteria**:
  - [ ] `alphabrief backtest run --data data/btc.csv --spec spec.json` 输出回测报告
  - [ ] 支持 `--output report.json` 写入 JSON 文件
  - [ ] 支持 `--strategy sma` 选择策略（默认 MovingAverageTrendStrategy）
  - [ ] 非法 StrategySpec JSON 时返回非零退出码

  **QA Scenarios**:
  ```
  Scenario: Run backtest and see metrics
    Tool: Bash
    Steps: 创建测试 CSV + StrategySpec JSON → alphabrief backtest run --data /tmp/test.csv --spec /tmp/spec.json
    Expected: 输出含 total_return、max_drawdown、trade_count
    Evidence: .omo/evidence/task-4-backtest-run.txt
  ```

  **Commit**: YES | Message: `feat(cli): add backtest run command` | Files: `apps/cli/backtest_commands.py`

- [x] 5. Brief Command

  **What to do**: 实现 `alphabrief brief daily`，调用 `generate_daily_alpha_brief`
  **Must NOT do**: 直接调用 provider、修改 brief 生成逻辑

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: 薄封装

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: task 1, task 2 (可选集成)

  **References**:
  - API: `alphabrief_models.generate_daily_alpha_brief`
  - Types: `alphabrief_models.DailyAlphaBrief`

  **Acceptance Criteria**:
  - [ ] `alphabrief brief daily --prompt-version daily_brief:v1` 生成日报并输出摘要
  - [ ] 无可用 provider 时返回非零退出码 + 错误信息
  - [ ] 支持 `--output brief.json` 写入 JSON

  **QA Scenarios**:
  ```
  Scenario: Generate daily brief with FakeProvider
    Tool: Bash
    Steps: alphabrief brief daily --provider fake
    Expected: 输出 DailyAlphaBrief JSON 摘要
    Evidence: .omo/evidence/task-5-brief-daily.txt
  ```

  **Commit**: YES | Message: `feat(cli): add brief daily command` | Files: `apps/cli/brief_commands.py`

- [x] 6. Model Command

  **What to do**: 实现 `alphabrief model test`，测试 provider 连通性
  **Must NOT do**: 绕过 ModelGateway 直接测试 provider

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: 薄封装

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: task 1

  **References**:
  - API: `alphabrief_models.ModelGateway`, `alphabrief_models.ModelRegistry`

  **Acceptance Criteria**:
  - [ ] `alphabrief model test --provider ollama` 测试本地 Ollama 连通性
  - [ ] `alphabrief model test --provider fake` 始终成功
  - [ ] 连接失败时返回非零退出码

  **QA Scenarios**:
  ```
  Scenario: Test fake provider succeeds
    Tool: Bash
    Steps: alphabrief model test --provider fake
    Expected: 输出 "Provider fake: OK"，退出码 0
    Evidence: .omo/evidence/task-6-model-test.txt
  ```

  **Commit**: YES | Message: `feat(cli): add model test command` | Files: `apps/cli/model_commands.py`

- [x] 7. Paper Commands (run + status)

  **What to do**: 实现 `alphabrief paper run` 和 `alphabrief paper status`
  **Must NOT do**: 绕过 RiskGate、live trading

  **Recommended Agent Profile**:
  - Category: `deep` — Reason: 涉及 RiskGate + PaperBroker 完整链路

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: task 1

  **References**:
  - API: `alphabrief_risk.RiskGate`, `alphabrief_risk.RiskLimitConfig`, `alphabrief_execution.PaperBroker`, `alphabrief_execution.PortfolioState`

  **Acceptance Criteria**:
  - [ ] `alphabrief paper run --spec spec.json` 运行 paper trading 并输出结果
  - [ ] `alphabrief paper status` 显示当前 portfolio 状态
  - [ ] 策略未启用时 paper run 被 RiskGate 拒绝（非零退出码）

  **QA Scenarios**:
  ```
  Scenario: Paper run with valid strategy
    Tool: Bash
    Steps: 创建 StrategySpec + CSV → alphabrief paper run --spec /tmp/spec.json
    Expected: 输出 paper trading 订单和成交记录
    Evidence: .omo/evidence/task-7-paper-run.txt

  Scenario: Paper status shows portfolio
    Tool: Bash
    Steps: alphabrief paper status
    Expected: 输出 cash、positions、realized_pnl
    Evidence: .omo/evidence/task-7-paper-status.txt
  ```

  **Commit**: YES | Message: `feat(cli): add paper run and status commands` | Files: `apps/cli/paper_commands.py`

- [x] 8. Risk Command

  **What to do**: 实现 `alphabrief risk check`，从 JSON 文件加载 OrderIntent → 调用 RiskGate → 输出 RiskDecision
  **Must NOT do**: 绕过 RiskGate

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: 薄封装

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: task 1

  **References**:
  - API: `alphabrief_risk.RiskGate.evaluate()`
  - Types: `alphabrief_core.OrderIntent`, `alphabrief_core.RiskDecision`

  **Acceptance Criteria**:
  - [ ] `alphabrief risk check --intent intent.json` 输出 RiskDecision JSON
  - [ ] 非法 OrderIntent JSON 时返回非零退出码

  **QA Scenarios**:
  ```
  Scenario: Check valid order intent
    Tool: Bash
    Steps: 创建 OrderIntent JSON 文件 → alphabrief risk check --intent /tmp/intent.json
    Expected: 输出 approved/rejected 状态的 RiskDecision JSON
    Evidence: .omo/evidence/task-8-risk-check.json
  ```

  **Commit**: YES | Message: `feat(cli): add risk check command` | Files: `apps/cli/risk_commands.py`

- [x] 9. Audit Command

  **What to do**: 实现 `alphabrief audit list`，列出审计事件
  **Must NOT do**: 修改审计日志格式

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: 薄封装

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: task 1

  **References**:
  - API: `alphabrief_execution.ExecutionAuditLog`

  **Acceptance Criteria**:
  - [ ] `alphabrief audit list` 输出审计事件列表
  - [ ] 空日志时输出 "No audit events"

  **QA Scenarios**:
  ```
  Scenario: List audit events after paper run
    Tool: Bash
    Steps: paper run → alphabrief audit list
    Expected: 输出含 risk_decision_recorded、order_created、fill_created 等事件
    Evidence: .omo/evidence/task-9-audit-list.txt
  ```

  **Commit**: YES | Message: `feat(cli): add audit list command` | Files: `apps/cli/audit_commands.py`

- [x] 10. Review Command

  **What to do**: 实现 `alphabrief review daily`，调用 Review Center 生成日报
  **Must NOT do**: 修改 review journal 生成逻辑

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: 薄封装

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: task 1

  **References**:
  - API: `alphabrief_review.ReviewCenterSnapshot`, `alphabrief_review.generate_daily_review`

  **Acceptance Criteria**:
  - [ ] `alphabrief review daily --snapshot snapshot.json` 输出每日复盘
  - [ ] 无快照文件时返回非零退出码

  **QA Scenarios**:
  ```
  Scenario: Generate daily review from snapshot
    Tool: Bash
    Steps: 创建 ReviewCenterSnapshot JSON → alphabrief review daily --snapshot /tmp/snapshot.json
    Expected: 输出格式化的每日复盘文本
    Evidence: .omo/evidence/task-10-review-daily.txt
  ```

  **Commit**: YES | Message: `feat(cli): add review daily command` | Files: `apps/cli/review_commands.py`

- [x] 11. CLI Integration Tests

  **What to do**: 为 9 个命令编写集成测试（每命令至少 1 个 happy path），使用 typer CliRunner
  **Must NOT do**: 调用真实外部 API

  **Recommended Agent Profile**:
  - Category: `deep` — Reason: 跨模块集成测试

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: none | Blocked By: 全部子命令任务

  **References**:
  - Pattern: `tests/test_paper_execution.py` — 集成测试模式
  - Tool: typer.testing.CliRunner

  **Acceptance Criteria**:
  - [ ] 9 个命令各至少 1 个集成测试通过
  - [ ] 测试覆盖：happy path + 错误输入 + 文件不存在

  **QA Scenarios**:
  ```
  Scenario: All CLI integration tests pass
    Tool: Bash
    Steps: python3 -m pytest tests/test_cli.py -v
    Expected: 全部通过，至少 9 个测试
    Evidence: .omo/evidence/task-11-cli-tests.txt
  ```

  **Commit**: YES | Message: `test(cli): add integration tests for all 9 commands` | Files: `tests/test_cli.py`

- [x] 12. Quality Gates + Docs

  **What to do**: 运行全量测试 + ruff + mypy，更新 development_log.md
  **Must NOT do**: 跳过任何质量检查

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: 验证 + 文档

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: none | Blocked By: task 11

  **Acceptance Criteria**:
  - [ ] `python3 -m pytest` 全部通过（205+ 个测试）
  - [ ] `.venv/bin/ruff check .` 全部通过
  - [ ] `.venv/bin/mypy` 全部通过
  - [ ] `docs/development_log.md` 追加 round 0023 记录

  **Commit**: YES | Message: `docs: add development log for round 0023` | Files: `docs/development_log.md`

## Final Verification Wave
> 4 review agents run in PARALLEL. ALL must APPROVE.

- [x] F1. Plan Compliance Audit — oracle
- [x] F2. Code Quality Review — unspecified-high
- [x] F3. Real Manual QA — unspecified-high (+ CLI 命令验证)
- [x] F4. Scope Fidelity Check — deep

## Commit Strategy
每个任务独立 commit，按 task 顺序提交：
```
feat(cli): add typer scaffold and entry point
feat(models): add OpenAIProviderAdapter
feat(cli): add data import and check commands
feat(cli): add backtest run command
feat(cli): add brief daily command
feat(cli): add model test command
feat(cli): add paper run and status commands
feat(cli): add risk check command
feat(cli): add audit list command
feat(cli): add review daily command
test(cli): add integration tests for all 9 commands
docs: add development log for round 0023
```

## Success Criteria
1. `alphabrief --help` 显示 9 个子命令
2. 每个子命令可独立运行并有合理的终端输出
3. `alphabrief brief daily` 可通过 OpenAI 适配器生成真实日报（需配置 API key）
4. 全量测试 205+ → 230+ 通过
5. ruff + mypy 严格模式通过
6. 零 regression（现有 205 个测试全通过）
