"""Multi-asset continuous-action trading environment (Phase 11)."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from alphabrief_core import Bar
from alphabrief_data import check_bar_quality
from pydantic import Field, field_validator

from alphabrief_gym.env import TradingEnvError
from alphabrief_gym.market_impact import LinearImpact, MarketImpactModel
from alphabrief_gym.rewards import (
    ReturnReward,
    RewardContext,
    RewardFunction,
)
from alphabrief_gym.schemas import (
    AlphaBriefEnvModel,
    AssetObservation,
    EpisodeMetricsV2,
    MultiAssetObservation,
    PortfolioSnapshot,
    bars_by_symbol,
)

BPS_DENOMINATOR = Decimal("10000")
DAYS_PER_YEAR = Decimal("365")


class AlphaBriefTradingEnvConfig(AlphaBriefEnvModel):
    """Configuration for the multi-asset environment."""

    initial_cash: Decimal = Field(default=Decimal("10000"))
    max_leverage: Decimal = Field(default=Decimal("1"))
    allow_short: bool = False
    borrow_cost_annual: Decimal = Field(default=Decimal("0"))
    margin_rate: Decimal = Field(default=Decimal("0.5"))
    fee_bps: Decimal = Field(default=Decimal("0"))
    slippage_bps: Decimal = Field(default=Decimal("0"))
    liquidity_limit_per_step: Decimal = Field(default=Decimal("0"))
    max_history_steps: int = Field(default=64, ge=0)

    @field_validator(
        "initial_cash", "max_leverage", "borrow_cost_annual", "margin_rate",
        "fee_bps", "slippage_bps", "liquidity_limit_per_step", mode="before",
    )
    @classmethod
    def _decimals_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("decimal fields must not be provided as float")
        return value


class StepResultV2(AlphaBriefEnvModel):
    """Step result for the multi-asset environment."""

    observation: MultiAssetObservation
    reward: Decimal
    terminated: bool
    truncated: bool
    info: dict[str, Decimal | int | str]

    @field_validator("reward", mode="before")
    @classmethod
    def _decimal_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("reward must not be provided as float")
        return value


def _require_positive(value: Decimal, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be > 0")


class AlphaBriefTradingEnvV2:
    """Multi-asset continuous-action trading environment."""

    def __init__(
        self,
        bars: list[Bar],
        *,
        config: AlphaBriefTradingEnvConfig | None = None,
        reward_function: RewardFunction | None = None,
        market_impact: MarketImpactModel | None = None,
    ) -> None:
        if len(bars) < 2:
            raise ValueError("at least two bars are required across assets")
        grouped_for_qc = bars_by_symbol(bars)
        for symbol, group in grouped_for_qc.items():
            quality = check_bar_quality(group)
            if not quality.passed:
                raise ValueError(
                    f"bars for symbol {symbol!r} failed quality checks"
                )

        self._config = config or AlphaBriefTradingEnvConfig()
        if self._config.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self._config.max_leverage <= 0:
            raise ValueError("max_leverage must be > 0")
        if self._config.margin_rate <= 0:
            raise ValueError("margin_rate must be > 0")
        if self._config.fee_bps < 0:
            raise ValueError("fee_bps must be >= 0")
        if self._config.slippage_bps < 0:
            raise ValueError("slippage_bps must be >= 0")
        if self._config.liquidity_limit_per_step < 0:
            raise ValueError("liquidity_limit_per_step must be >= 0")
        if self._config.borrow_cost_annual < 0:
            raise ValueError("borrow_cost_annual must be >= 0")

        self._bars_by_symbol = bars_by_symbol(bars)
        self._assets = sorted(self._bars_by_symbol.keys())
        if not self._assets:
            raise ValueError("at least one asset is required")
        if not self._all_assets_have_equal_length():
            raise ValueError("all assets must have the same number of bars")
        self._num_steps = len(self._bars_by_symbol[self._assets[0]])
        if self._num_steps < 2:
            raise ValueError("at least two bars are required per asset")

        self._reward_function: RewardFunction = reward_function or ReturnReward()
        self._market_impact: MarketImpactModel = market_impact or LinearImpact()
        self.reset()

    def _all_assets_have_equal_length(self) -> bool:
        lengths = [len(group) for group in self._bars_by_symbol.values()]
        return len(set(lengths)) == 1 and lengths[0] >= 2

    @property
    def assets(self) -> list[str]:
        return list(self._assets)

    @property
    def config(self) -> AlphaBriefTradingEnvConfig:
        return self._config

    def reset(self) -> MultiAssetObservation:
        self._current_index = 0
        self._cash = self._config.initial_cash
        self._positions = {asset: Decimal("0") for asset in self._assets}
        self._borrow_notional = {asset: Decimal("0") for asset in self._assets}
        self._trades = 0
        self._slippage_cost = Decimal("0")
        self._market_impact_cost = Decimal("0")
        self._borrow_cost = Decimal("0")
        self._realized_pnl = Decimal("0")
        self._terminated = False
        self._portfolio_history: list[Decimal] = [
            self._portfolio_value(self._current_bar(0)),
        ]
        self._returns_history: deque[Decimal] = deque(
            maxlen=self._config.max_history_steps,
        )
        return self._observation()

    def step(self, action: Mapping[str, Decimal]) -> StepResultV2:
        if self._terminated:
            raise TradingEnvError("episode is already terminated")
        self._validate_action(action)

        current_bar = self._current_bar(self._current_index)
        next_index = self._current_index + 1
        next_bar = self._current_bar(next_index)
        portfolio_value_before = self._portfolio_value(current_bar)
        self._apply_action(action, current_bar)
        portfolio_value_after = self._portfolio_value(next_bar)
        pnl_change = portfolio_value_after - portfolio_value_before

        if self._config.borrow_cost_annual > 0:
            self._accrue_borrow_cost()
        self._current_index = next_index
        self._portfolio_history.append(portfolio_value_after)

        ret = (
            pnl_change / portfolio_value_before
            if portfolio_value_before != 0
            else Decimal("0")
        )
        if self._config.max_history_steps > 0:
            self._returns_history.append(ret)
        reward = self._reward_function.compute(
            RewardContext(
                pnl_change=pnl_change,
                portfolio_value_before=portfolio_value_before,
                portfolio_value_after=portfolio_value_after,
                recent_returns=list(self._returns_history),
            )
        )

        terminated = self._current_index == self._num_steps - 1
        self._terminated = terminated

        return StepResultV2(
            observation=self._observation(),
            reward=reward,
            terminated=terminated,
            truncated=False,
            info={
                "portfolio_value": portfolio_value_after,
                "cash": self._cash,
                "leverage": self._leverage(portfolio_value_after),
                "borrow_cost_accrued": self._borrow_cost,
                "slippage_cost": self._slippage_cost,
                "market_impact_cost": self._market_impact_cost,
                "trades": self._trades,
            },
        )

    def metrics(self) -> EpisodeMetricsV2:
        if not self._portfolio_history:
            return EpisodeMetricsV2(
                initial_value=self._config.initial_cash,
                final_value=self._config.initial_cash,
                total_return=Decimal("0"),
                max_drawdown=Decimal("0"),
                steps=0,
                trades=0,
                slippage_cost=Decimal("0"),
                market_impact_cost=Decimal("0"),
                borrow_cost=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
        initial = self._portfolio_history[0]
        final = self._portfolio_history[-1]
        return EpisodeMetricsV2(
            initial_value=initial,
            final_value=final,
            total_return=(
                (final - initial) / initial if initial != 0 else Decimal("0")
            ),
            max_drawdown=_max_drawdown(self._portfolio_history),
            steps=len(self._portfolio_history) - 1,
            trades=self._trades,
            slippage_cost=self._slippage_cost,
            market_impact_cost=self._market_impact_cost,
            borrow_cost=self._borrow_cost,
            realized_pnl=self._realized_pnl,
        )

    def _current_bar(self, index: int) -> dict[str, Bar]:
        return {
            asset: group[index]
            for asset, group in self._bars_by_symbol.items()
        }

    def _observation(self) -> MultiAssetObservation:
        bars = self._current_bar(self._current_index)
        assets: dict[str, AssetObservation] = {}
        for asset, bar in bars.items():
            assets[asset] = AssetObservation(
                symbol=asset,
                timestamp=bar.timestamp,
                close=bar.close,
                position_quantity=self._positions[asset],
            )
        portfolio_value = self._portfolio_value(bars)
        portfolio = PortfolioSnapshot(
            cash=self._cash,
            positions=dict(self._positions),
            portfolio_value=portfolio_value,
            leverage=self._leverage(portfolio_value),
            borrow_cost_accrued=self._borrow_cost,
        )
        return MultiAssetObservation(
            step_index=self._current_index,
            timestamp=bars[self._assets[0]].timestamp,
            assets=assets,
            portfolio=portfolio,
        )

    def _portfolio_value(self, bars: Mapping[str, Bar]) -> Decimal:
        equity = self._cash
        for asset, quantity in self._positions.items():
            equity += quantity * bars[asset].close
        return equity

    def _leverage(self, portfolio_value: Decimal) -> Decimal:
        if portfolio_value <= 0:
            return Decimal("0")
        gross_exposure = sum(
            abs(quantity) * self._bars_by_symbol[asset][
                min(self._current_index, len(self._bars_by_symbol[asset]) - 1)
            ].close
            for asset, quantity in self._positions.items()
        )
        return gross_exposure / portfolio_value

    def _validate_action(self, action: Mapping[str, Decimal]) -> None:
        if set(action.keys()) != set(self._assets):
            missing = set(self._assets) - set(action.keys())
            extra = set(action.keys()) - set(self._assets)
            msg: list[str] = []
            if missing:
                msg.append(f"missing targets: {sorted(missing)}")
            if extra:
                msg.append(f"unexpected targets: {sorted(extra)}")
            raise ValueError("; ".join(msg))
        bounds = abs(self._config.max_leverage)
        for asset, raw in action.items():
            value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
            if value.copy_abs() > bounds:
                raise ValueError(
                    f"target weight for {asset!r} ({value}) exceeds "
                    f"max_leverage {self._config.max_leverage}"
                )
            if not self._config.allow_short and value < 0:
                raise ValueError(
                    f"short not allowed; target for {asset!r} is negative"
                )

    def _apply_action(
        self,
        action: Mapping[str, Decimal],
        current_bars: Mapping[str, Bar],
    ) -> None:
        portfolio_value = self._portfolio_value(current_bars)
        for asset, raw in action.items():
            target_weight = (
                raw if isinstance(raw, Decimal) else Decimal(str(raw))
            )
            current_price = current_bars[asset].close
            target_position_value = portfolio_value * target_weight
            current_position_value = (
                self._positions[asset] * current_price
            )
            delta_value = target_position_value - current_position_value
            if delta_value == 0:
                continue
            side = "buy" if delta_value > 0 else "sell"
            trade_value = abs(delta_value)
            trade_value = self._apply_liquidity_limit(trade_value)
            if trade_value <= 0:
                continue
            execution_price = self._execution_price(
                asset, current_price, side, trade_value
            )
            quantity = trade_value / execution_price
            if quantity <= 0:
                continue
            fee = trade_value * (self._config.fee_bps / BPS_DENOMINATOR)
            if side == "buy":
                if self._cash < trade_value + fee:
                    quantity = max(Decimal("0"), (self._cash - fee) / execution_price)
                    trade_value = quantity * execution_price
                    if trade_value <= 0:
                        continue
                self._cash -= trade_value + fee
                self._positions[asset] += quantity
                self._trades += 1
            else:
                if not self._config.allow_short and self._positions[asset] < quantity:
                    quantity = self._positions[asset]
                    trade_value = quantity * execution_price
                if quantity <= 0:
                    continue
                self._cash += trade_value - fee
                self._positions[asset] -= quantity
                self._trades += 1
            self._slippage_cost += trade_value * (
                self._config.slippage_bps / BPS_DENOMINATOR
            )

    def _apply_liquidity_limit(self, trade_value: Decimal) -> Decimal:
        limit = self._config.liquidity_limit_per_step
        if limit > 0 and trade_value > limit:
            return limit
        return trade_value

    def _execution_price(
        self,
        asset: str,
        reference_price: Decimal,
        side: str,
        trade_value: Decimal,
    ) -> Decimal:
        slip = self._config.slippage_bps / BPS_DENOMINATOR
        base = reference_price * (
            Decimal("1") + slip if side == "buy" else Decimal("1") - slip
        )
        impact = self._market_impact.estimate_impact(
            trade_value=trade_value,
            adv=reference_price,
            side=side,
        )
        if impact > 0:
            self._market_impact_cost += trade_value * impact
        return base * (Decimal("1") + impact)

    def _accrue_borrow_cost(self) -> None:
        if self._config.borrow_cost_annual == 0:
            return
        daily_rate = self._config.borrow_cost_annual / DAYS_PER_YEAR
        total_borrow = sum(
            -qty for qty in self._positions.values() if qty < 0
        )
        if total_borrow <= 0:
            return
        cost = total_borrow * daily_rate
        if cost <= 0:
            return
        self._cash -= cost
        self._borrow_cost += cost


def _max_drawdown(values: list[Decimal]) -> Decimal:
    peak = values[0]
    max_dd = Decimal("0")
    for value in values:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


__all__ = [
    "AlphaBriefTradingEnvConfig",
    "AlphaBriefTradingEnvV2",
    "StepResultV2",
]
