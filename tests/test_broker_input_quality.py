"""Broker facts are present, fresh, consistent and immutable model inputs."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alphabrief_execution.broker.oanda.input_facts import BrokerInputFacts
from alphabrief_trader.committee_prompts import build_committee_prompt
from alphabrief_trader.daily_cycle import _snapshot_fingerprint
from alphabrief_trader.data_quality import evaluate_snapshot_quality
from alphabrief_trader.schemas import CommitteeInput, MarketSnapshot

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def facts() -> BrokerInputFacts:
    return BrokerInputFacts(
        symbol="EUR_USD",
        bid=Decimal("1.1"),
        ask=Decimal("1.1002"),
        spread=Decimal("0.0002"),
        quote_to_home=Decimal(1),
        quote_position_to_home=Decimal(1),
        quote_captured_at=NOW,
        nav=Decimal(1000),
        margin_available=Decimal(0),
        margin_used=Decimal(0),
        account_captured_at=NOW,
        position_units=Decimal(-10),
        position_unrealized_pnl=Decimal("-1.5"),
        positions_captured_at=NOW,
        reconciliation_captured_at=NOW,
        daily_open_count=0,
    )


def snapshot(broker: BrokerInputFacts) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EUR_USD",
        reference_price=Decimal("1.1"),
        captured_at=NOW,
        broker_evidence=broker,
    )


def test_real_zero_margin_and_signed_short_are_valid_observations() -> None:
    assert evaluate_snapshot_quality(snapshot(facts()), now=NOW).passed


@pytest.mark.parametrize(
    "field",
    [
        "bid",
        "ask",
        "spread",
        "quote_to_home",
        "quote_position_to_home",
        "nav",
        "margin_available",
        "position_units",
        "position_unrealized_pnl",
        "daily_open_count",
    ],
)
def test_missing_broker_value_is_not_a_zero(field: str) -> None:
    verdict = evaluate_snapshot_quality(
        snapshot(facts().model_copy(update={field: None})), now=NOW
    )
    assert not verdict.passed
    assert any(reason.startswith(f"{field}_") for reason in verdict.reasons)


@pytest.mark.parametrize(
    "field,seconds",
    [
        ("quote_captured_at", 15),
        ("account_captured_at", 60),
        ("positions_captured_at", 60),
        ("reconciliation_captured_at", 60),
    ],
)
def test_freshness_boundary_expiry_future_and_missing(field: str, seconds: int) -> None:
    broker = facts().model_copy(update={field: NOW - timedelta(seconds=seconds)})
    assert evaluate_snapshot_quality(snapshot(broker), now=NOW).passed
    expired = broker.model_copy(
        update={field: NOW - timedelta(seconds=seconds, microseconds=1)}
    )
    assert (
        f"{field}_stale_or_future"
        in evaluate_snapshot_quality(snapshot(expired), now=NOW).reasons
    )
    future = broker.model_copy(update={field: NOW + timedelta(microseconds=1)})
    assert (
        f"{field}_stale_or_future"
        in evaluate_snapshot_quality(snapshot(future), now=NOW).reasons
    )
    missing = broker.model_copy(update={field: None})
    assert (
        f"{field}_missing"
        in evaluate_snapshot_quality(snapshot(missing), now=NOW).reasons
    )


@pytest.mark.parametrize(
    "update,reason",
    [
        ({"bid": Decimal(0)}, "bid_missing_or_not_positive"),
        ({"quote_to_home": Decimal(0)}, "quote_to_home_missing_or_not_positive"),
        ({"nav": Decimal(0)}, "nav_missing_or_not_positive"),
        ({"margin_used": None}, "margin_used_missing"),
        ({"margin_used": Decimal(-1)}, "margin_used_negative"),
        ({"spread": Decimal("0.001")}, "quote_spread_inconsistent"),
        ({"symbol": "GBP_USD"}, "broker_input_symbol_mismatch"),
        ({"errors": {"account": "TimeoutError"}}, "broker_account_unavailable"),
    ],
)
def test_bad_broker_values_fail_quality(update: dict[str, object], reason: str) -> None:
    assert (
        reason
        in evaluate_snapshot_quality(
            snapshot(facts().model_copy(update=update)), now=NOW
        ).reasons
    )


def test_broker_observation_values_and_time_enter_fingerprint() -> None:
    original = snapshot(facts())
    for update in (
        {"nav": Decimal(1001)},
        {"margin_used": Decimal(1)},
        {"quote_captured_at": NOW - timedelta(seconds=1)},
    ):
        changed = snapshot(facts().model_copy(update=update))
        assert _snapshot_fingerprint({"EUR_USD": original}) != _snapshot_fingerprint(
            {"EUR_USD": changed}
        )


def test_committee_gets_real_broker_values_without_an_account_identifier() -> None:
    prompt = build_committee_prompt("risk", CommitteeInput(snapshot=snapshot(facts())))
    assert '"bid":"1.1"' in prompt and '"margin_available":"0"' in prompt
    assert '"position_units":"-10"' in prompt
    assert '"position_unrealized_pnl":"-1.5"' in prompt
    assert "account_id" not in prompt


def test_facts_reject_float_naive_time_and_unknown_identity_fields() -> None:
    for update in (
        {"nav": 1000.0},
        {"margin_used": 1000.0},
        {"quote_captured_at": NOW.replace(tzinfo=None)},
        {"account_id": "private-account"},
    ):
        with pytest.raises(ValueError):
            BrokerInputFacts.model_validate(facts().model_dump() | update)


@pytest.mark.parametrize(
    "row",
    [
        None,
        {"instrument": "EUR_USD"},
        {"instrument": "EUR_USD", "long": {}, "short": {"units": "0"}},
        {"instrument": "EUR_USD", "long": {"units": "10"}, "short": {"units": "0"}},
        {
            "instrument": "EUR_USD",
            "long": {"units": "invalid"},
            "short": {"units": "0"},
        },
        {"instrument": "EUR_USD", "long": {"units": 1.2}, "short": {"units": "0"}},
    ],
)
def test_position_parse_failure_never_becomes_a_flat_position(row: object) -> None:
    from alphabrief_execution.broker.oanda.client import OandaHttpClient
    from alphabrief_execution.broker.oanda.config import OandaPaperConfig
    from alphabrief_execution.broker.oanda.position_ops import (
        PositionOperationError,
        PositionOpsClient,
    )

    client = OandaHttpClient(
        config=OandaPaperConfig(
            base_url="https://api-fxpractice.oanda.com",
            timeout_seconds=1,
            retry_backoff_seconds=0.01,
            max_retries=0,
        ),
        token="test-token",
        account_id="test-account",
        http_send=lambda request, timeout: json.dumps({"positions": [row]}).encode(),
    )
    with pytest.raises(PositionOperationError, match="protocol_error"):
        PositionOpsClient(client).list_positions()
