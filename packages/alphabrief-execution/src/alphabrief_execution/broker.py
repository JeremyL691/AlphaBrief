"""Paper broker for AlphaBrief MVP execution."""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from alphabrief_core import Order, OrderIntent, RiskDecision

from alphabrief_execution.audit import ExecutionAuditLog
from alphabrief_execution.fills import BPS_DENOMINATOR, Fill, FillSimulator
from alphabrief_execution.portfolio import PortfolioState
from alphabrief_execution.router import OrderRouter, OrderRouterError

if TYPE_CHECKING:
    from alphabrief_risk import RiskContextDecision


class PaperBrokerError(ValueError):
    """Raised when a paper broker operation cannot complete."""


@dataclass(frozen=True)
class PaperBrokerResult:
    order: Order
    fill: Fill
    portfolio: PortfolioState


class PaperBroker:
    """Simulate paper orders, fills, portfolio updates, and audit records."""

    def __init__(
        self,
        *,
        portfolio: PortfolioState,
        router: OrderRouter | None = None,
        fill_simulator: FillSimulator | None = None,
        audit_log: ExecutionAuditLog | None = None,
    ) -> None:
        self.portfolio = portfolio
        self.router = router or OrderRouter()
        self.fill_simulator = fill_simulator or FillSimulator()
        self.audit_log = audit_log or ExecutionAuditLog()

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision | None,
        *,
        reference_price: Decimal,
        risk_context: "RiskContextDecision | None" = None,
    ) -> PaperBrokerResult:
        decision_id = decision.decision_id if decision is not None else None
        rcx_id = risk_context.decision_id if risk_context is not None else None
        rcx_tags = (
            tuple(risk_context.risk_tags) if risk_context is not None else ()
        )
        rcx_mult = (
            risk_context.suggested_max_position_multiplier
            if risk_context is not None
            else None
        )

        self.audit_log.append(
            event_type="risk_decision_recorded",
            intent_id=intent.intent_id,
            risk_decision_id=decision_id,
            message="risk decision received",
            risk_context_decision_id=rcx_id,
            risk_context_tags=rcx_tags,
            risk_context_multiplier=rcx_mult,
        )

        if decision is not None and decision.requires_human_review:
            self.audit_log.append(
                event_type="order_rejected",
                intent_id=intent.intent_id,
                risk_decision_id=decision_id,
                message=(
                    "auto-execution blocked: risk decision requires "
                    "human review"
                ),
                risk_context_decision_id=rcx_id,
                risk_context_tags=rcx_tags,
                risk_context_multiplier=rcx_mult,
            )
            raise PaperBrokerError(
                "risk decision requires human review; "
                "auto-execution blocked by PaperBroker"
            )

        try:
            quantity = self._resolve_quantity(intent, reference_price)
            order = self.router.route(intent, decision, quantity=quantity)
        except (OrderRouterError, ValueError) as exc:
            self.audit_log.append(
                event_type="order_rejected",
                intent_id=intent.intent_id,
                risk_decision_id=decision_id,
                message=str(exc),
                risk_context_decision_id=rcx_id,
                risk_context_tags=rcx_tags,
                risk_context_multiplier=rcx_mult,
            )
            raise PaperBrokerError(str(exc)) from exc

        self.audit_log.append(
            event_type="order_created",
            intent_id=intent.intent_id,
            risk_decision_id=decision_id,
            order_id=order.order_id,
            message="paper order created",
            risk_context_decision_id=rcx_id,
            risk_context_tags=rcx_tags,
            risk_context_multiplier=rcx_mult,
        )

        try:
            fill = self.fill_simulator.fill(order, reference_price=reference_price)
            new_portfolio = self.portfolio.apply_fill(fill)
        except ValueError as exc:
            self.audit_log.append(
                event_type="order_rejected",
                intent_id=intent.intent_id,
                risk_decision_id=decision_id,
                order_id=order.order_id,
                message=str(exc),
                risk_context_decision_id=rcx_id,
                risk_context_tags=rcx_tags,
                risk_context_multiplier=rcx_mult,
            )
            raise PaperBrokerError(str(exc)) from exc

        self.portfolio = new_portfolio
        self.audit_log.append(
            event_type="fill_created",
            intent_id=intent.intent_id,
            risk_decision_id=decision_id,
            order_id=order.order_id,
            fill_id=fill.fill_id,
            message="paper fill created",
            risk_context_decision_id=rcx_id,
            risk_context_tags=rcx_tags,
            risk_context_multiplier=rcx_mult,
        )
        self.audit_log.append(
            event_type="portfolio_updated",
            intent_id=intent.intent_id,
            risk_decision_id=decision_id,
            order_id=order.order_id,
            fill_id=fill.fill_id,
            message="paper portfolio updated",
            risk_context_decision_id=rcx_id,
            risk_context_tags=rcx_tags,
            risk_context_multiplier=rcx_mult,
        )
        return PaperBrokerResult(order=order, fill=fill, portfolio=self.portfolio)

    def _resolve_quantity(
        self,
        intent: OrderIntent,
        reference_price: Decimal,
    ) -> Decimal:
        if reference_price <= 0:
            raise ValueError("reference_price must be positive")
        if intent.quantity is not None:
            return intent.quantity
        if intent.target_position_pct is None:
            raise ValueError("OrderIntent sizing is missing")
        if intent.side == "buy":
            slippage_rate = self.fill_simulator.slippage_bps / BPS_DENOMINATOR
            fee_rate = self.fill_simulator.fee_bps / BPS_DENOMINATOR
            execution_price = reference_price * (Decimal("1") + slippage_rate)
            target_value = self.portfolio.cash * intent.target_position_pct
            return target_value / (execution_price * (Decimal("1") + fee_rate))
        if intent.target_position_pct == 0:
            return self.portfolio.position_quantity(intent.symbol)
        raise ValueError("sell target_position_pct is only supported for flat targets")
