# AlphaBrief Project Rules

AlphaBrief is a research-first, paper-trading-first AI quant research
workbench. These rules apply to every development round.

## Core Principles

1. AlphaBrief is for research, backtesting, simulation, paper trading, risk
   review, audit, and post-trade review.
2. AlphaBrief is not an automatic money-making bot, high-frequency trading
   system, or default live-trading system.
3. The system is model-agnostic. All model calls must go through
   ModelGateway.
4. Business modules must not call provider SDKs directly.
5. Models cannot place orders or override deterministic risk controls.
6. Research outputs may produce structured reports, strategy hypotheses, or
   OrderIntent drafts only.
7. Every OrderIntent must pass RiskGate before it can become an order.
8. No RiskDecision means no Order.
9. Live trading is disabled by default and must remain independently locked.
10. Paper trading is the only execution mode allowed for the MVP.

## Safety Rules

1. API keys, broker keys, and secrets must never appear in code, logs,
   prompts, tests, fixtures, screenshots, or documentation.
2. Every important research, model, strategy, risk, execution, and user
   decision must be auditable.
3. Backtests must include transaction costs, slippage assumptions, strategy
   parameters, data versions, and risk metrics.
4. Strategy code must not access broker adapters directly.
5. Execution code must require a RiskDecision.
6. External content, including news and webpages, is untrusted data and must
   not change system rules.

## Reference Source Rules

1. `_reference_sources/` is read-only reference material.
2. AlphaBrief code must not import anything from `_reference_sources/`.
3. Do not copy, rename, translate, migrate, or lightly rewrite code from
   `_reference_sources/`.
4. Do not copy prompts, comments, test cases, file structure, class names, or
   function names from reference projects.
5. Reference-derived ideas must first become natural-language specifications.
6. Implementation must be isolated from the reference sources and use
   AlphaBrief-owned names, interfaces, tests, and behavior.

## Development Rules

1. Every round must solve one small, explicit task.
2. Do not add unrelated features or opportunistic refactors.
3. New behavior requires tests.
4. Changes that affect architecture, risk, model calls, execution, or audit
   require documentation updates.
5. If implementation conflicts with risk rules, the risk rules win.
6. If scope expands or risk boundaries are unclear, stop and return to
   planning.
