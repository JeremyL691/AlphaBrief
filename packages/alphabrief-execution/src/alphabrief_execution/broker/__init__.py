"""Broker adapter package.

Contains the broker-neutral :mod:`alphabrief_execution.broker.port`
plus the concrete practice-only OANDA adapter.

Note: BrokerAdapter instances may not be safe to share across
uncoordinated coroutines when state lives on the instance. Concrete
adapters should document their concurrency guarantees.
"""

from alphabrief_execution.broker.exposure import (
    build_account_exposure_context,
)
from alphabrief_execution.broker.oanda import OandaPaperAdapter
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
    "OandaPaperAdapter",
    "OrderState",
    "Position",
    "SubmitRequest",
    "SubmitResult",
    "build_account_exposure_context",
]
