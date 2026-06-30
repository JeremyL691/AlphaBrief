"""AI Trading Committee for AlphaBrief.

The committee is a thin orchestration layer on top of the existing
research, risk, and execution stacks. It never bypasses the
deterministic ``RiskGate`` and never opens the live-trading lock. The
daily cycle is paper-only by default; the
``ALPHABRIEF_AI_TRADING_ENABLED`` feature flag must be set to actually
place orders through the paper broker.
"""

from alphabrief_trader.committee import CommitteeResult, TradingCommittee
from alphabrief_trader.committee_prompts import (
    PROMPT_VERSION,
    build_committee_prompt,
    default_roles,
)
from alphabrief_trader.daily_cycle import (
    DailyTradingCycle,
    SnapshotLoader,
    is_ai_trading_enabled,
    is_live_trading_unlocked,
)
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.execution_backend import (
    ExecutionBackend,
    ExecutionBackendError,
    ExecutionBackendResult,
    ExternalPaperExecutionBackend,
    LocalPaperExecutionBackend,
    is_ai_external_paper_enabled,
)
from alphabrief_trader.model_factory import (
    build_ai_trading_committee,
    build_ai_trading_provider,
    build_conservative_fake_provider,
)
from alphabrief_trader.rules import DisciplineConfig, DisciplineGate
from alphabrief_trader.schemas import (
    AnalystAction,
    AnalystView,
    CommitteeInput,
    CommitteeRole,
    CommitteeVote,
    ConsensusLevel,
    CycleOutcome,
    DailyCycleRecord,
    DailyCycleSummary,
    MarketSnapshot,
    OrderAttempt,
    OrderSide,
    TradePlan,
)
from alphabrief_trader.snapshot_builder import (
    BarLoader,
    HeadlineLoader,
    StoredMarketSnapshotBuilder,
)

__all__ = [
    "AiTradingStore",
    "AnalystAction",
    "AnalystView",
    "BarLoader",
    "CommitteeInput",
    "CommitteeResult",
    "CommitteeRole",
    "CommitteeVote",
    "ConsensusLevel",
    "CycleOutcome",
    "DailyCycleRecord",
    "DailyCycleSummary",
    "DailyTradingCycle",
    "DisciplineConfig",
    "DisciplineGate",
    "ExecutionBackend",
    "ExecutionBackendError",
    "ExecutionBackendResult",
    "ExternalPaperExecutionBackend",
    "HeadlineLoader",
    "LocalPaperExecutionBackend",
    "MarketSnapshot",
    "OrderAttempt",
    "OrderSide",
    "PROMPT_VERSION",
    "SnapshotLoader",
    "StoredMarketSnapshotBuilder",
    "TradePlan",
    "TradingCommittee",
    "build_committee_prompt",
    "build_ai_trading_committee",
    "build_ai_trading_provider",
    "build_conservative_fake_provider",
    "default_roles",
    "is_ai_trading_enabled",
    "is_ai_external_paper_enabled",
    "is_live_trading_unlocked",
]
