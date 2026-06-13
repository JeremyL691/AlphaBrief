from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_core import Bar, Order, OrderIntent, RiskDecision, Signal
from pydantic import ValidationError

NOW = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)


def test_bar_accepts_valid_ohlcv_data() -> None:
    bar = Bar(
        symbol="BTC-USD",
        timestamp=NOW,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("95"),
        close=Decimal("105"),
        volume=Decimal("12.5"),
        source="fixture",
        data_version="v1",
    )

    assert bar.symbol == "BTC-USD"
    assert bar.close == Decimal("105")


def test_bar_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Bar(
            symbol="BTC-USD",
            timestamp=datetime(2026, 6, 12, 12, 0),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("12.5"),
            source="fixture",
            data_version="v1",
        )


def test_bar_rejects_inconsistent_high_low() -> None:
    with pytest.raises(ValidationError, match="high"):
        Bar(
            symbol="BTC-USD",
            timestamp=NOW,
            open=Decimal("100"),
            high=Decimal("99"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("12.5"),
            source="fixture",
            data_version="v1",
        )


def test_bar_rejects_float_decimal_inputs() -> None:
    with pytest.raises(ValidationError, match="float"):
        Bar.model_validate(
            {
                "symbol": "BTC-USD",
                "timestamp": NOW,
                "open": 100.0,
                "high": Decimal("110"),
                "low": Decimal("95"),
                "close": Decimal("105"),
                "volume": Decimal("12.5"),
                "source": "fixture",
                "data_version": "v1",
            }
        )


def test_signal_confidence_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        Signal(
            signal_id="sig_1",
            strategy_id="strategy_1",
            symbol="BTC-USD",
            timestamp=NOW,
            direction="long",
            confidence=1.2,
            horizon="1d",
            rationale="too confident",
        )


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Signal.model_validate(
            {
                "signal_id": "sig_1",
                "strategy_id": "strategy_1",
                "symbol": "BTC-USD",
                "timestamp": NOW,
                "direction": "flat",
                "confidence": Decimal("0.5"),
                "horizon": "1d",
                "rationale": "wait",
                "unexpected": True,
            }
        )


def test_order_intent_requires_exactly_one_sizing_mode() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        OrderIntent(
            intent_id="intent_1",
            source="strategy",
            symbol="BTC-USD",
            side="buy",
            order_type="market",
            rationale="invalid sizing",
            created_at=NOW,
        )

    with pytest.raises(ValidationError, match="exactly one"):
        OrderIntent(
            intent_id="intent_1",
            source="strategy",
            symbol="BTC-USD",
            side="buy",
            order_type="market",
            quantity=Decimal("1"),
            target_position_pct=Decimal("0.5"),
            rationale="invalid sizing",
            created_at=NOW,
        )


def test_order_intent_limit_and_market_price_rules() -> None:
    with pytest.raises(ValidationError, match="limit_price"):
        OrderIntent(
            intent_id="intent_1",
            source="strategy",
            symbol="BTC-USD",
            side="buy",
            order_type="limit",
            quantity=Decimal("1"),
            rationale="limit needs price",
            created_at=NOW,
        )

    with pytest.raises(ValidationError, match="market orders"):
        OrderIntent(
            intent_id="intent_2",
            source="strategy",
            symbol="BTC-USD",
            side="buy",
            order_type="market",
            quantity=Decimal("1"),
            limit_price=Decimal("100"),
            rationale="market cannot include limit price",
            created_at=NOW,
        )


def test_order_intent_allows_zero_target_position_pct() -> None:
    intent = OrderIntent(
        intent_id="intent_1",
        source="manual",
        symbol="BTC-USD",
        side="sell",
        order_type="market",
        target_position_pct=Decimal("0"),
        rationale="move to flat",
        created_at=NOW,
    )

    assert intent.target_position_pct == Decimal("0")


def test_risk_decision_accepts_rejection_schema() -> None:
    decision = RiskDecision(
        decision_id="risk_1",
        intent_id="intent_1",
        approved=False,
        reason="Daily loss limit breached",
        max_quantity=None,
        risk_tags=["daily_loss", "blocked"],
        requires_human_review=True,
        created_at=NOW,
    )

    assert decision.approved is False
    assert decision.requires_human_review is True


def test_order_requires_risk_decision_id_and_positive_quantity() -> None:
    with pytest.raises(ValidationError):
        Order(
            order_id="order_1",
            intent_id="intent_1",
            risk_decision_id="",
            broker="paper",
            symbol="BTC-USD",
            side="buy",
            order_type="market",
            quantity=Decimal("1"),
            status="created",
            created_at=NOW,
        )

    with pytest.raises(ValidationError, match="positive"):
        Order(
            order_id="order_1",
            intent_id="intent_1",
            risk_decision_id="risk_1",
            broker="paper",
            symbol="BTC-USD",
            side="buy",
            order_type="market",
            quantity=Decimal("0"),
            status="created",
            created_at=NOW,
        )
