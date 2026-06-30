"""Validated, paper-only execution policy configuration.

The policy is a reviewed operating boundary for future external paper
execution. It contains no credentials, does not call provider APIs, and does
not authorize orders by itself.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PaperOrderType = Literal["market", "limit"]
PaperProvider = Literal["alpaca_paper", "oanda_paper"]
PaperMarket = Literal["us_equity", "fx", "multi_asset"]
TradingDay = Literal["mon", "tue", "wed", "thu", "fri"]


class PaperExecutionPolicy(BaseModel):
    """A strict operating boundary for AlphaBrief paper execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["paper"]
    provider: PaperProvider
    market: PaperMarket
    symbols: tuple[str, ...] = Field(min_length=1)
    order_types: tuple[PaperOrderType, ...] = Field(min_length=1)
    timezone: Literal["America/New_York"]
    trading_days: tuple[TradingDay, ...] = Field(min_length=1)
    session_start: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    session_end: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    max_order_notional: Decimal = Field(gt=0)
    max_total_exposure: Decimal = Field(gt=0)
    require_human_review: bool
    automated_execution: Literal[False]

    @field_validator("symbols")
    @classmethod
    def symbols_must_be_unique_and_nonblank(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        normalized = tuple(symbol.strip().upper() for symbol in value)
        if any(not symbol for symbol in normalized):
            raise ValueError("symbols must not contain blank values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("symbols must be unique")
        return normalized

    @field_validator("trading_days")
    @classmethod
    def trading_days_must_be_unique(
        cls, value: tuple[TradingDay, ...]
    ) -> tuple[TradingDay, ...]:
        if len(set(value)) != len(value):
            raise ValueError("trading_days must be unique")
        return value

    @field_validator("max_order_notional", "max_total_exposure", mode="before")
    @classmethod
    def decimal_values_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("execution-policy decimal values must not be floats")
        return value

    @model_validator(mode="after")
    def session_and_exposure_must_be_valid(self) -> PaperExecutionPolicy:
        if self.session_start >= self.session_end:
            raise ValueError("session_start must be earlier than session_end")
        if self.max_total_exposure < self.max_order_notional:
            raise ValueError(
                "max_total_exposure must be at least max_order_notional"
            )
        return self


def load_paper_execution_policy(path: Path | str) -> PaperExecutionPolicy:
    """Load one strict, paper-only execution policy from a YAML file.

    A relative path is resolved against the discovered project root
    (the first ancestor containing ``pyproject.toml``), so the loader
    keeps working when the caller runs from a different working
    directory. Absolute paths are used verbatim.
    """

    policy_path = _resolve_policy_path(Path(path))
    try:
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except OSError as exc:
        message = f"unable to read execution policy {policy_path}: {exc}"
        raise ValueError(message) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML execution policy {policy_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("execution policy must be a YAML mapping")
    return PaperExecutionPolicy.model_validate(raw)


def _resolve_policy_path(path: Path) -> Path:
    """Resolve a relative policy path against the discovered project root.

    Discovery walks up from both ``Path.cwd()`` and ``__file__`` for the
    first ancestor that contains ``pyproject.toml``. This works whether
    the operator runs from the project root, from a sub-directory, or
    from outside the checkout (e.g. via an editable install).
    """

    if path.is_absolute():
        return path
    parents = (*Path.cwd().parents, *Path(__file__).resolve().parents)
    for directory in (Path.cwd(), *parents):
        if (directory / "pyproject.toml").is_file():
            return directory / path
    return path


__all__ = [
    "PaperExecutionPolicy",
    "PaperProvider",
    "PaperMarket",
    "PaperOrderType",
    "TradingDay",
    "load_paper_execution_policy",
]
