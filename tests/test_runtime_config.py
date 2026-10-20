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
