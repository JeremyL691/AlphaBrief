"""Cross-market inputs from completed broker candles, never simulated in runtime."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db.market_data import MarketDataStore
from alphabrief_core import Bar
from alphabrief_execution.broker.errors import BrokerAuthError, BrokerNotFoundError
from alphabrief_execution.broker.oanda.candles import (
    CandlePage,
    CandleRequest,
    OandaCandle,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.market_sync import (
    SIGNAL_INSTRUMENTS,
    SIGNAL_TIMEFRAMES,
    SignalCandleObservation,
    observe_signal_candles,
)
from alphabrief_trader.committee_prompts import build_committee_prompt
from alphabrief_trader.daily_cycle import _snapshot_fingerprint
from alphabrief_trader.data_quality import evaluate_snapshot_quality
from alphabrief_trader.schemas import (
    CommitteeInput,
    MarketSnapshot,
    SignalInputEvidence,
)
from alphabrief_trader.signal_inputs import build_signal_inputs

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def bars(
    symbol: str,
    timeframe: str,
    count: int,
    pattern: tuple[int, ...] = (1, -1),
) -> list[Bar]:
    duration = timedelta(hours=1) if timeframe == "H1" else timedelta(days=1)
    close = Decimal(10)
    result = []
    for i in range(count):
        if i:
            close *= 1 + Decimal(pattern[(i - 1) % len(pattern)]) / 100
        result.append(
            Bar(
                symbol=symbol,
                timestamp=NOW - duration * (count - i),
                open=close,
                high=close + Decimal("0.01"),
                low=close - Decimal("0.01"),
                close=close,
                volume=Decimal(100),
                source="oanda_practice",
                data_version=f"test:M:{timeframe}",
            )
        )
    return result


def observation() -> SignalCandleObservation:
    return SignalCandleObservation(
        {
            symbol: {tf: bars(symbol, tf, count) for tf, count in SIGNAL_TIMEFRAMES}
            for symbol in SIGNAL_INSTRUMENTS
        },
        {},
        {},
        NOW,
    )


def evidence(source: SignalCandleObservation | None = None) -> SignalInputEvidence:
    return build_signal_inputs(
        source or observation(), daily=bars("EUR_USD", "D", 60), now=NOW
    )


def snapshot(inputs: SignalInputEvidence) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EUR_USD",
        reference_price=Decimal(10),
        captured_at=NOW,
        signal_evidence=inputs,
    )


@pytest.mark.parametrize(
    "pattern,expected",
    [
        ((1, -1), Decimal(1)),
        ((-1, 1), Decimal(-1)),
        ((1, 1, -1, -1), Decimal(0)),
    ],
)
def test_decimal_correlation_matches_analytic_daily_return_series(
    pattern: tuple[int, ...],
    expected: Decimal,
) -> None:
    source = observation()
    source.series["XAU_USD"]["D"] = bars("XAU_USD", "D", 60, pattern)
    facts = evidence(source).signals["XAU_USD"]
    assert facts.correlation_20d is not None
    assert abs(facts.correlation_20d - expected) < Decimal("1e-24")
    assert facts.correlation_samples == 20 and facts.correlation_reason is None
    assert facts.counts == {"H1": 120, "D": 60}
    assert facts.h1_return_pct is not None and facts.daily_return_pct is not None
    assert len(facts.correlation_input_hash) == 64
    assert evaluate_snapshot_quality(snapshot(evidence(source)), now=NOW).passed


@pytest.mark.parametrize(
    "defect",
    [
        "short_h1",
        "short_daily",
        "stale",
        "future",
        "wrong_source",
        "wrong_component",
        "wrong_symbol",
    ],
)
def test_bad_signal_windows_reject_without_padding(defect: str) -> None:
    source = observation()
    series = source.series["XAU_USD"]
    if defect == "short_daily":
        series["D"] = series["D"][1:]
    elif defect == "stale":
        series["H1"] = [
            b.model_copy(update={"timestamp": b.timestamp - timedelta(hours=3)})
            for b in series["H1"]
        ]
    elif defect == "future":
        series["H1"][-1] = series["H1"][-1].model_copy(update={"timestamp": NOW})
    elif defect == "short_h1":
        series["H1"] = series["H1"][1:]
    else:
        update = {
            "wrong_source": {"source": "other"},
            "wrong_component": {"data_version": "test:B:H1"},
            "wrong_symbol": {"symbol": "GBP_USD"},
        }[defect]
        series["H1"][0] = series["H1"][0].model_copy(update=update)
    verdict = evaluate_snapshot_quality(snapshot(evidence(source)), now=NOW)
    assert not verdict.passed
    assert any(reason.startswith("signal:XAU_USD:") for reason in verdict.reasons)


@pytest.mark.parametrize("defect", ["gap", "unaligned", "constant", "newer_daily"])
def test_correlation_does_not_pair_different_intervals_or_invent_zero(
    defect: str,
) -> None:
    source = observation()
    daily = source.series["XAU_USD"]["D"]
    if defect == "gap":
        del daily[-5]
    elif defect == "unaligned":
        source.series["XAU_USD"]["D"] = [
            b.model_copy(update={"timestamp": b.timestamp + timedelta(minutes=1)})
            for b in daily
        ]
    elif defect == "newer_daily":
        pass  # The target below ends a day earlier than the complete signal series.
    else:
        source.series["XAU_USD"]["D"] = bars("XAU_USD", "D", 60, (0,))
    prepared = (
        build_signal_inputs(source, daily=bars("EUR_USD", "D", 60)[:-1], now=NOW)
        if defect == "newer_daily"
        else evidence(source)
    )
    facts = prepared.signals["XAU_USD"]
    assert facts.correlation_20d is None
    assert facts.correlation_reason is not None
    assert not evaluate_snapshot_quality(snapshot(prepared), now=NOW).passed


def test_explicit_broker_unreadable_is_recorded_but_unknown_missing_is_rejected() -> (
    None
):
    source = observation()
    del source.series["XAU_USD"]
    assert not evaluate_snapshot_quality(snapshot(evidence(source)), now=NOW).passed
    source.excluded["XAU_USD"] = "broker_not_found"
    loaded = snapshot(evidence(source))
    assert evaluate_snapshot_quality(loaded, now=NOW).passed
    prompt = build_committee_prompt("technical", CommitteeInput(snapshot=loaded))
    assert "XAU_USD" in prompt and "broker_not_found" in prompt
    assert "correlation_20d" in prompt and "SPX500_USD" in prompt


def test_signal_inputs_hash_times_prices_and_exclusions() -> None:
    original = snapshot(evidence())
    source = observation()
    source.series["XAU_USD"]["H1"][0] = source.series["XAU_USD"]["H1"][0].model_copy(
        update={"volume": Decimal(101)}
    )
    changed = snapshot(evidence(source))
    assert _snapshot_fingerprint({"EUR_USD": original}) != _snapshot_fingerprint(
        {"EUR_USD": changed}
    )
    for when in (NOW + timedelta(seconds=1), NOW - timedelta(hours=3)):
        timed = snapshot(evidence(replace(observation(), observed_at=when)))
        assert not evaluate_snapshot_quality(timed, now=NOW).passed
        assert _snapshot_fingerprint({"EUR_USD": original}) != _snapshot_fingerprint(
            {"EUR_USD": timed}
        )
    excluded = observation()
    del excluded.series["XAU_USD"]
    excluded.excluded["XAU_USD"] = "broker_not_found"
    assert _snapshot_fingerprint({"EUR_USD": original}) != _snapshot_fingerprint(
        {"EUR_USD": snapshot(evidence(excluded))}
    )


def test_signal_schema_rejects_float_naive_time_and_unproven_exclusion() -> None:
    data = evidence().model_dump()
    with pytest.raises(ValueError):
        SignalInputEvidence.model_validate(
            data | {"observed_at": NOW.replace(tzinfo=None)}
        )
    with pytest.raises(ValueError):
        SignalInputEvidence.model_validate(data | {"excluded": {"XAU_USD": "timeout"}})
    data["signals"]["XAU_USD"]["correlation_20d"] = 0.5
    with pytest.raises(ValueError):
        SignalInputEvidence.model_validate(data)


@pytest.mark.parametrize("failure", [None, "not_found", "auth", "timeout", "invalid"])
def test_signal_fetch_uses_only_candles_persists_and_classifies_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    from alphabrief_execution.broker.oanda import market_sync

    requests: list[CandleRequest] = []

    def fetch(client: object, *, request: CandleRequest) -> CandlePage:
        requests.append(request)
        if request.symbol == "XAU_USD" and failure is not None:
            exc = {
                "not_found": BrokerNotFoundError,
                "auth": BrokerAuthError,
                "timeout": TimeoutError,
                "invalid": ValueError,
            }[failure]
            raise exc("hidden-account-id-secret")
        count = request.count - 1
        rows = bars(request.symbol, request.granularity, count)
        return CandlePage(
            symbol=request.symbol,
            granularity=request.granularity,
            candles=tuple(
                OandaCandle(
                    symbol=b.symbol,
                    time=b.timestamp,
                    component="M",
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                    complete=True,
                    source_version="test",
                )
                for b in rows
            ),
        )

    monkeypatch.setattr(market_sync, "fetch_candles", fetch)
    store = MarketDataStore(tmp_path / "signals.duckdb")
    try:
        client = OandaHttpClient(
            config=OandaPaperConfig(
                base_url="https://api-fxpractice.oanda.com",
                timeout_seconds=1,
                retry_backoff_seconds=0.01,
                max_retries=0,
            ),
            token="test-token",
            account_id="test-account",
        )
        observed = observe_signal_candles(client, store=store, clock=lambda: NOW)
        assert all(
            r.components == ("M",) and r.granularity in {"H1", "D"} for r in requests
        )
        assert all(
            r.count == (121 if r.granularity == "H1" else 61) for r in requests
        )
        assert observed.observed_at == NOW
        assert len(observed.series["SPX500_USD"]["H1"]) == 120
        assert len(store.get_bar_models("SPX500_USD", data_version_suffix=":M:D")) == 60
        assert "hidden-account-id-secret" not in str(observed)
        if failure == "not_found":
            assert observed.excluded == {"XAU_USD": "broker_not_found"}
            assert observed.errors == {} and "XAU_USD" not in observed.series
        elif failure:
            assert observed.excluded == {}
            assert set(observed.errors) == {"XAU_USD:H1", "XAU_USD:D"}
        else:
            assert observed.excluded == observed.errors == {}
    finally:
        store.close()
