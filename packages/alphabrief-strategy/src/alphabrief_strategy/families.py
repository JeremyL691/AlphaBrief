"""Category-aware deterministic strategy families (M12-W02).

Each family is a frozen, pure function of its declared inputs: it reads
only bar fields and the feature keys it declares, and identical inputs
always produce identical signals. A missing declared feature produces
an explicit ``insufficient data`` flat outcome instead of a guess.

Families emit :class:`Signal` evidence only — never orders. Predictive
or learned outputs (Kronos/Gym) are handled by :mod:`admission` and are
never executable strategies (REQ-STRAT-007).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Literal

from alphabrief_core import Bar, Signal, SignalDirection

from alphabrief_strategy.interface import StrategyInput, StrategyOutput

#: OANDA instrument categories (M04-W04 taxonomy). Mirrored here so the
#: strategy runtime never imports broker code; parity with
#: ``alphabrief_execution.broker.oanda.taxonomy.InstrumentCategory`` is
#: enforced by tests/test_strategy_builtins.py.
StrategyInstrumentCategory = Literal[
    "CURRENCY",
    "METAL",
    "INDEX_CFD",
    "COMMODITY_CFD",
    "BOND_CFD",
    "EQUITY_CFD",
    "CRYPTO_CFD",
    "OTHER_CFD",
]

_ALL_CATEGORIES: frozenset[str] = frozenset(
    {
        "CURRENCY",
        "METAL",
        "INDEX_CFD",
        "COMMODITY_CFD",
        "BOND_CFD",
        "EQUITY_CFD",
        "CRYPTO_CFD",
        "OTHER_CFD",
    }
)


@dataclass(frozen=True)
class StrategyFamily:
    """Base for deterministic category-aware strategy families."""

    confidence: float = 0.6
    horizon: str = "1d"

    family_id: ClassVar[str]
    applicable_categories: ClassVar[frozenset[str]]

    def required_features(self) -> frozenset[str]:
        """The declared feature keys this family reads (empty = none)."""
        raise NotImplementedError

    def _outcome(
        self,
        bar: Bar,
        values: Mapping[str, Decimal | None],
    ) -> tuple[SignalDirection, str]:
        raise NotImplementedError

    def generate(self, strategy_input: StrategyInput) -> StrategyOutput:
        """Generate one advisory signal per bar from declared inputs."""
        signals: list[Signal] = []
        for bar, feature_row in zip(
            strategy_input.bars, strategy_input.features, strict=True
        ):
            direction, rationale = self._outcome(bar, feature_row.values)
            signals.append(
                Signal(
                    signal_id=(
                        f"{strategy_input.spec.strategy_id}:"
                        f"{bar.timestamp.isoformat()}"
                    ),
                    strategy_id=strategy_input.spec.strategy_id,
                    symbol=bar.symbol,
                    timestamp=bar.timestamp,
                    direction=direction,
                    confidence=self.confidence,
                    horizon=self.horizon,
                    rationale=rationale,
                )
            )
        return StrategyOutput(signals=signals)


@dataclass(frozen=True)
class TrendFamily(StrategyFamily):
    """Trend: long above, short below the trailing close SMA."""

    family_id: ClassVar[str] = "trend"
    applicable_categories: ClassVar[frozenset[str]] = _ALL_CATEGORIES - {
        "OTHER_CFD"
    }

    sma_window: int = 20

    def required_features(self) -> frozenset[str]:
        return frozenset({f"close_sma_{self.sma_window}"})

    def _outcome(
        self,
        bar: Bar,
        values: Mapping[str, Decimal | None],
    ) -> tuple[SignalDirection, str]:
        key = f"close_sma_{self.sma_window}"
        sma_value = values.get(key)
        if sma_value is None:
            return "flat", f"insufficient data: {key} unavailable"
        if bar.close > sma_value:
            return "long", f"close is above {key}"
        if bar.close < sma_value:
            return "short", f"close is below {key}"
        return "flat", f"close equals {key}"


@dataclass(frozen=True)
class MeanReversionFamily(StrategyFamily):
    """Mean reversion: long oversold, short overbought RSI."""

    family_id: ClassVar[str] = "mean_reversion"
    applicable_categories: ClassVar[frozenset[str]] = frozenset(
        {"CURRENCY", "METAL", "INDEX_CFD", "COMMODITY_CFD", "EQUITY_CFD"}
    )

    rsi_period: int = 14
    oversold: Decimal = Decimal("30")
    overbought: Decimal = Decimal("70")

    def required_features(self) -> frozenset[str]:
        return frozenset({f"rsi_{self.rsi_period}"})

    def _outcome(
        self,
        bar: Bar,
        values: Mapping[str, Decimal | None],
    ) -> tuple[SignalDirection, str]:
        key = f"rsi_{self.rsi_period}"
        rsi_value = values.get(key)
        if rsi_value is None:
            return "flat", f"insufficient data: {key} unavailable"
        if rsi_value <= self.oversold:
            return "long", f"{key} {rsi_value} is oversold (<= {self.oversold})"
        if rsi_value >= self.overbought:
            return "short", f"{key} {rsi_value} is overbought (>= {self.overbought})"
        return "flat", f"{key} {rsi_value} is inside the mean-reversion band"


@dataclass(frozen=True)
class BreakoutFamily(StrategyFamily):
    """Breakout: long above the upper band, short below the lower band."""

    family_id: ClassVar[str] = "breakout"
    applicable_categories: ClassVar[frozenset[str]] = frozenset(
        {"CURRENCY", "METAL", "INDEX_CFD", "COMMODITY_CFD", "CRYPTO_CFD"}
    )

    bb_period: int = 20

    def required_features(self) -> frozenset[str]:
        return frozenset(
            {f"bb_upper_{self.bb_period}", f"bb_lower_{self.bb_period}"}
        )

    def _outcome(
        self,
        bar: Bar,
        values: Mapping[str, Decimal | None],
    ) -> tuple[SignalDirection, str]:
        upper_key = f"bb_upper_{self.bb_period}"
        lower_key = f"bb_lower_{self.bb_period}"
        upper = values.get(upper_key)
        lower = values.get(lower_key)
        if upper is None or lower is None:
            return (
                "flat",
                f"insufficient data: {upper_key} or {lower_key} unavailable",
            )
        if bar.close > upper:
            return "long", f"close is above {upper_key}"
        if bar.close < lower:
            return "short", f"close is below {lower_key}"
        return "flat", "close is inside the breakout bands"


@dataclass(frozen=True)
class VolatilityRegimeFamily(StrategyFamily):
    """Volatility regime: flat in high volatility, trend otherwise."""

    family_id: ClassVar[str] = "volatility_regime"
    applicable_categories: ClassVar[frozenset[str]] = frozenset(
        {"CURRENCY", "METAL", "INDEX_CFD", "COMMODITY_CFD", "EQUITY_CFD"}
    )

    sma_window: int = 20
    atr_period: int = 14
    high_vol_atr_pct: Decimal = Decimal("0.02")

    def required_features(self) -> frozenset[str]:
        return frozenset(
            {f"close_sma_{self.sma_window}", f"atr_{self.atr_period}"}
        )

    def _outcome(
        self,
        bar: Bar,
        values: Mapping[str, Decimal | None],
    ) -> tuple[SignalDirection, str]:
        sma_key = f"close_sma_{self.sma_window}"
        atr_key = f"atr_{self.atr_period}"
        sma_value = values.get(sma_key)
        atr_value = values.get(atr_key)
        if sma_value is None or atr_value is None:
            return (
                "flat",
                f"insufficient data: {sma_key} or {atr_key} unavailable",
            )
        if bar.close <= 0:
            return "flat", "insufficient data: non-positive close"
        atr_pct = atr_value / bar.close
        if atr_pct >= self.high_vol_atr_pct:
            return (
                "flat",
                f"high volatility regime (atr is {atr_pct:.4f} of close)",
            )
        if bar.close > sma_value:
            return "long", f"normal regime, close is above {sma_key}"
        if bar.close < sma_value:
            return "short", f"normal regime, close is below {sma_key}"
        return "flat", f"normal regime, close equals {sma_key}"


@dataclass(frozen=True)
class NoTradeFamily(StrategyFamily):
    """First-class no-trade benchmark: always flat, no declared inputs."""

    family_id: ClassVar[str] = "no_trade"
    applicable_categories: ClassVar[frozenset[str]] = _ALL_CATEGORIES
    confidence: float = 1.0

    def required_features(self) -> frozenset[str]:
        return frozenset()

    def _outcome(
        self,
        bar: Bar,
        values: Mapping[str, Decimal | None],
    ) -> tuple[SignalDirection, str]:
        return "flat", "no-trade benchmark: no position"


#: Canonical family-id -> applicable OANDA instrument categories.
FAMILY_APPLICABILITY: dict[str, frozenset[str]] = {
    TrendFamily.family_id: TrendFamily.applicable_categories,
    MeanReversionFamily.family_id: MeanReversionFamily.applicable_categories,
    BreakoutFamily.family_id: BreakoutFamily.applicable_categories,
    VolatilityRegimeFamily.family_id: VolatilityRegimeFamily.applicable_categories,
    NoTradeFamily.family_id: NoTradeFamily.applicable_categories,
}


__all__ = [
    "FAMILY_APPLICABILITY",
    "BreakoutFamily",
    "MeanReversionFamily",
    "NoTradeFamily",
    "StrategyFamily",
    "StrategyInstrumentCategory",
    "TrendFamily",
    "VolatilityRegimeFamily",
]
