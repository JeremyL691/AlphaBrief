"""M12-W06: automated data-leakage and lookahead gates.

Covers AC-M12-W06-01: seeded lookahead, revised-future-data, target
leakage, train-test overlap, and timestamp-boundary violations each
fail the automated leakage gates with explicit reasons.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphabrief_backtest import (
    LeakageReport,
    check_chronological_bars,
    check_declared_data_version,
    check_signals_within_bars,
    check_trailing_features_lookahead,
    check_train_test_disjoint,
    run_leakage_gates,
)
from alphabrief_core import Bar, Signal

VERSION = "fixture-data-v1"


def _bars(
    closes: list[str],
    *,
    version: str = VERSION,
    start: datetime | None = None,
) -> list[Bar]:
    start = start or datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        bars.append(
            Bar(
                symbol="SPY",
                timestamp=start + timedelta(days=index),
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("10"),
                source="unit-test",
                data_version=version,
            )
        )
    return bars


def _trailing_features(
    bars: list[Bar],
    *,
    sma_windows: tuple[int, ...] = (3,),
    return_periods: tuple[int, ...] = (1,),
) -> list[dict[str, Decimal | None]]:
    """Correct trailing features (no lookahead) for a bar list."""
    rows: list[dict[str, Decimal | None]] = []
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    for index in range(len(bars)):
        values: dict[str, Decimal | None] = {}
        for window in sma_windows:
            start_index = index - window + 1
            if start_index < 0:
                values[f"close_sma_{window}"] = None
                values[f"volume_sma_{window}"] = None
            else:
                values[f"close_sma_{window}"] = sum(
                    closes[start_index : index + 1], Decimal("0")
                ) / Decimal(window)
                values[f"volume_sma_{window}"] = sum(
                    volumes[start_index : index + 1], Decimal("0")
                ) / Decimal(window)
        for period in return_periods:
            previous_index = index - period
            if previous_index < 0:
                values[f"return_{period}"] = None
            else:
                values[f"return_{period}"] = (
                    closes[index] - closes[previous_index]
                ) / closes[previous_index]
        rows.append(values)
    return rows


class TestTimestampBoundary:
    def test_chronological_bars_pass(self) -> None:
        verdict = check_chronological_bars(_bars(["100", "101", "102"]))
        assert verdict.gate_id == "timestamp_boundary"
        assert verdict.passed

    def test_reversed_bar_fails(self) -> None:
        bars = _bars(["100", "101", "102"])
        bars[2] = bars[2].model_copy(
            update={"timestamp": bars[0].timestamp - timedelta(days=1)}
        )
        verdict = check_chronological_bars(bars)
        assert not verdict.passed
        assert "strictly chronological" in verdict.reason

    def test_duplicate_timestamp_fails(self) -> None:
        bars = _bars(["100", "101", "102"])
        bars[2] = bars[2].model_copy(update={"timestamp": bars[1].timestamp})
        verdict = check_chronological_bars(bars)
        assert not verdict.passed


class TestRevisedFutureData:
    def test_single_version_passes(self) -> None:
        verdict = check_declared_data_version(_bars(["100", "101"]), VERSION)
        assert verdict.gate_id == "revised_future_data"
        assert verdict.passed

    def test_revised_version_fails(self) -> None:
        bars = _bars(["100", "101", "102"])
        bars[1] = bars[1].model_copy(update={"data_version": "v2-revised"})
        verdict = check_declared_data_version(bars, VERSION)
        assert not verdict.passed
        assert "v2-revised" in verdict.reason


class TestSeededLookahead:
    def test_clean_trailing_features_pass(self) -> None:
        bars = _bars(["100", "101", "102", "103"])
        features = _trailing_features(bars)
        verdict = check_trailing_features_lookahead(
            bars, features, sma_windows=(3,), return_periods=(1,)
        )
        assert verdict.gate_id == "seeded_lookahead"
        assert verdict.passed

    def test_future_close_seeded_into_sma_fails(self) -> None:
        bars = _bars(["100", "101", "102", "103"])
        features = _trailing_features(bars)
        # Seed bar 0's SMA with a value that only bar 1 could produce.
        features[0]["close_sma_3"] = Decimal("101")
        verdict = check_trailing_features_lookahead(
            bars, features, sma_windows=(3,), return_periods=(1,)
        )
        assert not verdict.passed
        assert "close_sma_3" in verdict.reason

    def test_future_return_seeded_fails(self) -> None:
        bars = _bars(["100", "101", "102", "103"])
        features = _trailing_features(bars)
        features[1]["return_1"] = Decimal("0.05")  # 102/101-1, uses bar 2
        verdict = check_trailing_features_lookahead(
            bars, features, sma_windows=(3,), return_periods=(1,)
        )
        assert not verdict.passed
        assert "return_1" in verdict.reason

    def test_missing_trailing_value_fails(self) -> None:
        bars = _bars(["100", "101", "102", "103"])
        features = _trailing_features(bars)
        features[2]["close_sma_3"] = Decimal("101.5")  # wrong trailing math
        verdict = check_trailing_features_lookahead(
            bars, features, sma_windows=(3,), return_periods=(1,)
        )
        assert not verdict.passed


class TestTrainTestOverlap:
    def test_disjoint_windows_pass(self) -> None:
        train = _bars(["100", "101", "102"])
        test = _bars(
            ["103", "104", "105"],
            start=train[-1].timestamp + timedelta(days=1),
        )
        verdict = check_train_test_disjoint(train, test)
        assert verdict.gate_id == "train_test_overlap"
        assert verdict.passed

    def test_shared_timestamp_fails(self) -> None:
        train = _bars(["100", "101", "102"])
        test = _bars(["102", "103", "104"])
        verdict = check_train_test_disjoint(train, test)
        assert not verdict.passed
        assert "share timestamp" in verdict.reason

    def test_test_before_train_end_fails(self) -> None:
        train = _bars(["100", "101", "102"])
        test = _bars(["101.5", "103", "104"])
        verdict = check_train_test_disjoint(train, test)
        assert not verdict.passed


class TestTargetLeakage:
    def test_signals_on_bar_timeline_pass(self) -> None:
        bars = _bars(["100", "101", "102"])
        signals = [
            Signal(
                signal_id=f"sig_{index}",
                strategy_id="s1",
                symbol="SPY",
                timestamp=bar.timestamp,
                direction="long",
                confidence=0.5,
                horizon="1d",
                rationale="test",
            )
            for index, bar in enumerate(bars)
        ]
        verdict = check_signals_within_bars(signals, bars)
        assert verdict.gate_id == "target_leakage"
        assert verdict.passed

    def test_future_dated_signal_fails(self) -> None:
        bars = _bars(["100", "101", "102"])
        signal = Signal(
            signal_id="sig_future",
            strategy_id="s1",
            symbol="SPY",
            timestamp=bars[-1].timestamp + timedelta(days=30),
            direction="long",
            confidence=0.5,
            horizon="1d",
            rationale="leaked",
        )
        verdict = check_signals_within_bars([signal], bars)
        assert not verdict.passed
        assert "not a bar timestamp" in verdict.reason

    def test_synthetic_timestamp_fails(self) -> None:
        bars = _bars(["100", "101", "102"])
        signal = Signal(
            signal_id="sig_synthetic",
            strategy_id="s1",
            symbol="SPY",
            timestamp=bars[1].timestamp + timedelta(minutes=1),
            direction="short",
            confidence=0.5,
            horizon="1d",
            rationale="synthetic",
        )
        verdict = check_signals_within_bars([signal], bars)
        assert not verdict.passed


class TestLeakageReport:
    def test_clean_fixture_passes_all_gates(self) -> None:
        bars = _bars(["100", "101", "102", "103", "104"])
        report = run_leakage_gates(
            bars=bars,
            feature_rows=_trailing_features(bars),
            sma_windows=(3,),
            return_periods=(1,),
            declared_version=VERSION,
            train_bars=bars[:3],
            test_bars=bars[3:],
            signals=[],
        )
        assert isinstance(report, LeakageReport)
        assert report.passed
        assert len(report.verdicts) == 5

    def test_any_failure_fails_the_report(self) -> None:
        bars = _bars(["100", "101", "102"])
        features = _trailing_features(bars)
        features[1]["return_1"] = Decimal("9.99")
        report = run_leakage_gates(
            bars=bars,
            feature_rows=features,
            sma_windows=(3,),
            return_periods=(1,),
            declared_version=VERSION,
        )
        assert not report.passed
        failed = [v for v in report.verdicts if not v.passed]
        assert len(failed) == 1
        assert failed[0].gate_id == "seeded_lookahead"

    def test_repeated_runs_are_identical(self) -> None:
        bars = _bars(["100", "101", "102", "103"])
        first = run_leakage_gates(
            bars=bars,
            feature_rows=_trailing_features(bars),
            sma_windows=(3,),
            return_periods=(1,),
            declared_version=VERSION,
        )
        second = run_leakage_gates(
            bars=bars,
            feature_rows=_trailing_features(bars),
            sma_windows=(3,),
            return_periods=(1,),
            declared_version=VERSION,
        )
        assert first.model_dump() == second.model_dump()
