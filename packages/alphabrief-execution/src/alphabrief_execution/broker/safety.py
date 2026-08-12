"""Deterministic OANDA-only production boundary gates (M01-W01).

This module proves the *selected* production configuration cannot express
any execution venue other than the OANDA practice account: the execution
policy provider/market, the OANDA paper endpoint, and the default runtime
settings. Every check is a positive assertion — the loaders are strict
(unknown fields fail), so any other selection is rejected by schema
validation, and the raw selector-line scan below guards against a future
loader that stops validating.

Dormant unselected files are out of scope here; the milestone-wide graph
gate (M01-W05) covers the absence of unused venues in the repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from alphabrief_core import load_paper_execution_policy
from alphabrief_core.config import load_settings
from alphabrief_core.execution_policy import PaperMarket, PaperProvider

from alphabrief_execution.broker.oanda.config import (
    DEFAULT_BASE_URL,
    load_oanda_paper_config,
)

#: Top-level YAML keys whose values describe the execution selection.
_SELECTOR_KEYS: frozenset[str] = frozenset(
    {
        "provider",
        "mode",
        "market",
        "base_url",
        "environment",
        "broker",
        "venue",
        "routing",
        "simulated",
        "fallback",
    }
)

#: Allowed values per selector key, kept in sync with the schema literals.
_ALLOWED_SELECTOR_VALUES: dict[str, frozenset[str]] = {
    "provider": frozenset(get_args(PaperProvider)),
    "mode": frozenset({"paper"}),
    "market": frozenset(get_args(PaperMarket)),
    "base_url": frozenset({DEFAULT_BASE_URL}),
    # environment/broker/venue/routing/simulated/fallback selectors have no
    # allowed value in OANDA-only production configuration.
    "environment": frozenset(),
    "broker": frozenset(),
    "venue": frozenset(),
    "routing": frozenset(),
    "simulated": frozenset(),
    "fallback": frozenset(),
}


def production_boundary_violations(root: Path | str) -> list[str]:
    """Return deterministic violations of the OANDA-only production boundary.

    Scans the execution policy, the OANDA paper config, and the default
    settings. An empty list means the selected production configuration is
    OANDA practice only and cannot select a live host, another broker,
    routing, or any in-memory execution substitute.
    """
    root_path = Path(root)
    problems: list[str] = []

    policy_path = root_path / "config/paper_execution_policy.yaml"
    policy_text = _read_text(policy_path, "execution policy", problems)
    if policy_text is not None:
        try:
            policy = load_paper_execution_policy(policy_path)
        except (ValueError, TypeError) as exc:
            problems.append(f"execution policy invalid: {exc}")
        else:
            if policy.mode != "paper":
                problems.append(
                    f"execution policy mode is {policy.mode!r}, expected 'paper'"
                )
            if policy.provider != "oanda_paper":
                problems.append(
                    f"execution policy provider is {policy.provider!r}, "
                    "expected 'oanda_paper'"
                )
        problems.extend(_unexpected_selector_lines(policy_text, policy_path))

    oanda_path = root_path / "config/oanda_paper.yaml"
    oanda_text = _read_text(oanda_path, "oanda paper config", problems)
    if oanda_text is not None:
        try:
            oanda_config = load_oanda_paper_config(oanda_path)
        except (ValueError, TypeError) as exc:
            problems.append(f"oanda paper config invalid: {exc}")
        else:
            if oanda_config.base_url != DEFAULT_BASE_URL:
                problems.append(
                    f"oanda base_url {oanda_config.base_url!r} is not the "
                    "locked practice endpoint"
                )
        problems.extend(_unexpected_selector_lines(oanda_text, oanda_path))

    if load_settings({}).live_trading_enabled:
        problems.append("default settings enable live trading")
    return problems


def _read_text(
    path: Path, label: str, problems: list[str]
) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        problems.append(f"{label} unreadable at {path}: {exc}")
        return None


def _unexpected_selector_lines(text: str, source: Path) -> list[str]:
    """Return selector lines whose value is outside the allowed set."""
    violations: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key not in _SELECTOR_KEYS:
            continue
        allowed = _ALLOWED_SELECTOR_VALUES[key]
        candidate = value.strip().strip("\"'")
        if candidate not in allowed:
            violations.append(
                f"{source.name} selector {key!r} value {candidate!r} is not "
                "allowed in OANDA-only production configuration"
            )
    return violations


__all__ = ["production_boundary_violations"]
