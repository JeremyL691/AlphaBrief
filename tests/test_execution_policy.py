from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent, load_paper_execution_policy, load_settings
from alphabrief_risk import AccountExposureContext
from pydantic import ValidationError

POLICY_NOW = datetime(2026, 6, 22, 14, 0, tzinfo=UTC)
# A Monday 10:00 America/New_York moment — inside the policy trading
# session, so the R21.2 ``require_market_open`` check does not reject.
# Kept in sync with ``POLICY_NOW`` so signal-staleness also passes.


def _empty_account_context(
    symbol: str = "SPY",
    mark: Decimal = Decimal("100"),
) -> "AccountExposureContext":
    """An AccountExposureContext with zero exposure.

    The Phase 19 default gate enforces the $300 total-exposure cap at
    runtime, so a buy without an account_context fails closed
    (``account_context_required``). R21.2 adds leverage (needs ``equity``)
    and price-deviation (needs ``reference_mark_prices``) checks, both
    fail-closed. R21.3 adds daily-loss (needs ``day_start_equity``) and
    drawdown (needs ``equity_high_water_mark``), also fail-closed. These
    tests exercise the symbol / order-value / human-review boundaries,
    not those checks, so the helper supplies a zero-exposure context
    with equity, mark, and HWM/day-start set to the current equity so
    only the boundaries under test surface. ``symbol`` / ``mark`` let
    each caller match the mark to its order price.
    """
    return AccountExposureContext(
        current_total_exposure=Decimal("0"),
        exposure_by_symbol={},
        cash=Decimal("100000"),
        account_id="paper_local",
        captured_at=POLICY_NOW,
        equity=Decimal("100000"),
        reference_mark_prices={symbol: mark},
        equity_high_water_mark=Decimal("100000"),
        day_start_equity=Decimal("100000"),
    )


def _configured_policy_text() -> str:
    return Path("config/paper_execution_policy.yaml").read_text(encoding="utf-8")


def test_checked_in_execution_policy_is_paper_only_and_locked() -> None:
    policy = load_paper_execution_policy("config/paper_execution_policy.yaml")

    assert policy.mode == "paper"
    assert policy.provider == "alpaca_paper"
    assert policy.symbols == (
        "SPY",
        "QQQ",
        "IVV",
        "VOO",
        "AGG",
        "BND",
        "GLD",
        "SLV",
    )
    assert policy.order_types == ("market", "limit")
    assert policy.max_order_notional == Decimal("100")
    assert policy.max_total_exposure == Decimal("300")
    assert policy.require_human_review is True
    assert policy.automated_execution is False


@pytest.mark.parametrize(
    ("replacement", "error"),
    [
        ("mode: live", "Input should be 'paper'"),
        ("order_types: [market, stop]", "market' or 'limit"),
        ("max_order_notional: 100.0", "must not be floats"),
        ('session_end: "09:30"', "session_start must be earlier"),
    ],
)
def test_execution_policy_rejects_invalid_operating_boundaries(
    tmp_path: Path,
    replacement: str,
    error: str,
) -> None:
    policy_path = tmp_path / "policy.yaml"
    baseline = _configured_policy_text()
    if replacement.startswith("mode:"):
        text = baseline.replace("mode: paper", replacement)
    elif replacement.startswith("order_types:"):
        text = baseline.replace("order_types: [market, limit]", replacement)
    elif replacement.startswith("max_order_notional:"):
        text = baseline.replace('max_order_notional: "100"', replacement)
    else:
        text = baseline.replace('session_end: "16:00"', replacement)
    policy_path.write_text(text, encoding="utf-8")

    with pytest.raises((ValidationError, ValueError), match=error):
        load_paper_execution_policy(policy_path)


def test_execution_policy_rejects_unknown_fields(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(_configured_policy_text() + "live_endpoint: nope\n")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_paper_execution_policy(policy_path)


def test_execution_policy_accepts_reviewed_oanda_paper_boundary(
    tmp_path: Path,
) -> None:
    policy_path = tmp_path / "oanda_policy.yaml"
    policy_path.write_text(
        _configured_policy_text()
        .replace("provider: alpaca_paper", "provider: oanda_paper")
        .replace("market: us_equity", "market: fx")
        .replace(
            "symbols: [SPY, QQQ, IVV, VOO, AGG, BND, GLD, SLV]",
            "symbols: [EUR_USD, GBP_USD]",
        ),
        encoding="utf-8",
    )

    policy = load_paper_execution_policy(policy_path)

    assert policy.provider == "oanda_paper"
    assert policy.market == "fx"
    assert policy.symbols == ("EUR_USD", "GBP_USD")


def test_settings_accepts_execution_policy_file_override() -> None:
    settings = load_settings({"ALPHABRIEF_EXECUTION_POLICY_FILE": "custom/policy.yaml"})

    assert settings.execution_policy_file == Path("custom/policy.yaml")


def test_default_api_risk_gate_enforces_policy_subset() -> None:
    from alphabrief_api.routes.risk import _get_risk_gate, _reset_risk_gate

    _reset_risk_gate()
    gate = _get_risk_gate()
    gate.clock = lambda: POLICY_NOW  # session-in, fresh signal
    allowed = OrderIntent(
        intent_id="policy-spy",
        source="manual",
        symbol="SPY",
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        rationale="policy boundary test",
        created_at=POLICY_NOW,
    )
    blocked_symbol = allowed.model_copy(update={"symbol": "BTC-USD"})
    blocked_value = allowed.model_copy(update={"quantity": Decimal("2")})

    ctx = _empty_account_context()
    allowed_decision = gate.evaluate(
        allowed, estimated_price=Decimal("100"), account_context=ctx
    )
    blocked_symbol_decision = gate.evaluate(
        blocked_symbol, estimated_price=Decimal("100"), account_context=ctx
    )
    blocked_value_decision = gate.evaluate(
        blocked_value, estimated_price=Decimal("100"), account_context=ctx
    )
    assert allowed_decision.approved is True
    assert allowed_decision.requires_human_review is True
    assert blocked_symbol_decision.approved is False
    assert blocked_value_decision.approved is False


@pytest.mark.parametrize("symbol", ["IVV", "VOO", "AGG", "BND", "GLD", "SLV"])
def test_risk_gate_accepts_extended_etf_symbols(symbol: str) -> None:
    from alphabrief_api.routes.risk import _get_risk_gate, _reset_risk_gate

    _reset_risk_gate()
    gate = _get_risk_gate()
    gate.clock = lambda: POLICY_NOW  # session-in, fresh signal
    intent = OrderIntent(
        intent_id=f"policy-{symbol.lower()}",
        source="manual",
        symbol=symbol,
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        rationale="policy boundary test",
        created_at=POLICY_NOW,
    )

    decision = gate.evaluate(
        intent,
        estimated_price=Decimal("50"),
        account_context=_empty_account_context(symbol=symbol, mark=Decimal("50")),
    )

    assert decision.approved is True


@pytest.mark.parametrize("symbol", ["AAPL", "TSLA", "BTC-USD", "ETH-USD"])
def test_risk_gate_rejects_unapproved_symbols(symbol: str) -> None:
    from alphabrief_api.routes.risk import _get_risk_gate, _reset_risk_gate

    _reset_risk_gate()
    gate = _get_risk_gate()
    intent = OrderIntent(
        intent_id=f"policy-{symbol.lower()}",
        source="manual",
        symbol=symbol,
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        rationale="policy boundary test",
        created_at=datetime(2026, 6, 20, tzinfo=UTC),
    )

    decision = gate.evaluate(intent, estimated_price=Decimal("100"))

    assert decision.approved is False
    assert "symbol_not_allowed" in decision.risk_tags


def test_relative_policy_path_resolves_against_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative path still resolves even when the caller is in a different cwd."""

    policy = load_paper_execution_policy("config/paper_execution_policy.yaml")
    monkeypatch.chdir(tmp_path)

    again = load_paper_execution_policy("config/paper_execution_policy.yaml")

    assert policy.provider == again.provider
    assert policy.symbols == again.symbols
    assert policy.market == again.market
