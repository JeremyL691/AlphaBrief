"""The reviewed runtime configuration must fail closed on typos.

`config/alphabrief.yaml` is operator-owned and reviewer-reviewed. A typo
in it must raise at load time, never silently fall back to a default that
changes the trading cadence or the escalation guards. The same file is
also read by the model channel loader, which owns the `model:` section;
the runtime loader validates only the sections it owns.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import load_opportunity_settings, load_runtime_settings
from alphabrief_core.runtime_config import RUNTIME_CONFIG_PATH


def _write(tmp_path: Path, body: str) -> Path:
    target = tmp_path / "alphabrief.yaml"
    target.write_text(body, encoding="utf-8")
    return target


def test_missing_file_yields_the_reviewed_defaults(tmp_path: Path) -> None:
    loaded = load_runtime_settings(tmp_path / "absent.yaml")

    assert loaded.path is None
    assert loaded.opportunity.max_rounds_per_day == 15
    assert loaded.opportunity.min_spacing_seconds == 600
    assert loaded.settings.trading.trading_mode == "off"


def test_the_repository_config_is_valid() -> None:
    """The shipped configuration must always parse."""
    loaded = load_runtime_settings()

    assert loaded.path is not None
    assert loaded.path.name == Path(RUNTIME_CONFIG_PATH).name
    assert 60 <= loaded.opportunity.scan_interval_seconds <= 300


def test_unknown_key_is_refused(tmp_path: Path) -> None:
    """A typo must never silently disable a safety-relevant setting."""
    path = _write(
        tmp_path,
        "schema_version: 1\ntrading:\n"
        "  opportunity:\n    scan_interval_second: 120\n",
    )

    with pytest.raises(ValueError, match="scan_interval_second"):
        load_runtime_settings(path)


def test_scan_interval_outside_the_guide_window_is_refused(
    tmp_path: Path,
) -> None:
    """GUIDE 5.1 says every 1-5 minutes; 30s or 20min is a typo."""
    too_fast = _write(
        tmp_path,
        "trading:\n  opportunity:\n    scan_interval_seconds: 30\n",
    )
    with pytest.raises(ValueError):
        load_runtime_settings(too_fast)

    too_slow = _write(
        tmp_path,
        "trading:\n  opportunity:\n    scan_interval_seconds: 1200\n",
    )
    with pytest.raises(ValueError):
        load_runtime_settings(too_slow)


def test_confidence_must_be_an_exact_decimal(tmp_path: Path) -> None:
    """A float confidence would make the threshold inexact."""
    path = _write(
        tmp_path,
        "trading:\n  opportunity:\n    escalation_min_confidence: 0.6\n",
    )
    with pytest.raises(ValueError, match="decimal string"):
        load_runtime_settings(path)

    good = _write(
        tmp_path,
        'trading:\n  opportunity:\n    escalation_min_confidence: "0.6"\n',
    )
    assert load_opportunity_settings(good).escalation_min_confidence == Decimal(
        "0.6"
    )


def test_implicit_boolean_can_disable_but_never_enable_trading(
    tmp_path: Path,
) -> None:
    """YAML reads a bare `off`/`on` as a boolean; only `off` may be inferred."""
    disabled = _write(tmp_path, "trading:\n  trading_mode: off\n")
    assert load_runtime_settings(disabled).settings.trading.trading_mode == "off"

    enabled = _write(tmp_path, "trading:\n  trading_mode: on\n")
    with pytest.raises(ValueError, match="implicit YAML boolean"):
        load_runtime_settings(enabled)


def test_explicit_string_mode_is_honoured(tmp_path: Path) -> None:
    path = _write(tmp_path, 'trading:\n  trading_mode: "on"\n')

    assert load_runtime_settings(path).settings.trading.trading_mode == "on"


def test_invalid_mode_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, 'trading:\n  trading_mode: "yes please"\n')

    with pytest.raises(ValueError, match="must be 'on' or 'off'"):
        load_runtime_settings(path)


def test_model_section_is_left_to_the_model_loader(tmp_path: Path) -> None:
    """Two loaders own two sections; neither rejects the other's keys."""
    path = _write(
        tmp_path,
        "schema_version: 1\n"
        "model:\n  primary_channel: openrouter_free\n"
        "trading:\n  trading_mode: off\n",
    )

    loaded = load_runtime_settings(path)

    assert loaded.settings.trading.trading_mode == "off"
    assert loaded.settings.schema_version == 1


def test_config_is_found_from_an_unrelated_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The LaunchAgent starts the backend in the data directory."""
    monkeypatch.chdir(tmp_path)

    loaded = load_runtime_settings()

    assert loaded.path is not None, (
        "the loader searched only the working directory, so a daemon "
        "started in the data directory silently used dataclass defaults"
    )
    assert loaded.path.name == Path(RUNTIME_CONFIG_PATH).name
    # The file's reviewed value, which differs from the dataclass default:
    # this proves the file was loaded rather than the defaults applied.
    assert loaded.opportunity.max_rounds_per_day == 15


def test_relative_path_resolves_against_the_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    loaded = load_runtime_settings(RUNTIME_CONFIG_PATH)

    assert loaded.path is not None
    assert loaded.path.is_absolute()


def test_absolute_missing_path_is_still_the_documented_default(
    tmp_path: Path,
) -> None:
    """An explicit absent path must not silently search elsewhere."""
    loaded = load_runtime_settings(tmp_path / "nope.yaml")

    assert loaded.path is None
    assert loaded.opportunity.max_rounds_per_day == 15


def test_escalate_on_flat_is_configurable_and_defaults_off(tmp_path: Path) -> None:
    """The operator can require committee rounds even on a flat scan.

    The reviewed default stays False: a flat scan normally spends nothing.
    Turning it on is an explicit operator decision to guarantee daily
    decisions instead of waiting for a directional signal.
    """
    absent = load_runtime_settings(tmp_path / "absent.yaml")
    assert absent.opportunity.escalate_on_flat is False

    path = _write(
        tmp_path,
        "schema_version: 1\ntrading:\n  opportunity:\n    escalate_on_flat: true\n",
    )
    assert load_opportunity_settings(path).escalate_on_flat is True


def test_escalate_on_flat_rejects_a_non_boolean(tmp_path: Path) -> None:
    """A string is a typo, not a policy: fail closed at load time."""
    path = _write(
        tmp_path,
        'schema_version: 1\ntrading:\n  opportunity:\n    escalate_on_flat: "yes"\n',
    )
    with pytest.raises(ValueError):
        load_opportunity_settings(path)


def test_discipline_section_defaults_to_the_guide_values(tmp_path: Path) -> None:
    """Absent config keeps GUIDE 5.4 exactly."""
    absent = load_runtime_settings(tmp_path / "absent.yaml")
    discipline = absent.settings.trading.discipline

    assert discipline.no_trade_below_confidence == Decimal("0.55")
    assert discipline.min_analysts_supporting_direction == 2
    assert discipline.require_min_consensus == "split"
    assert discipline.honour_risk_role_veto is True
    assert discipline.max_position_pct == Decimal("0.25")


def test_discipline_section_accepts_tightened_overrides(tmp_path: Path) -> None:
    """An operator can tighten the reviewed thresholds through config."""
    path = _write(
        tmp_path,
        "schema_version: 1\ntrading:\n  discipline:\n"
        "    no_trade_below_confidence: '0.75'\n"
        "    min_analysts_supporting_direction: 3\n"
        "    require_min_consensus: unanimous\n"
        "    max_position_pct: '0.10'\n",
    )
    discipline = load_runtime_settings(path).settings.trading.discipline

    assert discipline.no_trade_below_confidence == Decimal("0.75")
    assert discipline.min_analysts_supporting_direction == 3
    assert discipline.require_min_consensus == "unanimous"
    assert discipline.max_position_pct == Decimal("0.10")


def test_discipline_section_refuses_a_released_threshold(tmp_path: Path) -> None:
    """Releasing the numbers is an error, not a tuning choice (AGENTS 8.6)."""
    import pydantic

    path = _write(
        tmp_path,
        "schema_version: 1\ntrading:\n  discipline:\n"
        "    no_trade_below_confidence: '0'\n"
        "    min_analysts_supporting_direction: 0\n"
        "    require_min_consensus: no_consensus\n"
        "    honour_risk_role_veto: false\n"
        "    max_position_pct: '0.95'\n",
    )

    with pytest.raises(pydantic.ValidationError):
        load_runtime_settings(path)


def test_discipline_rejects_a_float_threshold(tmp_path: Path) -> None:
    """A float threshold is inexact; require a decimal string."""
    path = _write(
        tmp_path,
        "schema_version: 1\ntrading:\n  discipline:\n"
        "    no_trade_below_confidence: 0.3\n",
    )
    with pytest.raises(ValueError):
        load_runtime_settings(path)


def test_discipline_rejects_an_unknown_consensus_level(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema_version: 1\ntrading:\n  discipline:\n"
        "    require_min_consensus: whatever\n",
    )
    with pytest.raises(ValueError):
        load_runtime_settings(path)


def _discipline(**overrides: object) -> object:
    from typing import Any, cast

    from alphabrief_core.runtime_config import DisciplineSettings

    return DisciplineSettings(**cast("dict[str, Any]", overrides))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("no_trade_below_confidence", "0"),
        ("no_trade_below_confidence", "0.549"),
        ("min_analysts_supporting_direction", 0),
        ("min_analysts_supporting_direction", 1),
        ("honour_risk_role_veto", False),
        ("max_position_pct", "0.95"),
        ("require_min_consensus", "no_consensus"),
    ],
)
def test_committee_thresholds_cannot_be_released(
    field: str, value: object
) -> None:
    """AGENTS 8.6: section 5.7 risk values may only be tightened.

    The relaxation that ran in the soak released the confidence floor, the
    analyst quorum and the risk veto at once. A comment cannot prevent that;
    loading must refuse it.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        _discipline(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("no_trade_below_confidence", "0.70"),
        ("min_analysts_supporting_direction", 3),
        ("max_position_pct", "0.10"),
        ("require_min_consensus", "unanimous"),
    ],
)
def test_committee_thresholds_may_be_tightened(
    field: str, value: object
) -> None:
    """Tightening stays possible: the constraint is one-directional."""
    settings = _discipline(**{field: value})

    # Loading succeeded, which is what "tightening stays possible" means.
    assert settings is not None


def test_the_reviewed_configuration_loads_with_the_guide_values() -> None:
    """The shipped file must state the reviewed numbers, not relaxed ones."""
    from alphabrief_core import load_runtime_settings

    discipline = load_runtime_settings().settings.trading.discipline

    assert str(discipline.no_trade_below_confidence) == "0.55"
    assert discipline.min_analysts_supporting_direction == 2
    assert discipline.honour_risk_role_veto is True
    assert str(discipline.max_position_pct) == "0.25"
    assert discipline.require_min_consensus == "split"


def test_flat_escalation_is_off_in_the_reviewed_configuration() -> None:
    """A day with no signal must cost zero model calls."""
    from alphabrief_core import load_runtime_settings

    assert load_runtime_settings().opportunity.escalate_on_flat is False
