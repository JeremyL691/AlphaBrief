"""Automated tests for S7: Enabled Strategy signals as Committee evidence.

Verifies:
- Enabled strategy in StrategySpecStore has its signal computed on OANDA bars.
- snapshot.strategy_signals is populated.
- build_evidence_catalog creates strategy:<strategy_id> entries.
- CommitteeInput.evidence_ids includes strategy:<strategy_id>.
- build_committee_prompt includes strategy:<id> in available evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db import MarketDataStore, NewsStore, StrategySpecStore
from alphabrief_cli.cycle_commands import _snapshot_loader
from alphabrief_core import Bar
from alphabrief_news.ingestion import NewsIngestionStore
from alphabrief_trader import CommitteeInput, MarketSnapshot
from alphabrief_trader.committee_prompts import build_committee_prompt
from alphabrief_trader.evidence_catalog import build_evidence_catalog


def _seed_bars(store: MarketDataStore, symbol: str = "EUR_USD") -> None:
    base_time = datetime.now(UTC) - timedelta(days=5)
    bars: list[Bar] = []
    price = Decimal("1.1000")
    for i in range(30):
        ts = base_time + timedelta(hours=i)
        close = price + Decimal("0.0005")
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=ts,
                open=price,
                high=price + Decimal("0.0010"),
                low=price - Decimal("0.0005"),
                close=close,
                volume=Decimal("500"),
                source="oanda_practice",
                data_version="oanda-candles-v1:M:H1",
            )
        )
        price = close
    store.insert_bars(
        bars=bars,
        source="oanda_practice",
        data_version="oanda-candles-v1:M:H1",
    )


def test_evidence_catalog_contains_strategy_signals() -> None:
    now = datetime.now(UTC)
    snapshot = MarketSnapshot(
        symbol="EUR_USD",
        reference_price=Decimal("1.1050"),
        captured_at=now,
        strategy_signals={
            "momentum_v1": {
                "signal_id": "sig_mom_1",
                "direction": "long",
                "confidence": 0.85,
                "horizon": "24h",
                "rationale": "positive 20-bar momentum",
            }
        },
    )

    catalog = build_evidence_catalog(snapshot)
    assert "strategy:momentum_v1" in catalog
    assert '"strategy_id":"momentum_v1"' in catalog["strategy:momentum_v1"]
    assert '"direction":"long"' in catalog["strategy:momentum_v1"]

    # Verify CommitteeInput binds strategy:<id> to evidence_ids
    committee_input = CommitteeInput(snapshot=snapshot)
    assert "strategy:momentum_v1" in committee_input.evidence_ids

    # Verify committee prompt includes strategy evidence
    prompt = build_committee_prompt("technical", committee_input)
    assert "strategy:momentum_v1" in prompt


def test_snapshot_loader_computes_enabled_strategy_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "alphabrief_test.duckdb"
    monkeypatch.setattr("alphabrief_core.paths.db_path", lambda: db_file)

    # 1. Store bars
    mstore = MarketDataStore(db_path=db_file)
    _seed_bars(mstore, "EUR_USD")
    mstore.close()

    # 2. Register and enable a strategy spec
    spec_store = StrategySpecStore(db_path=db_file)
    spec_payload = {
        "strategy_id": "momentum_trend_s7",
        "name": "Momentum Trend S7",
        "version": "1.0.0",
        "universe": {"symbols": ["EUR_USD"]},
        "timeframe": "1h",
        "entry": {"condition": "close > open"},
        "exit": {"condition": "close < open"},
        "risk": {"max_position_pct": "0.3"},
        "costs": {"fee_bps": "2", "slippage_bps": "2"},
        "evaluation": {
            "train_period": {"start": "2024-01-01", "end": "2024-06-30"},
            "test_period": {"start": "2024-07-01", "end": "2024-12-31"},
        },
    }
    spec_store.save_spec(spec_payload, enabled=True)
    spec_store.close()

    # 3. Create loader and build snapshot
    nstore = NewsStore(db_path=db_file)
    nhealth = NewsIngestionStore(db_path=db_file)
    mstore2 = MarketDataStore(db_path=db_file)
    try:
        loader = _snapshot_loader(mstore2, nstore, nhealth)
        snapshot = loader("EUR_USD")
        assert snapshot is not None
        assert "momentum_trend_s7" in snapshot.strategy_signals
        signal_info = snapshot.strategy_signals["momentum_trend_s7"]
        assert "direction" in signal_info
        assert "confidence" in signal_info

        # Check evidence catalog
        catalog = build_evidence_catalog(snapshot)
        assert "strategy:momentum_trend_s7" in catalog

        # Check committee input evidence ids
        cinput = CommitteeInput(snapshot=snapshot)
        assert "strategy:momentum_trend_s7" in cinput.evidence_ids
    finally:
        mstore2.close()
        nstore.close()
        nhealth.close()


def test_snapshot_loader_survives_multi_granularity_bars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signals use the H1 series only and never crash the round.

    Real stores keep M15/H1/H4/D facts for the same symbol, and D/H4
    timestamps collide with H1. Feeding the flattened multi-granularity
    batch to a strategy failed the bars quality check and aborted the
    whole cycle; the loader must compute signals on the H1 series alone.
    """
    db_file = tmp_path / "alphabrief_test.duckdb"
    monkeypatch.setattr("alphabrief_core.paths.db_path", lambda: db_file)

    mstore = MarketDataStore(db_path=db_file)
    try:
        base_time = datetime.now(UTC) - timedelta(days=5)
        bars: list[Bar] = []
        price = Decimal("1.1000")
        for i in range(30):
            ts = base_time + timedelta(hours=i)
            close = price + Decimal("0.0005")
            for gran in ("M:H1", "M:H4"):
                bars.append(
                    Bar(
                        symbol="EUR_USD",
                        timestamp=ts,
                        open=price,
                        high=price + Decimal("0.0010"),
                        low=price - Decimal("0.0005"),
                        close=close,
                        volume=Decimal("500"),
                        source="oanda_practice",
                        data_version=f"oanda-candles-v1:{gran}",
                    )
                )
            price = close
        mstore.insert_bars(
            bars=bars, source="oanda_practice", data_version="oanda-candles-v1:M:H1"
        )
        mstore.insert_bars(
            bars=bars, source="oanda_practice", data_version="oanda-candles-v1:M:H4"
        )
    finally:
        mstore.close()

    spec_store = StrategySpecStore(db_path=db_file)
    try:
        spec_store.save_spec(
            {
                "strategy_id": "momentum",
                "name": "Momentum",
                "version": "1.0.0",
                "universe": {"symbols": ["EUR_USD"]},
                "timeframe": "H1",
                "entry": {"condition": "close > open"},
                "exit": {"condition": "close < open"},
                "risk": {"max_position_pct": "0.3"},
                "costs": {"fee_bps": "2", "slippage_bps": "2"},
                "evaluation": {
                    "train_period": {"start": "2024-01-01", "end": "2024-06-30"},
                    "test_period": {"start": "2024-07-01", "end": "2024-12-31"},
                },
            },
            enabled=True,
        )
    finally:
        spec_store.close()

    nstore = NewsStore(db_path=db_file)
    nhealth = NewsIngestionStore(db_path=db_file)
    mstore2 = MarketDataStore(db_path=db_file)
    try:
        loader = _snapshot_loader(mstore2, nstore, nhealth)
        snapshot = loader("EUR_USD")
        assert snapshot is not None
        assert "momentum" in snapshot.strategy_signals
    finally:
        mstore2.close()
        nstore.close()
        nhealth.close()
