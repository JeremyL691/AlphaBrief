"""Automated data-leakage and lookahead gates (M12-W06).

Each gate is a pure function over declared inputs and returns a
deterministic :class:`LeakageVerdict`. A gate never silently passes:
seeded lookahead, revised future data, target leakage, train/test
overlap, and timestamp-boundary violations each fail with an explicit
reason (REQ-STRAT-006).
"""

from __future__ import annotations

from decimal import Decimal

from alphabrief_core import Bar, Signal
from pydantic import BaseModel, ConfigDict, Field


class LeakageVerdict(BaseModel):
    """One deterministic leakage-gate verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str = Field(min_length=1)
    passed: bool
    reason: str = Field(min_length=1)
    detail: str | None = None


class LeakageReport(BaseModel):
    """The aggregate result of every automated leakage gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdicts: tuple[LeakageVerdict, ...]
    passed: bool


def check_chronological_bars(bars: list[Bar]) -> LeakageVerdict:
    """Fail on any timestamp-boundary violation (non-increasing bars)."""
    for previous, current in zip(bars, bars[1:], strict=False):
        if current.timestamp <= previous.timestamp:
            return LeakageVerdict(
                gate_id="timestamp_boundary",
                passed=False,
                reason=(
                    "bars are not strictly chronological: "
                    f"{current.timestamp.isoformat()} follows "
                    f"{previous.timestamp.isoformat()}"
                ),
                detail=f"bar index {bars.index(current)}",
            )
    return LeakageVerdict(
        gate_id="timestamp_boundary",
        passed=True,
        reason="bars are strictly chronological",
    )


def check_declared_data_version(
    bars: list[Bar], declared_version: str
) -> LeakageVerdict:
    """Fail on any bar carrying a different (revised) data version."""
    for bar in bars:
        if bar.data_version != declared_version:
            return LeakageVerdict(
                gate_id="revised_future_data",
                passed=False,
                reason=(
                    f"bar {bar.timestamp.isoformat()} carries data version "
                    f"{bar.data_version!r}, not the declared immutable "
                    f"version {declared_version!r}"
                ),
            )
    return LeakageVerdict(
        gate_id="revised_future_data",
        passed=True,
        reason="every bar carries the declared immutable data version",
    )


def _trailing_average(
    values: list[Decimal], *, index: int, window: int
) -> Decimal | None:
    start_index = index - window + 1
    if start_index < 0:
        return None
    window_values = values[start_index : index + 1]
    return sum(window_values, Decimal("0")) / Decimal(window)


def _trailing_return(
    bars: list[Bar], *, index: int, period: int
) -> Decimal | None:
    previous_index = index - period
    if previous_index < 0:
        return None
    previous_close = bars[previous_index].close
    if previous_close == 0:
        return None
    return (bars[index].close - previous_close) / previous_close


def check_trailing_features_lookahead(
    bars: list[Bar],
    feature_rows: list[dict[str, Decimal | None]],
    *,
    sma_windows: tuple[int, ...],
    return_periods: tuple[int, ...],
) -> LeakageVerdict:
    """Fail when any trailing feature at bar ``i`` uses later bars.

    Every ``close_sma_W`` / ``volume_sma_W`` / ``return_P`` value at
    index ``i`` is recomputed from bars ``[: i + 1]`` only and compared
    with the provided value; any mismatch is a seeded lookahead.
    """
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]

    for index, values in enumerate(feature_rows):
        for window in sma_windows:
            key = f"close_sma_{window}"
            if key in values:
                expected = _trailing_average(closes, index=index, window=window)
                if values[key] != expected:
                    return LeakageVerdict(
                        gate_id="seeded_lookahead",
                        passed=False,
                        reason=(
                            f"{key} at bar index {index} is "
                            f"{values[key]!r} but trailing bars [: {index + 1}] "
                            f"produce {expected!r}"
                        ),
                    )
            key = f"volume_sma_{window}"
            if key in values:
                expected = _trailing_average(volumes, index=index, window=window)
                if values[key] != expected:
                    return LeakageVerdict(
                        gate_id="seeded_lookahead",
                        passed=False,
                        reason=(
                            f"{key} at bar index {index} is "
                            f"{values[key]!r} but trailing bars [: {index + 1}] "
                            f"produce {expected!r}"
                        ),
                    )
        for period in return_periods:
            key = f"return_{period}"
            if key in values:
                expected = _trailing_return(bars, index=index, period=period)
                if values[key] != expected:
                    return LeakageVerdict(
                        gate_id="seeded_lookahead",
                        passed=False,
                        reason=(
                            f"{key} at bar index {index} is "
                            f"{values[key]!r} but trailing bars [: {index + 1}] "
                            f"produce {expected!r}"
                        ),
                    )
    return LeakageVerdict(
        gate_id="seeded_lookahead",
        passed=True,
        reason="every trailing feature is computed from its own past only",
    )


def check_train_test_disjoint(
    train_bars: list[Bar], test_bars: list[Bar]
) -> LeakageVerdict:
    """Fail when train and test windows overlap or share timestamps."""
    train_timestamps = {bar.timestamp for bar in train_bars}
    test_timestamps = {bar.timestamp for bar in test_bars}
    shared = train_timestamps & test_timestamps
    if shared:
        sample = sorted(shared)[0]
        return LeakageVerdict(
            gate_id="train_test_overlap",
            passed=False,
            reason=f"train and test share timestamp {sample.isoformat()}",
        )
    if train_bars and test_bars:
        if test_bars[0].timestamp <= train_bars[-1].timestamp:
            return LeakageVerdict(
                gate_id="train_test_overlap",
                passed=False,
                reason=(
                    "test window starts at "
                    f"{test_bars[0].timestamp.isoformat()} which is not "
                    "after the train window end "
                    f"{train_bars[-1].timestamp.isoformat()}"
                ),
            )
    return LeakageVerdict(
        gate_id="train_test_overlap",
        passed=True,
        reason="train and test windows are disjoint and ordered",
    )


def check_signals_within_bars(
    signals: list[Signal], bars: list[Bar]
) -> LeakageVerdict:
    """Fail on any signal timestamp outside the bar timeline.

    A signal dated after the last bar (or missing from the bar
    timeline) would leak future or synthetic information into the
    decision (target leakage).
    """
    bar_timestamps = {bar.timestamp for bar in bars}
    for signal in signals:
        if signal.timestamp not in bar_timestamps:
            return LeakageVerdict(
                gate_id="target_leakage",
                passed=False,
                reason=(
                    f"signal {signal.signal_id!r} is dated "
                    f"{signal.timestamp.isoformat()} which is not a bar "
                    "timestamp"
                ),
            )
    return LeakageVerdict(
        gate_id="target_leakage",
        passed=True,
        reason="every signal timestamp belongs to the bar timeline",
    )


def run_leakage_gates(
    *,
    bars: list[Bar],
    feature_rows: list[dict[str, Decimal | None]],
    sma_windows: tuple[int, ...],
    return_periods: tuple[int, ...],
    declared_version: str,
    train_bars: list[Bar] | None = None,
    test_bars: list[Bar] | None = None,
    signals: list[Signal] | None = None,
) -> LeakageReport:
    """Run every applicable leakage gate and aggregate the verdicts."""
    verdicts = [
        check_chronological_bars(bars),
        check_declared_data_version(bars, declared_version),
        check_trailing_features_lookahead(
            bars,
            feature_rows,
            sma_windows=sma_windows,
            return_periods=return_periods,
        ),
    ]
    if train_bars is not None and test_bars is not None:
        verdicts.append(check_train_test_disjoint(train_bars, test_bars))
    if signals is not None:
        verdicts.append(check_signals_within_bars(signals, bars))
    return LeakageReport(
        verdicts=tuple(verdicts),
        passed=all(verdict.passed for verdict in verdicts),
    )


__all__ = [
    "LeakageReport",
    "LeakageVerdict",
    "check_chronological_bars",
    "check_declared_data_version",
    "check_signals_within_bars",
    "check_trailing_features_lookahead",
    "check_train_test_disjoint",
    "run_leakage_gates",
]
