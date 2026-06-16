# AlphaBrief Phase 12 开发计划

> **计划范围**：Phase 11 已完成新闻/宏观研究上下文、更多 Provider、`AlphaBriefTradingEnvV2` 与多页面 Dashboard。Phase 12 的目标不是扩大交易权限，而是把 Phase 11 的数据与仿真能力接入更可审计的策略信号、风险提示、回测报告与只读展示面。
>
> **计划产出**：本文件覆盖当前 Phase 12 计划，并在文末完整保留 Phase 11 原计划作为历史附录。Phase 12 仍需按 `Plan -> Review Plan -> Implement -> Test -> Self Review -> Document -> Commit -> Next Task Proposal` 小步执行。
>
> **当前基线**：`docs/AI_HANDOFF.md` 记录 Phase 11 完成时为 `597 passed`、ruff clean、strict mypy clean。若 README 或旧文档仍显示 `431` 等旧测试数量，Phase 12 文档收尾轮需要一并校正为最新实际结果。
>
> **模型分工约定**：
> - `kimi-k2.7-code`：架构/Schema 联动、Risk/Strategy 边界设计、EnvV2 报告接入。
> - `deepseek-v4-flash`：API/CLI/Dashboard 实现、Provider 解析、测试补充。
> - `minimax-m3`：文档、简单 route/command、HTML/JS 小改、回归测试整理。

---

## 1. 任务目标

### A. 新闻/宏观数据 → 策略信号 / Risk Rules 集成

1. 让新闻情绪、宏观指标和 `ResearchContextBuilder` 的输出可以成为策略信号的**证据与风险上下文**，但不直接生成订单。
2. 扩展 StrategySpec/Signal 周边的可选元数据，使策略信号可携带 `news_evidence`、`macro_evidence`、`sentiment_score`、`external_context_version` 等审计信息。
3. 在 RiskGate 外围新增一个**风险上下文评估层**（例如 `RiskContext` / `RiskSignalAdjustment` / `RiskRuleInput`），由调用方把新闻/宏观风险汇总为 deterministic metadata，再交给 RiskGate 现有接口或配置消费。
4. 明确不改 RiskGate 核心判定语义：新闻极差时可提高风险标签、要求人工复核、降低建议仓位上限，但不得绕过现有限额或 KillSwitch。
5. 可选：DailyAlphaBrief 增加“新闻驱动的观察建议”区块，只输出 watchlist / research task / strategy hypothesis，不输出 approved order。

### B. Trading Env v2 接入回测和报告

1. 将 `AlphaBriefTradingEnvV2` 的多资产 episode 结果转换为可持久化、可展示的报告结构。
2. 扩展 `BacktestReport` 或新增 `BacktestReportV2` / `EnvV2BacktestReport`，支持多资产指标、资产权重历史、成本拆分、borrow cost、market impact、leverage exposure。
3. 在 API/CLI 中提供显式 v2 入口，避免破坏既有 single-asset vectorized backtest 行为。
4. 支持把 EnvV2 报告写入现有 backtest report store，或新增兼容字段，确保 dashboard/report viewer 可读。
5. 不把 EnvV2 作为训练系统，不引入 RL 训练依赖，不默认启用 short/leverage。

### C. Dashboard 增强

1. 增强 Equity Curve 展示：原生 Canvas/JS 支持基本缩放、平移、重置视图，不引入前端依赖。
2. 新增回测报告对比页面，展示 legacy backtest 与 EnvV2 report 的核心指标、成本、回撤、资产暴露对比。
3. 增强 paper trading 净值展示：基于现有 paper portfolio / audit / fills 数据提供可刷新的只读净值曲线。
4. 所有页面保持只读，禁止加入下单、启停策略、修改 live trading、修改风控配置的 UI。
5. 所有外部文本继续走 `escapeHtml`，尤其是新闻标题、摘要、provider 错误和模型输出字段。

### D. 更多 Provider

1. 新增一个免费/低门槛市场数据 provider，例如 `TwelveDataProvider` 或 `EodhdProvider`，遵循 `MarketDataProvider` protocol。
2. Provider 仅使用 `urllib` 与可注入 `http_get`；API key 仅从构造参数或环境变量读取，不写入日志、测试 fixture、文档真实值。
3. CLI/API 增加 source 分支，错误使用现有 `MarketDataProviderError` / error code 体系。
4. 新 Provider 优先作为独立小轮次，不与 Risk/Strategy 或 Dashboard 混做。
5. 若免费接口需要 key 或限制不稳定，先实现严格 mock/fixture 测试与清晰 `MISSING_API_KEY` 行为。

---

## 2. 涉及文件

### A. 新闻/宏观 → Strategy/Risk

**可能修改/新建**：

- `packages/alphabrief-strategy/src/alphabrief_strategy/spec.py`：为 StrategySpec 增加可选 external data / evidence 配置；必须保持向后兼容。
- `packages/alphabrief-strategy/src/alphabrief_strategy/interface.py`：允许 `StrategyOutput` / `Signal` 周边携带外部上下文元数据；不得让策略访问 broker。
- `packages/alphabrief-strategy/src/alphabrief_strategy/builtins.py`：如需要示例策略，仅做最小演示，不改旧行为。
- `packages/alphabrief-core/src/alphabrief_core/models.py`（若 Signal 定义在此）：增加可选 evidence/risk metadata 字段；所有新增字段必须有默认值。
- `packages/alphabrief-research/src/alphabrief_research/context.py`：复用 `ResearchContextBuilder`，必要时增加结构化摘要输出，而不是只返回 prompt 文本。
- `packages/alphabrief-news/src/alphabrief_news/sentiment.py`：复用情绪汇总函数；如需新增评分类型，保持 deterministic。
- `packages/alphabrief-risk/src/alphabrief_risk/context.py`（新建优先）：定义 RiskContext / NewsMacroRiskSummary / RiskAdjustment，不直接改 `gate.py` 核心。
- `packages/alphabrief-risk/src/alphabrief_risk/gate.py`（谨慎，仅必要）：只做可选 metadata 或 human-review flag 输入，禁止重写核心拒绝规则。
- `apps/api/src/alphabrief_api/routes/risk.py`：展示新闻/宏观风险上下文，不开放绕过接口。
- `apps/api/src/alphabrief_api/routes/brief.py`：DailyAlphaBrief 可展示新闻驱动观察建议。
- `apps/cli/src/alphabrief_cli/risk_commands.py`：新增只读 risk context 检查命令（可选）。
- `tests/test_strategy_spec_schema.py`、`tests/test_strategy_interface.py`、`tests/test_research_context.py`、`tests/test_risk_gate.py`、`tests/test_api_server.py`。
- `docs/risk_model.md`、`docs/architecture.md`、`docs/roadmap.md`。

### B. Trading Env v2 → Backtest/Report

**可能修改/新建**：

- `packages/alphabrief-gym/src/alphabrief_gym/env_v2.py`：读取 episode metrics，不改核心 step/reset 语义。
- `packages/alphabrief-gym/src/alphabrief_gym/schemas.py`：补齐 report 所需的 `EpisodeMetricsV2` / 权重历史 / 成本拆分 schema。
- `packages/alphabrief-gym/src/alphabrief_gym/report.py`：新增 EnvV2 报告适配器或 comparison report 扩展。
- `packages/alphabrief-backtest/src/alphabrief_backtest/report.py`（若存在）或 `vectorized.py`：扩展报告 schema 或新增 v2 report type；不得破坏 legacy report JSON。
- `apps/api/src/alphabrief_api/routes/backtest.py`：新增显式 v2 route/body flag，例如 `engine="env_v2"`，默认仍为 legacy。
- `apps/api/src/alphabrief_api/db/backtest_reports.py`：持久化 v2 report 字段，优先做向后兼容 JSON payload。
- `apps/cli/src/alphabrief_cli/backtest_commands.py`：新增 `--engine env-v2` / `--multi-asset` 显式入口。
- `tests/test_trading_env_v2.py`、`tests/test_trading_env.py`、`tests/test_vectorized_backtester.py`、`tests/test_api_server.py`。
- `docs/architecture.md`、`docs/roadmap.md`。

### C. Dashboard 增强

**可能修改/新建**：

- `apps/api/src/alphabrief_api/routes/dashboard.py`：增强 `/dashboard`，新增 `/dashboard/backtests/compare` 或 `/dashboard/backtests` 页面。
- `apps/api/src/alphabrief_api/routes/backtest.py`：确认 report list/detail 可支持对比页 fetch。
- `apps/api/src/alphabrief_api/routes/paper.py`：确认 paper portfolio/fills/audit 可支持净值曲线刷新。
- `apps/api/src/alphabrief_api/db/backtest_reports.py`：确保报告列表包含对比所需 summary 字段。
- `apps/api/src/alphabrief_api/db/paper.py`：确认 portfolio snapshots 可读；如缺失，只做只读查询扩展。
- `tests/test_api_server.py`：页面 200、DOM anchor、fetch endpoint、HTML escape 测试。
- `docs/architecture.md`。

### D. 更多 Provider

**可能修改/新建**：

- `packages/alphabrief-data/src/alphabrief_data/providers/twelvedata.py`（新建）或 `eodhd.py`（二选一，优先 TwelveData）。
- `packages/alphabrief-data/src/alphabrief_data/providers/__init__.py`：导出新 provider。
- `apps/api/src/alphabrief_api/routes/data.py`：新增 source dispatch。
- `apps/cli/src/alphabrief_cli/data_commands.py`：新增 source option/help。
- `.env.example`：仅新增占位变量，例如 `TWELVEDATA_API_KEY=`，不得写真实值。
- `tests/test_market_data_providers.py` 或 `tests/test_twelvedata_provider.py`（新建）。
- `tests/test_api_server.py`、`tests/test_data_commands.py`。
- `docs/architecture.md`、`docs/roadmap.md`。

---

## 3. 不应修改的范围

1. `packages/alphabrief-models/src/alphabrief_models/gateway.py` 核心：不改 `ModelGateway` 选择逻辑、核心 request/response 语义。
2. `packages/alphabrief-risk/src/alphabrief_risk/gate.py` 核心：不重写现有 deterministic 拒绝规则；优先新增外围 context/rule adapter。
3. `packages/alphabrief-risk/src/alphabrief_risk/kill_switch.py` 核心：不改变 KillSwitch 激活/检查语义。
4. `_reference_sources/` 下任何文件：不读取实现后迁移，不复制、翻译、改名复用。
5. 任何 provider SDK 直接调用：Provider 只能用现有协议与 `urllib`/可注入 HTTP seam；模型 provider 仍通过 ModelGateway adapter。
6. 已有测试断言：不得删除、禁用、降低断言；新增行为用新增测试覆盖。
7. 用户配置、`.env`、密钥文件：不得修改；只允许 `.env.example` 增加空占位。
8. live trading：不得新增真实 broker adapter，不得默认启用，不得增加前端 live trading 操作。
9. `pyproject.toml` 依赖：Dashboard 和 Provider 默认不新增依赖；若必须新增，单独 Plan。
10. Backtest legacy JSON：不得破坏现有报告字段和旧 report 读取路径。

---

## 4. 分步骤执行计划

### Round 12.1 — Strategy 信号外部证据 Schema

- **目标**：让 Strategy/Signal 可携带新闻/宏观证据 metadata，作为后续风险上下文输入。
- **模型**：`kimi-k2.7-code`。
- **涉及文件**：`alphabrief_strategy/spec.py`、`alphabrief_strategy/interface.py`、可能的 `alphabrief_core/models.py`、`tests/test_strategy_spec_schema.py`、`tests/test_strategy_interface.py`。
- **步骤**：
  1. 定义可选 `ExternalEvidenceConfig` / `SignalEvidence`（命名以现有风格为准）。
  2. 字段包括 source、data_version、headline_ids、macro_indicator_ids、sentiment_score、generated_at。
  3. 所有字段可选，不改变旧 StrategySpec/Signal 构造。
  4. `run_strategy()` 仅校验 metadata 合法性，不读取 DB、不调用 provider。
- **验收**：旧 strategy tests 全过；新增 schema/validation 测试；无 broker/model 调用。
- **测试命令**：`.venv/bin/python -m pytest tests/test_strategy_spec_schema.py tests/test_strategy_interface.py`。
- **回滚**：还原 strategy/core 相关文件并删除新增测试。

### Round 12.2 — ResearchContextBuilder 结构化摘要输出

- **目标**：在现有 prompt 文本之外，输出可供 risk/strategy 使用的 deterministic 新闻/宏观摘要对象。
- **模型**：`kimi-k2.7-code`。
- **涉及文件**：`alphabrief_research/context.py`、`alphabrief_news/sentiment.py`、`tests/test_research_context.py`。
- **步骤**：
  1. 新增 `build_structured_summary(...)` 或等价函数。
  2. 输出 headline count、negative/positive/neutral count、worst sentiment、macro indicators、data versions。
  3. 保留 untrusted-data 标识；摘要不能生成订单建议。
  4. 空数据返回空摘要而非异常。
- **验收**：空数据、多 headline、多 indicator、混合 data_version 均有测试。
- **测试命令**：`.venv/bin/python -m pytest tests/test_research_context.py tests/test_news.py`。
- **回滚**：还原 context/sentiment 改动。

### Round 12.3 — Risk Context 外围规则层

- **目标**：新增 RiskGate 外围的新闻/宏观风险上下文评估，不改核心 RiskGate 规则。
- **模型**：`kimi-k2.7-code`。
- **涉及文件**：`packages/alphabrief-risk/src/alphabrief_risk/context.py`（新建）、`packages/alphabrief-risk/src/alphabrief_risk/__init__.py`、`tests/test_risk_gate.py` 或 `tests/test_risk_context.py`。
- **步骤**：
  1. 定义 `NewsMacroRiskContext` 与 `RiskContextDecision`。
  2. 规则示例：极端负面情绪 → `requires_human_review=True`、risk_tags 增加 `negative_news_context`；高宏观风险 → 建议降低 max position metadata。
  3. 输出只能“加严”风险，不得放宽现有限额。
  4. 不调用 ModelGateway、不读 DB、不访问 provider。
- **验收**：负面新闻加严、空上下文 no-op、positive news 不放宽、KillSwitch 不受影响。
- **测试命令**：`.venv/bin/python -m pytest tests/test_risk_gate.py tests/test_risk_context.py`（若新建）。
- **回滚**：删除 `context.py` 并还原 `__init__.py`。

### Round 12.4 — Risk API/CLI 只读上下文展示

- **目标**：把 Round 12.2/12.3 的风险上下文展示给用户，不允许用户绕过规则。
- **模型**：`deepseek-v4-flash`。
- **涉及文件**：`apps/api/src/alphabrief_api/routes/risk.py`、`apps/cli/src/alphabrief_cli/risk_commands.py`、`tests/test_api_server.py`、相关 CLI 测试。
- **步骤**：
  1. 新增只读 endpoint 或扩展 risk dashboard response。
  2. CLI 增加 `alphabrief risk context`（可选）读取本地 stores 并输出摘要。
  3. 返回 risk tags / human review / evidence ids，不返回秘密或原始 prompt。
  4. 不改变 order routing。
- **验收**：API/CLI 测试覆盖空数据、负面上下文、HTML/JSON 安全输出。
- **测试命令**：`.venv/bin/python -m pytest tests/test_api_server.py tests/test_data_commands.py tests/test_risk_gate.py`。
- **回滚**：还原 risk route/CLI。

### Round 12.5 — DailyAlphaBrief 新闻驱动观察建议

- **目标**：在 DailyAlphaBrief 中加入“新闻/宏观驱动观察建议”字段或渲染区块。
- **模型**：`kimi-k2.7-code`。
- **涉及文件**：`alphabrief_models/briefs.py`、`alphabrief_models/prompts.py`、`alphabrief_models/daily.py`、`apps/api/routes/brief.py`、`tests/test_daily_alpha_brief.py`、`tests/test_prompt_templates.py`。
- **步骤**：
  1. 新增可选 `news_driven_watchlist` / `risk_officer_notes` 字段。
  2. Prompt 明确只允许 watchlist/research task/strategy hypothesis。
  3. Fake provider 测试仍可省略新增字段。
  4. API/CLI 仅在 include-news/include-macro 时填充上下文。
- **验收**：结构化输出校验通过；无 approved order 字段；旧测试不改断言。
- **测试命令**：`.venv/bin/python -m pytest tests/test_daily_alpha_brief.py tests/test_prompt_templates.py tests/test_api_server.py`。
- **回滚**：还原 brief/prompt/API 改动。

### Round 12.6 — EnvV2 Episode Report Adapter

- **目标**：把 EnvV2 episode metrics 转换为可序列化 report，不接 API。
- **模型**：`kimi-k2.7-code`。
- **涉及文件**：`alphabrief_gym/report.py`、`alphabrief_gym/schemas.py`、`alphabrief_gym/env_v2.py`（只读或最小补充）、`tests/test_trading_env_v2.py`。
- **步骤**：
  1. 定义 `EnvV2Report` / `EnvV2AssetMetrics` / `EnvV2CostBreakdown`。
  2. 从 episode result 中提取 total_return、drawdown、trade_count、leverage、borrow_cost、impact/slippage cost。
  3. 支持 JSON-safe dict 输出。
  4. 保留 legacy `StrategyComparisonReport`。
- **验收**：两资产 episode report 可序列化；成本拆分准确；默认 short/leverage off。
- **测试命令**：`.venv/bin/python -m pytest tests/test_trading_env_v2.py tests/test_trading_env.py`。
- **回滚**：还原 gym report/schema 改动。

### Round 12.7 — BacktestReport Schema v2 兼容扩展

- **目标**：让 backtest report store/API 能保存和读取 EnvV2 report。
- **模型**：`kimi-k2.7-code`。
- **涉及文件**：`alphabrief_backtest/vectorized.py` 或 report schema 文件、`apps/api/db/backtest_reports.py`、`tests/test_vectorized_backtester.py`、`tests/test_db.py`。
- **步骤**：
  1. 选择新增 `report_engine` / `report_version` / `engine_payload` 字段或新 v2 schema。
  2. 旧 report JSON 不变，新字段可选。
  3. DB store 以 JSON payload 兼容持久化。
  4. 文档记录 legacy 与 env_v2 的差异。
- **验收**：旧报告 round-trip 测试仍过；v2 report round-trip 新测试通过。
- **测试命令**：`.venv/bin/python -m pytest tests/test_vectorized_backtester.py tests/test_db.py`。
- **回滚**：还原 report schema/store 改动。

### Round 12.8 — CLI/API EnvV2 Backtest 显式入口

- **目标**：提供显式 EnvV2 backtest/report 入口，默认仍为 legacy。
- **模型**：`deepseek-v4-flash`。
- **涉及文件**：`apps/api/routes/backtest.py`、`apps/cli/backtest_commands.py`、`tests/test_api_server.py`、CLI 相关测试。
- **步骤**：
  1. API request 增加 `engine` 字段，默认 legacy。
  2. CLI 增加 `--engine legacy|env-v2`，必须显式选择 env-v2。
  3. EnvV2 输入要求多资产 bars，缺失时报结构化错误。
  4. 写入 BacktestReportStore。
- **验收**：legacy API/CLI 测试不变；env-v2 happy path、invalid input、persisted report 测试通过。
- **测试命令**：`.venv/bin/python -m pytest tests/test_api_server.py tests/test_data_commands.py tests/test_trading_env_v2.py`。
- **回滚**：还原 backtest route/CLI。

### Round 12.9 — Dashboard Equity Curve 交互增强

- **目标**：为主页 equity curve 增加缩放/平移/重置。
- **模型**：`deepseek-v4-flash`。
- **涉及文件**：`apps/api/routes/dashboard.py`、`tests/test_api_server.py`。
- **步骤**：
  1. 在现有 Canvas 绘图代码上增加 mouse wheel zoom、drag pan、reset button。
  2. 空数据/单点数据正常显示。
  3. 不引入外部 JS/CSS。
  4. 所有文本继续 escape。
- **验收**：页面包含相关 DOM/JS；现有 dashboard 页面 200。
- **测试命令**：`.venv/bin/python -m pytest tests/test_api_server.py`。
- **回滚**：还原 `dashboard.py`。

### Round 12.10 — Dashboard Backtest Report 对比页

- **目标**：新增只读 report comparison 页面。
- **模型**：`deepseek-v4-flash`。
- **涉及文件**：`apps/api/routes/dashboard.py`、`apps/api/routes/backtest.py`、`tests/test_api_server.py`。
- **步骤**：
  1. 新增 `/dashboard/backtests` 或 `/dashboard/backtests/compare`。
  2. fetch report list/detail，展示 return、drawdown、costs、engine、data_version。
  3. 支持 EnvV2 的资产级指标展示。
  4. 无 report 时显示 empty state。
- **验收**：页面 200，包含 fetch endpoint、empty state、escapeHtml。
- **测试命令**：`.venv/bin/python -m pytest tests/test_api_server.py`。
- **回滚**：还原 dashboard/backtest route 改动。

### Round 12.11 — Dashboard Paper Trading 净值刷新

- **目标**：Dashboard 只读显示 paper trading 实时/准实时净值。
- **模型**：`minimax-m3`。
- **涉及文件**：`apps/api/routes/dashboard.py`、`apps/api/routes/paper.py`、`apps/api/db/paper.py`、`tests/test_api_server.py`。
- **步骤**：
  1. 复用现有 portfolio/fills/audit 数据生成 equity series。
  2. 前端 `setInterval` 定时 fetch，只读刷新。
  3. 不增加 order 操作按钮。
  4. 空数据显示安全状态。
- **验收**：页面测试验证刷新 endpoint 和禁用交易操作。
- **测试命令**：`.venv/bin/python -m pytest tests/test_api_server.py`。
- **回滚**：还原 dashboard/paper 改动。

### Round 12.12 — TwelveData MarketDataProvider

- **目标**：新增一个 provider（优先 TwelveData）作为独立扩展。
- **模型**：`deepseek-v4-flash`。
- **涉及文件**：`alphabrief_data/providers/twelvedata.py`、`providers/__init__.py`、`.env.example`、`tests/test_market_data_providers.py` 或 `tests/test_twelvedata_provider.py`。
- **步骤**：
  1. 实现 protocol：`fetch_ohlcv(symbol, start, end, interval, data_version)`。
  2. API key 从 `TWELVEDATA_API_KEY` 或构造参数读取；缺失抛 `missing_api_key`。
  3. 使用 `urllib` + injectable `http_get` + `RetryPolicy`。
  4. 解析 mock JSON 为 `Bar`，处理 empty/error/rate limit。
- **验收**：success、missing key、HTTP 4xx/5xx、empty payload、bad payload、retry 测试通过；无 SDK。
- **测试命令**：`.venv/bin/python -m pytest tests/test_market_data_providers.py tests/test_twelvedata_provider.py`。
- **回滚**：删除 provider 文件与 export、还原 `.env.example`。

### Round 12.13 — TwelveData CLI/API Source Wiring

- **目标**：把新 provider 暴露到 `data fetch` CLI/API。
- **模型**：`minimax-m3`。
- **涉及文件**：`apps/api/routes/data.py`、`apps/cli/data_commands.py`、`tests/test_api_server.py`、`tests/test_data_commands.py`。
- **步骤**：
  1. `_build_provider` 增加 `source="twelvedata"`。
  2. 更新 request Literal 与 CLI help。
  3. API/CLI 错误不泄露 key。
  4. 持久化仍走 `MarketDataStore`。
- **验收**：API/CLI source 分支、missing key、mock success 测试通过。
- **测试命令**：`.venv/bin/python -m pytest tests/test_api_server.py tests/test_data_commands.py tests/test_market_data_providers.py`。
- **回滚**：还原 route/CLI source 分支。

### Round 12.14 — 文档、状态校正与最终质量门

- **目标**：更新文档，记录 Phase 12 完成状态，校正文档中旧测试数量。
- **模型**：`minimax-m3`。
- **涉及文件**：`docs/architecture.md`、`docs/roadmap.md`、`docs/risk_model.md`、`docs/development_log.md`（如存在）、`README.md`（仅状态数字/Phase summary）、`docs/AI_HANDOFF.md`。
- **步骤**：
  1. 记录新闻/宏观 → strategy/risk 的边界：只加严、不放宽、不下单。
  2. 记录 EnvV2 report/API/CLI/dashboard 行为。
  3. 记录新 provider 与 API key 安全边界。
  4. 更新实际测试数量与质量门结果。
- **验收**：文档与代码一致；无旧 Phase 9/11 测试数量误导；最终命令全过。
- **测试命令**：`.venv/bin/python -m pytest && .venv/bin/ruff check . && .venv/bin/mypy`。
- **回滚**：还原相关文档文件。

---

## 5. 风险点

### A. 新闻/宏观 → Strategy/Risk

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| 外部内容变成交易指令 | 新闻或社交内容可能诱导模型/策略直接下单。 | 外部内容只作为 untrusted evidence；Strategy 输出 Signal/OrderIntent draft；执行仍需 RiskGate。 |
| RiskGate 核心被污染 | 将情绪规则直接塞进核心 gate 可能破坏 deterministic 边界。 | 优先新增外围 context/rule adapter；只能加严，不能放宽。 |
| 情绪评分过度自信 | 规则情绪分析可能误判。 | 输出 evidence 与 confidence，不作为唯一拒绝依据；需要 human review。 |
| Schema 破坏兼容 | 新字段若必填会破坏旧测试/fixture。 | 全部可选，有默认值；旧断言不改。 |

### B. Trading Env v2 报告

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| 报告口径混乱 | legacy vectorized backtest 与 EnvV2 episode 指标含义不同。 | 增加 `engine` / `report_version`；文档明确差异。 |
| 杠杆/做空误导 | EnvV2 支持 short/leverage，但默认不应启用。 | CLI/API 必须显式选择；默认 `allow_short=false`、`max_leverage=1.0`。 |
| 成本遗漏 | market impact/borrow/slippage 未写入报告会夸大收益。 | report 必须有成本拆分测试。 |
| 持久化破坏旧 report | DB schema 变更可能破坏旧 report 读取。 | 使用可选 JSON payload 或迁移兼容测试。 |

### C. Dashboard

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| XSS | 新闻/宏观/模型输出展示可能含恶意文本。 | 全部 `escapeHtml`；测试覆盖危险字符串。 |
| 前端功能蔓延 | 图表和对比页容易引入复杂依赖。 | 原生 JS/Canvas；不引入新依赖。 |
| 误加交易控制 | Dashboard 增强可能误加执行按钮。 | 只读原则；测试检查页面不含 order submit/live enable 控件。 |
| 实时刷新压力 | 高频轮询可能影响本地 API。 | 低频 refresh；支持手动刷新。 |

### D. 更多 Provider

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| API key 泄露 | 新 provider 可能把 key 放入错误或日志。 | 测试断言错误信息不含 key；只用 env name/constructor。 |
| 接口限制/变更 | 免费 provider 可能限流或格式变化。 | 结构化错误码、retry、mock parser tests。 |
| SDK 依赖 | provider SDK 会扩大依赖和边界。 | 仅 `urllib`；SDK 需求单独 Plan。 |
| 与现有 source 冲突 | CLI/API Literal/source dispatch 易破坏旧 source。 | 新增分支，不改旧分支；全量 API/CLI 回归。 |

---

## 6. 验收标准

### 通用验收标准

1. 不修改 `_reference_sources/`。
2. 不复制、翻译、改名复用参考源码。
3. 不修改 ModelGateway / RiskGate / KillSwitch 核心语义。
4. 不默认启用 live trading，不新增真实 broker adapter。
5. 不直接调用 provider SDK；新增 provider 使用 protocol + injectable HTTP。
6. 不删除、禁用、弱化已有测试断言。
7. 新增行为必须有测试；涉及架构/风控/模型/报告需更新文档。
8. 每个 commit 前必须通过：`.venv/bin/python -m pytest && .venv/bin/ruff check . && .venv/bin/mypy`。
9. API key、broker key、secret 不进入代码、日志、测试、fixtures、prompt、文档真实值。
10. 外部内容只作为 untrusted data，不得改变系统规则。

### Aspect 专项验收

**A. 新闻/宏观 → Strategy/Risk**：
- Signal/StrategySpec 可携带外部证据 metadata，旧数据仍可验证。
- RiskContext 能基于负面新闻/宏观风险加严 human review/risk tags。
- Positive news 不得放宽现有限额；KillSwitch 仍优先阻断。
- DailyAlphaBrief 只输出观察建议和研究任务，不输出 approved order。

**B. EnvV2 报告**：
- EnvV2 episode report 可 JSON 序列化并持久化。
- 报告包含多资产指标、成本拆分、leverage/borrow/impact 信息。
- Legacy backtest report 旧测试仍过。
- API/CLI env-v2 入口必须显式选择。

**C. Dashboard**：
- Equity curve 支持缩放、平移、重置，空数据安全。
- Backtest compare 页面返回 200，能展示 legacy/env-v2 核心指标。
- Paper equity refresh 只读，不含交易按钮。
- 外部文本均 escape。

**D. Provider**：
- 新 provider 缺 key 时返回结构化 missing-key 错误，不泄露 key。
- HTTP mock 覆盖 success/error/retry/bad payload。
- API/CLI source 分支可用，旧 source 不受影响。

---

## 7. 测试命令

### 每轮相关测试

```bash
# Strategy/Risk/Research context
.venv/bin/python -m pytest \
  tests/test_strategy_spec_schema.py \
  tests/test_strategy_interface.py \
  tests/test_research_context.py \
  tests/test_risk_gate.py

# DailyAlphaBrief / prompts / research
.venv/bin/python -m pytest \
  tests/test_daily_alpha_brief.py \
  tests/test_prompt_templates.py \
  tests/test_research.py

# EnvV2 / backtest reports
.venv/bin/python -m pytest \
  tests/test_trading_env_v2.py \
  tests/test_trading_env.py \
  tests/test_vectorized_backtester.py

# API / CLI / Dashboard
.venv/bin/python -m pytest \
  tests/test_api_server.py \
  tests/test_data_commands.py \
  tests/test_serve_command.py

# Providers
.venv/bin/python -m pytest \
  tests/test_news.py \
  tests/test_market_data_providers.py \
  tests/test_alphavantage_provider.py
```

### 提交前最终质量门

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check . && .venv/bin/mypy
```

---

## 8. 回滚建议

### 按 Round 回滚

每个 Round 单独 commit，提交信息建议：

```bash
git commit -m "phase-12-risk-context: add news macro risk context metadata"
git commit -m "phase-12-env-v2-report: persist multi-asset episode reports"
git commit -m "phase-12-dashboard: add backtest comparison page"
git commit -m "phase-12-provider: add twelvedata market data provider"
```

失败时优先：

```bash
git revert <commit-hash>
```

### 按 Aspect 回滚

**A. Strategy/Risk 上下文**：

```bash
git checkout packages/alphabrief-strategy/src/alphabrief_strategy/spec.py
git checkout packages/alphabrief-strategy/src/alphabrief_strategy/interface.py
git checkout packages/alphabrief-risk/src/alphabrief_risk/__init__.py
git rm packages/alphabrief-risk/src/alphabrief_risk/context.py
```

**B. EnvV2 报告**：

```bash
git checkout packages/alphabrief-gym/src/alphabrief_gym/report.py
git checkout packages/alphabrief-gym/src/alphabrief_gym/schemas.py
git checkout apps/api/src/alphabrief_api/routes/backtest.py
git checkout apps/api/src/alphabrief_api/db/backtest_reports.py
```

**C. Dashboard**：

```bash
git checkout apps/api/src/alphabrief_api/routes/dashboard.py
git checkout apps/api/src/alphabrief_api/routes/paper.py
```

**D. Provider**：

```bash
git rm packages/alphabrief-data/src/alphabrief_data/providers/twelvedata.py
git checkout packages/alphabrief-data/src/alphabrief_data/providers/__init__.py
git checkout apps/api/src/alphabrief_api/routes/data.py
git checkout apps/cli/src/alphabrief_cli/data_commands.py
git checkout .env.example
```

### 紧急停止条件

若出现以下情况，停止实现并回到 Plan：

1. 需要改 RiskGate 核心拒绝规则才能继续。
2. EnvV2 report 需要破坏 legacy report JSON。
3. Dashboard 需要新增前端依赖或执行型交易控件。
4. Provider 需要 SDK 或真实 secret 才能测试。
5. 测试大量失败且原因不明。

---

## 9. 推荐实施顺序

1. **首选 Round 12.1 → 12.3**：先完成新闻/宏观 → Strategy/Risk 的只加严上下文链路。这是 Phase 11 之后最自然的核心增量。
2. **然后 Round 12.6 → 12.8**：把 EnvV2 从“可运行环境”提升为“可报告/可持久化/可展示”的研究资产。
3. **再做 Round 12.9 → 12.11**：Dashboard 只读增强依赖稳定报告/API，不宜提前做。
4. **Provider Round 12.12 → 12.13** 可并行或延后；它是独立扩展，不应阻塞 Risk/EnvV2 主线。
5. **最后 Round 12.14**：文档、状态校正、最终 quality gate 与 handoff。

---

# 附录 A：AlphaBrief Phase 11 原开发计划（保留）

> **计划范围**：Phase 10 已完成 News & Macro Data Layer 的独立数据接入（`alphabrief_news`、DuckDB 存储、CLI/API）。Phase 11 的目标是把新闻/宏观数据真正喂进研究、交易仿真和 Dashboard，同时扩展更多免费数据源、交易环境能力和前端展示面。
>
> **计划产出**：本文件只用于规划，不直接修改业务代码。每个子任务必须拆分为独立的开发轮次（Round），遵循 `ALPHABRIEF_DEVELOPMENT_CADENCE.md` 的 `Plan -> Review Plan -> Implement -> Test -> Self Review -> Document -> Commit -> Next Task Proposal` 流程。
>
> **模型分工约定**：
> - `kimi-k2.7-code`：架构设计、多文件协议/Schema 联动、复杂 Prompt 工程、交易环境重构。
> - `deepseek-v4-flash`：数据解析、Provider 实现、Dashboard HTML/JS、结构化输出处理。
> - `minimax-m3`：单测/集成测试补充、CLI 选项扩展、文档更新、简单 Schema 字段增补。

---

## 1. 任务目标

### 1.1 新闻/宏观数据接入研究简报

- 让 `DailyAlphaBrief`、`MarketBrief`、`SymbolBrief` 的生成能够显式消费 `NewsHeadline` 与 `MacroIndicator`。
- 新增一个“研究上下文组装器”，从 `NewsStore` / `MacroStore` 按时间窗口和 symbol 拉取相关数据，渲染成自然语言上下文。
- 在 `DebateOrchestrator` 的 prompt 中注入新闻/宏观上下文，使多模型辩论能基于最新外部信息。
- 新增/升级 prompt template（例如 `daily_alpha_brief:v2`、`market_brief:v2`、`symbol_brief:v2`、`debate_context:v1`），预留 `{{news_context}}`、`{{macro_context}}` 等占位。
- 可选：对新闻 headline 做简单情绪分析（规则或模型），结果以 `SentimentLabel` 写入 `NewsHeadline.sentiment`。
- 更新 `docs/architecture.md` 中 Research Layer 与 News & Macro Data Layer 的集成说明。

### 1.2 更多数据源扩展

- 将 `FredMacroProvider` 从 stub 升级为真实可用实现：运行时读取 `FRED_API_KEY` 环境变量，仅使用 `urllib` 调用 FRED API，返回 `MacroIndicator`，不硬编码密钥。
- 新增 SEC EDGAR RSS Provider：通过 EDGAR RSS（如 `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent` 或 company feeds）获取 filings/财报披露，包装为 `NewsProvider`，headline 类别为 `earnings`。
- 新增社交媒体情绪数据源 Provider（stub 或免费 RSS/API），包装为 `NewsProvider`，输出带 `sentiment` 的 `NewsHeadline`。
- 新增一个额外的免费市场数据源 Provider（如 `AlphaVantageProvider` stub 或 `TwelveDataProvider` stub），包装为 `MarketDataProvider`，明确 API key 由用户配置。
- 所有新 Provider 必须遵循 `MarketDataProvider` / `NewsProvider` / `MacroProvider` 协议，复用 `RetryPolicy` 与结构化错误码。

### 1.3 Trading 环境扩展

- 将 `AlphaBriefTradingEnv` 从单资产 long/flat 扩展为多资产 portfolio allocation。
- 支持 continuous action space：每个资产的目标权重（可正可负），替代当前的离散 `hold/buy/sell`。
- 支持做空（short）：允许负目标权重，按 `borrow_cost` 按日计息。
- 支持杠杆模拟：设置 `max_leverage`，按杠杆约束截断或惩罚 action。
- 支持流动性约束：单个标的的最大下单金额/数量、最小交易量限制。
- 支持 borrow cost 与 market impact（可选线性冲击函数）。
- 支持 regime-aware rewards：根据市场环境（volatility / trend regime）调整 reward 缩放或夏普风格 reward。
- 同步扩展 `TradingObservation`、`StepResult`、`EpisodeMetrics` 与相关 schemas；保持旧接口在测试中的可兼容性（新增扩展版本，不破坏已有测试）。

### 1.4 Web Dashboard 完善

- 新增 `/dashboard/news` 与 `/dashboard/macro` 页面：展示已存储 headline、indicator 列表与情绪/数值趋势。
- 改进 `/dashboard` 主页：显示 paper trading 仓位列表、净值曲线、最近成交。
- 新增 `/dashboard/brief` 页面：展示 `DailyAlphaBrief` 历史与详情。
- 新增 `/dashboard/debate` 页面：展示多模型辩论记录与共识结果。
- 所有新页面均通过 JavaScript `fetch` 复用现有 API 端点，不新增未受控的后端权限或执行能力。

---

## 2. 涉及文件

### 2.1 新闻/宏观数据接入研究简报

**修改/新建文件**：
- `packages/alphabrief-models/src/alphabrief_models/briefs.py`：为 `MarketBrief`、`SymbolBrief`、`DailyAlphaBrief` 增加 `news_context` / `macro_context` / `sentiment_summary` 等可选字段。
- `packages/alphabrief-models/src/alphabrief_models/prompts.py`：新增/注册 prompt template（`daily_alpha_brief:v2`、`market_brief:v2`、`symbol_brief:v2`、`debate_context:v1`）。
- `packages/alphabrief-research/src/alphabrief_research/context.py`（新建）：`ResearchContextBuilder`，从 `NewsStore` / `MacroStore` 读取并渲染上下文文本。
- `packages/alphabrief-research/src/alphabrief_research/orchestrator.py`：在 `_build_prompt` 中注入 `question.context` 之外的新闻/宏观上下文；支持 `DebateQuestion` 携带 `news_context` / `macro_context`。
- `packages/alphabrief-research/src/alphabrief_research/schemas.py`：为 `DebateQuestion` 增加可选的 `news_context`、`macro_context`。
- `packages/alphabrief-news/src/alphabrief_news/sentiment.py`（新建）：简单情绪分析器（规则或可选模型调用），输出 `SentimentLabel`。
- `packages/alphabrief-news/src/alphabrief_news/types.py`：确认 `NewsHeadline.sentiment` 字段已存在；如需新增“情绪摘要”类型则扩展。
- `apps/api/src/alphabrief_api/routes/brief.py`：在 `/generate` 中组装研究上下文并调用升级后的生成器。
- `apps/api/src/alphabrief_api/routes/research.py`：在 `/debate` 中组装上下文并传给 `DebateOrchestrator`。
- `apps/cli/src/alphabrief_cli/brief_commands.py`：为 `brief daily` 增加 `--include-news`、`--include-macro` 等选项。
- `apps/cli/src/alphabrief_cli/research_commands.py`：为 `research debate` 增加 `--include-news`、`--include-macro` 选项。
- `tests/test_research.py`、`tests/test_daily_alpha_brief.py`、`tests/test_news.py`：新增上下文注入、prompt 渲染、schema 验证测试。
- `docs/architecture.md`：更新 Research Layer 与 News & Macro Data Layer 章节。

### 2.2 更多数据源扩展

**修改/新建文件**：
- `packages/alphabrief-news/src/alphabrief_news/providers/fred.py`：从 stub 升级为真实 `FredMacroProvider`。
- `packages/alphabrief-news/src/alphabrief_news/providers/sec_edgar.py`（新建）：`SecEdgarNewsProvider`，实现 `NewsProvider`。
- `packages/alphabrief-news/src/alphabrief_news/providers/social_sentiment.py`（新建）：`SocialSentimentNewsProvider`（stub 或真实免费源）。
- `packages/alphabrief-data/src/alphabrief_data/providers/alphavantage.py`（新建）：`AlphaVantageProvider` 或类似 `MarketDataProvider` stub。
- `packages/alphabrief-news/src/alphabrief_news/providers/__init__.py`：导出新增 provider。
- `packages/alphabrief-data/src/alphabrief_data/providers/__init__.py`：导出新增 provider。
- `apps/api/src/alphabrief_api/routes/macro.py`：`_build_provider` 中 `source=fred` 走真实实现；同时保留 `mock`。
- `apps/api/src/alphabrief_api/routes/news.py`：`_build_provider` 中新增 `sec`、`sentiment` 分支。
- `apps/api/src/alphabrief_api/routes/data.py`：`_build_provider` 中新增 `alphavantage` 分支。
- `apps/cli/src/alphabrief_cli/macro_commands.py`：支持 `source=fred`。
- `apps/cli/src/alphabrief_cli/news_commands.py`：支持 `source=sec`、`source=sentiment`。
- `apps/cli/src/alphabrief_cli/data_commands.py`：支持 `source=alphavantage`。
- `.env.example`：新增 `FRED_API_KEY`、`ALPHAVANTAGE_API_KEY` 等占位（仅占位，无真实值）。
- `tests/test_news.py`、`tests/test_market_data_providers.py`：新增 provider 单元测试（HTTP 全部 mock）。
- `docs/architecture.md`：更新 News & Macro Data Layer 与 Market Data Providers 章节。

### 2.3 Trading 环境扩展

**修改/新建文件**：
- `packages/alphabrief-gym/src/alphabrief_gym/schemas.py`（新建）：提取 `TradingObservation`、`StepResult`、`EpisodeMetrics`、`PortfolioSnapshot` 等公共 schema。
- `packages/alphabrief-gym/src/alphabrief_gym/env.py`：扩展 `AlphaBriefTradingEnv` 支持多资产、continuous action、short、leverage、liquidity、borrow cost、market impact、regime-aware reward；保留旧单资产入口的兼容性。
- `packages/alphabrief-gym/src/alphabrief_gym/rewards.py`（新建）：`RewardFunction` 协议与 `RegimeAwareReward`、`SharpeReward` 等实现。
- `packages/alphabrief-gym/src/alphabrief_gym/action.py`（新建）：`ActionSpace` 抽象、`DiscreteActionSpace`、`ContinuousActionSpace`。
- `packages/alphabrief-gym/src/alphabrief_gym/market_impact.py`（新建）：可选线性/平方根 market impact 函数。
- `packages/alphabrief-gym/src/alphabrief_gym/policies.py`：新增多资产随机策略与 regime-aware 基线。
- `packages/alphabrief-gym/src/alphabrief_gym/report.py`：扩展 `StrategyComparisonReport` 以展示多资产指标。
- `tests/test_trading_env.py`：新增扩展能力测试，不删除旧测试。
- `docs/architecture.md`：更新 Trading Environment 章节。

### 2.4 Web Dashboard 完善

**修改/新建文件**：
- `apps/api/src/alphabrief_api/routes/dashboard.py`：扩展 HTML dashboard，新增 `/dashboard/news`、`/dashboard/macro`、`/dashboard/brief`、`/dashboard/debate` 路由与页面；主页增加仓位列表、净值曲线、成交历史卡片。
- `apps/api/src/alphabrief_api/routes/paper.py`：确认已有 `/api/v1/paper/fills`、`/api/v1/paper/orders`、`/api/v1/paper/portfolio` 可被 dashboard 消费；如缺历史成交列表则补充。
- `apps/api/src/alphabrief_api/routes/status.py`：确认 `/api/status` 包含必要信息；如需补充 dashboard 用字段则扩展。
- `tests/test_api_server.py`：新增 dashboard 页面路由测试。
- `docs/architecture.md`：更新 Dashboard 章节。

---

## 3. 不应修改的范围

以下模块/文件在任何子任务中均不得修改：

1. `packages/alphabrief-models/src/alphabrief_models/gateway.py` 核心（`ModelGateway`、`ProviderAdapter`、`ModelRequest`、`ModelResponse`、`ModelCallRecord` 的定义与选择逻辑）。
2. `packages/alphabrief-risk/src/alphabrief_risk/gate.py` 核心（`RiskGate` 的判定逻辑、`RiskLimitConfig` 核心字段与拒绝规则）。
3. `packages/alphabrief-risk/src/alphabrief_risk/kill_switch.py` 核心（KillSwitch 的激活/检查语义）。
4. `_reference_sources/` 下任何文件（只读参考）。
5. 任何 provider SDK 的直接调用必须在 `ModelGateway` / ProviderAdapter 边界内；业务模块不得直接调用外部 SDK。
6. 已有的测试文件只能新增测试，不得删除、禁用或修改现有断言逻辑（除非现有断言因新增必填字段而自然失效，此时需回到 Plan 重新评估）。
7. `.env`、用户配置文件、密钥文件：只能更新 `.env.example` 占位，不得写入真实密钥。
8. live trading 相关设置：不得默认启用、不得新增真实 broker adapter、不得修改 `live_trading_enabled` 的默认语义。
9. `pyproject.toml` 的核心依赖列表：新增可选依赖需经独立评估，优先使用标准库或已有依赖。

---

## 4. 分步骤执行计划

### Round 11.1 — 扩展研究简报 Schema（上下文字段）

- **目标**：为 `MarketBrief`、`SymbolBrief`、`DailyAlphaBrief`、`DebateQuestion` 增加可选的新闻/宏观参数字段。
- **涉及文件**：`packages/alphabrief-models/src/alphabrief_models/briefs.py`、`packages/alphabrief-research/src/alphabrief_research/schemas.py`。
- **模型**：`kimi-k2.7-code`（Schema 联动设计）。
- **步骤**：
  1. 在 `MarketBrief` 增加 `news_summary: str | None`、`macro_summary: str | None`。
  2. 在 `SymbolBrief` 增加 `news_headlines: list[str]`、`macro_factors: list[str]`。
  3. 在 `DailyAlphaBrief` 增加 `news_and_macro_summary: str | None`。
  4. 在 `DebateQuestion` 增加 `news_context: str | None`、`macro_context: str | None`。
  5. 所有新增字段必须可选，避免破坏现有 fake provider 生成的测试数据。
- **验收**：现有 489 项测试仍然通过；新增 schema 边界测试。
- **回滚**：`git checkout packages/alphabrief-models/src/alphabrief_models/briefs.py packages/alphabrief-research/src/alphabrief_research/schemas.py`。

### Round 11.2 — 研究上下文组装器

- **目标**：创建 `ResearchContextBuilder`，从 `NewsStore` / `MacroStore` 拉取数据并渲染为自然语言上下文。
- **涉及文件**：`packages/alphabrief-research/src/alphabrief_research/context.py`（新建）。
- **模型**：`deepseek-v4-flash`（数据解析与文本组装）。
- **步骤**：
  1. 定义 `ResearchContextBuilder` 类，注入 `NewsStore`、`MacroStore`。
  2. 实现 `build_news_context(symbols, start, end, limit)` → 返回一段中文/英文摘要文本（ headlines 标题列表 + 情绪统计）。
  3. 实现 `build_macro_context(indicators, start, end)` → 返回宏观指标摘要文本。
  4. 提供 `build_for_symbol(symbol, start, end)` 便利方法。
  5. 所有文本输出仅用于 prompt，不用于交易决策；必须标记为 untrusted external data。
- **验收**：单元测试覆盖空数据、单条数据、多条数据、情绪统计、时间窗口过滤。
- **回滚**：删除 `packages/alphabrief-research/src/alphabrief_research/context.py`。

### Round 11.3 — Prompt Template 升级

- **目标**：新增带新闻/宏观占位的 prompt template 版本。
- **涉及文件**：`packages/alphabrief-models/src/alphabrief_models/prompts.py`、可能的 `packages/alphabrief-models/src/alphabrief_models/prompt_registry.py`（新建，可选）。
- **模型**：`kimi-k2.7-code`（Prompt 工程）。
- **步骤**：
  1. 定义 `daily_alpha_brief:v2`、`market_brief:v2`、`symbol_brief:v2`、`debate_context:v1`。
  2. 每个 template body 包含 `{{market_data_context}}`、`{{news_context}}`、`{{macro_context}}` 等占位。
  3. 在 `PromptTemplateRegistry` 中注册新版本，旧版本保留。
  4. 提供工具函数 `render_brief_prompt_v2(...)` 便于调用方使用。
- **验收**：prompt 渲染测试验证所有占位必须提供、不能多也不能少。
- **回滚**：`git checkout packages/alphabrief-models/src/alphabrief_models/prompts.py`。

### Round 11.4 — 接入 DailyAlphaBrief 与 MarketBrief/SymbolBrief 生成

- **目标**：让 brief 生成流程真正消费新闻/宏观上下文。
- **涉及文件**：`packages/alphabrief-models/src/alphabrief_models/daily.py`、`apps/api/src/alphabrief_api/routes/brief.py`、`apps/cli/src/alphabrief_cli/brief_commands.py`。
- **模型**：`kimi-k2.7-code`（多模块协调）。
- **步骤**：
  1. 在 API `/generate` 中调用 `ResearchContextBuilder` 组装上下文。
  2. 渲染 `daily_alpha_brief:v2` prompt，传入 `generate_daily_alpha_brief`。
  3. 在 CLI `brief daily` 增加 `--include-news`、`--include-macro` 选项。
  4. fake provider 的 sample brief 保持旧字段兼容，仅当使用 v2 时才需要新字段。
- **验收**：API/CLI 集成测试验证上下文注入与生成成功；结构校验通过。
- **回滚**：还原 brief route、CLI、daily generator 的改动。

### Round 11.5 — DebateOrchestrator 接入新闻/宏观上下文

- **目标**：多模型辩论 prompt 能使用外部新闻/宏观上下文。
- **涉及文件**：`packages/alphabrief-research/src/alphabrief_research/orchestrator.py`、`apps/api/src/alphabrief_api/routes/research.py`、`apps/cli/src/alphabrief_cli/research_commands.py`。
- **模型**：`kimi-k2.7-code`（Prompt 工程）。
- **步骤**：
  1. 修改 `_build_prompt`：若 `question.news_context` / `question.macro_context` 非空，追加到 prompt 的 Context 段。
  2. 在 API `/debate` 中根据请求参数调用 `ResearchContextBuilder` 组装上下文。
  3. 在 CLI `research debate` 增加 `--include-news`、`--include-macro` 选项。
  4. 更新 `_PERSPECTIVE_PROMPTS` 中的 fundamental/risk/judge 视角说明，提示其考虑提供的外部信息但保持批判性。
- **验收**：debate 测试验证上下文出现在 prompt 文本中；模型响应解析正常。
- **回滚**：还原 orchestrator、route、CLI 改动。

### Round 11.6 — 新闻情绪分析（可选）

- **目标**：为 headline 生成简单情绪标签。
- **涉及文件**：`packages/alphabrief-news/src/alphabrief_news/sentiment.py`（新建）、`packages/alphabrief-news/src/alphabrief_news/providers/rss.py`。
- **模型**：`deepseek-v4-flash`（规则/轻量模型实现）。
- **步骤**：
  1. 实现 `RuleBasedSentimentAnalyzer`：基于关键词列表（positive/negative）打分，输出 `SentimentLabel`。
  2. 可选实现 `ModelSentimentAnalyzer`：通过 `ModelGateway` 调用低成本模型做摘要情绪判断；必须隔离，不得让外部内容改变系统规则。
  3. 在 `RssNewsProvider` 解析 headline 后调用默认规则分析器填充 `sentiment`。
  4. 提供 `sentiment_summary(headlines)` 工具函数供 `ResearchContextBuilder` 使用。
- **验收**：单元测试覆盖正负中三类 headline；模型版本测试验证 prompt 安全边界。
- **回滚**：删除 sentiment 模块并移除 RSS provider 中的调用。

### Round 11.7 — FredMacroProvider 真实实现

- **目标**：把 FRED stub 替换为可配置的 urllib 实现。
- **涉及文件**：`packages/alphabrief-news/src/alphabrief_news/providers/fred.py`。
- **模型**：`deepseek-v4-flash`（数据解析）。
- **步骤**：
  1. `FredMacroProvider` 接收 `api_key: str | None = None`；若为 None 则读取 `FRED_API_KEY` 环境变量；仍缺失则抛 `NO_API_KEY`。
  2. 使用 `urllib` 调用 `https://api.stlouisfed.org/fred/series/observations`。
  3. 解析 JSON/XML，返回 `list[MacroIndicator]`；`indicator_id` 形如 `fred:{series_id}`。
  4. 复用 `call_with_retry` 与 `NewsProviderError` 错误码。
  5. 不记录、不存储 API key。
- **验收**：HTTP mock 测试覆盖成功、NO_API_KEY、HTTP 错误、空返回、retry。
- **回滚**：恢复 FRED stub版本。

### Round 11.8 — SEC EDGAR News Provider

- **目标**：通过 EDGAR RSS 获取 filings/财报数据。
- **涉及文件**：`packages/alphabrief-news/src/alphabrief_news/providers/sec_edgar.py`（新建）。
- **模型**：`deepseek-v4-flash`（XML/HTTP 解析）。
- **步骤**：
  1. 使用 `urllib` 请求 SEC EDGAR current RSS 或指定 CIK 的 RSS feed。
  2. 使用标准库 XML 解析，提取 title、link、filing date、form type。
  3. 将每条 filing 映射为 `NewsHeadline`，`category="earnings"`（form 10-K/10-Q/8-K 等），`symbols=[ticker]`。
  4. 遵守 SEC 公平访问政策：设置 `User-Agent`（可配置公司/联系邮箱，但不硬编码真实邮箱）。
  5. 注入 `http_get` 便于测试 mock。
- **验收**：mock RSS 测试覆盖解析、时间窗口过滤、错误处理。
- **回滚**：删除 `sec_edgar.py` 并从 `__init__.py`、route、CLI 中移除引用。

### Round 11.9 — 社交媒体情绪 Provider（stub/真实）

- **目标**：新增一个 `NewsProvider` 输出带情绪的社交/情绪数据。
- **涉及文件**：`packages/alphabrief-news/src/alphabrief_news/providers/social_sentiment.py`（新建）。
- **模型**：`minimax-m3`（简单 provider 与测试）。
- **步骤**：
  1. 若找到免费稳定源（如 Crypto Fear & Greed RSS 或类似公开端点），实现真实 HTTP 抓取。
  2. 若未找到稳定免费源，则实现 `SocialSentimentNewsProvider` 为 stub，返回确定性 mock 数据并抛 `UNSUPPORTED_OPERATION` 当用户请求真实抓取。
  3. 输出 `NewsHeadline`，`sentiment` 字段填充，类别可设为 `other` 或新增 `sentiment` literal（需同步 `NewsCategory`）。
- **验收**：stub 模式测试覆盖；真实模式测试覆盖 HTTP mock。
- **回滚**：删除 `social_sentiment.py` 并移除引用。

### Round 11.10 — 额外免费市场数据 Provider

- **目标**：新增一个 `MarketDataProvider` 实现（stub 或真实）。
- **涉及文件**：`packages/alphabrief-data/src/alphabrief_data/providers/alphavantage.py`（新建，或类似）。
- **模型**：`minimax-m3`（简单 provider 与测试）。
- **步骤**：
  1. 实现 `AlphaVantageProvider`（或 TwelveData/EODHD stub），仅使用 `urllib`。
  2. API key 从 `ALPHAVANTAGE_API_KEY` 环境变量读取；缺失则抛 `MISSING_API_KEY` 类错误。
  3. 支持常见 interval（1d 等），返回 `list[Bar]`，`source="alphavantage"`。
  4. 复用 `MarketDataProviderError` 与 `RetryPolicy`。
- **验收**：mock 测试覆盖成功、缺 key、HTTP 错误、数据解析。
- **回滚**：删除新增文件并移除 route/CLI 引用。

### Round 11.11 — CLI/API 暴露新数据源

- **目标**：让用户能通过 CLI/API 使用 FRED、SEC、Sentiment、新市场数据源。
- **涉及文件**：`apps/cli/src/alphabrief_cli/macro_commands.py`、`apps/cli/src/alphabrief_cli/news_commands.py`、`apps/cli/src/alphabrief_cli/data_commands.py`、`apps/api/src/alphabrief_api/routes/macro.py`、`apps/api/src/alphabrief_api/routes/news.py`、`apps/api/src/alphabrief_api/routes/data.py`、`.env.example`。
- **模型**：`minimax-m3`（CLI/API 选项扩展与测试）。
- **步骤**：
  1. 在 `_build_provider` 中新增 source 分支。
  2. 更新 request/response 的 `Literal` 类型。
  3. 更新 `--source` help 文本。
  4. 在 `.env.example` 增加 `FRED_API_KEY=`、`ALPHAVANTAGE_API_KEY=` 占位。
- **验收**：CLI 集成测试验证各 source 分支；API 集成测试验证请求校验与 mock provider。
- **回滚**：还原 CLI/API 改动与 `.env.example`。

### Round 11.12 — Trading Env Schema 重构

- **目标**：提取并扩展 Trading Env 的公共 schema。
- **涉及文件**：`packages/alphabrief-gym/src/alphabrief_gym/schemas.py`（新建）、`packages/alphabrief-gym/src/alphabrief_gym/env.py`。
- **模型**：`kimi-k2.7-code`（架构设计）。
- **步骤**：
  1. 新建 `schemas.py`，定义 `PortfolioSnapshot`、`AssetObservation`、`MultiAssetObservation`、`ContinuousActionSpace`、`DiscreteActionSpace`、`EpisodeMetricsV2`。
  2. `env.py` 保留现有单资产类，但内部依赖新 schema；不破坏已有测试。
  3. 新增 `AlphaBriefTradingEnvConfig` dataclass，支持多资产、continuous action、short、leverage 等开关。
- **验收**：所有现有 `test_trading_env.py` 测试通过；新 schema 单元测试通过。
- **回滚**：删除 `schemas.py` 并还原 `env.py`。

### Round 11.13 — 多资产与 Continuous Action

- **目标**：实现多资产 portfolio allocation 与 continuous action space。
- **涉及文件**：`packages/alphabrief-gym/src/alphabrief_gym/env.py`、`packages/alphabrief-gym/src/alphabrief_gym/action.py`。
- **模型**：`kimi-k2.7-code`（复杂交易环境逻辑）。
- **步骤**：
  1. `AlphaBriefTradingEnv` 接收 `assets: list[str]` 与对应 bars（按 symbol 组织）。
  2. continuous action 为 `dict[str, Decimal]`，表示每个资产的目标权重 [-max_leverage, max_leverage]。
  3. step 时根据目标权重与当前价格计算目标市值，再计算买卖量，按 execution logic 成交。
  4. 默认 `max_leverage=1.0` 保持无杠杆。
- **验收**：单元测试验证两资产、连续权重、再平衡。
- **回滚**：还原 env.py/action.py。

### Round 11.14 — Short、Leverage、Borrow Cost

- **目标**：支持做空、杠杆、借券成本。
- **涉及文件**：`packages/alphabrief-gym/src/alphabrief_gym/env.py`、`packages/alphabrief-gym/src/alphabrief_gym/rewards.py`。
- **模型**：`kimi-k2.7-code`（金融逻辑）。
- **步骤**：
  1. 允许负目标权重表示做空；做空部分按日计 `borrow_cost`（年化转日化）。
  2. `max_leverage` 约束总敞口绝对值 / portfolio_value。
  3. 杠杆使用下，按 `margin_rate` 计算所需保证金，超限则截断 action 或触发 episode 终止（可配置）。
  4. 在 `info` 中返回 `leverage`、`borrow_cost_accrued`。
- **验收**：单元测试验证做空盈利/亏损、borrow cost 扣减、杠杆超限行为。
- **回滚**：还原相关模块。

### Round 11.15 — Liquidity 与 Market Impact

- **目标**：增加流动性约束和市场冲击模拟。
- **涉及文件**：`packages/alphabrief-gym/src/alphabrief_gym/env.py`、`packages/alphabrief-gym/src/alphabrief_gym/market_impact.py`。
- **模型**：`deepseek-v4-flash`（实现与测试）。
- **步骤**：
  1. `market_impact_model` 可选：`LinearImpact`（价格冲击与下单金额占日均成交额比例线性相关）。
  2. `liquidity_limit`：每个资产单步最大成交金额或数量。
  3. 当目标交易量超过流动性限制时，按限制成交，剩余量作为未成交 intent 不执行。
  4. 更新 `EpisodeMetrics` 加入 `slippage_cost`、`market_impact_cost`。
- **验收**：单元测试验证冲击函数、流动性截断、成本拆分。
- **回滚**：删除 market_impact.py 并还原 env.py。

### Round 11.16 — Regime-Aware Rewards

- **目标**：根据市场环境调整 reward。
- **涉及文件**：`packages/alphabrief-gym/src/alphabrief_gym/rewards.py`。
- **模型**：`deepseek-v4-flash`。
- **步骤**：
  1. 定义 `RewardFunction` Protocol：`compute(step_info) -> Decimal`。
  2. 实现 `PnLReward`（默认）、`SharpeStyleReward`（滚动夏普近似）、`RegimeScaledReward`（高波动 regime 下缩放 reward）。
  3. 在 `AlphaBriefTradingEnv` 构造时注入 `reward_function`。
  4. Regime 可基于历史 close 的滚动波动或预定义 regime 标签计算；不允许使用未来 bar。
- **验收**：单元测试验证不同 reward 函数、regime 不泄露未来。
- **回滚**：删除 rewards.py 并恢复默认 PnL reward。

### Round 11.17 — Dashboard 主页增强

- **目标**：在 `/dashboard` 展示 paper trading 仓位、净值曲线、成交历史。
- **涉及文件**：`apps/api/src/alphabrief_api/routes/dashboard.py`、`apps/api/src/alphabrief_api/routes/paper.py`（如缺 fills 历史接口则补充）。
- **模型**：`deepseek-v4-flash`（前端）。
- **步骤**：
  1. 在 dashboard HTML 新增卡片：Positions（列表）、Equity Curve（Canvas/SVG 简单折线）、Recent Fills（列表）。
  2. 通过 `fetch` 调用 `/api/v1/paper/portfolio`、新增/已有的 `/api/v1/paper/fills`。
  3. 保持现有风格与颜色语义；不引入外部 CDN（避免新增依赖）。
- **验收**：API 测试验证页面返回 200 且包含新增 DOM 元素；数据接口测试通过。
- **回滚**：还原 dashboard.py。

### Round 11.18 — Dashboard 新闻/宏观/简报/辩论页面

- **目标**：新增独立页面展示新闻、宏观、简报、辩论。
- **涉及文件**：`apps/api/src/alphabrief_api/routes/dashboard.py`。
- **模型**：`deepseek-v4-flash`（前端）。
- **步骤**：
  1. 新增 `/dashboard/news`：列表展示 `/api/v1/news/headlines`，显示 title、source、category、sentiment。
  2. 新增 `/dashboard/macro`：列表展示 `/api/v1/macro/indicators`，显示 name、value、unit、released_at。
  3. 新增 `/dashboard/brief`：列表 + 详情展示 `/api/v1/brief/history` 与 `/{id}`。
  4. 新增 `/dashboard/debate`：列表 + 详情展示 `/api/v1/research/debate`。
  5. 在 dashboard 主页增加导航链接。
- **验收**：每个新页面路由返回 200；页面测试验证关键 DOM 与 fetch 端点。
- **回滚**：还原 dashboard.py。

### Round 11.19 — 文档更新与架构说明

- **目标**：更新 `docs/architecture.md` 与 `docs/roadmap.md` 反映 Phase 11 变化。
- **涉及文件**：`docs/architecture.md`、`docs/roadmap.md`。
- **模型**：`minimax-m3`。
- **步骤**：
  1. 在 `architecture.md` 更新 Research Layer 集成新闻/宏观数据、Trading Environment 扩展、Market Data Providers 新增 provider、Dashboard 新页面。
  2. 在 `roadmap.md` 增加 Phase 11 章节，记录完成状态、测试数量变化。
- **验收**：文档与代码一致；无语法错误。
- **回滚**：`git checkout docs/architecture.md docs/roadmap.md`。

---

## 5. 风险点

### 5.1 新闻/宏观数据接入研究简报

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| Prompt 注入 | 外部新闻内容可能包含恶意指令，若直接放入 prompt 可能诱导模型绕过规则。 | 所有外部内容标记为 untrusted；不得让外部内容修改系统规则；生成的 OrderIntent 仍必须过 RiskGate。 |
| 模型幻觉加剧 | 模型可能基于不完整新闻产生过度自信观点。 | 多模型辩论 + 风险反方视角；`needs_human_review` 默认开启；研究输出不直接转订单。 |
| 数据新鲜度不足 | RSS/mock 数据可能滞后，导致研究简报基于过时信息。 | 在上下文中显式标注数据时间窗口与来源；支持 `data_version` 追踪。 |
| Schema 兼容破坏 | 新增必填字段会导致现有 fake provider 测试失败。 | 所有新增字段必须可选（`Optional` 或默认值）。 |

### 5.2 更多数据源扩展

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| API key 泄露 | FRED/AlphaVantage 需要 key，实现不当可能写入代码或日志。 | 只从环境变量读取；不在代码/日志/测试/fixtures 中存储或打印 key；错误信息不返回 key。 |
| 外部 API 可用性变化 | SEC/Yahoo/Binance/FRED 接口可能变更或限流。 | 使用结构化错误码；复用 retry；对不稳定源优先实现为 stub 并文档化。 |
| 法律/合规 | SEC EDGAR 有公平访问政策；抓取需合理 User-Agent 与速率。 | 使用可配置 User-Agent；遵守 robots/速率限制；不提供绕过限制的逻辑。 |
| 依赖膨胀 | 新增 provider 可能引入 SDK。 | 仅使用标准库 `urllib`；新增 PyPI 依赖需独立评估。 |

### 5.3 Trading 环境扩展

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| 回测真实性虚假提升 | 连续 action、杠杆、做空若成本参数不合理，可能产生误导性收益。 | 默认参数保守；所有 cost/impact 必须显式可配置并计入 metrics；不允许零成本默认。 |
| 未来函数泄漏 | Regime-aware reward 若误用未来 bar 计算 regime，会导致 reward 泄漏。 | 严格使用当前及历史数据；新增 “no-lookahead” 测试。 |
| 与旧测试不兼容 | 多资产改造可能破坏现有单资产测试。 | 保留旧单资产 API 入口；新增扩展版本；不修改已有测试断言。 |
| 杠杆/做空默认启用 | 可能让 paper trading 产生意外大亏损。 | 默认 `max_leverage=1.0`、默认不允许 short；启用 short/leverage 需显式配置。 |

### 5.4 Web Dashboard 完善

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| XSS | Dashboard 展示外部新闻 headline 时若未转义可能触发 XSS。 | 所有外部文本使用 `escapeHtml`；不直接拼接 HTML。 |
| 信息泄露 | Dashboard 若暴露 API key 或配置详情会造成泄露。 | 只调用已存在的只读 API；不在前端暴露密钥字段。 |
| 前端依赖失控 | 引入图表库可能导致依赖和版本问题。 | Phase 11 仅使用原生 Canvas/SVG 或简单 DOM，不引入新 JS 库。 |
| 功能蔓延 | Dashboard 容易越做越大。 | 本阶段只做新闻/宏观/简报/辩论/仓位/净值/成交展示，不做拖拽编辑器、权限系统。 |

---

## 6. 验收标准

### 6.1 通用验收标准（每个 Round 都必须满足）

1. `ruff check .` 无错误。
2. `mypy` strict 模式无错误。
3. `pytest` 全部通过（当前基线 489 项）。
4. 不修改 `_reference_sources/`。
5. 不修改 ModelGateway / RiskGate / KillSwitch 核心。
6. 不默认启用 live trading。
7. API key 不进入代码/日志/测试/文档。
8. 新增代码必须有单元测试或集成测试覆盖；新行为至少一个通过测试。
9. 涉及架构、接口、风控、模型调用的变更必须同步更新文档。

### 6.2 各 Aspect 专项验收标准

**新闻/宏观数据接入研究简报**：
- `DailyAlphaBrief` schema 能接受新闻/宏观参数字段且验证通过。
- `ResearchContextBuilder` 能从 `NewsStore` / `MacroStore` 拉取数据并生成文本上下文。
- `DebateOrchestrator` prompt 在提供上下文时包含外部数据摘要。
- Fake provider 测试无需真实新闻/宏观数据即可通过。
- 文档说明外部内容被视为 untrusted data。

**更多数据源扩展**：
- `FredMacroProvider` 在设置 `FRED_API_KEY` 后可返回 `MacroIndicator`；未设置时抛 `NO_API_KEY`。
- `SecEdgarNewsProvider` 能解析 mock RSS 并返回 `NewsHeadline`。
- 新 provider 均通过 `RetryPolicy` 处理 HTTP 错误。
- CLI/API 暴露新 source 且请求校验正确。

**Trading 环境扩展**：
- 多资产 continuous action 环境可 `reset`/`step` 并返回合法 observation。
- 做空时 portfolio value 计算正确，borrow cost 按日扣减。
- 杠杆约束生效；超限 action 被截断或触发配置的行为。
- Market impact 与 liquidity limit 改变成交价格或成交量。
- Regime-aware reward 不使用未来数据。

**Web Dashboard 完善**：
- `/dashboard`、`/dashboard/news`、`/dashboard/macro`、`/dashboard/brief`、`/dashboard/debate` 均返回 200。
- 页面通过 `fetch` 调用现有 API，且外部文本均经过 HTML 转义。
- 不引入新的前端依赖。

---

## 7. 测试命令

每个 Round 结束后必须运行：

```bash
# 1. 类型检查
.venv/bin/mypy

# 2. Lint
.venv/bin/ruff check .

# 3. 全量测试
.venv/bin/python -m pytest

# 4. 若 Round 只影响特定模块，可先运行相关测试
.venv/bin/python -m pytest tests/test_news.py tests/test_research.py tests/test_daily_alpha_brief.py
.venv/bin/python -m pytest tests/test_trading_env.py
.venv/bin/python -m pytest tests/test_api_server.py
.venv/bin/python -m pytest tests/test_market_data_providers.py
```

**提交前最终命令**：

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check . && .venv/bin/mypy
```

---

## 8. 回滚建议

### 8.1 按 Round 回滚

每个 Round 都是独立小变更，推荐在提交前单独保存一个 commit：

```bash
git add <本轮文件>
git commit -m "phase-11-news-brief: add news/macro context fields to brief schemas"
```

若某 Round 测试失败或架构冲突，直接撤销该 commit：

```bash
git revert <commit-hash>
```

### 8.2 按 Aspect 回滚

若 Aspect 1（新闻/宏观接入）需要整体回滚：

```bash
git log --oneline --grep="phase-11-news"
# 对相关 commits 逐个 revert，或基于 baseline 重置未合并分支
```

若 Aspect 2（数据源扩展）需要整体回滚：

```bash
git rm packages/alphabrief-news/src/alphabrief_news/providers/sec_edgar.py
# 恢复 fred.py 到 stub 版本
# 移除 CLI/API 中的 source 分支
```

若 Aspect 3（Trading Env 扩展）需要回滚：

```bash
git checkout packages/alphabrief-gym/src/alphabrief_gym/env.py
# 删除新建的 schemas.py / action.py / rewards.py / market_impact.py
```

若 Aspect 4（Dashboard）需要回滚：

```bash
git checkout apps/api/src/alphabrief_api/routes/dashboard.py
```

### 8.3 紧急回滚到 Phase 10 基线

若 Phase 11 整体失败，可基于已标记的 Phase 10 tag/branch 重建：

```bash
git checkout -b phase-11-rollback phase-10-baseline
# 或 git reset --hard <phase-10-commit>
```

**注意**：`git reset --hard` 会丢失未提交改动，仅在确认无价值改动后使用。

---

## 9. 下一阶段建议（Phase 12 草案）

1. **模型评测与路由优化**：基于 ModelCallRecord 统计 schema 通过率、幻觉率、成本，自动为不同任务选择模型。
2. **策略自动生成与审计**：让模型生成 `StrategySpec` 草案，经人工/风控 review 后入库。
3. **Knowledge Base 沉淀**：把研究简报、辩论、回测、交易记录写入可检索知识库。
4. **更真实的市场数据覆盖**：接入更多免费/付费数据源，并实现跨源校验与数据质量评分。
