# AlphaBrief Phase 11 — AI Handoff

> 生成时间: 2026-06-16
> 最后 Commit: `722d455` — `feat(phase-11): news/macro research integration, data sources, trading env v2, dashboard`

## 当前状态

- **工作区**: 干净，无未提交更改
- **测试**: 597 passed（从 Phase 10 的 489 +108）
- **mypy**: ✅ 0 errors（strict 模式）
- **ruff**: ✅ clean

## Phase 11 完成内容（4 大方向，19 个 Round）

### 1. 新闻/宏观数据 → 研究简报 ✅
- `MarketBrief` / `SymbolBrief` / `DailyAlphaBrief` Schema 新增 `news_summary`、`macro_summary` 等可选字段
- `DebateQuestion` 新增 `news_context` / `macro_context`
- **`ResearchContextBuilder`** (`alphabrief_research/context.py`) — 从 `NewsStore` / `MacroStore` 拉取数据渲染为自然语言上下文
- v2 Prompt Templates: `daily_alpha_brief:v2`、`market_brief:v2`、`symbol_brief:v2`、`debate_context:v1`
- API `/generate` 和 CLI `--include-news` / `--include-macro` 选项
- DebateOrchestrator `_build_prompt` 注入新闻/宏观上下文
- **`RuleBasedSentimentAnalyzer`** (`alphabrief_news/sentiment.py`) — 关键词打分情绪分析

### 2. 数据源扩展 ✅
| Provider | 类型 | 状态 |
|----------|------|:----:|
| `FredMacroProvider` | Macro — 真实 urllib 实现 | ✅ |
| `SecEdgarNewsProvider` | News — SEC EDGAR RSS filings → earnings headlines | ✅ |
| `SocialSentimentNewsProvider` | News — deterministic stub | ✅ |
| `AlphaVantageProvider` | MarketData — 日/周/月 OHLCV | ✅ |
- 全部复用 `RetryPolicy`、结构化错误码，仅用 `urllib`
- CLI/API 新增 source 分支，`.env.example` 新增占位

### 3. Trading 环境 v2 ✅
- **新模块**: `action.py`、`schemas.py`、`rewards.py`、`market_impact.py`、`env_v2.py`
- `AlphaBriefTradingEnvV2` — 多资产 continuous target-weight action
- **做空**: 允许负权重，borrow cost 按日计（**默认关**）
- **杠杆**: `max_leverage` 约束（**默认 1.0**）
- **Market Impact**: 线性冲击函数（可插拔）
- **Liquidity**: 单步最大成交金额/数量约束
- **Reward**: PnL / Return / Sharpe / Regime-Scaled（可插拔）
- 旧 `AlphaBriefTradingEnv` 保持兼容，已有测试未改

### 4. Web Dashboard ✅
- `/dashboard` 主页 — 仓位列表、Equity Curve（Canvas）、成交历史
- `/dashboard/news` — 新闻 headline 列表 + 情绪
- `/dashboard/macro` — 宏观指标列表
- `/dashboard/brief` — DailyAlphaBrief 历史
- `/dashboard/debate` — 多模型辩论记录
- 纯原生 HTML/JS/CSS，无新依赖，外部文本 escapeHtml

## 约束维护情况

| 约束 | 状态 |
|------|:----:|
| 不改 ModelGateway / RiskGate / KillSwitch 核心 | ✅ |
| 不改 `_reference_sources/` | ✅ |
| API key 不进代码/日志 | ✅ |
| 无新增 SDK 依赖（仅 urllib） | ✅ |
| 无 live trading 默认启用 | ✅ |
| 已有测试断言未改 | ✅ |

## 已知问题 / 待办

- `FredMacroProvider` 和 `AlphaVantageProvider` 需用户自行配置 `FRED_API_KEY` / `ALPHAVANTAGE_API_KEY` 环境变量才能真实使用
- `SocialSentimentNewsProvider` 为 stub，真实数据源待接入
- Dashboard 页面为原生 HTML，后续可考虑更丰富的可视化
- `docs/AI_PLAN.md` 包含 Phase 11 完整计划，继续开发时可参考

## 下一轮建议方向

- **Phase 12**: 新闻/宏观数据 → 策略信号 / Risk Rules 集成
- Trading Env v2 接入回测报告对比
- Dashboard 增强（交互式图表、历史回放）
- 更多 Provider（EODHD、TwelveData 等）
