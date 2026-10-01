"""Practice test: real OANDA candle and quote ingestion (S3-1).

Run with ``pytest -m practice -k market_sync_practice``; CI excludes it
with ``-m "not practice"``. It reads the practice account and writes into
an isolated data directory, so it never touches the soak database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_core import Bar, load_env_file
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import (
    load_oanda_paper_config,
    read_oanda_credentials,
)
from alphabrief_execution.broker.oanda.market_sync import sync_market_data
from alphabrief_execution.broker.runtime import oanda_is_configured

pytestmark = pytest.mark.practice


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_local_env() -> None:
    """Load the developer's ``.env`` so practice runs see real credentials."""
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        load_env_file(env_path)


class _MemoryStore:
    def __init__(self) -> None:
        self.bars: list[Bar] = []

    def insert_bars(
        self, bars: list[Bar], source: str, data_version: str
    ) -> int:
        del source, data_version
        self.bars.extend(bars)
        return len(bars)


def test_real_candles_and_quotes_are_fetched() -> None:
    _load_local_env()
    if not oanda_is_configured():
        pytest.fail(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )
    token, account_id = read_oanda_credentials()
    client = OandaHttpClient(
        config=load_oanda_paper_config(REPO_ROOT / "config/oanda_paper.yaml"),
        token=token,
        account_id=account_id,
    )
    store = _MemoryStore()

    report = sync_market_data(
        client,
        instruments=["EUR_USD"],
        store=store,
        timeframes=(("H1", 10),),
    )

    assert report.errors == {}
    assert report.bars_by_granularity["EUR_USD:H1"] >= 5
    assert report.quotes == 1
    # Every ingested bar is a completed practice candle.
    assert store.bars
    assert all(bar.source == "oanda_practice" for bar in store.bars)
    assert all(bar.timestamp.tzinfo is not None for bar in store.bars)
