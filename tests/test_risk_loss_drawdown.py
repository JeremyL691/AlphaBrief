"""R21.3 — daily-loss + drawdown risk rules.

Each rule is exercised through pass / reject / boundary / fail-closed
(failure to provide required context) / audit cases. Both rules are
tighten-only (can only reject, tag, or reduce ``max_quantity``) and
fail-closed (a missing required input is a rejection, never a silent
skip).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_core import OrderIntent
from alphabrief_risk import AccountExposureContext, RiskGate, RiskLimitConfig

NOW = datetime(2026, 6, 22, 14, 0, tzinfo=UTC)

# Sentinel distinguishes "omitted" (default to equity) from "explicit
# None" (exercise the fail-closed path).
_SENTINEL: object = object()


def _intent(**overrides: object) -> OrderIntent:
    payload: dict[str, object] = {
        "intent_id": "intent_1",
        "source": "manual",
        "symbol": "SPY",
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1"),
        "rationale": "r21.3 test",
        "created_at": NOW,
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def _gate(limits: RiskLimitConfig) -> RiskGate:
    return RiskGate(
        limits=limits,
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )


def _base_limits(**overrides: object) -> RiskLimitConfig:
    base: dict[str, object] = {
        "trading_enabled": True,
        "symbol_allowlist": frozenset({"SPY"}),
        "max_order_value": Decimal("100000"),
    }
    base.update(overrides)
    return RiskLimitConfig(**base)  # type: ignore[arg-type]


def _ctx(
    *,
    equity: Decimal | None = Decimal("100000"),
    hwm: Decimal | None | object = _SENTINEL,
    day_start: Decimal | None | object = _SENTINEL,
) -> AccountExposureContext:
    """Build a context with the stateful-rule inputs.

    ``hwm`` / ``day_start`` default to the current ``equity`` (a
    zero-drawdown / zero-day-loss baseline) when omitted. Pass an
    explicit ``None`` to exercise the fail-closed path.
    """
    payload: dict[str, object] = {
        "current_total_exposure": Decimal("0"),
        "exposure_by_symbol": {},
        "cash": Decimal("100000"),
        "account_id": "paper_local",
        "captured_at": NOW,
        "equity": equity,
        "equity_high_water_mark": equity if hwm is _SENTINEL else hwm,
        "day_start_equity": equity if day_start is _SENTINEL else day_start,
    }
    return AccountExposureContext.model_validate(payload)


# ---------------------------------------------------------------------------
# 1. daily-loss cap (max_daily_loss_pct)
# ---------------------------------------------------------------------------


def test_max_daily_loss_passes_under_cap() -> None:
    gate = _gate(_base_limits(max_daily_loss_pct=Decimal("0.05")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("96000"), day_start=Decimal("100000")),
    )
    # 4% loss < 5% cap -> approved.
    assert decision.approved is True
    assert "max_daily_loss" not in decision.risk_tags


def test_max_daily_loss_rejects_over_cap() -> None:
    gate = _gate(_base_limits(max_daily_loss_pct=Decimal("0.05")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("94000"), day_start=Decimal("100000")),
    )
    # 6% loss > 5% cap -> rejected.
    assert decision.approved is False
    assert "max_daily_loss" in decision.risk_tags


def test_max_daily_loss_boundary_at_cap_is_approved() -> None:
    gate = _gate(_base_limits(max_daily_loss_pct=Decimal("0.05")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("95000"), day_start=Decimal("100000")),
    )
    # exactly 5% loss -> approved (strict >).
    assert decision.approved is True


def test_max_daily_loss_fails_closed_without_day_start_equity() -> None:
    gate = _gate(_base_limits(max_daily_loss_pct=Decimal("0.05")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("100000"), day_start=None),
    )
    assert decision.approved is False
    assert "missing_day_start_equity" in decision.risk_tags


def test_max_daily_loss_fails_closed_without_current_equity() -> None:
    gate = _gate(_base_limits(max_daily_loss_pct=Decimal("0.05")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=None, day_start=Decimal("100000")),
    )
    assert decision.approved is False
    assert "missing_equity" in decision.risk_tags


def test_max_daily_loss_does_not_block_sells() -> None:
    # A sell that realizes a loss is itself the protective action; the
    # check applies to buys only.
    gate = _gate(_base_limits(max_daily_loss_pct=Decimal("0.01")))
    decision = gate.evaluate(
        _intent(side="sell"),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("50000"), day_start=Decimal("100000")),
    )
    assert "max_daily_loss" not in decision.risk_tags


# ---------------------------------------------------------------------------
# 2. drawdown floor (max_drawdown_floor_pct)
# ---------------------------------------------------------------------------


def test_max_drawdown_floor_passes_under_cap() -> None:
    gate = _gate(_base_limits(max_drawdown_floor_pct=Decimal("0.10")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("95000"), hwm=Decimal("100000")),
    )
    # 5% drawdown < 10% cap -> approved.
    assert decision.approved is True
    assert "max_drawdown_floor" not in decision.risk_tags


def test_max_drawdown_floor_rejects_over_cap() -> None:
    gate = _gate(_base_limits(max_drawdown_floor_pct=Decimal("0.10")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("85000"), hwm=Decimal("100000")),
    )
    # 15% drawdown > 10% cap -> rejected.
    assert decision.approved is False
    assert "max_drawdown_floor" in decision.risk_tags


def test_max_drawdown_floor_boundary_at_cap_is_approved() -> None:
    gate = _gate(_base_limits(max_drawdown_floor_pct=Decimal("0.10")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("90000"), hwm=Decimal("100000")),
    )
    # exactly 10% drawdown -> approved (strict >).
    assert decision.approved is True


def test_max_drawdown_floor_fails_closed_without_hwm() -> None:
    gate = _gate(_base_limits(max_drawdown_floor_pct=Decimal("0.10")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("95000"), hwm=None),
    )
    assert decision.approved is False
    assert "missing_equity_hwm" in decision.risk_tags


def test_max_drawdown_floor_fails_closed_without_current_equity() -> None:
    gate = _gate(_base_limits(max_drawdown_floor_pct=Decimal("0.10")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=None, hwm=Decimal("100000")),
    )
    assert decision.approved is False
    assert "missing_equity" in decision.risk_tags


def test_max_drawdown_floor_does_not_block_sells() -> None:
    gate = _gate(_base_limits(max_drawdown_floor_pct=Decimal("0.01")))
    decision = gate.evaluate(
        _intent(side="sell"),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=Decimal("50000"), hwm=Decimal("100000")),
    )
    assert "max_drawdown_floor" not in decision.risk_tags
