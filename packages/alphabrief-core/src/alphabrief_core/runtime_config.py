"""Strict loader for the runtime section of ``config/alphabrief.yaml``.

The reviewed configuration is the operator's boundary for the unattended
runtime. Like every other reviewer-owned file it is parsed with
``extra="forbid"`` so a typo can never silently disable a safety-relevant
setting, and every numeric field validates its guide range at load time
rather than at 03:00 on the trading floor.

The values themselves live in ``config/alphabrief.yaml``; the defaults in
this module exist only so a missing file still yields the reviewed
behaviour instead of an unconfigured runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_core.policy_version import project_root

#: The reviewed configuration file, relative to the project root.
RUNTIME_CONFIG_PATH = Path("config/alphabrief.yaml")


class OpportunitySettings(BaseModel):
    """The opportunity-check cadence and its escalation guards.

    ``scan_interval_seconds`` is bounded to 60-300 because PROJECT_GUIDE
    5.1 says "every 1-5 minutes"; anything outside that range is a typo,
    not a policy choice.

    ``max_rounds_per_day`` and ``min_spacing_seconds`` bound the model
    spend: one committee round costs roughly 39 calls, the free channel
    allows 1000 per UTC day, and 15 x 39 = 585 leaves room for repair
    calls, the single-call shadow baseline and the other tasks.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scan_interval_seconds: int = Field(default=180, ge=60, le=300)
    max_rounds_per_day: int = Field(default=15, ge=1, le=100)
    min_spacing_seconds: int = Field(default=600, ge=0, le=3600)
    escalation_min_confidence: Decimal = Field(
        default=Decimal("0.60"), ge=Decimal(0), le=Decimal(1)
    )

    @field_validator("escalation_min_confidence", mode="before")
    @classmethod
    def parse_decimal(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("escalation_min_confidence must be a decimal")
        if isinstance(value, (int, float)):
            # A float would make the threshold inexact; require a string.
            raise ValueError(
                "escalation_min_confidence must be a decimal string such as '0.60'"
            )
        if isinstance(value, str):
            return Decimal(value)
        return value


class TradingSettings(BaseModel):
    """The ``trading:`` section: mode switch plus opportunity guardrails."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trading_mode: str = "off"
    opportunity: OpportunitySettings = Field(default_factory=OpportunitySettings)

    @field_validator("trading_mode", mode="before")
    @classmethod
    def validate_mode(cls, value: Any) -> str:
        """Normalize the mode, failing safe on YAML's implicit booleans.

        YAML 1.1 turns the bare words ``off``/``on``/``no``/``yes`` into
        booleans, so ``trading_mode: off`` reaches us as ``False``. Every
        spelling of "disabled" may therefore become ``"off"``. Only an
        explicit string may enable trading: an unquoted ``yes`` or
        ``true`` in a config file is far more likely to be a mistake than
        a deliberate decision to turn on order submission.
        """
        if isinstance(value, bool):
            if value is False:
                return "off"
            raise ValueError(
                "trading.trading_mode: write the enabling value as an explicit "
                'string ("on"); an implicit YAML boolean must never turn on '
                "order submission"
            )
        normalized = str(value).strip().lower()
        if normalized not in {"on", "off"}:
            raise ValueError("trading.trading_mode must be 'on' or 'off'")
        return normalized


class RuntimeSettings(BaseModel):
    """The reviewed runtime configuration document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    trading: TradingSettings = Field(default_factory=TradingSettings)


@dataclass(frozen=True)
class LoadedRuntimeSettings:
    """The parsed settings plus where they came from."""

    settings: RuntimeSettings
    path: Path | None

    @property
    def opportunity(self) -> OpportunitySettings:
        return self.settings.trading.opportunity


def load_runtime_settings(path: Path | str | None = None) -> LoadedRuntimeSettings:
    """Read the reviewed runtime configuration.

    A missing file yields the reviewed defaults; a malformed or
    out-of-range section raises so a typo cannot quietly change the
    cadence or the escalation guards.
    """
    resolved: Path | None = None
    if path is not None:
        candidate = Path(path)
        resolved = candidate if candidate.is_file() else None
    else:
        try:
            candidate = project_root() / RUNTIME_CONFIG_PATH
        except Exception:
            candidate = RUNTIME_CONFIG_PATH
        resolved = candidate if candidate.is_file() else None

    if resolved is None:
        return LoadedRuntimeSettings(settings=RuntimeSettings(), path=None)

    document = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if document is None:
        return LoadedRuntimeSettings(settings=RuntimeSettings(), path=resolved)
    if not isinstance(document, dict):
        raise ValueError(f"{resolved} must contain a YAML mapping")
    # ``model:`` is owned by alphabrief_models and parsed there; the
    # runtime loader validates only the sections it owns so the two
    # loaders can evolve independently without duplicating a schema.
    owned = {
        key: value
        for key, value in document.items()
        if key in {"schema_version", "trading"}
    }
    return LoadedRuntimeSettings(
        settings=RuntimeSettings.model_validate(owned), path=resolved
    )


def load_opportunity_settings(
    path: Path | str | None = None,
) -> OpportunitySettings:
    """Convenience accessor for the opportunity section alone."""
    return load_runtime_settings(path).opportunity


__all__ = [
    "LoadedRuntimeSettings",
    "OpportunitySettings",
    "RUNTIME_CONFIG_PATH",
    "RuntimeSettings",
    "TradingSettings",
    "load_opportunity_settings",
    "load_runtime_settings",
]
