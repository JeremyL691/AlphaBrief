"""Gymnasium-style trading environment for AlphaBrief."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from alphabrief_core import Bar
from alphabrief_data import check_bar_quality
from pydantic import BaseModel, ConfigDict, Field, field_validator

TradingAction = Literal["hold", "buy", "sell"]
BPS_DENOMINATOR = Decimal("10000")


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("decimal fields must not be provided as float values")
    return value


class TradingEnvError(ValueError):
    """Raised when the trading environment cannot perform a transition."""


class TradingObservation(BaseModel):
    """Observation returned by AlphaBriefTradingEnv."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_index: int = Field(ge=0)
    symbol: str = Field(min_length=1)
    timestamp: datetime
    close: Decimal
    cash: Decimal
    position_quantity: Decimal
    portfolio_value: Decimal

    @field_validator(
        "close",
        "cash",
        "position_quantity",
        "portfolio_value",
        mode="before",
    )
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class StepResult(BaseModel):
    """Gymnasium-style step result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation: TradingObservation
    reward: Decimal
    terminated: bool
    truncated: bool
    info: dict[str, Decimal | int | str]

    @field_validator("reward", mode="before")
    @classmethod
    def _reward_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class EpisodeMetrics(BaseModel):
    """Episode-level environment metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_value: Decimal
    final_value: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    steps: int = Field(ge=0)
    trades: int = Field(ge=0)


class AlphaBriefTradingEnv:
    """Minimal single-asset long/flat trading environment."""

    action_space: tuple[TradingAction, ...] = ("hold", "buy", "sell")

    def __init__(
        self,
        bars: list[Bar],
        *,
        initial_cash: Decimal = Decimal("10000"),
        trade_fraction: Decimal = Decimal("1"),
        fee_bps: Decimal = Decimal("0"),
        slippage_bps: Decimal = Decimal("0"),
    ) -> None:
        if len(bars) < 2:
            raise ValueError("at least two bars are required")
        quality = check_bar_quality(bars)
        if not quality.passed:
            raise ValueError("bars must pass data quality checks")
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if not (Decimal("0") < trade_fraction <= Decimal("1")):
            raise ValueError("trade_fraction must be between 0 and 1")
        if fee_bps < 0:
            raise ValueError("fee_bps must be non-negative")
        if slippage_bps < 0:
            raise ValueError("slippage_bps must be non-negative")

        self._bars = bars
        self.initial_cash = initial_cash
        self.trade_fraction = trade_fraction
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self._current_index = 0
        self._cash = initial_cash
        self._position_quantity = Decimal("0")
        self._equity_curve: list[Decimal] = []
        self._trades = 0
        self._terminated = False
        self.reset()

    def reset(self) -> TradingObservation:
        """Reset the episode and return the first observation."""

        self._current_index = 0
        self._cash = self.initial_cash
        self._position_quantity = Decimal("0")
        self._trades = 0
        self._terminated = False
        self._equity_curve = [self._portfolio_value(self._bars[0].close)]
        return self._observation()

    def step(self, action: TradingAction) -> StepResult:
        """Apply an action and advance one bar."""

        if action not in self.action_space:
            raise TradingEnvError(f"unsupported action: {action}")
        if self._terminated:
            raise TradingEnvError("episode is already terminated")

        current_bar = self._bars[self._current_index]
        before_value = self._portfolio_value(current_bar.close)
        self._apply_action(action, current_bar.close)

        next_index = self._current_index + 1
        next_bar = self._bars[next_index]
        after_value = self._portfolio_value(next_bar.close)
        reward = (after_value - before_value) / before_value

        self._current_index = next_index
        self._equity_curve.append(after_value)
        self._terminated = self._current_index == len(self._bars) - 1

        return StepResult(
            observation=self._observation(),
            reward=reward,
            terminated=self._terminated,
            truncated=False,
            info={
                "portfolio_value": after_value,
                "cash": self._cash,
                "position_quantity": self._position_quantity,
                "trades": self._trades,
            },
        )

    def metrics(self) -> EpisodeMetrics:
        """Return current episode metrics."""

        initial_value = self._equity_curve[0]
        final_value = self._equity_curve[-1]
        return EpisodeMetrics(
            initial_value=initial_value,
            final_value=final_value,
            total_return=(final_value - initial_value) / initial_value,
            max_drawdown=_max_drawdown(self._equity_curve),
            steps=len(self._equity_curve) - 1,
            trades=self._trades,
        )

    def _observation(self) -> TradingObservation:
        bar = self._bars[self._current_index]
        return TradingObservation(
            step_index=self._current_index,
            symbol=bar.symbol,
            timestamp=bar.timestamp,
            close=bar.close,
            cash=self._cash,
            position_quantity=self._position_quantity,
            portfolio_value=self._portfolio_value(bar.close),
        )

    def _portfolio_value(self, close_price: Decimal) -> Decimal:
        return self._cash + (self._position_quantity * close_price)

    def _apply_action(self, action: TradingAction, reference_price: Decimal) -> None:
        if action == "buy":
            self._buy(reference_price)
        elif action == "sell":
            self._sell(reference_price)

    def _buy(self, reference_price: Decimal) -> None:
        if self._cash <= 0:
            return
        fee_rate = self.fee_bps / BPS_DENOMINATOR
        slippage_rate = self.slippage_bps / BPS_DENOMINATOR
        execution_price = reference_price * (Decimal("1") + slippage_rate)
        spendable_cash = self._cash * self.trade_fraction
        quantity = spendable_cash / (execution_price * (Decimal("1") + fee_rate))
        if quantity <= 0:
            return
        gross_value = quantity * execution_price
        fee = gross_value * fee_rate
        self._cash -= gross_value + fee
        self._position_quantity += quantity
        self._trades += 1

    def _sell(self, reference_price: Decimal) -> None:
        if self._position_quantity <= 0:
            return
        fee_rate = self.fee_bps / BPS_DENOMINATOR
        slippage_rate = self.slippage_bps / BPS_DENOMINATOR
        execution_price = reference_price * (Decimal("1") - slippage_rate)
        gross_value = self._position_quantity * execution_price
        fee = gross_value * fee_rate
        self._cash += gross_value - fee
        self._position_quantity = Decimal("0")
        self._trades += 1


def _max_drawdown(values: list[Decimal]) -> Decimal:
    peak = values[0]
    max_drawdown = Decimal("0")
    for value in values:
        if value > peak:
            peak = value
        if peak > 0:
            drawdown = (peak - value) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    return max_drawdown
