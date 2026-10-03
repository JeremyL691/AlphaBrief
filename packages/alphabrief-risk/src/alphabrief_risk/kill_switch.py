"""Deterministic, durable kill switch for AlphaBrief order flow.

The persisted switch blocks new exposure while verified reduce-only exits
remain available. Automatic drawdown halts cannot be manually released.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any

import duckdb
from alphabrief_core import paths as _paths

from .drawdown_policy import DrawdownStateStore, DrawdownVerdict, evaluate_drawdown

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS kill_switch_state (
    scope       TEXT PRIMARY KEY,
    active      BOOLEAN NOT NULL,
    reason      TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    automatic   BOOLEAN NOT NULL DEFAULT FALSE
)
"""

#: One switch for the whole runtime.
DEFAULT_SCOPE = "default"
_DRAWDOWN_LOCK = Lock()


@dataclass
class KillSwitch:
    """Blocks new exposure when activated."""

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
        read_only: bool = False,
    ) -> None:
        self._db_path = Path(db_path) if db_path is not None else _paths.db_path()
        if not read_only:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path), read_only=read_only)
        if not read_only:
            self._conn.execute(_CREATE_TABLE)
        columns = self._conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'kill_switch_state'"
        ).fetchall()
        self._has_table = bool(columns)
        self._has_automatic = ("automatic",) in columns
        if not read_only and not self._has_automatic:
            # DuckDB's ADD COLUMN IF NOT EXISTS with a DEFAULT can overwrite
            # existing values. Migrate only an actually absent legacy column.
            self._conn.execute(
                "ALTER TABLE kill_switch_state ADD COLUMN "
                "automatic BOOLEAN DEFAULT FALSE"
            )
            self._has_automatic = True
        self._read_only = read_only
        self._scope = scope

    def load(self) -> dict[str, Any] | None:
        """Return the persisted state, or ``None`` when never set."""
        if not self._has_table:
            return None
        automatic = "automatic" if self._has_automatic else "FALSE"
        row = self._conn.execute(
            f"SELECT active, reason, updated_at, {automatic} FROM kill_switch_state "
            "WHERE scope = ?",
            [self._scope],
        ).fetchone()
        if row is None:
            return None
        if (
            not isinstance(row[0], bool) or not isinstance(row[3], bool)
            or not isinstance(row[1], str) or not row[1].strip()
            or not isinstance(row[2], datetime) or row[2].tzinfo is None
            or (row[3] and not row[0])
        ):
            raise ValueError("invalid_kill_switch_state")
        return {
            "active": bool(row[0]),
            "reason": str(row[1]),
            "updated_at": row[2].astimezone(UTC).isoformat(),
            "automatic": row[3],
        }

    def activate(self, *, reason: str, automatic: bool = False) -> dict[str, Any]:
        """Persist an active switch; a blank reason is refused."""
        if not reason.strip():
            raise ValueError("kill switch reason must not be blank")
        return self._write(active=True, reason=reason, automatic=automatic)

    def deactivate(self, *, reason: str = "manual deactivate") -> dict[str, Any]:
        """Persist an inactive switch, recording why it was released."""
        with _DRAWDOWN_LOCK:
            exists = self._conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'ai_drawdown_state'"
            ).fetchone()
            if exists is not None and self._conn.execute(
                "SELECT 1 FROM ai_drawdown_state WHERE state = 'soak_halted' LIMIT 1"
            ).fetchone() is not None:
                # A crash/write failure between drawdown persistence and switch
                # activation must never make that halt manually releasable.
                raise ValueError("automatic_kill_switch_cannot_be_released")
            return self._write(active=False, reason=reason, automatic=False)

    def _write(
        self, *, active: bool, reason: str, automatic: bool
    ) -> dict[str, Any]:
        if self._read_only:
            raise ValueError("kill_switch_store_read_only")
        if not reason.strip():
            raise ValueError("kill switch reason must not be blank")
        # Validate existing rows before permitting any mutation.
        self.load()
        now = datetime.now(UTC)
        row = self._conn.execute(
            """
            INSERT INTO kill_switch_state (scope, active, reason, updated_at, automatic)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (scope) DO UPDATE SET
                active = EXCLUDED.active,
                reason = CASE WHEN kill_switch_state.automatic
                    THEN kill_switch_state.reason ELSE EXCLUDED.reason END,
                updated_at = CASE WHEN kill_switch_state.automatic
                    THEN kill_switch_state.updated_at ELSE EXCLUDED.updated_at END,
                automatic = kill_switch_state.automatic OR EXCLUDED.automatic
            WHERE NOT kill_switch_state.automatic OR EXCLUDED.active
            RETURNING active, reason, updated_at, automatic
            """,
            [self._scope, active, reason, now, automatic],
        ).fetchone()
        if row is None:
            raise ValueError("automatic_kill_switch_cannot_be_released")
        state = self.load()
        assert state is not None
        return state

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


def load_persisted_kill_switch() -> KillSwitch:
    """Refresh the switch from the authoritative runtime database."""
    store = KillSwitchStore()
    try:
        return KillSwitch.from_store(store)
    finally:
        store.close()


def observe_drawdown(
    *, account_id: str, nav: Decimal, now: datetime
) -> DrawdownVerdict:
    """Advance real NAV observations and latch the automatic emergency stop."""
    if not account_id.strip():
        raise ValueError("drawdown_account_required")
    if not isinstance(nav, Decimal) or not nav.is_finite() or nav < 0:
        raise ValueError("drawdown_nav_invalid")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("drawdown_clock_invalid")
    # Entry-context and resident-monitor workers share one writer process.
    # Serialize read/advance/save so an older observation cannot undo a halt.
    with _DRAWDOWN_LOCK:
        store = DrawdownStateStore()
        try:
            previous = store.load(account_id)
            if previous is not None and (
                previous.state not in {"normal", "blocked", "half_risk", "soak_halted"}
                or previous.updated_at is None or previous.updated_at.tzinfo is None
                or previous.updated_at > now
            ):
                raise ValueError("drawdown_state_invalid")
            high_water = previous.high_water if previous is not None else nav
            if high_water is None or not high_water.is_finite() or high_water <= 0:
                raise ValueError("drawdown_high_water_invalid")
            verdict = evaluate_drawdown(
                equity=nav, high_water=high_water, now=now, previous=previous
            )
            store.save(account_id, verdict.state)
        finally:
            store.close()
        if verdict.state.state == "soak_halted":
            switch = KillSwitchStore()
            try:
                switch.activate(reason=verdict.reason, automatic=True)
            finally:
                switch.close()
        return verdict
