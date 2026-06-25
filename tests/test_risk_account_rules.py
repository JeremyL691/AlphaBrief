"""R21.2 — stateless account-level risk rules.

Each of the 7 rules (per-symbol exposure, concentration, max leverage,
duplicate order, price deviation, market session, signal staleness) is
exercised through pass / reject / boundary / fail-closed / audit cases.
All rules are tighten-only (can only reject, tag, or reduce
``max_quantity``) and fail-closed (a missing required context input is a
rejection, never a silent skip).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_core import OrderIntent, PaperExecutionPolicy
from alphabrief_risk import AccountExposureContext, RiskGate, RiskLimitConfig

# Monday 2026-06-22 14:00 UTC == 10:00 America/New_York: a trading day
# inside the 09:30-16:00 session, so the market-open rule passes here.
SESSION_NOW = datetime(2026, 6, 22, 14, 0, tzinfo=UTC)
# Saturday 2026-06-21 14:00 UTC: a non-trading day for the market rule.
WEEKEND_NOW = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
# 2026-06-22 13:00 UTC == 09:00 NY: before the 09:30 session start.
PRE_OPEN_NOW = datetime(2026, 6, 22, 13, 0, tzinfo=UTC)

_SESSION_POLICY = PaperExecutionPolicy(
    mode="paper",
    provider="alpaca_paper",
    market="us_equity",
    symbols=("SPY", "QQQ"),
    order_types=("market", "limit"),
    timezone="America/New_York",
    trading_days=("mon", "tue", "wed", "thu", "fri"),
    session_start="09:30",
    session_end="16:00",
    max_order_notional=Decimal("1000"),
    max_total_exposure=Decimal("10000"),
    require_human_review=False,
    automated_execution=False,
)


def _intent(**overrides: object) -> OrderIntent:
    payload: dict[str, object] = {
        "intent_id": "intent_1",
        "source": "manual",
        "symbol": "SPY",
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1"),
        "rationale": "r21.2 test",
        "created_at": SESSION_NOW,
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def _ctx(
    *,
    total: Decimal = Decimal("0"),
    by_symbol: dict[str, Decimal] | None = None,
    equity: Decimal | None = Decimal("100000"),
    marks: dict[str, Decimal] | None = None,
    captured_at: datetime = SESSION_NOW,
) -> AccountExposureContext:
    return AccountExposureContext(
        current_total_exposure=total,
        exposure_by_symbol=by_symbol or {},
        cash=Decimal("100000"),
        account_id="paper_local",
        captured_at=captured_at,
        equity=equity,
        reference_mark_prices=marks or {},
    )


def _gate(
    limits: RiskLimitConfig,
    *,
    clock: datetime = SESSION_NOW,
) -> RiskGate:
    return RiskGate(
        limits=limits,
        clock=lambda: clock,
        decision_id_factory=lambda: "risk_1",
    )


def _base_limits(**overrides: object) -> RiskLimitConfig:
    base: dict[str, object] = {
        "trading_enabled": True,
        "symbol_allowlist": frozenset({"SPY", "QQQ"}),
        "max_order_value": Decimal("1000"),
    }
    base.update(overrides)
    return RiskLimitConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. per-symbol exposure cap (max_symbol_exposure) — with clamp
# ---------------------------------------------------------------------------


def test_max_symbol_exposure_passes_under_cap() -> None:
    gate = _gate(_base_limits(max_symbol_exposure=Decimal("500")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(by_symbol={"SPY": Decimal("0")}),
    )
    assert decision.approved is True
    assert "max_symbol_exposure" not in decision.risk_tags


def test_max_symbol_exposure_rejects_over_cap() -> None:
    gate = _gate(_base_limits(max_symbol_exposure=Decimal("150")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(by_symbol={"SPY": Decimal("100")}),
    )
    # 100 existing + 100 new = 200 > 150.
    assert decision.approved is False
    assert "max_symbol_exposure" in decision.risk_tags


def test_max_symbol_exposure_boundary_at_cap_is_approved() -> None:
    gate = _gate(_base_limits(max_symbol_exposure=Decimal("150")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(by_symbol={"SPY": Decimal("50")}),
    )
    # 50 + 100 = 150 == cap -> approved.
    assert decision.approved is True


def test_max_symbol_exposure_clamps_max_quantity_to_headroom() -> None:
    gate = _gate(
        _base_limits(
            max_order_quantity=Decimal("10"), max_symbol_exposure=Decimal("150")
        )
    )
    decision = gate.evaluate(
        _intent(quantity=Decimal("10")),
        estimated_price=Decimal("100"),
        account_context=_ctx(by_symbol={"SPY": Decimal("100")}),
    )
    # Over cap -> rejected; headroom = 50 -> clamp = 0.5 < max_order_quantity 10.
    assert decision.approved is False
    assert decision.max_quantity == Decimal("0.5")


def test_max_symbol_exposure_fails_closed_without_account_context() -> None:
    gate = _gate(_base_limits(max_symbol_exposure=Decimal("150")))
    decision = gate.evaluate(_intent(), estimated_price=Decimal("100"))
    assert decision.approved is False
    assert "account_context_required" in decision.risk_tags


# ---------------------------------------------------------------------------
# 2. concentration (max_concentration_pct)
# ---------------------------------------------------------------------------


def test_max_concentration_passes_under_pct() -> None:
    gate = _gate(_base_limits(max_concentration_pct=Decimal("0.9")))
    decision = gate.evaluate(
        _intent(symbol="SPY"),
        estimated_price=Decimal("100"),
        account_context=_ctx(
            total=Decimal("100"), by_symbol={"SPY": Decimal("40"), "QQQ": Decimal("60")}
        ),
    )
    # After: SPY 140, total 200 -> 0.7 <= 0.9 -> approved.
    assert decision.approved is True
    assert "max_concentration" not in decision.risk_tags


def test_max_concentration_rejects_when_one_symbol_dominates() -> None:
    gate = _gate(_base_limits(max_concentration_pct=Decimal("0.5")))
    decision = gate.evaluate(
        _intent(symbol="SPY"),
        estimated_price=Decimal("100"),
        account_context=_ctx(total=Decimal("50"), by_symbol={"QQQ": Decimal("50")}),
    )
    # After: SPY 100, total 150 -> 0.667 > 0.5 -> rejected.
    assert decision.approved is False
    assert "max_concentration" in decision.risk_tags


def test_max_concentration_boundary_at_pct_is_approved() -> None:
    gate = _gate(_base_limits(max_concentration_pct=Decimal("0.5")))
    decision = gate.evaluate(
        _intent(symbol="SPY"),
        estimated_price=Decimal("100"),
        account_context=_ctx(total=Decimal("100"), by_symbol={"QQQ": Decimal("100")}),
    )
    # After: SPY 100, total 200 -> exactly 0.5 -> approved (strict >).
    assert decision.approved is True
    assert "max_concentration" not in decision.risk_tags


def test_max_concentration_fails_closed_without_account_context() -> None:
    gate = _gate(_base_limits(max_concentration_pct=Decimal("0.5")))
    decision = gate.evaluate(_intent(), estimated_price=Decimal("100"))
    assert decision.approved is False
    assert "account_context_required" in decision.risk_tags


# ---------------------------------------------------------------------------
# 3. max leverage (max_leverage) — fail-closed missing_equity
# ---------------------------------------------------------------------------


def test_max_leverage_passes_under_cap() -> None:
    gate = _gate(_base_limits(max_leverage=Decimal("1.0")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(total=Decimal("0"), equity=Decimal("100000")),
    )
    assert decision.approved is True


def test_max_leverage_rejects_over_cap() -> None:
    gate = _gate(_base_limits(max_leverage=Decimal("1.0")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(total=Decimal("100000"), equity=Decimal("100000")),
    )
    # 100000 + 100 = 100100 > 1.0 * 100000 -> rejected.
    assert decision.approved is False
    assert "max_leverage" in decision.risk_tags


def test_max_leverage_boundary_at_cap_is_approved() -> None:
    gate = _gate(_base_limits(max_leverage=Decimal("1.0")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(total=Decimal("99900"), equity=Decimal("100000")),
    )
    # 99900 + 100 = 100000 == 1.0 * 100000 -> approved (strict >).
    assert decision.approved is True


def test_max_leverage_fails_closed_when_equity_missing() -> None:
    gate = _gate(_base_limits(max_leverage=Decimal("1.0")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(equity=None),
    )
    assert decision.approved is False
    assert "missing_equity" in decision.risk_tags


# ---------------------------------------------------------------------------
# 4. duplicate order (duplicate_order_window_seconds) — in-memory
# ---------------------------------------------------------------------------


def test_duplicate_order_first_is_approved() -> None:
    gate = _gate(
        _base_limits(duplicate_order_window_seconds=30, duplicate_order_max_count=1)
    )
    decision = gate.evaluate(_intent(), estimated_price=Decimal("100"))
    assert decision.approved is True


def test_duplicate_order_second_identical_is_rejected() -> None:
    gate = _gate(
        _base_limits(duplicate_order_window_seconds=30, duplicate_order_max_count=1)
    )
    gate.evaluate(_intent(), estimated_price=Decimal("100"))
    decision = gate.evaluate(_intent(), estimated_price=Decimal("100"))
    assert decision.approved is False
    assert "duplicate_order" in decision.risk_tags


def test_duplicate_order_passes_after_window_expires() -> None:
    gate = _gate(
        _base_limits(duplicate_order_window_seconds=30, duplicate_order_max_count=1),
        clock=SESSION_NOW,
    )
    gate.evaluate(_intent(created_at=SESSION_NOW), estimated_price=Decimal("100"))
    # 60 seconds later — outside the 30s window.
    later = datetime(2026, 6, 22, 14, 1, tzinfo=UTC)
    gate.clock = lambda: later
    decision = gate.evaluate(_intent(created_at=later), estimated_price=Decimal("100"))
    assert decision.approved is True


def test_duplicate_order_boundary_at_max_count() -> None:
    gate = _gate(
        _base_limits(duplicate_order_window_seconds=30, duplicate_order_max_count=2)
    )
    first = gate.evaluate(_intent(), estimated_price=Decimal("100"))
    second = gate.evaluate(_intent(), estimated_price=Decimal("100"))
    third = gate.evaluate(_intent(), estimated_price=Decimal("100"))
    assert first.approved is True
    assert second.approved is True  # 2 <= max_count 2
    assert third.approved is False  # 3 > max_count 2
    assert "duplicate_order" in third.risk_tags


# ---------------------------------------------------------------------------
# 5. price deviation (max_price_deviation_pct) — fail-closed missing_mark_price
# ---------------------------------------------------------------------------


def test_price_deviation_passes_within_band() -> None:
    gate = _gate(_base_limits(max_price_deviation_pct=Decimal("0.05")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("102"),
        account_context=_ctx(marks={"SPY": Decimal("100")}),
    )
    # |102-100|/100 = 0.02 <= 0.05 -> approved.
    assert decision.approved is True


def test_price_deviation_rejects_beyond_band() -> None:
    gate = _gate(_base_limits(max_price_deviation_pct=Decimal("0.05")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("110"),
        account_context=_ctx(marks={"SPY": Decimal("100")}),
    )
    # 0.10 > 0.05 -> rejected.
    assert decision.approved is False
    assert "price_deviation" in decision.risk_tags


def test_price_deviation_boundary_at_band_is_approved() -> None:
    gate = _gate(_base_limits(max_price_deviation_pct=Decimal("0.05")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("105"),
        account_context=_ctx(marks={"SPY": Decimal("100")}),
    )
    # exactly 0.05 -> approved (strict >).
    assert decision.approved is True


def test_price_deviation_fails_closed_without_mark() -> None:
    gate = _gate(_base_limits(max_price_deviation_pct=Decimal("0.05")))
    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        account_context=_ctx(marks={}),  # no mark for SPY
    )
    assert decision.approved is False
    assert "missing_mark_price" in decision.risk_tags


# ---------------------------------------------------------------------------
# 6. market session (require_market_open) — ponytail: no holiday calendar
# ---------------------------------------------------------------------------


def test_market_open_passes_mid_session() -> None:
    gate = _gate(
        _base_limits(require_market_open=True, session_policy=_SESSION_POLICY),
        clock=SESSION_NOW,
    )
    decision = gate.evaluate(
        _intent(created_at=SESSION_NOW), estimated_price=Decimal("100")
    )
    assert decision.approved is True


def test_market_open_rejects_on_weekend() -> None:
    gate = _gate(
        _base_limits(require_market_open=True, session_policy=_SESSION_POLICY),
        clock=WEEKEND_NOW,
    )
    decision = gate.evaluate(
        _intent(created_at=WEEKEND_NOW), estimated_price=Decimal("100")
    )
    assert decision.approved is False
    assert "market_closed" in decision.risk_tags


def test_market_open_rejects_before_session_start() -> None:
    gate = _gate(
        _base_limits(require_market_open=True, session_policy=_SESSION_POLICY),
        clock=PRE_OPEN_NOW,
    )
    decision = gate.evaluate(
        _intent(created_at=PRE_OPEN_NOW), estimated_price=Decimal("100")
    )
    assert decision.approved is False
    assert "market_closed" in decision.risk_tags


def test_market_open_fails_closed_without_session_policy() -> None:
    gate = _gate(
        _base_limits(require_market_open=True, session_policy=None),
        clock=SESSION_NOW,
    )
    decision = gate.evaluate(
        _intent(created_at=SESSION_NOW), estimated_price=Decimal("100")
    )
    assert decision.approved is False
    assert "market_closed" in decision.risk_tags


# ---------------------------------------------------------------------------
# 7. signal staleness (max_signal_age_seconds)
# ---------------------------------------------------------------------------


def test_signal_age_passes_when_fresh() -> None:
    gate = _gate(_base_limits(max_signal_age_seconds=300), clock=SESSION_NOW)
    decision = gate.evaluate(
        _intent(created_at=SESSION_NOW), estimated_price=Decimal("100")
    )
    assert decision.approved is True


def test_signal_age_rejects_when_stale() -> None:
    gate = _gate(_base_limits(max_signal_age_seconds=300), clock=SESSION_NOW)
    old = datetime(2026, 6, 22, 13, 0, tzinfo=UTC)  # 1h before SESSION_NOW
    decision = gate.evaluate(_intent(created_at=old), estimated_price=Decimal("100"))
    assert decision.approved is False
    assert "stale_signal" in decision.risk_tags


def test_signal_age_boundary_at_max_age_is_approved() -> None:
    gate = _gate(_base_limits(max_signal_age_seconds=300), clock=SESSION_NOW)
    # exactly 300s old -> approved (strict >).
    edge = datetime(2026, 6, 22, 13, 55, tzinfo=UTC)  # 300s before 14:00
    decision = gate.evaluate(_intent(created_at=edge), estimated_price=Decimal("100"))
    assert decision.approved is True


# ---------------------------------------------------------------------------
# Tighten-only invariant: no rule can re-approve a rejected intent
# ---------------------------------------------------------------------------


def test_account_rules_never_reapprove_a_rejected_intent() -> None:
    # A symbol outside the allowlist is rejected by the base check. None
    # of the R21.2 rules may turn it back into an approval.
    gate = _gate(
        _base_limits(
            max_symbol_exposure=Decimal("10000"),
            max_concentration_pct=Decimal("1.0"),
            max_leverage=Decimal("10"),
            max_price_deviation_pct=Decimal("1.0"),
            max_signal_age_seconds=300,
            require_market_open=True,
            session_policy=_SESSION_POLICY,
            duplicate_order_window_seconds=30,
        ),
        clock=SESSION_NOW,
    )
    decision = gate.evaluate(
        _intent(symbol="BTC-USD"),
        estimated_price=Decimal("100"),
        account_context=_ctx(
            total=Decimal("0"),
            by_symbol={"SPY": Decimal("0")},
            marks={"SPY": Decimal("100")},
        ),
    )
    assert decision.approved is False
    assert "symbol_not_allowed" in decision.risk_tags
