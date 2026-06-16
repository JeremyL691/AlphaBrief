# AlphaBrief Phase 12 — AI Handoff

> 生成时间: 2026-06-16
> 最后 Commit: `26031ce` — `phase-12-risk-context: add news/macro risk context decision layer`
> 工作区包含: R12.5–R12.6 未提交改动

## 当前状态

- **工作区**: 有未提交更改（10 个文件 + 1 个新测试文件）
- **测试**: 659 passed（从 Phase 11 的 597 +62）
- **mypy**: ✅ 0 errors（strict 模式）
- **ruff**: ✅ clean

## Phase 12 完成内容（2 个 Commit，6 个 Round）

### 已提交 (R12.1–R12.4) — 2 commits

| Round | 内容 | 状态 |
|-------|------|:----:|
| 12.1 | `SignalEvidence` domain model（evidence_type, sentiment_score）| ✅ |
| 12.2 | `ResearchContextSummary` 扩展（aggregate_sentiment, macro IDs）| ✅ |
| 12.3 | `alphabrief_risk.context` — deterministic tighten-only risk layer | ✅ |
| 12.4 | Strategy interface: `ExternalEvidenceConfig` + `SignalEvidence` on signals | ✅ |

提交记录:
- `26031ce` — `phase-12-risk-context: add news/macro risk context decision layer`
- `11db8f0` — `phase-12-risk-context: add strategy external evidence + research structured summary`

### 工作区 (R12.5–R12.6) — 未提交

| Round | 内容 | 状态 |
|-------|------|:----:|
| 12.5 | Risk API/CLI 暴露 risk-context endpoint + `alphabrief risk context` 命令 | ✅ |
| 12.6 | Gymnasium EnvV2 episode reports (EnvV2Report, cost breakdown) | ✅ |

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

## 已知问题 / 待办

- R12.5–R12.6 代码未提交（见工作区改动列表）
- `FredMacroProvider` 和 `AlphaVantageProvider` 需用户自行配置环境变量
- `SocialSentimentNewsProvider` 为 stub，真实数据源待接入

## 下一轮建议方向

- **Phase 13**: Risk context → RiskGate 正式接线（RiskGate 在评估 OrderIntent 时可选地读取 NewsMacroRiskContext）
- Dashboard risk context 页面
- Trading Env V2 接入回测报告对比
