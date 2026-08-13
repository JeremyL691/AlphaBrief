"""CLI subcommands for the external paper broker.

Commands
--------

- ``broker status``
  Print a one-line broker health summary.
- ``broker reconcile [--scope startup|cycle|eod]``
  Run one reconciliation pass and print the snapshot.
- ``broker orders``
  List open orders reported by the broker.
- ``broker positions``
  List open positions.
- ``broker account``
  Print the account cash / equity / buying-power snapshot.
- ``broker freeze [--reason <text>]``
  Raise a manual freeze (auto-ordering blocks).
- ``broker unfreeze <event_id> [--reason <text>]``
  Clear an open freeze by id.

The CLI proxies through the API when the server is running and runs
the identical durable :class:`ReconciliationRunner` against the OANDA
practice runtime otherwise.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import typer
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.reconciliation import (
    ALLOWED_SCOPES,
    ReconciliationRunner,
)
from alphabrief_execution.broker.runtime import get_broker_runtime

from alphabrief_cli.api_client import is_api_running, print_api_unavailable_hint

broker_app = typer.Typer(help="Inspect and operate the external paper broker.")


# ---------------------------------------------------------------------------
# Local store helper (used only when the API is not running)
# ---------------------------------------------------------------------------


def _open_store() -> BrokerReconStore:
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return BrokerReconStore(db_path=db_dir / "alphabrief.db")
    return BrokerReconStore()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _dump(payload: object, *, pretty: bool, default: bool = False) -> None:
    """Write JSON to stdout, formatting Decimal/datetime as strings when needed."""
    json.dump(
        payload,
        sys.stdout,
        indent=2 if pretty else None,
        sort_keys=True,
        default=str if default else None,
    )
    sys.stdout.write("\n")


@broker_app.command("status")
def status_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Print a short broker health summary from the local recon store."""
    if is_api_running():
        import urllib.request

        url = f"{os.environ.get('ALPHABRIEF_API_URL', 'http://127.0.0.1:8000')}/api/v1/broker/status"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — CLI surfaces any failure
            print(
                f"error: failed to reach broker status endpoint: {exc}",
                file=sys.stderr,
            )
            print_api_unavailable_hint(command="broker status")
            sys.exit(1)
        _dump(payload, pretty=pretty, default=True)
        return

    store = _open_store()
    try:
        latest = store.latest_snapshot()
        open_freezes = store.list_freezes(only_open=True)
    finally:
        store.close()
    payload = {
        "latest_snapshot": (
            {
                "snapshot_id": latest.snapshot_id,
                "captured_at": latest.captured_at,
                "scope": latest.scope,
                "all_match": latest.all_match,
            }
            if latest is not None
            else None
        ),
        "open_freeze_count": len(open_freezes),
    }
    _dump(payload, pretty=pretty)


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------


@broker_app.command("reconcile")
def reconcile_cmd(
    scope: str = typer.Option(  # noqa: B008
        "cycle",
        "--scope",
        help="Reconciliation scope: 'startup', 'cycle', or 'eod'.",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Run one reconciliation pass through the shared durable service.

    Uses the same :class:`ReconciliationRunner` as the API and the
    scheduler (AC-M07-W06-03): with the API running the pass is proxied
    to it; otherwise the local process runs the identical durable
    service against the OANDA practice runtime. Missing OANDA practice
    credentials record a fail-closed non-matching snapshot — never a
    placeholder all-match.
    """
    if scope not in ALLOWED_SCOPES:
        print(
            f"error: --scope must be one of {sorted(ALLOWED_SCOPES)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if is_api_running():
        import urllib.request

        base = os.environ.get("ALPHABRIEF_API_URL", "http://127.0.0.1:8000")
        url = f"{base}/api/v1/broker/reconcile?scope={scope}"
        try:
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(
                f"error: failed to reach broker reconcile endpoint: {exc}",
                file=sys.stderr,
            )
            print(
                "note: broker reconcile needs OANDA practice credentials "
                "on the API server; start the API server with credentials "
                "and try again.",
                file=sys.stderr,
            )
            print_api_unavailable_hint(command="broker reconcile")
            sys.exit(1)
        _dump(payload, pretty=pretty, default=True)
        return

    store = _open_store()
    try:
        runner = ReconciliationRunner(
            adapter=get_broker_runtime().adapter, store=store
        )
        result = asyncio.run(runner.reconcile(scope=scope))
    finally:
        store.close()
    payload = {
        "snapshot_id": result.snapshot.snapshot_id,
        "captured_at": result.snapshot.captured_at,
        "scope": result.snapshot.scope,
        "all_match": result.snapshot.all_match,
        "freeze_raised": result.freeze_raised,
    }
    _dump(payload, pretty=pretty)


# ---------------------------------------------------------------------------
# orders / positions / account
# ---------------------------------------------------------------------------


def _read_broker_endpoint(endpoint: str, *, command: str) -> dict[str, Any]:
    """Fetch a JSON payload from ``/api/v1/broker/{endpoint}`` or exit with an error."""
    if not is_api_running():
        print(
            f"error: broker {command} requires the API server to be running",
            file=sys.stderr,
        )
        print_api_unavailable_hint(command=f"broker {command}")
        sys.exit(1)
    import urllib.request

    base = os.environ.get("ALPHABRIEF_API_URL", "http://127.0.0.1:8000")
    url = f"{base}/api/v1/broker/{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(
            f"error: broker {command} failed to reach {url}: {exc}",
            file=sys.stderr,
        )
        print_api_unavailable_hint(command=f"broker {command}")
        sys.exit(1)
    if not isinstance(payload, dict):
        raise ValueError(f"broker {command} returned a non-object JSON response")
    return payload


@broker_app.command("orders")
def orders_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """List open broker orders (via the API)."""
    _dump(
        _read_broker_endpoint("orders", command="orders"),
        pretty=pretty,
        default=True,
    )


@broker_app.command("positions")
def positions_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """List open broker positions (via the API)."""
    _dump(
        _read_broker_endpoint("positions", command="positions"),
        pretty=pretty,
        default=True,
    )


@broker_app.command("account")
def account_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Print the account cash / equity / buying-power snapshot (via the API)."""
    _dump(
        _read_broker_endpoint("account", command="account"),
        pretty=pretty,
        default=True,
    )


# ---------------------------------------------------------------------------
# freeze / unfreeze
# ---------------------------------------------------------------------------


@broker_app.command("freeze")
def freeze_cmd(
    reason: str = typer.Option(  # noqa: B008
        "manual freeze",
        "--reason",
        help="Human-readable reason for the freeze.",
    ),
) -> None:
    """Raise a manual freeze. Auto-ordering will block until unfreeze."""
    store = _open_store()
    try:
        event = store.raise_freeze(reason=reason, source="manual")
    finally:
        store.close()
    print(f"event_id: {event.event_id}")
    print(f"reason: {event.reason}")
    print(f"raised_at: {event.raised_at}")


@broker_app.command("unfreeze")
def unfreeze_cmd(
    event_id: str = typer.Argument(  # noqa: B008
        ...,
        help="Identifier of the freeze event to clear.",
    ),
    reason: str = typer.Option(  # noqa: B008
        "manual unfreeze",
        "--reason",
        help="Human-readable reason for the unfreeze.",
    ),
) -> None:
    """Clear an open freeze by id."""
    store = _open_store()
    try:
        event = store.clear_freeze(event_id=event_id, reason=reason)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        store.close()
    print(f"event_id: {event.event_id}")
    print(f"cleared_at: {event.cleared_at}")


__all__ = ["broker_app"]
