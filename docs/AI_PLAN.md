# AlphaBrief Phase 11 开发计划

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
