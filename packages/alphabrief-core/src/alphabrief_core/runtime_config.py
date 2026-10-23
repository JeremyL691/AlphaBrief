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
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    #: Escalate a flat scan too, so the committee still decides. Off by
    #: default; an operator turns it on to guarantee a number of daily
    #: decisions instead of depending on a directional signal appearing.
    escalate_on_flat: bool = False

    @field_validator("escalate_on_flat", mode="before")
    @classmethod
    def require_real_boolean(cls, value: Any) -> Any:
        """Reject strings: ``"false"`` is truthy and would invert the flag."""
        if isinstance(value, bool):
            return value
        raise ValueError("escalate_on_flat must be true or false, not a string")

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


#: Reviewed GUIDE 5.4 committee thresholds. Configuration may tighten these
#: (raise the floor, raise the quorum, strengthen consensus, lower the cap) but
#: never release them (AGENTS 8.6).
GUIDE_MIN_CONFIDENCE = Decimal("0.55")
GUIDE_MIN_ANALYSTS = 2
GUIDE_MIN_CONSENSUS = "split"
GUIDE_MAX_POSITION_PCT = Decimal("0.25")
#: Weakest to strongest; an index comparison enforces "only tighten".
CONSENSUS_ORDER = ("no_consensus", "split", "majority", "unanimous")


class DisciplineSettings(BaseModel):
    """The ``trading.discipline:`` section: reviewed committee thresholds.

    These are the GUIDE 5.4 numbers the committee applies after the models
    answer. They live in the reviewed configuration so a change is a reviewable
    diff instead of an edit buried in code.

    AGENTS 8.6 allows these numbers to be *tightened* and never released: the
    configuration may raise the confidence floor, raise the analyst quorum,
    require stronger consensus and lower the position cap, but attempting to
    relax any of them fails loading. The earlier release of all four values is
    why this class validates instead of merely documenting the rule.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Below this confidence the plan is forced to no-trade.
    no_trade_below_confidence: Decimal = Field(
        default=Decimal("0.55"), ge=Decimal(0), le=Decimal(1)
    )
    #: How many analysts must support the manager's direction to open.
    min_analysts_supporting_direction: int = Field(default=2, ge=0, le=8)
    #: Required consensus quality: unanimous | majority | split | no_consensus.
    require_min_consensus: str = "split"
    #: The risk role's veto is a hard block.
    honour_risk_role_veto: bool = True
    #: Cap on any single symbol's target position fraction.
    max_position_pct: Decimal = Field(
        default=Decimal("0.25"), gt=Decimal(0), le=Decimal(1)
    )

    @model_validator(mode="after")
    def reject_relaxed_thresholds(self) -> DisciplineSettings:
        """Refuse any value looser than the reviewed GUIDE 5.4 number.

        AGENTS 8.6 states that section 5.7 risk values may only be tightened.
        Asserting that in the schema means a relaxed committee threshold is a
        configuration error that stops the run, not a silent widening of what
        reaches the RiskGate.
        """
        if self.no_trade_below_confidence < GUIDE_MIN_CONFIDENCE:
            raise ValueError(
                "no_trade_below_confidence may only be tightened: "
                f"{self.no_trade_below_confidence} is below the reviewed "
                f"{GUIDE_MIN_CONFIDENCE}"
            )
        if self.min_analysts_supporting_direction < GUIDE_MIN_ANALYSTS:
            raise ValueError(
                "min_analysts_supporting_direction may only be tightened: "
                f"{self.min_analysts_supporting_direction} is below the "
                f"reviewed {GUIDE_MIN_ANALYSTS}"
            )
        if not self.honour_risk_role_veto:
            raise ValueError(
                "honour_risk_role_veto may not be released: GUIDE 5.4 makes "
                "the risk role's veto a hard block"
            )
        if self.max_position_pct > GUIDE_MAX_POSITION_PCT:
            raise ValueError(
                "max_position_pct may only be tightened: "
                f"{self.max_position_pct} is above the reviewed "
                f"{GUIDE_MAX_POSITION_PCT}"
            )
        if CONSENSUS_ORDER.index(self.require_min_consensus) < (
            CONSENSUS_ORDER.index(GUIDE_MIN_CONSENSUS)
        ):
            raise ValueError(
                "require_min_consensus may only be tightened: "
                f"{self.require_min_consensus} is weaker than the reviewed "
                f"{GUIDE_MIN_CONSENSUS}"
            )
        return self

    @field_validator(
        "no_trade_below_confidence",
        "max_position_pct",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: Any) -> Any:
        """Require a decimal string so a threshold is never a float."""
        if isinstance(value, bool):
            raise ValueError("must be a decimal string such as '0.55'")
        if isinstance(value, (int, float)):
            raise ValueError("must be a decimal string such as '0.55'")
        if isinstance(value, str):
            return Decimal(value)
        return value

    @field_validator("require_min_consensus")
    @classmethod
    def require_valid_consensus(cls, value: str) -> str:
        allowed = {"unanimous", "majority", "split", "no_consensus"}
        if value not in allowed:
            raise ValueError(f"require_min_consensus must be one of {sorted(allowed)}")
        return value


class TradingSettings(BaseModel):
    """The ``trading:`` section: mode switch plus opportunity guardrails."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trading_mode: str = "off"
    opportunity: OpportunitySettings = Field(default_factory=OpportunitySettings)
    discipline: DisciplineSettings = Field(default_factory=DisciplineSettings)

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


def _repository_root() -> Path:
    """The checkout (or bundle) holding the reviewed configuration.

    ``project_root`` already understands the PyInstaller bundle. The
    package walk covers an editable install whose working directory is
    somewhere else entirely - which is exactly how the LaunchAgent starts
    the backend.
    """
    try:
        return project_root()
    except Exception:  # noqa: BLE001 - fall back to the package location
        pass
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / "pyproject.toml").is_file():
            return ancestor
        if (ancestor / RUNTIME_CONFIG_PATH).is_file():
            return ancestor
    return Path.cwd()


def _resolve_config_path(path: Path | str | None) -> Path | None:
    """Find the reviewed configuration, or ``None`` when it is absent.

    An explicit path wins. A relative one resolves against the repository
    root rather than only the cwd, so a daemon started in the data
    directory still reads the reviewed values instead of silently
    accepting the dataclass defaults.
    """
    if path is not None:
        candidate = Path(path)
        if candidate.is_file():
            return candidate
        if not candidate.is_absolute():
            anchored = _repository_root() / candidate
            return anchored if anchored.is_file() else None
        return None

    candidate = Path(RUNTIME_CONFIG_PATH)
    if candidate.is_file():
        return candidate
    anchored = _repository_root() / RUNTIME_CONFIG_PATH
    return anchored if anchored.is_file() else None


def load_runtime_settings(path: Path | str | None = None) -> LoadedRuntimeSettings:
    """Read the reviewed runtime configuration.

    A missing file yields the reviewed defaults; a malformed or
    out-of-range section raises so a typo cannot quietly change the
    cadence or the escalation guards.
    """
    resolved = _resolve_config_path(path)

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


def load_discipline_settings(
    path: Path | str | None = None,
) -> DisciplineSettings:
    """Convenience accessor for the reviewed committee thresholds."""
    return load_runtime_settings(path).settings.trading.discipline


__all__ = [
    "DisciplineSettings",
    "LoadedRuntimeSettings",
    "OpportunitySettings",
    "RUNTIME_CONFIG_PATH",
    "RuntimeSettings",
    "TradingSettings",
    "load_discipline_settings",
    "load_opportunity_settings",
    "load_runtime_settings",
]
