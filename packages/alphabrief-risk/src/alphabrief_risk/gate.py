"""RiskGate MVP for AlphaBrief paper trading."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alphabrief_core import OrderIntent, RiskDecision

from alphabrief_risk.kill_switch import KillSwitch


@dataclass(frozen=True)
class RiskLimitConfig:
    """Static risk limits used by the MVP RiskGate."""

    trading_enabled: bool = True
    live_trading_enabled: bool = False
    enabled_strategies: frozenset[str] = frozenset()
    symbol_allowlist: frozenset[str] = frozenset()
    max_order_quantity: Decimal | None = None
    max_order_value: Decimal | None = None
    require_data_quality_passed: bool = True
    require_human_review: bool = False

    def __post_init__(self) -> None:
        if self.max_order_quantity is not None and self.max_order_quantity <= 0:
            raise ValueError("max_order_quantity must be positive")
        if self.max_order_value is not None and self.max_order_value <= 0:
            raise ValueError("max_order_value must be positive")


@dataclass
class RiskGate:
    """Approve or reject OrderIntent objects before paper execution."""

    limits: RiskLimitConfig
    kill_switch: KillSwitch = field(default_factory=KillSwitch)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    decision_id_factory: Callable[[], str] = field(
        default=lambda: f"risk_{uuid4().hex}"
    )

    def evaluate(
        self,
        intent: OrderIntent,
        *,
        strategy_id: str | None = None,
        estimated_price: Decimal | None = None,
        estimated_quantity: Decimal | None = None,
        data_quality_passed: bool = True,
    ) -> RiskDecision:
        """Return a complete RiskDecision for an order intent."""

        failures: list[str] = []
        tags: list[str] = []

        if self.kill_switch.active:
            failures.append(self.kill_switch.reason)
            tags.append("kill_switch")

        if not self.limits.trading_enabled:
            failures.append("trading disabled")
            tags.append("trading_disabled")

        if self.limits.live_trading_enabled:
            failures.append("live trading is not allowed in MVP")
            tags.append("live_trading_locked")

        if self.limits.require_data_quality_passed and not data_quality_passed:
            failures.append("data quality check failed")
            tags.append("data_quality")

        if (
            self.limits.symbol_allowlist
            and intent.symbol not in self.limits.symbol_allowlist
        ):
            failures.append(f"symbol {intent.symbol} is not allowed")
            tags.append("symbol_not_allowed")

        if (
            strategy_id is not None
            and self.limits.enabled_strategies
            and strategy_id not in self.limits.enabled_strategies
        ):
            failures.append(f"strategy {strategy_id} is not enabled")
            tags.append("strategy_disabled")

        if intent.quantity is not None:
            self._check_quantity_limit(intent.quantity, failures, tags)
            self._check_order_value_limit(
                quantity=intent.quantity,
                estimated_price=estimated_price,
                failures=failures,
                tags=tags,
            )
        elif intent.target_position_pct is not None:
            self._check_target_pct_limits(
                estimated_quantity=estimated_quantity,
                estimated_price=estimated_price,
                failures=failures,
                tags=tags,
            )

        approved = not failures
        if approved:
            tags.append("approved")

        return RiskDecision(
            decision_id=self.decision_id_factory(),
            intent_id=intent.intent_id,
            approved=approved,
            reason="approved" if approved else "; ".join(failures),
            max_quantity=self.limits.max_order_quantity,
            risk_tags=tags,
            requires_human_review=self.limits.require_human_review,
            source_module="alphabrief_risk",
            created_at=self.clock(),
        )

    def _check_target_pct_limits(
        self,
        *,
        estimated_quantity: Decimal | None,
        estimated_price: Decimal | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        has_quantity_limit = self.limits.max_order_quantity is not None
        has_value_limit = self.limits.max_order_value is not None
        if not has_quantity_limit and not has_value_limit:
            return
        if estimated_quantity is None:
            failures.append(
                "estimated_quantity required for target_position_pct limits"
            )
            tags.append("missing_quantity_estimate")
            return
        self._check_quantity_limit(estimated_quantity, failures, tags)
        self._check_order_value_limit(
            quantity=estimated_quantity,
            estimated_price=estimated_price,
            failures=failures,
            tags=tags,
        )

    def _check_quantity_limit(
        self,
        quantity: Decimal,
        failures: list[str],
        tags: list[str],
    ) -> None:
        if (
            self.limits.max_order_quantity is not None
            and quantity > self.limits.max_order_quantity
        ):
            failures.append("order quantity exceeds max_order_quantity")
            tags.append("max_quantity")

    def _check_order_value_limit(
        self,
        *,
        quantity: Decimal,
        estimated_price: Decimal | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        if self.limits.max_order_value is None:
            return
        if estimated_price is None:
            failures.append("estimated_price is required for max_order_value")
            tags.append("missing_price")
            return
        if quantity * estimated_price > self.limits.max_order_value:
            failures.append("order value exceeds max_order_value")
            tags.append("max_order_value")
