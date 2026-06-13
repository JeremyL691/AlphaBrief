# AlphaBrief Agent Protocol

This document records the expected protocol for future research agents.

## Boundaries

1. Agents are researchers, reviewers, and explainers; they are not autonomous
   traders.
2. Agents may produce structured research briefs, thesis comparisons,
   StrategySpec drafts, risk narratives, or OrderIntent candidates.
3. Agents must not submit orders, alter broker configuration, disable audit
   logging, or change live-trading locks.
4. Any model-backed agent must use ModelGateway.
5. Agent outputs that affect risk, strategy, or execution must be structured
   and auditable.

No agent runtime is implemented in the scaffold round.
