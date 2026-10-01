"""Deterministic, durable kill switch for AlphaBrief order flow.

The kill switch blocks every order (including closes, per PROJECT_GUIDE
5.7 rule 1) and its state is **persisted**: a switch that silently resets
when the process restarts is not a kill switch. The store keeps one row in
the runtime database, and both the CLI and the dashboard operate it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from alphabrief_core import paths as _paths

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS kill_switch_state (
    scope       TEXT PRIMARY KEY,
    active      BOOLEAN NOT NULL,
    reason      TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
)
"""

#: One switch for the whole runtime.
DEFAULT_SCOPE = "default"


@dataclass
class KillSwitch:
    """Blocks all orders when activated."""

    active: bool = False
    reason: str = "kill switch inactive"

    def activate(self, reason: str) -> None:
        if reason.strip() == "":
            raise ValueError("kill switch reason must not be blank")
        self.active = True
        self.reason = reason

    def deactivate(self) -> None:
        self.active = False
        self.reason = "kill switch inactive"

    @classmethod
    def from_store(cls, store: KillSwitchStore) -> KillSwitch:
        """Load the persisted state, defaulting to inactive when unset."""
        state = store.load()
        if state is None:
            return cls()
        return cls(active=bool(state["active"]), reason=str(state["reason"]))


class KillSwitchStore:
    """DuckDB-backed durable kill-switch state."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        scope: str = DEFAULT_SCOPE,
    ) -> None:
        self._db_path = Path(db_path) if db_path is not None else _paths.db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLE)
        self._scope = scope

    def load(self) -> dict[str, Any] | None:
        """Return the persisted state, or ``None`` when never set."""
        row = self._conn.execute(
            "SELECT active, reason, updated_at FROM kill_switch_state "
            "WHERE scope = ?",
            [self._scope],
        ).fetchone()
        if row is None:
            return None
        return {
            "active": bool(row[0]),
            "reason": str(row[1]),
            "updated_at": str(row[2]),
        }

    def activate(self, *, reason: str) -> dict[str, Any]:
        """Persist an active switch; a blank reason is refused."""
        if not reason.strip():
            raise ValueError("kill switch reason must not be blank")
        return self._write(active=True, reason=reason)

    def deactivate(self, *, reason: str = "manual deactivate") -> dict[str, Any]:
        """Persist an inactive switch, recording why it was released."""
        return self._write(active=False, reason=reason)

    def _write(self, *, active: bool, reason: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        self._conn.execute(
            """
            INSERT INTO kill_switch_state (scope, active, reason, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (scope) DO UPDATE SET
                active = EXCLUDED.active,
                reason = EXCLUDED.reason,
                updated_at = EXCLUDED.updated_at
            """,
            [self._scope, active, reason, now],
        )
        return {"active": active, "reason": reason, "updated_at": now.isoformat()}

    def state_json(self) -> str:
        """JSON-safe view for the API and the dashboard."""
        return json.dumps(
            self.load() or {"active": False, "reason": "", "updated_at": None},
            sort_keys=True,
        )

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001 - closing twice is harmless
            pass


__all__ = ["DEFAULT_SCOPE", "KillSwitch", "KillSwitchStore"]
