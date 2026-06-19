"""CLI subcommands for the strategy registry.

This module provides the ``alphabrief strategy`` subcommand group. It is the
CLI counterpart to the strategy-spec HTTP API: every command here ultimately
goes through :class:`alphabrief_api.db.strategies.StrategySpecStore`.

Commands
--------

- ``strategy save --from-yaml <path> [--from-json <path>] [--enable|--disable]``
  Persist a ``StrategySpec`` from a YAML or JSON file. Validates the payload
  as a ``StrategySpec`` before writing.
- ``strategy list [--enabled|--disabled] [--pretty|--compact]``
  List summary records (id, name, version, enabled flag, timestamps).
- ``strategy show <strategy_id>``
  Print the full stored record (including the spec payload) as JSON.
- ``strategy enable <strategy_id>`` and ``strategy disable <strategy_id>``
  Flip the activation flag. The flag is advisory at this round and does not
  block orders, gate execution, or affect risk allowlists.
- ``strategy delete <strategy_id>``
  Remove a strategy from the registry.
- ``strategy record-signal --from-yaml <path> [--source <label>]``
  Persist a signal to the advisory history table.
- ``strategy list-signals [--strategy-id] [--symbol] [--source] [--limit]``
  List signal history rows (advisory only).
- ``strategy show-signal <signal_id>``
  Print one signal record (including the full payload) as JSON.
- ``strategy count-signals <strategy_id>``
  Print the number of stored signals for a strategy.

The CLI never imports RiskGate, PaperBroker, broker code, or
``_reference_sources``. It only persists and reads registry rows.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import typer
import yaml
from alphabrief_api.db import StrategySignalStore, StrategySpecStore
from alphabrief_strategy import StrategySpec

strategy_app = typer.Typer(help="Manage the local strategy registry.")


# ---------------------------------------------------------------------------
# Store helper
# ---------------------------------------------------------------------------


def _open_store() -> StrategySpecStore:
    """Return a store rooted at ``$ALPHABRIEF_DATA_DIR`` (if set)."""
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return StrategySpecStore(db_path=db_dir / "alphabrief.db")
    return StrategySpecStore()


def _open_signal_store() -> StrategySignalStore:
    """Return a signal store rooted at ``$ALPHABRIEF_DATA_DIR`` (if set)."""
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return StrategySignalStore(db_path=db_dir / "alphabrief.db")
    return StrategySignalStore()


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


@strategy_app.command("save")
def save_cmd(
    from_yaml: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--from-yaml",
        help="Path to a YAML file containing a StrategySpec payload.",
    ),
    from_json: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--from-json",
        help="Path to a JSON file containing a StrategySpec payload.",
    ),
    enable: bool = typer.Option(  # noqa: B008 - typer pattern
        False,
        "--enable/--disable",
        help="Activation flag to set (advisory only at this round).",
    ),
) -> None:
    """Save a StrategySpec from YAML or JSON.

    Validates the payload against :class:`StrategySpec` and persists it via
    :class:`StrategySpecStore`. Re-saving an existing ``strategy_id``
    upserts the spec while preserving the activation flag unless
    ``--enable`` / ``--disable`` is passed.
    """
    if from_yaml is None and from_json is None:
        print(
            "error: provide --from-yaml or --from-json",
            file=sys.stderr,
        )
        sys.exit(1)
    if from_yaml is not None and from_json is not None:
        print(
            "error: --from-yaml and --from-json are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(1)

    src = from_yaml if from_yaml is not None else from_json
    assert src is not None  # for type checkers
    try:
        raw = src.read_text()
    except OSError as exc:
        print(f"error: could not read {src}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        if from_yaml is not None:
            payload: Any = yaml.safe_load(raw)
        else:
            payload = json.loads(raw)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"error: invalid payload in {src}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(payload, dict):
        print(
            f"error: payload in {src} must be a JSON/YAML object",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        spec = StrategySpec.model_validate(payload)
    except Exception as exc:
        print(
            f"error: invalid StrategySpec in {src}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    store = _open_store()
    try:
        store.save_spec(
            payload,
            enabled=enable,
        )
    finally:
        store.close()

    print(f"strategy_id: {spec.strategy_id}")
    print(f"name: {spec.name}")
    print(f"version: {spec.version}")
    print(f"enabled: {enable}")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@strategy_app.command("list")
def list_cmd(
    enabled: bool | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--enabled/--disabled",
        help="If set, filter to enabled (--enabled) or disabled (--disabled).",
    ),
    pretty: bool = typer.Option(  # noqa: B008 - typer pattern
        True,
        "--pretty/--compact",
        help="Pretty-print the JSON output (default: pretty).",
    ),
) -> None:
    """List all stored strategies as JSON summaries."""
    enabled_only: bool | None
    if enabled is True:
        enabled_only = True
    elif enabled is False:
        enabled_only = False
    else:
        enabled_only = None

    store = _open_store()
    try:
        rows = store.list_specs(enabled_only=enabled_only)
    finally:
        store.close()

    indent = 2 if pretty else None
    json.dump(
        {"strategies": rows},
        sys.stdout,
        indent=indent,
        sort_keys=True,
        default=str,
    )
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@strategy_app.command("show")
def show_cmd(
    strategy_id: str = typer.Argument(  # noqa: B008 - typer pattern
        ...,
        help="Identifier of the strategy to show.",
    ),
    pretty: bool = typer.Option(  # noqa: B008 - typer pattern
        True,
        "--pretty/--compact",
        help="Pretty-print the JSON output (default: pretty).",
    ),
) -> None:
    """Print the full record (including the spec payload) as JSON."""
    store = _open_store()
    try:
        record = store.get_spec(strategy_id)
    finally:
        store.close()

    if record is None:
        print(f"error: strategy {strategy_id!r} not found", file=sys.stderr)
        sys.exit(1)

    indent = 2 if pretty else None
    json.dump(record, sys.stdout, indent=indent, sort_keys=True, default=str)
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# enable / disable / delete
# ---------------------------------------------------------------------------


@strategy_app.command("enable")
def enable_cmd(
    strategy_id: str = typer.Argument(  # noqa: B008 - typer pattern
        ...,
        help="Identifier of the strategy to enable.",
    ),
) -> None:
    """Flip the activation flag to enabled.

    The flag is advisory only at this round and never blocks orders, gates
    execution, or affects the risk allowlist.
    """
    store = _open_store()
    try:
        ok = store.set_enabled(strategy_id, True)
    finally:
        store.close()
    if not ok:
        print(f"error: strategy {strategy_id!r} not found", file=sys.stderr)
        sys.exit(1)
    print(f"strategy_id: {strategy_id}")
    print("enabled: True")


@strategy_app.command("disable")
def disable_cmd(
    strategy_id: str = typer.Argument(  # noqa: B008 - typer pattern
        ...,
        help="Identifier of the strategy to disable.",
    ),
) -> None:
    """Flip the activation flag to disabled (advisory only)."""
    store = _open_store()
    try:
        ok = store.set_enabled(strategy_id, False)
    finally:
        store.close()
    if not ok:
        print(f"error: strategy {strategy_id!r} not found", file=sys.stderr)
        sys.exit(1)
    print(f"strategy_id: {strategy_id}")
    print("enabled: False")


@strategy_app.command("delete")
def delete_cmd(
    strategy_id: str = typer.Argument(  # noqa: B008 - typer pattern
        ...,
        help="Identifier of the strategy to delete.",
    ),
) -> None:
    """Remove a strategy from the registry."""
    store = _open_store()
    try:
        ok = store.delete_spec(strategy_id)
    finally:
        store.close()
    if not ok:
        print(f"error: strategy {strategy_id!r} not found", file=sys.stderr)
        sys.exit(1)
    print(f"strategy_id: {strategy_id}")
    print("deleted: True")


# ---------------------------------------------------------------------------
# Signal history (advisory)
# ---------------------------------------------------------------------------


_VALID_SOURCES: frozenset[str] = frozenset({"backtest", "manual", "other"})


@strategy_app.command("record-signal")
def record_signal_cmd(
    from_yaml: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--from-yaml",
        help="Path to a YAML file containing a signal payload.",
    ),
    from_json: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--from-json",
        help="Path to a JSON file containing a signal payload.",
    ),
    source: str = typer.Option(  # noqa: B008 - typer pattern
        "other",
        "--source",
        help="Source label: 'backtest', 'manual', or 'other'.",
    ),
) -> None:
    """Persist a single signal to the advisory history.

    The payload is validated as a signal (``signal_id``,
    ``strategy_id``, ``symbol``, ``timestamp``, ``direction``,
    ``confidence``, ``horizon``). The record is purely advisory.
    """
    if from_yaml is None and from_json is None:
        print(
            "error: provide --from-yaml or --from-json",
            file=sys.stderr,
        )
        sys.exit(1)
    if from_yaml is not None and from_json is not None:
        print(
            "error: --from-yaml and --from-json are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(1)
    if source not in _VALID_SOURCES:
        print(
            f"error: --source must be one of {sorted(_VALID_SOURCES)}",
            file=sys.stderr,
        )
        sys.exit(1)

    src = from_yaml if from_yaml is not None else from_json
    assert src is not None
    try:
        raw = src.read_text()
    except OSError as exc:
        print(f"error: could not read {src}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        if from_yaml is not None:
            payload: Any = yaml.safe_load(raw)
        else:
            payload = json.loads(raw)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"error: invalid payload in {src}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(payload, dict):
        print(
            f"error: payload in {src} must be a JSON/YAML object",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        store = _open_signal_store()
        signal_id = store.save_signal(payload, source=source)
    except ValueError as exc:
        print(f"error: invalid signal payload: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            store.close()
        except (NameError, UnboundLocalError):
            pass

    print(f"signal_id: {signal_id}")
    print(f"source: {source}")


@strategy_app.command("list-signals")
def list_signals_cmd(
    strategy_id: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--strategy-id",
        help="Filter to a single strategy id.",
    ),
    symbol: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--symbol",
        help="Filter to a single symbol.",
    ),
    source: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--source",
        help="Filter by source label.",
    ),
    limit: int | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--limit",
        min=1,
        help="Cap on the number of returned rows.",
    ),
    pretty: bool = typer.Option(  # noqa: B008 - typer pattern
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List signal history rows (advisory only)."""
    store = _open_signal_store()
    try:
        rows = store.list_signals(
            strategy_id=strategy_id,
            symbol=symbol,
            source=source,
            limit=limit,
        )
    finally:
        store.close()

    indent = 2 if pretty else None
    json.dump(
        {"signals": rows},
        sys.stdout,
        indent=indent,
        sort_keys=True,
        default=str,
    )
    sys.stdout.write("\n")


@strategy_app.command("show-signal")
def show_signal_cmd(
    signal_id: str = typer.Argument(  # noqa: B008 - typer pattern
        ...,
        help="Identifier of the signal to show.",
    ),
    pretty: bool = typer.Option(  # noqa: B008 - typer pattern
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Print one signal record (including the full payload) as JSON."""
    store = _open_signal_store()
    try:
        record = store.get_signal(signal_id)
    finally:
        store.close()

    if record is None:
        print(f"error: signal {signal_id!r} not found", file=sys.stderr)
        sys.exit(1)

    indent = 2 if pretty else None
    json.dump(record, sys.stdout, indent=indent, sort_keys=True, default=str)
    sys.stdout.write("\n")


@strategy_app.command("count-signals")
def count_signals_cmd(
    strategy_id: str = typer.Argument(  # noqa: B008 - typer pattern
        ...,
        help="Strategy id whose signal count to show.",
    ),
) -> None:
    """Print the number of stored signals for a strategy."""
    store = _open_signal_store()
    try:
        count = store.count_signals(strategy_id=strategy_id)
    finally:
        store.close()
    print(f"strategy_id: {strategy_id}")
    print(f"count: {count}")


__all__ = ["strategy_app"]
