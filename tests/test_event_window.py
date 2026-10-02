"""Tests for the rule-6 event window (PROJECT_GUIDE 5.7).

The rule blocks new exposure inside the window; the news layer classifies
the headlines that feed it. Both halves are pinned here, plus the gate
integration and the close exemption.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alphabrief_core import OrderIntent
from alphabrief_news.high_impact import HeadlineLike, high_impact_events
from alphabrief_risk import KillSwitch, RiskGate, RiskLimitConfig
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.entry_rules import EntryRulePolicy, evaluate_entry_rules
from alphabrief_risk.event_window import (
    DEFAULT_EVENT_WINDOW_MINUTES,
    HIGH_IMPACT_KEYWORDS,
    event_window_reason,
    keyword_currency,
    match_high_impact_keyword,
    window_reason_map,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _headline(
    *,
    title: str,
    symbols: tuple[str, ...] = ("GENERAL",),
    published_at: datetime | None = None,
    headline_id: str = "h1",
    summary: str = "",
    source: str = "FXStreet",
) -> HeadlineLike:
    return HeadlineLike(
        headline_id=headline_id,
        title=title,
        summary=summary,
        source=source,
        published_at=published_at or NOW - timedelta(minutes=5),
        symbols=symbols,
    )


class TestClassification:
    def test_keyword_matching_covers_the_guide_list(self) -> None:
        for keyword in HIGH_IMPACT_KEYWORDS:
            assert match_high_impact_keyword(f"Something about {keyword} today")

    def test_non_high_impact_text_is_not_matched(self) -> None:
        assert match_high_impact_keyword("Gold edges higher on safe-haven bid") is None

    def test_central_bank_keywords_name_a_currency(self) -> None:
        assert keyword_currency("fomc") == "USD"
        assert keyword_currency("ecb") == "EUR"
        assert keyword_currency("boj") == "JPY"
        assert keyword_currency("cpi") is None

    def test_central_bank_headline_pins_its_currency(self) -> None:
        events = high_impact_events(
            [_headline(title="FOMC statement released", symbols=("GENERAL",))],
            now=NOW,
        )

        assert {event.symbol for event in events} == {
            "EUR_USD",
            "GBP_USD",
            "USD_JPY",
            "AUD_USD",
            "USD_CAD",
        }
        assert {event.currency for event in events} == {"USD"}

    def test_generic_keyword_uses_the_headline_tags(self) -> None:
        events = high_impact_events(
            [_headline(title="CPI beats expectations", symbols=("GBP_USD",))],
            now=NOW,
        )

        assert [event.symbol for event in events] == ["GBP_USD"]
        assert events[0].currency == "MULTI"

    def test_untagged_generic_keyword_fails_closed_for_everything(self) -> None:
        events = high_impact_events(
            [_headline(title="Rate decision due today", symbols=("GENERAL",))],
            now=NOW,
        )

        assert len(events) == 5

    def test_events_outside_the_window_are_dropped(self) -> None:
        old = _headline(
            title="NFP misses badly",
            published_at=NOW - timedelta(minutes=DEFAULT_EVENT_WINDOW_MINUTES + 1),
        )
        future = _headline(
            title="NFP due next hour",
            published_at=NOW + timedelta(minutes=10),
        )

        assert high_impact_events([old, future], now=NOW) == ()

    def test_window_boundary_is_inclusive(self) -> None:
        at_edge = _headline(
            title="NFP just released",
            published_at=NOW - timedelta(minutes=DEFAULT_EVENT_WINDOW_MINUTES),
        )

        assert len(high_impact_events([at_edge], now=NOW)) == 5

    def test_bad_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="window_minutes must be positive"):
            high_impact_events([], now=NOW, window_minutes=0)

    def test_reason_map_carries_the_source_and_time(self) -> None:
        events = high_impact_events(
            [_headline(title="BoE hikes rates", source="Bank of England")],
            now=NOW,
        )
        reasons = window_reason_map(events, now=NOW)

        assert set(reasons) == {"GBP_USD"}
        assert "boe" in reasons["GBP_USD"]
        assert "Bank of England" in reasons["GBP_USD"]


class TestRule:
    def _intent(self, **overrides: object) -> OrderIntent:
        payload: dict[str, object] = {
            "intent_id": "intent_1",
            "source": "model",
            "symbol": "EUR_USD",
            "side": "buy",
            "order_type": "market",
            "quantity": Decimal("1000"),
            "stop_loss": Decimal("1.0900"),
            "take_profit": Decimal("1.1200"),
            "rationale": "rule 6 test",
            "created_at": NOW,
        }
        payload.update(overrides)
        return OrderIntent.model_validate(payload)

    def _context(self, **overrides: object) -> AccountExposureContext:
        payload: dict[str, object] = {
            "current_total_exposure": Decimal("0"),
            "cash": Decimal("100000"),
            "account_id": "acct-1",
            "captured_at": NOW,
            "quote_captured_at": NOW,
            "quote_tradeable": True,
        }
        payload.update(overrides)
        return AccountExposureContext.model_validate(payload)

    def test_event_inside_the_window_rejects_an_entry(self) -> None:
        policy = EntryRulePolicy(event_window_minutes=30)
        context = self._context(
            recent_high_impact_events={"EUR_USD": "ecb (EUR) at 12:00Z"}
        )

        rejections = evaluate_entry_rules(
            self._intent(), policy=policy, now=NOW, account_context=context
        )

        assert [r.code for r in rejections] == ["EVENT_WINDOW"]
        assert "ecb" in rejections[0].detail

    def test_no_event_allows_the_entry(self) -> None:
        policy = EntryRulePolicy(event_window_minutes=30)

        rejections = evaluate_entry_rules(
            self._intent(),
            policy=policy,
            now=NOW,
            account_context=self._context(),
        )

        assert rejections == ()

    def test_missing_context_fails_closed(self) -> None:
        policy = EntryRulePolicy(event_window_minutes=30)

        rejections = evaluate_entry_rules(
            self._intent(), policy=policy, now=NOW, account_context=None
        )

        assert [r.code for r in rejections] == ["EVENT_WINDOW"]

    def test_rule_disabled_by_default(self) -> None:
        rejections = evaluate_entry_rules(
            self._intent(),
            policy=EntryRulePolicy(),
            now=NOW,
            account_context=self._context(
                recent_high_impact_events={"EUR_USD": "ecb (EUR)"}
            ),
        )

        assert rejections == ()

    def test_event_for_another_symbol_does_not_block(self) -> None:
        policy = EntryRulePolicy(event_window_minutes=30)

        rejections = evaluate_entry_rules(
            self._intent(),
            policy=policy,
            now=NOW,
            account_context=self._context(
                recent_high_impact_events={"GBP_USD": "boe (GBP)"}
            ),
        )

        assert rejections == ()


class TestGateIntegration:
    def _gate(self) -> RiskGate:
        return RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True,
                symbol_allowlist=frozenset({"EUR_USD"}),
                entry_rules=EntryRulePolicy(event_window_minutes=30),
            ),
            kill_switch=KillSwitch(),
            clock=lambda: NOW,
        )

    def _intent(self, *, reduce_only: bool = False) -> OrderIntent:
        return OrderIntent(
            intent_id="intent_1",
            source="manual" if reduce_only else "model",
            symbol="EUR_USD",
            side="sell" if reduce_only else "buy",
            order_type="market",
            quantity=Decimal("1000"),
            stop_loss=None if reduce_only else Decimal("1.0900"),
            take_profit=None if reduce_only else Decimal("1.1200"),
            reduce_only=reduce_only,
            rationale="gate test",
            created_at=NOW,
        )

    def _context(self) -> AccountExposureContext:
        return AccountExposureContext(
            current_total_exposure=Decimal("0"),
            cash=Decimal("100000"),
            account_id="acct-1",
            captured_at=NOW,
            quote_captured_at=NOW,
            quote_tradeable=True,
            recent_high_impact_events={"EUR_USD": "fomc (USD) at 12:00Z"},
        )

    def test_entry_is_rejected_with_the_guide_code(self) -> None:
        decision = self._gate().evaluate(
            self._intent(),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("1000"),
            account_context=self._context(),
        )

        assert decision.approved is False
        assert "EVENT_WINDOW" in decision.risk_tags

    def test_close_is_exempt_from_the_event_window(self) -> None:
        decision = self._gate().evaluate(
            self._intent(reduce_only=True),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("1000"),
            account_context=self._context(),
        )

        assert decision.approved is True

    def test_event_window_reason_helper_reads_maps_and_objects(self) -> None:
        assert event_window_reason("EUR_USD", {"EUR_USD": "cpi"}) == "cpi"
        assert event_window_reason("GBP_USD", {"EUR_USD": "cpi"}) is None
        events = high_impact_events([_headline(title="ECB holds rates")], now=NOW)
        assert event_window_reason("EUR_USD", events) is not None
