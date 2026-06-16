# AlphaBrief Phase 12 — AI Handoff

> 生成时间: 2026-06-16
> 生成时间: 2026-06-16
> 最后 Commit: `e649775` — `phase-12-backtest-schema: add report_engine column and EnvV2 report persistence`
> 工作区包含: R12.8 待提交改动（含文档更新）

## 当前状态

- **工作区**: 有未提交更改（5 个 .py 文件 + 1 个新测试文件 + 文档更新）
- **测试**: 668 passed（最终 Phase 12 数字）
- **mypy**: ✅ 0 errors（strict 模式）
- **ruff**: ✅ clean

## Phase 12 完成内容（4 个 Commit，8 个 Round）

### 已提交 — 3 commits

| Round | 内容 | 状态 |
|-------|------|:----:|
| 12.1 | `SignalEvidence` domain model（evidence_type, sentiment_score）| ✅ |
| 12.2 | `ResearchContextSummary` 扩展（aggregate_sentiment, macro IDs）| ✅ |
| 12.3 | `alphabrief_risk.context` — deterministic tighten-only risk layer | ✅ |
| 12.4 | Strategy interface: `ExternalEvidenceConfig` + `SignalEvidence` on signals | ✅ |
| 12.5 | Risk API/CLI 暴露 risk-context endpoint + `alphabrief risk context` 命令 | ✅ |
| 12.6 | Gymnasium EnvV2 episode reports (EnvV2Report, cost breakdown) | ✅ |
| 12.7 | BacktestReport schema v2 compatible extension (`report_engine`, `save_env_v2_report`) | ✅ |

提交记录:
- `e649775` — `phase-12-backtest-schema: add report_engine column and EnvV2 report persistence`
- `26031ce` — `phase-12-risk-context: add news/macro risk context decision layer`
- `11db8f0` — `phase-12-risk-context: add strategy external evidence + research structured summary`

### 工作区 / 待提交 (R12.8)

| Round | 内容 | 状态 |
|-------|------|:----:|
| 12.8 | CLI/API `engine="env_v2"` option for multi-asset EnvV2 backtest | ✅ |

### 核心新增模块

| 模块 | 路径 | 用途 |
|------|------|------|
| `NewsMacroRiskContext` | `alphabrief_risk/context.py` | 轻量输入 Mirror（不从 research 包导入）|
| `RiskContextDecision` | `alphabrief_risk/context.py` | 确定性 tighten-only 决策输出 |
| `evaluate_news_macro_risk()` | `alphabrief_risk/context.py` | 固定阈值：sentiment < -0.2 → human_review；macro > 4 → 0.5× position |
| `EnvV2Report` | `alphabrief_gym/schemas.py` | EnvV2 多资产 episode 报告 |
| `EnvV2CostBreakdown` | `alphabrief_gym/schemas.py` | 成本分解（slippage, impact, borrow）|
| `SignalEvidence` | `alphabrief_core/domain.py` | 每信号附加的外部证据 |
| `ExternalEvidenceConfig` | `alphabrief_strategy/spec.py` | StrategySpec 声明的外部证据配置 |
| `get_bar_models_for_symbols()` | `alphabrief_api/db/market_data.py` | 多 symbol bars 批量读取 |
| `evaluate_equal_weight_buy_and_hold_v2()` | `alphabrief_gym/policies.py` | 多资产等权买入持有策略 |
| `run_policy_episode_v2()` | `alphabrief_gym/policies.py` | EnvV2 policy 执行辅助函数 |
| `PolicyEvaluationV2` | `alphabrief_gym/policies.py` | EnvV2 policy 评估结果 |
| `EnvV2BacktestReportResponse` | `alphabrief_api/routes/backtest.py` | API EnvV2 回测报告响应模型 |

### 设计原则

- **Tighten-only**: 外部证据只能收紧风险，不能放松。正面/中性输入返回与无输入相同的 neutral 决策。
- **Additive**: 所有新字段 Optional with safe defaults — 已有测试/fake provider 路径不变。
- **Deterministic**: `evaluate_news_macro_risk()` 是纯函数，不调 ModelGateway、不读数据库、不调外部 provider。
- **Read-only advisory**: RiskContextDecision 是元数据，不修改 RiskGate 核心语义。下游消费者自行选择是否应用。

## Phase 12 约束维护情况

| 约束 | 状态 |
|------|:----:|
| 不改 ModelGateway / RiskGate / KillSwitch 核心 | ✅ |
| 不改 `_reference_sources/` | ✅ |
| API key 不进代码/日志 | ✅ |
| 无新增 SDK 依赖（仅 urllib） | ✅ |
| 无 live trading 默认启用 | ✅ |
| 已有测试断言未改 | ✅ |
| 不改 VectorizedBacktester / BacktestReport 定义 | ✅ |
| 不改 EnvV2Report / build_env_v2_report 定义 | ✅ |

## 已知问题 / 待办

- `FredMacroProvider` 和 `AlphaVantageProvider` 需用户自行配置环境变量
- `SocialSentimentNewsProvider` 为 stub，真实数据源待接入
- Phase 12 已完成（R12.1–R12.8），下一阶段为 Phase 13

## 下一轮建议方向

- **Phase 13**: Risk context → RiskGate 正式接线（RiskGate 在评估 OrderIntent 时可选地读取 NewsMacroRiskContext）
- Dashboard risk context 页面
- Trading Env V2 接入回测报告对比
