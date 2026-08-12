"""Shared scheduler-DB snapshot + merged-read helpers.

The launchd-managed scheduler holds the DuckDB writer lock on its own
database for its lifetime, so the API process cannot open that file
directly (DuckDB is single-writer). When ``ALPHABRIEF_SCHEDULER_DB_DIR``
is set, dashboard routes serve a periodically-refreshed copy of that
database alongside the API's own database, merging both sources so
scheduler-produced content (bars, news, macro, briefs, debates,
evaluations) and API/CLI-produced content are both visible.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_SNAPSHOT_TTL_SECONDS = 10.0
_snapshot_state: tuple[float, Path] | None = None
_snapshot_lock = threading.Lock()



def scheduler_snapshot_path() -> Path | None:
    """Return a path to a fresh copy of the scheduler DB, or ``None``.

    The copy (DB + WAL) is refreshed at most once per
    ``_SNAPSHOT_TTL_SECONDS``. Stale WAL files from a previous refresh
    are removed first so the copied DB always matches its WAL. A lock
    serializes concurrent dashboard polls during the first refresh.
    """
    global _snapshot_state
    src_dir = os.environ.get("ALPHABRIEF_SCHEDULER_DB_DIR", "").strip()
    if not src_dir:
        return None
    src = Path(src_dir) / "alphabrief.db"
    if not src.is_file():
        return None
    now = time.monotonic()
    if (
        _snapshot_state is not None
        and now - _snapshot_state[0] < _SNAPSHOT_TTL_SECONDS
    ):
        return _snapshot_state[1]
    with _snapshot_lock:
        # Re-check under the lock: another thread may have refreshed.
        if (
            _snapshot_state is not None
            and time.monotonic() - _snapshot_state[0] < _SNAPSHOT_TTL_SECONDS
        ):
            return _snapshot_state[1]
        dst_dir = Path(tempfile.gettempdir()) / "alphabrief_scheduler_snapshot"
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / "alphabrief.db"
        dst_wal = dst.with_name("alphabrief.db.wal")
        if dst_wal.exists():
            dst_wal.unlink()
        shutil.copy2(src, dst)
        src_wal = src.with_name("alphabrief.db.wal")
        if src_wal.is_file():
            shutil.copy2(src_wal, dst_wal)
        _snapshot_state = (time.monotonic(), dst)
        return dst


def open_snapshot_store[U](factory: Callable[[Path], U]) -> U | None:
    """Open *factory* on the scheduler-DB snapshot, or ``None``.

    Returns ``None`` when the scheduler DB is not configured (the route
    then serves only the API's own database).
    """
    snapshot = scheduler_snapshot_path()
    if snapshot is None:
        return None
    return factory(snapshot)


def merge_dedupe(
    local: list[Any],
    snapshot: list[Any],
    *,
    key: Callable[[Any], Any],
    sort_key: Callable[[Any], Any],
    reverse: bool = True,
) -> list[Any]:
    """Merge two result lists, deduplicated by *key*, newest-first.

    The snapshot (scheduler DB) wins on ties so scheduler-produced
    content is not shadowed by stale API rows.
    """
    merged: dict[Any, Any] = {}
    for item in snapshot:
        merged[key(item)] = item
    for item in local:
        merged.setdefault(key(item), item)
    return sorted(merged.values(), key=sort_key, reverse=reverse)


def reset_snapshot_cache() -> None:
    """Clear the cached snapshot path (test isolation)."""
    global _snapshot_state
    _snapshot_state = None
