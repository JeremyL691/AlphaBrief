# AlphaBrief Phase 13 — AI Handoff

> 生成时间: 2026-06-17
> 最后 Commit: `<R13.1 commit>` — `phase-13-risk-gate-context: wire optional RiskContextDecision into RiskGate`
> 工作区状态: clean

## 当前状态

- **测试**: 679 passed（659 → 679，新增 20 个 R13.1 测试）
- **mypy**: ✅ 0 errors（strict 模式）
- **ruff**: ✅ clean

## Phase 13 — 已完成 Round

### R13.1 — RiskGate 接收 optional RiskContextDecision

| 项目 | 详情 |
|------|------|
| 修改文件 | `packages/alphabrief-risk/src/alphabrief_risk/gate.py` |
| 新增测试 | `tests/test_risk_gate.py`（+20 测试）|
| 文档 | `docs/risk_model.md`、`docs/roadmap.md` |
| 状态 | ✅ |

**核心变更**

- `RiskGate.evaluate()` 新增 keyword-only 参数 `risk_context: RiskContextDecision | None = None`
- 无 context 时 `evaluate()` 与 Phase 12 完全一致（byte-for-byte 向后兼容）
- 接入规则（tighten-only）：
  1. context `risk_tags` 合并进 decision tags（去重，保持原顺序）
  2. context `requires_human_review=True` 触发 `requires_human_review` 取 OR
  3. context `suggested_max_position_multiplier` ∈ (0.0, 1.0) 时按 Decimal 缩放 `max_quantity`（no rounding，只减不增）
- 硬约束：context 不能
  - 让已 rejected 的 intent 变成 approved
  - 覆盖 kill switch
  - 解除 live trading lock
  - 增加 symbol allowlist
  - 增大 `max_quantity`

**测试覆盖**

- `test_risk_gate_no_context_matches_default_behavior`
- `test_risk_gate_negative_context_flips_human_review`
- `test_risk_gate_macro_high_risk_reduces_max_quantity`
- `test_risk_gate_combined_context_applies_both_effects`
- `test_risk_gate_context_cannot_reapprove_rejected_intent`
- `test_risk_gate_context_with_multiplier_one_does_not_relax`
- `test_risk_gate_context_cannot_override_kill_switch`
- `test_risk_gate_context_cannot_override_live_trading_lock`
- `test_risk_gate_context_tags_dedup_with_existing`
- `test_risk_gate_static_human_review_and_context_combine`
- `test_risk_gate_context_multiplier_below_one_only_reduces_not_relaxes`
- 以及 9 个原有 Phase 12 测试保持不变

## Phase 12 完成内容（4 个 Commit，8 个 Round）

### 已提交 — 4 commits

| Round | 内容 | 状态 |
|-------|------|:----:|
| 12.1 | `SignalEvidence` domain model（evidence_type, sentiment_score）| ✅ |
| 12.2 | `ResearchContextSummary` 扩展（aggregate_sentiment, macro IDs）| ✅ |
| 12.3 | `alphabrief_risk.context` — deterministic tighten-only risk layer | ✅ |
| 12.4 | Strategy interface: `ExternalEvidenceConfig` + `SignalEvidence` on signals | ✅ |
| 12.5 | Risk API/CLI 暴露 risk-context endpoint + `alphabrief risk context` 命令 | ✅ |
| 12.6 | Gymnasium EnvV2 episode reports (EnvV2Report, cost breakdown) | ✅ |
| 12.7 | BacktestReport schema v2 compatible extension (`report_engine`, `save_env_v2_report`) | ✅ |
| 12.8 | CLI/API `engine="env_v2"` option for multi-asset EnvV2 backtest | ✅ |

提交记录:
- `989d535` — `phase-12-env-v2-api-cli: add engine option for multi-asset EnvV2 backtest`
- `e649775` — `phase-12-backtest-schema: add report_engine column and EnvV2 report persistence`
- `26031ce` — `phase-12-risk-context: add news/macro risk context decision layer`
- `11db8f0` — `phase-12-risk-context: add strategy external evidence + research structured summary`

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

- **R13.2**: `alphabrief risk check` CLI 和 `POST /api/v1/risk/check` 接受 optional `risk_context` payload
- **R13.3**: `alphabrief paper order` 和 `POST /api/v1/paper/orders` 接受 optional `risk_context`，merge 后要求人工 review 时阻止 auto-execution
- **R13.4**: `ExecutionAuditLog` 记录 risk-context decision ID、tags、multiplier；不暴露 secret
- **R13.5**: 文档、roadmap、AI handoff 最终更新
- Dashboard risk context 页面（Phase 14+ 候选）
- Trading Env V2 接入回测报告对比（Phase 14+ 候选）
