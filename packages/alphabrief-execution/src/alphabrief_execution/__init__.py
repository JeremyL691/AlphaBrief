"""Paper execution components for AlphaBrief."""

from alphabrief_execution.audit import ExecutionAuditEntry, ExecutionAuditLog
from alphabrief_execution.broker import (  # legacy: top-level broker.py
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerTimeInForce,
    CancelResult,
    OrderState,
    PaperBroker,
    PaperBrokerError,
    PaperBrokerResult,
    Position,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.broker import (
    Fill as BrokerFill,
)
from alphabrief_execution.broker import alpaca as alpaca_broker
from alphabrief_execution.broker import errors as broker_errors
from alphabrief_execution.broker.alpaca import (
    DEFAULT_BASE_URL,
    ENV_KEY,
    ENV_SECRET,
    AlpacaHttpClient,
    AlpacaHttpResponse,
    AlpacaPaperAdapter,
    AlpacaPaperConfig,
    load_alpaca_paper_config,
    read_alpaca_credentials,
)
from alphabrief_execution.broker.alpaca import (
    run_async as alpaca_run_async,
)
from alphabrief_execution.broker.recon_store import (
    BrokerReconStore,
    FreezeEvent,
    ReconSnapshot,
)
from alphabrief_execution.broker.reconciliation import (
    ALLOWED_SCOPES,
    ReconcilerConfig,
    ReconciliationRunner,
    ReconResult,
)
from alphabrief_execution.fills import Fill, FillSimulator
from alphabrief_execution.operations import (
    AlertSink,
    HeartbeatStore,
    OperationsScheduler,
    ScheduledTask,
    SchedulerConfig,
    SchedulerStartupBlockedError,
)
from alphabrief_execution.portfolio import PortfolioState
from alphabrief_execution.portfolio import Position as InternalPosition
from alphabrief_execution.router import OrderRouter, OrderRouterError

__all__ = [
    "ALLOWED_SCOPES",
    "AccountSnapshot",
    "AlertSink",
    "AlpacaHttpClient",
    "AlpacaHttpResponse",
    "AlpacaPaperAdapter",
    "AlpacaPaperConfig",
    "BrokerAdapter",
    "BrokerFill",
    "BrokerHealth",
    "BrokerOrderSide",
    "BrokerOrderStatus",
    "BrokerOrderType",
    "BrokerReconStore",
    "BrokerTimeInForce",
    "CancelResult",
    "DEFAULT_BASE_URL",
    "ENV_KEY",
    "ENV_SECRET",
    "ExecutionAuditEntry",
    "ExecutionAuditLog",
    "Fill",
    "FillSimulator",
    "FreezeEvent",
    "HeartbeatStore",
    "OperationsScheduler",
    "OrderRouter",
    "OrderRouterError",
    "OrderState",
    "PaperBroker",
    "PaperBrokerError",
    "PaperBrokerResult",
    "PortfolioState",
    "Position",
    "ReconcilerConfig",
    "ReconciliationRunner",
    "ReconResult",
    "ReconSnapshot",
    "ScheduledTask",
    "SchedulerConfig",
    "SchedulerStartupBlockedError",
    "SubmitRequest",
    "SubmitResult",
    "alpaca_broker",
    "alpaca_run_async",
    "broker_errors",
    "load_alpaca_paper_config",
    "read_alpaca_credentials",
    "InternalPosition",
]
