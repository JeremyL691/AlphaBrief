"""Deterministic opportunity scan (PROJECT_GUIDE 5.1).

Forex is open around the clock Monday 21:00 UTC to Friday 21:00 UTC. The
guide requires an opportunity check every 1-5 minutes during that window,
and full committee rounds only when a strategy signal actually justifies
one. The scan is therefore pure and cheap: no model call, no order, no
database write. It returns a stable escalate/no-trigger verdict with a
reason code that later lands in the cycle record.

Budget arithmetic matters here: one committee round costs roughly 39
model calls, and the free channel is capped at 1000 calls per UTC day.
The scan cannot decide the budget itself, but it must honour the guard it
is given and refuse to escalate when the daily round cap or the minimum
spacing between rounds is exhausted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphabrief_trader.opportunity import (
    OpportunityLimits,
    OpportunityScan,
    SymbolOpportunity,
    scan_opportunities,
)
from alphabrief_trader.schemas import MarketSnapshot

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _snapshot(
    symbol: str = "EUR_USD",
    *,
    signals: dict[str, dict[str, object]] | None = None,
    bid: str = "1.0812",
    ask: str = "1.0813",
    position_units: str = "0",
) -> MarketSnapshot:
    """A complete, fresh snapshot with one optional strategy signal."""

    from alphabrief_execution.broker.oanda.input_facts import BrokerInputFacts

    facts = BrokerInputFacts(
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        spread=Decimal(ask) - Decimal(bid),
        quote_to_home=Decimal("1"),
        margin_available=Decimal("100000"),
        margin_used=Decimal("0"),
        position_units=Decimal(position_units),
        position_unrealized_pnl=Decimal("0"),
        daily_open_count=0,
        quote_captured_at=NOW,
        positions_captured_at=NOW,
        reconciliation_captured_at=NOW,
    )
    return MarketSnapshot(
        symbol=symbol,
        reference_price=Decimal("1.08125"),
        atr=Decimal("0.0004"),
        broker_evidence=facts,
        strategy_signals=dict(signals or {}),
        captured_at=NOW,
    )


def _signal(direction: str, confidence: str = "0.80") -> dict[str, object]:
    return {
        "signal_id": "momentum:2026-10-20T11:00:00+00:00",
        "direction": direction,
        "confidence": confidence,
        "horizon": "24h",
        "rationale": "test fixture signal",
        "timestamp": "2026-10-20T11:00:00+00:00",
    }


LIMITS = OpportunityLimits()


def test_no_signal_does_not_escalate() -> None:
    """An empty signal set is the normal case and must not spend a round."""
    scan = scan_opportunities(
        [ _snapshot() ], session_open=True, limits=LIMITS, now=NOW
    )

    assert scan.escalate is False
    assert scan.reason == "no_signal"
    assert scan.symbols[0].reason == "no_signal"


def test_flat_signal_does_not_escalate() -> None:
    """A flat strategy opinion is not a trading opportunity."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("flat")})],
        session_open=True,
        limits=LIMITS,
        now=NOW,
    )

    assert scan.escalate is False
    assert scan.reason == "flat_signal"


def test_low_confidence_signal_does_not_escalate() -> None:
    """Below the escalation floor the committee would only see noise."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("long", "0.55")})],
        session_open=True,
        limits=LIMITS,
        now=NOW,
    )

    assert scan.escalate is False
    assert scan.symbols[0].reason == "confidence_below_floor"


def test_confident_directional_signal_escalates() -> None:
    """A confident, unheld, tradeable signal is exactly what a round is for."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("long", "0.80")})],
        session_open=True,
        limits=LIMITS,
        now=NOW,
    )

    assert scan.escalate is True
    assert scan.reason == "signal_above_threshold"
    assert scan.symbols[0].escalate is True
    assert scan.symbols[0].symbol == "EUR_USD"


def test_signal_matching_current_position_does_not_escalate() -> None:
    """Already positioned in that direction: the manager would only hold."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("long")}, position_units="1000")],
        session_open=True,
        limits=LIMITS,
        now=NOW,
    )

    assert scan.escalate is False
    assert scan.symbols[0].reason == "already_positioned_same_direction"


def test_signal_against_current_position_escalates_for_the_close() -> None:
    """An opposing signal is a real decision: hold, or reduce the position."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("short")}, position_units="1000")],
        session_open=True,
        limits=LIMITS,
        now=NOW,
    )

    assert scan.escalate is True
    assert scan.symbols[0].reason == "signal_against_position"


def test_closed_session_never_scans() -> None:
    """Outside the FX session there is no opportunity to check."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("long")})],
        session_open=False,
        limits=LIMITS,
        now=NOW,
    )

    assert scan.escalate is False
    assert scan.reason == "market_closed"
    assert scan.symbols[0].reason == "market_closed"


def test_untrusted_quote_does_not_escalate() -> None:
    """A missing or non-positive quote cannot be traded or reasoned about."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("long")}, bid="0", ask="0")],
        session_open=True,
        limits=LIMITS,
        now=NOW,
    )

    assert scan.escalate is False
    assert scan.symbols[0].reason == "quote_unusable"


def test_exhausted_daily_round_cap_does_not_escalate() -> None:
    """The free channel's 1000 calls/day is not negotiable."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("long")})],
        session_open=True,
        limits=LIMITS,
        now=NOW,
        rounds_today=LIMITS.max_rounds_per_day,
    )

    assert scan.escalate is False
    assert scan.reason == "daily_round_cap_reached"


def test_minimum_spacing_blocks_a_second_round() -> None:
    """Two rounds a minute apart would triple the model cost for no edge."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("long")})],
        session_open=True,
        limits=LIMITS,
        now=NOW,
        # One minute ago: inside the ten-minute spacing floor.
        last_round_at=NOW - timedelta(minutes=1),
        rounds_today=1,
    )

    assert scan.escalate is False
    assert scan.reason == "round_too_soon"


def test_spacing_frees_up_once_the_gap_elapsed() -> None:
    """The spacing rule must not wedge the runtime shut forever."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("long")})],
        session_open=True,
        limits=OpportunityLimits(min_spacing_seconds=600),
        now=NOW,
        # Twenty minutes ago: the spacing floor has elapsed.
        last_round_at=NOW - timedelta(minutes=20),
        rounds_today=1,
    )

    assert scan.escalate is True


def test_unavailable_model_budget_does_not_escalate() -> None:
    """No budget means a round would produce a blocked record, not a decision."""
    scan = scan_opportunities(
        [_snapshot(signals={"momentum": _signal("long")})],
        session_open=True,
        limits=LIMITS,
        now=NOW,
        budget_available=False,
    )

    assert scan.escalate is False
    assert scan.reason == "model_budget_unavailable"


def test_one_escalating_symbol_is_enough() -> None:
    """The round covers the universe, so one opportunity justifies it."""
    scan = scan_opportunities(
        [
            _snapshot("EUR_USD", signals={"momentum": _signal("flat")}),
            _snapshot("GBP_USD", signals={"momentum": _signal("short", "0.9")}),
        ],
        session_open=True,
        limits=LIMITS,
        now=NOW,
    )

    assert scan.escalate is True
    by_symbol = {s.symbol: s for s in scan.symbols}
    assert by_symbol["EUR_USD"].escalate is False
    assert by_symbol["GBP_USD"].escalate is True


def test_scan_carries_every_symbol_it_was_given() -> None:
    """The record must explain the whole universe, not just the winner."""
    symbols = ["EUR_USD", "GBP_USD", "USD_JPY"]
    scan = scan_opportunities(
        [_snapshot(name) for name in symbols],
        session_open=True,
        limits=LIMITS,
        now=NOW,
    )

    assert [s.symbol for s in scan.symbols] == symbols
    assert isinstance(scan, OpportunityScan)
    assert all(isinstance(s, SymbolOpportunity) for s in scan.symbols)


def test_scan_is_pure_and_repeatable() -> None:
    """Same inputs, same verdict: the scan must stay trivially testable."""
    snapshots = [_snapshot(signals={"momentum": _signal("long")})]
    first = scan_opportunities(
        snapshots, session_open=True, limits=LIMITS, now=NOW
    )
    second = scan_opportunities(
        snapshots, session_open=True, limits=LIMITS, now=NOW
    )

    assert first.to_dict() == second.to_dict()
    # The caller's snapshots are never mutated by the scan.
    assert snapshots[0].strategy_signals["momentum"]["direction"] == "long"


def test_limits_reject_values_outside_the_guide_window() -> None:
    """GUIDE 5.1 says every 1-5 minutes; anything else is a typo."""
    import pytest

    with pytest.raises(ValueError):
        OpportunityLimits(scan_interval_seconds=30)
    with pytest.raises(ValueError):
        OpportunityLimits(scan_interval_seconds=600)
    with pytest.raises(ValueError):
        OpportunityLimits(max_rounds_per_day=0)
    with pytest.raises(ValueError):
        OpportunityLimits(escalation_min_confidence=Decimal("1.5"))


def test_round_cap_matches_the_documented_call_budget() -> None:
    """15 rounds x ~39 calls stays inside the 1000-call free allowance."""
    from alphabrief_models.model_budget import DEFAULT_OPENROUTER_FREE_DAILY_CALLS

    assert LIMITS.max_rounds_per_day == 15
    assert LIMITS.max_rounds_per_day * 39 <= DEFAULT_OPENROUTER_FREE_DAILY_CALLS
