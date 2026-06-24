"""Broker adapter package.

Contains the broker-neutral :mod:`alphabrief_execution.broker.port`
plus concrete paper-only adapters (currently Alpaca).

The legacy deterministic :class:`PaperBroker` lives in
:mod:`alphabrief_execution.broker.legacy` and is re-exported here
so existing imports (``from alphabrief_execution.broker import
PaperBroker``) continue to work.

Note: BrokerAdapter instances may not be safe to share across
uncoordinated coroutines when state lives on the instance. Concrete
adapters should document their concurrency guarantees.
"""

from alphabrief_execution.broker.exposure import (
    build_account_exposure_context,
    build_account_exposure_context_from_portfolio,
)
from alphabrief_execution.broker.legacy import (
    PaperBroker,
    PaperBrokerError,
    PaperBrokerResult,
)
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerTimeInForce,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)

__all__ = [
    "AccountSnapshot",
    "BrokerAdapter",
    "BrokerHealth",
    "BrokerOrderSide",
    "BrokerOrderStatus",
    "BrokerOrderType",
    "BrokerTimeInForce",
    "CancelResult",
    "Fill",
    "OrderState",
    "PaperBroker",
    "PaperBrokerError",
    "PaperBrokerResult",
    "Position",
    "SubmitRequest",
    "SubmitResult",
    "build_account_exposure_context",
    "build_account_exposure_context_from_portfolio",
]
