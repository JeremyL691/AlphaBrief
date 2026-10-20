"""Signal-instrument candles must stay as fresh as the traded ones.

PROJECT_GUIDE 5.3 requires the cross-market signals (gold, S&P 500, Brent)
to have the same freshness as the traded K lines, and 5.7 rule 6 blocks
entries around high-impact events for the instrument. The decision cycle
reads those signal series from the stored candles.

`market_sync` used to refresh only the traded universe, so the signal
instruments were refreshed only incidentally when a committee round ran.
After a quiet stretch their H1 series aged past the two-hour limit and
every symbol failed data quality with ``signal:BCO_USD:H1_stale_or_future``
- a deterministic refusal that looked like a market problem but was
actually a missing refresh.

The runtime's periodic sync must therefore cover both sets.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_cli import run_commands
from alphabrief_execution.broker.oanda.market_sync import SIGNAL_INSTRUMENTS


def _record_refresh(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Capture the symbol tuple each refresh call asks for."""
    calls: list[tuple[str, ...]] = []

    def _fake_refresh(store: object, symbols: tuple[str, ...]) -> dict[str, str]:
        calls.append(tuple(symbols))
        return {}

    monkeypatch.setattr(
        "alphabrief_cli.cycle_commands._refresh_market_bars", _fake_refresh
    )
    return calls


def test_market_sync_includes_the_signal_instruments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One sync must refresh traded and signal candles together."""
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    calls = _record_refresh(monkeypatch)

    run_commands.market_sync_once(symbols=("EUR_USD", "GBP_USD"))

    assert calls, "market_sync_once did not refresh any candles"
    requested = set(calls[0])
    for signal in SIGNAL_INSTRUMENTS:
        assert signal in requested, (
            f"{signal} is missing from the periodic refresh; its H1 series "
            "would age past the 2-hour data-quality limit"
        )
    assert {"EUR_USD", "GBP_USD"} <= requested


def test_market_sync_does_not_duplicate_a_signal_symbol(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A traded symbol that is also a signal must not be fetched twice."""
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    calls = _record_refresh(monkeypatch)

    run_commands.market_sync_once(symbols=("EUR_USD", "XAU_USD"))

    requested = list(calls[0])
    assert len(requested) == len(set(requested))
