# AlphaBrief Product Blueprint

> **File Purpose**: This file is the long-term product, architecture, model integration, development, risk control, and review guide for the AlphaBrief project.
> **Suggested Location**: Project root: `ALPHABRIEF_PRODUCT_BLUEPRINT.md`.
> **Highest Principle**: AlphaBrief is an AI-native quantitative research and paper-trading system with its own architecture, its own code, and its own risk controls. External open-source projects may only serve as requirements and architecture references — they must never become the source of implementation.
> **Build Method Note**: vibe coding tools are only engineering aids used when developing the system; they are not an AlphaBrief product capability, runtime dependency, or user-facing selling point. This blueprint defines only the AlphaBrief product itself.

---

## 0. One-Line Project Definition

**AlphaBrief is a model-agnostic, local-first AI quantitative research workbench centered on research, backtesting, simulation, paper trading, risk auditing, and post-trade review.**

It helps users complete:

```text
Market data ingestion → Multi-model research and analysis → Trading hypothesis generation → Strategy formalization → Backtest validation → Simulation training → Paper trading → Risk auditing → Review and improvement
```

AlphaBrief's core value is not "letting AI make money for the user automatically," but rather:

> **Letting individual traders, like a small quantitative research team, systematically generate, validate, execute, audit, and review their trading ideas.**

AlphaBrief's AI capability comes from a unified **Model Gateway**, which can connect to APIs from different vendors, with different models, and different inference capabilities. The system is not tied to any single model vendor, and does not treat any development tool as a product capability.

---

## 1. Product North Star

### 1.1 What AlphaBrief Should Become for the User

AlphaBrief should become the user's:

```text
AI market researcher
Multi-model research committee
Strategy laboratory
Backtest laboratory
Trading simulation environment
Paper trading sandbox
Risk officer
Audit system
Trade review journal
Personal trading knowledge base
```

Final product form:

> **AI-Native Quant Research & Paper-Trading Workbench**
> **AI-Native Quantitative Research and Paper-Trading Workbench**

### 1.2 How Users Will Use AlphaBrief Daily

When a user opens AlphaBrief each day, they should see:

```text
1. Today's market summary
2. Technical structure of watched symbols
3. News / macro / sentiment changes
4. Multi-model research conclusions
5. Bull/bear argument summaries
6. Strategy signals and candidate watchlist
7. Risk officer alerts
8. Paper trading positions, orders, fills, equity
9. Historical decision review
10. Next research tasks
```

Users can input natural language:

```text
Research NVDA's bull/bear opportunities for the next 5 trading days.
Turn this trading idea into a backtestable StrategySpec.
Check whether this strategy hypothesis has look-ahead bias.
Compare multiple models' views on BTC's movement this week.
Generate today's AlphaBrief daily report.
Explain the main sources of yesterday's paper-trading loss.
```

What the system outputs is not "blind trading instructions," but:

```text
Structured research reports
Multi-model viewpoint comparison
Auditable strategy specs
Backtest reports
Risk review results
Paper trading records
Post-trade review summaries
```

---

## 2. Product Boundaries: What AlphaBrief Is and Is Not

### 2.1 What AlphaBrief Is

AlphaBrief is:

```text
1. A personal quantitative research system
2. A multi-model financial research workbench
3. A strategy hypothesis validation platform
4. A backtest and simulation system
5. A paper trading system
6. A risk control and audit system
7. A trade review system
8. A personal research knowledge base
```

### 2.2 What AlphaBrief Is Not

AlphaBrief is not:

```text
1. An AI auto-trading robot
2. A high-frequency trading system
3. A one-click "get rich quick" strategy generator
4. Code stitched together from three GitHub projects
5. A wrapper app for some model vendor
6. A productized wrapper around some development tool
7. A system that defaults to live-money auto-ordering
8. A system that lets models modify trading logic without audit
```

### 2.3 What MVP Explicitly Does Not Do

MVP does not include:

```text
1. Default live trading
2. Leveraged auto-trading
3. High-frequency trading
4. Models placing orders directly
5. Models autonomously adding to positions
6. Auto-strategies going straight to live trading
7. Unaudited broker adapters
8. Backtests without transaction costs
9. Non-reproducible research workflows
10. Untraceable model outputs
```

---

## 3. Role of the Three Reference Projects in AlphaBrief

This project will place the source code of three GitHub projects into the project folder as **reference material**. They are used only to understand the product form, module boundaries, interaction patterns, test scenarios, and architectural ideas.

AlphaBrief does not copy, repurpose under renamed files, directly migrate, or use their code as an implementation foundation.

| Reference Project | Reference Value in AlphaBrief | What Is Not Allowed |
|---|---|---|
| QuantDinger | Local-first quant platform, strategy development, backtesting, execution, product shell, audit logs | Do not copy backend, frontend, broker adapter, UI, naming, or business code |
| TradingGym | Gym/Gymnasium-style trading simulation environment, reward, episode, action/observation design | Do not copy env implementation, reward implementation, or training scripts |
| TradingAgents | Multi-agent research workflow, analyst / researcher / risk / trader role division | Do not copy agent prompts, workflow implementation, class structures, or tool-calling code |

### 3.1 Reference Source Directory Rules

Recommended directory:

```text
alphabrief/
├── _reference_sources/
│   ├── QuantDinger/        # Read-only reference source
│   ├── TradingGym/         # Read-only reference source
│   └── TradingAgents/      # Read-only reference source
├── docs/
├── packages/
├── apps/
└── PROJECT_RULES.md
```

`_reference_sources/` must follow these rules:

```text
1. It is not included in the AlphaBrief package import path.
2. AlphaBrief code may not import any module from it.
3. Functions, classes, files, comments, prompts, configs, or tests may not be copied from the reference sources.
4. Files from the reference sources may not be renamed and placed into AlphaBrief.
5. Development tasks may not request "migrate this file," "rewrite based on this class," or "refactor according to this implementation."
6. Only the following may be extracted: product requirements, module boundaries, behavior descriptions, test scenarios, interaction patterns.
7. Any inspiration drawn from the reference projects must first be turned into a natural-language spec, then implemented from that spec.
8. If a reference project's license conflicts with AlphaBrief's goals, AlphaBrief's own implementation takes precedence.
```

### 3.2 The Safest Rewrite Process

We recommend the "spec extraction → isolated implementation → similarity audit" process:

```text
Phase A: Reference Analysis
1. The AI engineering assistant reads _reference_sources.
2. Only outputs docs/reference_notes/*.md.
3. reference_notes may only contain natural-language requirements, interface ideas, behavior constraints, and test scenarios.
4. Original project code snippets are not allowed.
5. Class names, function names, prompt text, and file structures from the original projects may not be preserved.

Phase B: Implementation Isolation
1. Close, move, or ignore _reference_sources.
2. Implement AlphaBrief only from blueprint, PROJECT_RULES.md, reference_notes, and issues.
3. Every module must have its own interface, its own naming, and its own tests.
4. During implementation, opening reference project files for line-by-line comparison is forbidden.

Phase C: Similarity Audit
1. Check for large blocks of similar code.
2. Check for same-named classes / same-named functions / same-structure files.
3. Check for copied prompts, comments, or README text.
4. Check licenses and NOTICE.
5. Only after passing review may changes be merged to main.
```

If the vibe coding tool does not support ignoring directories, it is recommended to temporarily move `_reference_sources/` outside the repo during the actual implementation phase.

---

## 4. Core Product Principles

### 4.1 Research-first

AlphaBrief's first principle is research, not trading.

Every trading action must be traceable back to:

```text
Research hypothesis
Data evidence
Strategy logic
Backtest results
Risk review
User authorization
```

### 4.2 Paper-first

MVP only allows paper trading.

Live trading must satisfy:

```text
1. Explicit configuration enabling it
2. Clear broker adapter unlocking
3. User secondary confirmation
4. Complete risk thresholds
5. Audit logging enabled
6. Kill switch available
7. Paper trading has run stably for at least 30-60 days
```

### 4.3 Model-as-researcher, Not Trader

Models may only generate:

```text
Research reports
Bull/bear views
Evidence summaries
Risk explanations
Strategy spec drafts
OrderIntent
Post-trade review summaries
```

Models may not directly execute:

```text
Live orders
Bypassing risk controls
Modifying broker adapters
Disabling audit logs
Changing the live trading switch
Automatically increasing leverage
Automatically raising position caps
```

### 4.4 Deterministic Risk Before Execution

Every trading intent must go through:

```text
OrderIntent → RiskGate → RiskDecision → PaperBroker / BrokerAdapter
```

Without a RiskDecision, no Order may be generated.

### 4.5 Model-agnostic

AlphaBrief must be model-agnostic.

```text
1. Not tied to any single model vendor.
2. Model names may not be hard-coded in business logic.
3. All model calls must go through the Model Gateway.
4. Different models may take on different roles.
5. Model outputs must be structured, verifiable, and auditable.
6. The system must be able to degrade gracefully when a model fails.
```

### 4.6 Audit Everything

The following must be recorded:

```text
Model inputs
Model outputs
Model version / provider / parameters
Research conclusions
Strategy signals
OrderIntent
RiskDecision
Orders
Fills
Position changes
User actions
Configuration changes
```

---

## 5. Overall System Architecture

### 5.1 Layered Architecture

```text
AlphaBrief
├── Product Layer
│   ├── Web Dashboard
│   ├── CLI
│   ├── API
│   └── Report Viewer
│
├── AI Research Layer
│   ├── Model Gateway
│   ├── Provider Adapters
│   ├── Model Registry
│   ├── Prompt / Task Templates
│   ├── Structured Output Parser
│   ├── Research Agents
│   ├── Debate / Committee Flow
│   └── Brief Generator
│
├── Strategy Layer
│   ├── StrategySpec
│   ├── Strategy Interface
│   ├── Signal Engine
│   ├── Strategy Registry
│   └── Strategy Evaluation
│
├── Simulation Layer
│   ├── Vectorized Backtester
│   ├── Event-driven Backtester
│   ├── Trading Environment
│   ├── Reward Functions
│   └── Walk-forward Evaluator
│
├── Risk Layer
│   ├── RiskGate
│   ├── Position Limits
│   ├── Order Sanity Checks
│   ├── Exposure Rules
│   ├── Drawdown Guard
│   └── Kill Switch
│
├── Execution Layer
│   ├── PaperBroker
│   ├── BrokerAdapter Interface
│   ├── OrderRouter
│   ├── Fill Simulator
│   └── Execution Audit Log
│
├── Data Layer
│   ├── Market Data Providers
│   ├── News / Macro / Sentiment Providers
│   ├── Feature Store
│   ├── Data Quality Checks
│   └── Storage
│
└── Observability Layer
    ├── Logs
    ├── Metrics
    ├── Traces
    ├── Cost Tracking
    ├── Model Evaluation
    └── Decision Archive
```

### 5.2 Core Data Flow

```text
Market Data / News / Macro
        ↓
Data Quality + Feature Store
        ↓
AI Research Layer + Strategy Layer
        ↓
ResearchBrief / StrategySpec / Signal
        ↓
Backtest / Simulation / Evaluation
        ↓
OrderIntent
        ↓
RiskGate
        ↓
RiskDecision
        ↓
PaperBroker / BrokerAdapter
        ↓
Fill / PortfolioState / AuditLog
        ↓
Review / Daily AlphaBrief / Knowledge Base
```

---

## 6. Multi-Model Integration Blueprint: Model Gateway

AlphaBrief's AI capability must be provided by a unified **Model Gateway**. Business modules may not directly call any model vendor API.

### 6.1 Responsibilities of the Model Gateway

```text
1. Unify how different vendor APIs are invoked
2. Manage providers, models, capabilities, pricing, context windows, and rate limits
3. Support capability flags for text, structured output, tool calling, long context, vision, multimodal, etc.
4. Select models based on task type
5. Support fallback and retry
6. Record inputs, outputs, cost, latency, and errors
7. Validate whether model outputs conform to the schema
8. Manage prompt templates and versions
9. Support model evaluation and A/B comparison
```

### 6.2 Provider Adapter

Every model vendor must integrate through a Provider Adapter:

```text
ModelGateway
    ├── OpenAIAdapter
    ├── AnthropicAdapter
    ├── GoogleAdapter
    ├── DeepSeekAdapter
    ├── AlibabaQwenAdapter
    ├── MoonshotAdapter
    ├── ZhipuAdapter
    ├── MistralAdapter
    ├── XAIAdapter
    ├── LocalOllamaAdapter
    └── LocalVLLMAdapter
```

Note: The above are only optional integration directions; they do not mean the MVP must implement all of them.

### 6.3 Model Capability Abstraction

Models must not be managed only by name; they must be managed by capability.

```text
ModelCapability
├── text_generation
├── structured_output
├── tool_calling
├── json_mode
├── long_context
├── low_latency
├── low_cost
├── strong_reasoning
├── multilingual
├── code_generation
├── vision
├── embeddings
└── reranking
```

Business modules may only state requirements:

```text
I need: strong_reasoning + structured_output + long_context
I need: low_cost + summarization
I need: json_mode + tool_calling
```

They may not hard-code:

```text
Must use some specific model
Must use some specific vendor
```

### 6.4 Recommended Model Task Routing

```text
Market summary: low-cost long-context model
News digest: low-cost summarization model
Complex reasoning: strong-reasoning model
Bull/bear debate: different models for cross-validation
Structured output: model with stable JSON
Code explanation: model with strong code capability
Risk review: strong-reasoning + structured-output model
Review summaries: long-context + strong Chinese-expressiveness model
```

### 6.5 Multi-Model Research Committee

AlphaBrief should support multiple models giving independent judgments on the same question.

```text
Question: Is NVDA worth adding to the watchlist for the next 5 trading days?

Model A: Technical analysis
Model B: News and earnings summary
Model C: Bear-case risk view
Model D: Synthesizing adjudicator

Output:
1. Consensus view
2. Points of disagreement
3. Key evidence
4. Uncertainty
5. Suggested observation conditions
6. Conditions that prohibit execution
```

### 6.6 Model Outputs Must Be Structured

All key model outputs must conform to a schema.

Forbidden:

```text
The model returns a free-text blob, and the system trusts it directly.
```

Required:

```text
The model returns JSON / a Pydantic-verifiable structure.
If validation fails, it is rejected from proceeding to the next stage.
```

Example:

```json
{
  "symbol": "NVDA",
  "time_horizon": "5 trading days",
  "view": "bullish_watchlist",
  "confidence": 0.62,
  "bullish_evidence": ["..."],
  "bearish_evidence": ["..."],
  "key_risks": ["..."],
  "suggested_action": "watch",
  "order_intent": null,
  "needs_human_review": true
}
```

---

## 7. Core Module Definitions

## 7.1 Data Layer

The Data Layer is responsible for all data ingestion, cleaning, storage, and quality checks.

### Goals

```text
1. Ingest OHLCV data
2. Ingest news / macro / sentiment data
3. Standardize symbol, timezone, and calendar
4. Generate features
5. Check for missing data, duplicates, and outliers
6. Save reproducible data snapshots
```

### MVP Data Sources

```text
1. CSV / Parquet
2. Manually uploaded data
3. Open API data sources
4. Simulated news inputs
```

### Future Data Sources

```text
1. Stock quotes
2. Crypto quotes
3. ETF data
4. Earnings / filings
5. News APIs
6. Social sentiment
7. Macro data
8. On-chain data
```

### Non-Negotiable Requirements

```text
1. Every backtest must record the data version.
2. All features must avoid look-ahead bias.
3. Every timestamp must carry a timezone or an explicit calendar.
4. If data quality fails, the strategy may not enter backtest.
```

---

## 7.2 Research Layer

The Research Layer is responsible for generating AlphaBrief's research content.

### Output Objects

```text
MarketBrief
SymbolBrief
SectorBrief
RiskBrief
ModelDebateReport
DailyAlphaBrief
```

### Core Capabilities

```text
1. Summarize the market environment
2. Summarize news and macro changes
3. Explain price structure
4. Detect abnormal volatility
5. Generate bull/bear hypotheses
6. Organize multiple models for cross-evaluation
7. Produce traceable research reports
```

### Research Conclusions May Not Directly Become Orders

The Research Layer may output at most:

```text
watchlist
research_thesis
strategy_hypothesis
order_intent_candidate
```

It may not output:

```text
approved_order
broker_order
live_order
```

---

## 7.3 Strategy Layer

The Strategy Layer is responsible for turning trading ideas into verifiable strategy specs.

### StrategySpec

A strategy in AlphaBrief should first be a spec, not code.

```yaml
strategy_id: ema_trend_v1
name: EMA Trend Following
universe:
  symbols: [BTC-USD]
timeframe: 4h
entry:
  condition: close > ema_50
exit:
  condition: close < ema_50
risk:
  max_position_pct: 0.2
  stop_loss: atr_2x
costs:
  fee_bps: 5
  slippage_bps: 10
evaluation:
  train_period: 2020-01-01:2023-12-31
  test_period: 2024-01-01:2025-12-31
```

### Strategy Implementation Principles

```text
1. A strategy must have a StrategySpec first.
2. Strategy implementations must be testable.
3. Strategies may not directly access the broker.
4. Strategies may only emit Signals or OrderIntents.
5. Strategies may not bypass the RiskGate.
6. Strategies must record their parameters and version.
```

### Strategy Code Generation Boundaries

AlphaBrief may use model assistance to generate:

```text
1. Strategy spec drafts
2. Strategy logic explanations
3. Test case suggestions
4. Pseudocode
5. Risk checklist
```

But production-grade strategy implementations must satisfy:

```text
1. Pass unit tests
2. Pass backtest-consistency tests
3. Pass look-ahead bias checks
4. Pass human review
5. Pass risk-control review
6. Have an explicit version number
```

Model output may not automatically enter the live-trading path.

---

## 7.4 Backtest Layer

The Backtest Layer is the core of AlphaBrief's credibility.

### Must Support

```text
1. Fees
2. Slippage
3. Equity curve
4. Benchmark comparison
5. CAGR
6. Sharpe
7. Sortino
8. Max drawdown
9. Win rate
10. Turnover
11. Exposure
12. Trade list
13. Strategy parameter snapshot
14. Data version snapshot
```

### Backtest Reports Must Include

```text
1. Strategy ID
2. Strategy parameters
3. Data range
4. Data source
5. Transaction cost assumptions
6. In-sample performance
7. Out-of-sample performance
8. Maximum drawdown
9. Worst trade
10. Whether overfitting is possible
11. Whether look-ahead bias check passed
12. Whether allowed to enter paper trading
```

### Backtests That Are Rejected

```text
1. No fees
2. No slippage
3. No out-of-sample period
4. No benchmark
5. No data version
6. No strategy parameters
7. No look-ahead bias check
8. Shows returns but no risk
```

---

## 7.5 Simulation / Trading Environment Layer

The Simulation Layer is responsible for the trading environment, RL interface, and strategy simulation.

### Goals

```text
1. Provide a Gymnasium-style trading environment
2. Support action / observation / reward abstractions
3. Support fees and slippage
4. Support multiple reward functions
5. Support comparison among random, rule-based, and RL strategies
6. Support episode-level evaluation
```

### MVP Environment

```text
AlphaBriefTradingEnv
├── Single asset
├── OHLCV input
├── Discrete action
│   ├── 0 hold
│   ├── 1 half long
│   └── 2 full long
├── transaction cost
├── slippage
├── portfolio value
└── episode metrics
```

### Future Extensions

```text
1. Multi-asset allocation
2. Continuous action
3. Shorting
4. Leverage simulation
5. Liquidity constraints
6. Borrow cost
7. Market impact
8. Regime-aware rewards
```

### Cautions

The goal of the simulation environment is not to prove a strategy makes money, but to prove:

```text
1. The environment is defined correctly
2. Transaction costs are realistic
3. The reward does not leak the future
4. Train / test separation
5. Strategies can be compared fairly
```

---

## 7.6 Risk Layer

The Risk Layer is AlphaBrief's core safety boundary.

### RiskGate Must Check

```text
1. trading_enabled
2. live_trading_enabled
3. strategy_enabled
4. symbol_allowed
5. max_position_pct
6. max_order_value
7. max_daily_loss
8. max_drawdown
9. max_leverage
10. concentration risk
11. duplicate order
12. stale signal
13. data quality status
14. model confidence threshold
15. user approval requirement
```

### RiskDecision

RiskGate outputs:

```json
{
  "approved": false,
  "reason": "Daily loss limit breached",
  "max_quantity": null,
  "risk_tags": ["daily_loss", "blocked"],
  "requires_human_review": true
}
```

### Hard Rules

```text
1. Without a RiskDecision, no Order may be generated.
2. RiskDecisions must be written to the audit log.
3. Models may not override a RiskDecision.
4. Users may not bypass the RiskGate via natural language.
5. Live trading must have an independent switch.
6. After the kill switch is triggered, all strategies stop.
```

---

## 7.7 Execution Layer

The Execution Layer is responsible for paper trading and future real-broker integration.

### MVP Only Implements PaperBroker

```text
PaperBroker
├── submit_order
├── cancel_order
├── get_positions
├── get_cash
├── get_fills
├── get_portfolio_state
└── audit_log
```

### BrokerAdapter Interface

Real brokers may be added later, but must follow a unified interface:

```text
BrokerAdapter
├── capabilities
├── connection_status
├── submit_order
├── cancel_order
├── get_order
├── list_positions
├── list_balances
├── get_fills
└── health_check
```

### Live Trading Is Forbidden From Defaulting On

```text
1. By default, no live broker adapter is enabled.
2. live_trading_enabled defaults to false in the config file.
3. Live trading defaults to false in environment variables.
4. The UI must show live-trading status.
5. First-time enabling requires secondary confirmation.
6. All live orders must be audited independently.
```

---

## 7.8 Audit & Review Layer

AlphaBrief's long-term value comes from review.

### Must Record

```text
1. Every research task
2. Every model call
3. Every strategy parameter change
4. Every backtest
5. Every signal
6. Every OrderIntent
7. Every RiskDecision
8. Every paper order
9. Every fill
10. Every position change
11. Every user confirmation
12. Every exception and failure
```

### Review Outputs

```text
DailyReview
WeeklyReview
StrategyReview
ModelPerformanceReview
RiskReview
PostTradeReview
```

### Long-Term Knowledge Base

All research, backtests, trading, and reviews should accumulate into:

```text
1. Strategy knowledge base
2. Failure case library
3. Risk case library
4. Model performance library
5. Market regime records
6. User trading-bias records
```

---

## 8. Core Domain Models

### 8.1 Market Data

```python
class Bar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: str
    data_version: str
```

### 8.2 Research

```python
class ResearchBrief:
    brief_id: str
    symbol: str
    created_at: datetime
    time_horizon: str
    market_context: str
    bullish_evidence: list[str]
    bearish_evidence: list[str]
    key_risks: list[str]
    model_votes: list[ModelVote]
    confidence: float
    suggested_next_steps: list[str]
```

### 8.3 Model Call

```python
class ModelCallRecord:
    call_id: str
    provider: str
    model: str
    task_type: str
    prompt_version: str
    input_hash: str
    output_hash: str
    latency_ms: int
    cost_estimate: Decimal | None
    status: str
    created_at: datetime
```

### 8.4 Signal

```python
class Signal:
    signal_id: str
    strategy_id: str
    symbol: str
    timestamp: datetime
    direction: Literal["long", "short", "flat"]
    confidence: float
    horizon: str
    rationale: str
```

### 8.5 OrderIntent

```python
class OrderIntent:
    intent_id: str
    source: Literal["strategy", "model", "manual"]
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    quantity: Decimal | None
    target_position_pct: Decimal | None
    limit_price: Decimal | None
    rationale: str
    created_at: datetime
```

### 8.6 RiskDecision

```python
class RiskDecision:
    decision_id: str
    intent_id: str
    approved: bool
    reason: str
    max_quantity: Decimal | None
    risk_tags: list[str]
    requires_human_review: bool
    created_at: datetime
```

### 8.7 Order

```python
class Order:
    order_id: str
    intent_id: str
    risk_decision_id: str
    broker: str
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    quantity: Decimal
    status: str
    created_at: datetime
```

---

## 9. Recommended Repository Structure

```text
alphabrief/
├── README.md
├── ALPHABRIEF_PRODUCT_BLUEPRINT.md
├── PROJECT_RULES.md
├── LICENSE
├── NOTICE.md
├── pyproject.toml
├── docker-compose.yml
├── .env.example
│
├── _reference_sources/
│   ├── QuantDinger/
│   ├── TradingGym/
│   └── TradingAgents/
│
├── docs/
│   ├── architecture.md
│   ├── model_gateway.md
│   ├── risk_model.md
│   ├── agent_protocol.md
│   ├── strategy_spec.md
│   ├── backtest_standard.md
│   ├── paper_trading.md
│   ├── reference_notes/
│   └── roadmap.md
│
├── apps/
│   ├── api/
│   ├── web/
│   └── worker/
│
├── packages/
│   ├── alphabrief-core/
│   ├── alphabrief-data/
│   ├── alphabrief-models/
│   ├── alphabrief-research/
│   ├── alphabrief-strategy/
│   ├── alphabrief-backtest/
│   ├── alphabrief-gym/
│   ├── alphabrief-risk/
│   ├── alphabrief-execution/
│   └── alphabrief-audit/
│
├── strategies/
│   ├── examples/
│   ├── experiments/
│   └── paper_enabled/
│
├── reports/
├── notebooks/
├── scripts/
└── tests/
```

---

## 10. Module Responsibility Boundaries

### 10.1 alphabrief-core

Responsible for:

```text
domain models
events
errors
config
time utilities
symbol utilities
```

Not responsible for:

```text
model calls
broker calls
UI
external data fetching
```

### 10.2 alphabrief-models

Responsible for:

```text
Model Gateway
provider adapters
model registry
prompt templates
structured output parsing
model call logging
model evaluation
```

Not responsible for:

```text
trade execution
position modification
risk bypass
strategy start/stop directly
```

### 10.3 alphabrief-research

Responsible for:

```text
market brief
symbol brief
multi-model debate
risk narrative
daily AlphaBrief report
```

Not responsible for:

```text
generating Orders
calling brokers
modifying portfolio
```

### 10.4 alphabrief-strategy

Responsible for:

```text
StrategySpec
strategy interface
signal generation
strategy registry
parameter management
```

Not responsible for:

```text
placing orders directly
sneakily adjusting orders after reading live broker state
disabling risk controls
```

### 10.5 alphabrief-backtest

Responsible for:

```text
vectorized backtest
event-driven backtest
metrics
backtest reports
walk-forward validation
```

Not responsible for:

```text
live execution
model calls
user interface
```

### 10.6 alphabrief-risk

Responsible for:

```text
RiskGate
limits
pre-trade checks
post-trade checks
kill switch
risk reports
```

It may not be bypassed by any module.

### 10.7 alphabrief-execution

Responsible for:

```text
PaperBroker
BrokerAdapter
OrderRouter
FillSimulator
execution logs
```

Must depend on:

```text
RiskDecision
```

Without a RiskDecision, submitting orders is not allowed.

---

## 11. Tech Stack Recommendations

### 11.1 MVP Tech Stack

```text
Language: Python 3.12+
API: FastAPI
Validation: Pydantic
DataFrame: pandas / polars
Storage: DuckDB + Parquet
Testing: pytest
Property Testing: hypothesis
Lint: ruff
Type Check: mypy / pyright
CLI: typer
Scheduler: APScheduler / Celery / RQ / Arq
Frontend MVP: Streamlit or Next.js
Charts: Plotly / lightweight-charts
```

### 11.2 Future Tech Stack

```text
DB: PostgreSQL
Cache: Redis
Queue: Celery / Dramatiq / Arq
Frontend: Next.js
Auth: Auth.js / custom JWT
Observability: OpenTelemetry
Deployment: Docker Compose → Kubernetes
Model Serving: Ollama / vLLM / hosted API
```

### 11.3 Configuration Principles

```text
1. All secrets are managed through environment variables or a secret manager.
2. API keys may not be written into code.
3. API keys may not be written into prompts.
4. API keys may not be written into logs.
5. Provider configuration is separated from business logic.
6. Live-trading configuration is separated from research configuration.
```

---

## 12. Development Method: Vibe Coding as an Engineering Assistant

vibe coding tools are used to accelerate engineering development, but AlphaBrief's quality bar must be determined by tests, architectural boundaries, risk-control rules, and review workflows.

### 12.1 Tool Positioning

vibe coding tools may assist with:

```text
1. Generating module drafts
2. Refactoring code
3. Supplementing tests
4. Summarizing reference source behavior
5. Generating documentation
6. Checking type errors
7. Fixing failing tests
8. Generating migration scripts
9. Writing interface adapters
```

vibe coding tools may not:

```text
1. Copy reference source implementations
2. Bypass the project's architecture
3. Skip tests
4. Skip risk controls
5. Auto-merge high-risk code
6. Generate logic that defaults live trading on
7. Casually write trading logic without a spec
```

### 12.2 Standard Format for Every Development Task

Every task must contain:

```text
Goal: What to implement
Context: Related modules and docs
Inputs: Input data / schema / config
Outputs: Output objects / files / APIs
Constraints: Prohibitions and boundaries
Tests: Tests that must be added or passed
Done When: Definition of done
```

### 12.3 Development Task Example

```text
Goal:
Implement the ModelGateway MVP for alphabrief-models.

Context:
Read ALPHABRIEF_PRODUCT_BLUEPRINT.md and docs/model_gateway.md.
Do not read or copy implementation code from _reference_sources.

Inputs:
ModelRequest, ModelTaskType, ModelCapability, ProviderConfig.

Outputs:
ModelResponse, ModelCallRecord, ProviderAdapter interface.

Constraints:
- Business modules may not directly call provider SDKs.
- Provider names may not be hard-coded in the research module.
- Do not implement anything related to real trading.
- Do not log API keys.

Tests:
- A fake provider can return structured results.
- Fallback takes effect when a provider fails.
- Schema validation failure returns a rejected status.
- ModelCallRecord contains no sensitive information.

Done When:
pytest passes, type checking passes, docs/model_gateway.md is updated.
```

### 12.4 Development Review Checklist

Every PR / commit must check:

```text
1. Was reference project code copied?
2. Are same-named classes, same-named functions, or same-structure files introduced?
3. Is RiskGate being bypassed?
4. Are models allowed to place orders directly?
5. Are API keys being written or leaked?
6. Are tests missing?
7. Is audit logging missing?
8. Is look-ahead bias risk being introduced?
9. Is live trading enabled by default?
10. Is the model-agnostic principle being broken?
```

---

## 13. What PROJECT_RULES.md Should Contain

`PROJECT_RULES.md` should be created at the project root as the rule all development tools and contributors must follow.

Suggested contents:

```text
# AlphaBrief Project Rules

1. AlphaBrief is research-first and paper-trading-first.
2. The system is model-agnostic. All model calls go through ModelGateway.
3. No provider SDK may be called directly from business modules.
4. Models cannot place orders.
5. Models can only produce structured research outputs, StrategySpec drafts, or OrderIntent.
6. Every OrderIntent must pass RiskGate.
7. No RiskDecision means no Order.
8. Live trading is disabled by default.
9. Every strategy must include tests.
10. Every backtest must include transaction costs.
11. Every backtest must include data version and parameter snapshot.
12. No strategy result is accepted without out-of-sample evaluation.
13. _reference_sources is read-only reference material.
14. Do not copy, rename, translate, or migrate code from _reference_sources.
15. Any reference-derived idea must first become a natural language spec.
16. API keys and secrets must never appear in code, logs, prompts, tests, or docs.
17. All important decisions must be audit-logged.
18. If implementation conflicts with risk rules, risk rules win.
```

---

## 14. MVP Roadmap

## Phase 1: AlphaBrief Core

Goal: Complete the minimum runnable research and backtest core.

Implementation:

```text
1. repo scaffold
2. core domain models
3. config system
4. CSV / Parquet market data loader
5. data quality checks
6. feature generation
7. StrategySpec schema
8. simple strategy interface
9. vectorized backtester
10. basic metrics
```

Done when:

```text
1. OHLCV data can be imported.
2. A moving-average strategy can be run.
3. backtest_report.json can be output.
4. Backtest includes fees and slippage.
5. Tests and type checking pass.
```

---

## Phase 2: Model Gateway + Research Brief

Goal: Complete the model-agnostic AI research layer.

Implementation:

```text
1. ModelGateway
2. ProviderAdapter interface
3. FakeProvider for tests
4. At least one real provider adapter
5. ModelRegistry
6. PromptTemplate versioning
7. Structured output parser
8. MarketBrief
9. SymbolBrief
10. DailyAlphaBrief
```

Done when:

```text
1. The research module does not directly call any provider SDK.
2. Models can be switched via configuration.
3. Model output failure can be rejected.
4. Every model call has a ModelCallRecord.
5. The daily AlphaBrief report can be generated.
```

---

## Phase 3: Risk + Paper Trading

Goal: Complete the safe paper-trading loop.

Implementation:

```text
1. OrderIntent
2. RiskGate
3. RiskDecision
4. PaperBroker
5. OrderRouter
6. FillSimulator
7. PortfolioState
8. ExecutionAuditLog
9. KillSwitch
```

Done when:

```text
1. OrderIntent must go through RiskGate.
2. RiskDecision is fully recorded.
3. PaperBroker can simulate orders and fills.
4. The kill switch can block all orders.
5. Live trading is completely off.
```

---

## Phase 4: Trading Environment

Goal: Complete the simulation environment.

Implementation:

```text
1. AlphaBriefTradingEnv
2. action / observation space
3. reward functions
4. transaction cost
5. slippage
6. random policy evaluation
7. buy-and-hold baseline
8. strategy comparison report
```

Done when:

```text
1. Environment reset / step works normally.
2. Episode metrics work normally.
3. The reward contains no look-ahead.
4. Costs and slippage take effect.
5. A baseline is available for comparison.
```

---

## Phase 5: Dashboard + Review

Goal: Complete the daily user interface.

Implementation:

```text
1. strategy list
2. backtest report viewer
3. daily AlphaBrief viewer
4. model call history
5. paper portfolio
6. order audit log
7. risk dashboard
8. review journal
```

Done when:

```text
1. Users can view research reports.
2. Users can view backtest reports.
3. Users can view paper-trading status.
4. Users can view every risk decision.
5. Users can generate daily / weekly reviews.
```

---

## 15. First Batch of GitHub Issues

```text
Issue 1: Create repository scaffold and PROJECT_RULES.md
Issue 2: Implement core domain models
Issue 3: Implement market data loader for CSV and Parquet
Issue 4: Implement data quality checks
Issue 5: Implement StrategySpec schema
Issue 6: Implement simple strategy interface
Issue 7: Implement vectorized backtester MVP
Issue 8: Implement backtest metrics and report schema
Issue 9: Implement ModelGateway interface and FakeProvider
Issue 10: Implement provider adapter configuration system
Issue 11: Implement structured output parser
Issue 12: Implement MarketBrief and SymbolBrief schemas
Issue 13: Implement DailyAlphaBrief generator
Issue 14: Implement OrderIntent and RiskDecision schemas
Issue 15: Implement RiskGate MVP
Issue 16: Implement PaperBroker MVP
Issue 17: Implement ExecutionAuditLog
Issue 18: Implement KillSwitch
Issue 19: Implement AlphaBriefTradingEnv MVP
Issue 20: Implement CLI commands for data, backtest, brief, paper
```

---

## 16. CLI Design

MVP should prioritize the CLI because it is better suited for rapidly validating the system core.

```text
alphabrief data import --file data/btc.csv --symbol BTC-USD
alphabrief data check --symbol BTC-USD
alphabrief backtest run --strategy ema_trend_v1 --symbol BTC-USD
alphabrief brief daily --symbols BTC-USD ETH-USD NVDA
alphabrief model test --provider openai --task market_summary
alphabrief paper run --strategy ema_trend_v1
alphabrief paper status
alphabrief risk check --intent order_intent.json
alphabrief audit list --date today
alphabrief review daily
```

---

## 17. API Design

### 17.1 Research API

```text
POST /research/briefs/daily
GET  /research/briefs/{brief_id}
POST /research/symbols/{symbol}/analyze
POST /research/debate
```

### 17.2 Model API

```text
GET  /models/providers
GET  /models/registry
POST /models/call
GET  /models/calls/{call_id}
GET  /models/evaluations
```

### 17.3 Strategy API

```text
POST /strategies/specs
GET  /strategies
GET  /strategies/{strategy_id}
POST /strategies/{strategy_id}/signals
```

### 17.4 Backtest API

```text
POST /backtests
GET  /backtests/{backtest_id}
GET  /backtests/{backtest_id}/report
```

### 17.5 Paper Trading API

```text
POST /paper/order-intents
POST /paper/risk-check
POST /paper/orders
GET  /paper/portfolio
GET  /paper/fills
```

### 17.6 Audit API

```text
GET /audit/events
GET /audit/model-calls
GET /audit/orders
GET /audit/risk-decisions
```

---

## 18. Data Storage Design

### 18.1 MVP Storage

```text
DuckDB
Parquet
JSONL audit logs
local filesystem
```

### 18.2 Recommended Tables

```text
bars
features
strategies
strategy_specs
backtests
backtest_metrics
model_calls
research_briefs
signals
order_intents
risk_decisions
paper_orders
paper_fills
portfolio_snapshots
audit_events
```

### 18.3 Audit Log Format

```json
{
  "event_id": "evt_...",
  "event_type": "risk_decision.created",
  "timestamp": "2026-01-01T12:00:00Z",
  "actor": "system",
  "source_module": "alphabrief-risk",
  "object_type": "RiskDecision",
  "object_id": "rd_...",
  "payload_hash": "...",
  "metadata": {
    "strategy_id": "ema_trend_v1",
    "symbol": "BTC-USD"
  }
}
```

---

## 19. Testing Standards

### 19.1 Must Test

```text
1. domain model validation
2. data loading
3. data quality checks
4. feature no-lookahead
5. strategy signal generation
6. backtest accounting
7. transaction cost
8. slippage
9. metrics correctness
10. model gateway fallback
11. structured output validation
12. risk gate rejection
13. paper broker fills
14. audit log creation
15. kill switch
```

### 19.2 High-Risk Tests

```text
1. If the model returns malicious JSON, no order may be placed.
2. If the model requests increased position size, limits may not be bypassed.
3. If the user says in natural language "ignore risk controls," it may not execute.
4. If data is missing, backtest may not run.
5. If the signal is stale, no order may be placed.
6. If the kill switch is on, no order may be placed.
7. If live trading is not enabled, no real broker may be connected.
8. Provider API keys may not enter logs.
```

### 19.3 Look-Ahead Bias Checks

Must test:

```text
1. Features only use current and past data.
2. Signal generation may not use future bars.
3. Backtest fill prices may not use prices that would not have been obtainable.
4. train / test periods are strictly separated.
5. Rolling features may not be center-aligned.
```

---

## 20. Risk and Compliance Boundaries

### 20.1 Product Disclaimers

AlphaBrief should explicitly state:

```text
1. This system is for research, paper trading, and personal decision support.
2. The system does not provide investment advice.
3. Model output may be wrong, outdated, or incomplete.
4. Backtest results do not represent future returns.
5. Users must bear trading risk themselves.
6. If real-trading capability is enabled in the future, it must be separately authorized and audited.
```

### 20.2 Model Risk

Models may:

```text
1. Fabricate facts
2. Ignore important risks
3. Misunderstand recent news
4. Be overconfident
5. Produce unstable JSON
6. Be inconsistent on the same question
7. Be influenced by prompt injection
```

The system must mitigate risk through:

```text
1. Structured output validation
2. Multi-model cross-validation
3. Citation and source-of-data recording
4. A risk bear-case role
5. Human confirmation
6. Hard risk-control rules
7. Audit logs
```

### 20.3 Prompt Injection Defense

External news, web pages, reports, and social content may contain malicious instructions.

System rules:

```text
1. External content is always treated as untrusted data.
2. External content may not change system rules.
3. External content may not request API keys.
4. External content may not trigger trade execution.
5. When models read external content, they must use a safe template.
6. Any OrderIntent generated from external content must still pass the RiskGate.
```

---

## 21. Model Evaluation System

AlphaBrief doesn't just integrate models; it also evaluates them.

### 21.1 Evaluation Dimensions

```text
1. JSON validity rate
2. Schema pass rate
3. Hallucination rate
4. Citation accuracy
5. Risk-identification ability
6. Reasoning consistency
7. Latency
8. Cost
9. Chinese expression quality
10. Ex-post contribution to trading results
```

### 21.2 Model Performance Library

Every model's task performance should be recorded:

```text
model_id
provider
capability
task type
success rate
failure rate
average latency
average cost
schema failure rate
human rating
ex-post performance
```

### 21.3 Model Selection Strategy

Model routing should not only ask "which is the strongest," but:

```text
1. What capabilities does this task need?
2. Is this task high-risk?
3. Is low latency required?
4. Is low cost required?
5. Is long context required?
6. Is Chinese expression required?
7. Is stable structured output required?
```

---

## 22. Dashboard Blueprint

The dashboard should include:

```text
1. Home
   - Today's AlphaBrief
   - Watched symbols
   - Strategy status
   - Risk alerts

2. Research
   - Market summary
   - Symbol details
   - Multi-model views
   - Bull/bear debate
   - Citations and evidence

3. Strategies
   - StrategySpec list
   - Strategy parameters
   - Signal history
   - Backtest entry

4. Backtests
   - Equity curve
   - Metrics
   - Trade list
   - In-sample / out-of-sample
   - Cost analysis

5. Paper Trading
   - Positions
   - Orders
   - Fills
   - Cash
   - Equity

6. Risk
   - RiskDecision
   - limits
   - kill switch
   - blocked orders

7. Models
   - provider status
   - Model call history
   - Cost
   - Schema failure rate
   - Model performance comparison

8. Review
   - Daily review
   - Weekly review
   - Strategy review
   - Failure cases
```

---

## 23. AlphaBrief Daily Report Format

```markdown
# AlphaBrief Daily Report

Date: 2026-01-01
Universe: BTC-USD, ETH-USD, SPY, QQQ, NVDA

## 1. Market Regime
- Trend:
- Volatility:
- Liquidity:
- Risk appetite:

## 2. Watchlist
| Symbol | View | Confidence | Reason | Risk |
|---|---|---:|---|---|

## 3. Multi-Model Consensus
- Agreement:
- Disagreement:
- Key uncertainty:

## 4. Strategy Signals
| Strategy | Symbol | Signal | Confidence | Backtest Status |
|---|---|---|---:|---|

## 5. Risk Officer Notes
- Blocked ideas:
- Position concerns:
- Data quality concerns:

## 6. Paper Trading Summary
- Portfolio value:
- Daily PnL:
- Open positions:
- New orders:

## 7. Review Questions
- What changed today?
- Which thesis was invalidated?
- What should be tested next?
```

---

## 24. AlphaBrief's Long-Term Moat

AlphaBrief's long-term value lies not in how many models it integrates, but in:

```text
1. Its own research workflow
2. Its own strategy-spec system
3. Its own backtest standards
4. Its own risk system
5. Its own audit logs
6. Its own model evaluation data
7. Its own trade review knowledge base
8. Its own paper-trading ex-post performance
```

Models are replaceable; the data and review systems are the real assets.

---

## 25. Final Acceptance Criteria

When the AlphaBrief MVP is done, it must achieve:

```text
1. Market data can be imported.
2. At least one strategy backtest can be run.
3. Backtests include costs, slippage, and risk metrics.
4. At least one model provider can be called via ModelGateway.
5. Model outputs must be structured and verifiable.
6. Daily AlphaBrief can be generated.
7. OrderIntent can be generated.
8. OrderIntent must go through RiskGate.
9. Paper-trading simulated orders and fills can complete.
10. All key behaviors have audit logs.
11. Live trading is off by default.
12. No module has directly copied reference project code.
13. Tests pass.
14. Type checking passes.
15. README and project rules are complete.
```

---

## 26. Final Principles Spanning the Whole Project

```text
Research first, not trading first.
Simulation first, not real money first.
Risk control first, not equity curve first.
Structured output first, not free text first.
Multi-model replaceable, not locked to one vendor.
Audit first, not black-box automation first.
Own implementation first, no copying reference project code.
Long-term review first, not short-term demo chasing.
```

AlphaBrief's ultimate goal is to become a personal AI quantitative research system that can be iterated over the long term:

> **It does not gamble for the user; it helps the user turn trading research into an engineering system that is verifiable, auditable, reviewable, and sustainably improvable.**