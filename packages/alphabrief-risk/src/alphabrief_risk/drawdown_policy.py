"""Rule 11: the soak drawdown state machine (PROJECT_GUIDE 5.7).

Measured against the highest NAV seen during the soak:

* drawdown < 3% — normal, full size;
* 3% <= drawdown < 5% — no new exposure for 48 hours; after the window
  the system resumes at **half risk** until the drawdown recovers below
  3%;
* drawdown >= 5% — no new exposure for the remainder of the soak.

Closes and reconciliation are unaffected: the state only gates new
exposure. The state is persisted (see :class:`DrawdownStateStore`) so a
restart cannot reset a block, and it is recomputed from the broker's real
NAV and the persisted high-water mark, never from an in-memory counter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

import duckdb
from alphabrief_core import paths as _paths

#: Drawdown levels as fractions of the high-water mark.
DRAWDOWN_BLOCK_PCT = Decimal("0.03")
DRAWDOWN_HALT_PCT = Decimal("0.05")

#: How long new exposure stays blocked at the 3% level.
DRAWDOWN_BLOCK_HOURS = 48

#: The size multiplier applied after a 3% block expires.
DRAWDOWN_HALF_RISK_MULTIPLIER = Decimal("0.5")

DrawdownStateName = Literal["normal", "blocked", "half_risk", "soak_halted"]

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ai_drawdown_state (
    account_id    TEXT PRIMARY KEY,
    state         TEXT NOT NULL,
    triggered_at  TIMESTAMPTZ,
    blocked_until TIMESTAMPTZ,
    high_water    TEXT,
    updated_at    TIMESTAMPTZ NOT NULL
)
"""


@dataclass(frozen=True)
class DrawdownState:
    """The persisted drawdown state for one account."""

    state: DrawdownStateName = "normal"
    triggered_at: datetime | None = None
    blocked_until: datetime | None = None
    high_water: Decimal | None = None
    updated_at: datetime | None = None

    @property
    def blocks_entries(self) -> bool:
        return self.state in {"blocked", "soak_halted"}

    @property
    def risk_multiplier(self) -> Decimal:
        return (
            DRAWDOWN_HALF_RISK_MULTIPLIER
            if self.state == "half_risk"
            else Decimal("1")
        )


@dataclass(frozen=True)
class DrawdownVerdict:
    """One deterministic drawdown verdict for an entry decision."""

    state: DrawdownState
    drawdown_pct: Decimal
    blocked: bool
    risk_multiplier: Decimal
    reason: str
    code: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "state": self.state.state,
            "drawdown_pct": str(self.drawdown_pct),
            "blocked": self.blocked,
            "risk_multiplier": str(self.risk_multiplier),
            "reason": self.reason,
            "code": self.code,
        }


def drawdown_pct(*, equity: Decimal, high_water: Decimal) -> Decimal:
    """The drawdown from the high-water mark as a fraction (0..1)."""
    if high_water <= 0:
        raise ValueError("high_water must be positive")
    if equity >= high_water:
        return Decimal("0")
    return (high_water - equity) / high_water


def evaluate_drawdown(
    *,
    equity: Decimal,
    high_water: Decimal,
    now: datetime,
    previous: DrawdownState | None = None,
) -> DrawdownVerdict:
    """Advance the state machine one step from the real NAV.

    The state only ever tightens within a soak: a 5% drawdown latches
    ``soak_halted`` until the soak ends, and a 3% drawdown starts a 48h
    block whose expiry leaves the system at half risk until it recovers.
    """
    if equity < 0:
        raise ValueError("equity must not be negative")
    observed_at = now.astimezone(UTC)
    current = previous or DrawdownState()
    peak = max(current.high_water or Decimal("0"), equity, high_water)
    level = drawdown_pct(equity=equity, high_water=peak)

    if current.state == "soak_halted" or level >= DRAWDOWN_HALT_PCT:
        return DrawdownVerdict(
            state=DrawdownState(
                state="soak_halted",
                triggered_at=current.triggered_at or observed_at,
                blocked_until=None,
                high_water=peak,
                updated_at=observed_at,
            ),
            drawdown_pct=level,
            blocked=True,
            risk_multiplier=Decimal("0"),
            reason=(
                f"drawdown {level:.2%} of the high-water mark is at or beyond "
                f"the {DRAWDOWN_HALT_PCT:.0%} soak limit"
            ),
            code="DRAWDOWN",
        )

    if level >= DRAWDOWN_BLOCK_PCT:
        blocked_until = current.blocked_until
        triggered_at = current.triggered_at or observed_at
        if blocked_until is None:
            blocked_until = observed_at + timedelta(hours=DRAWDOWN_BLOCK_HOURS)
        if observed_at < blocked_until:
            return DrawdownVerdict(
                state=DrawdownState(
                    state="blocked",
                    triggered_at=triggered_at,
                    blocked_until=blocked_until,
                    high_water=peak,
                    updated_at=observed_at,
                ),
                drawdown_pct=level,
                blocked=True,
                risk_multiplier=Decimal("0"),
                reason=(
                    f"drawdown {level:.2%} is at or beyond "
                    f"{DRAWDOWN_BLOCK_PCT:.0%}; new exposure is blocked until "
                    f"{blocked_until.isoformat()}"
                ),
                code="DRAWDOWN",
            )
        return DrawdownVerdict(
            state=DrawdownState(
                state="half_risk",
                triggered_at=triggered_at,
                blocked_until=blocked_until,
                high_water=peak,
                updated_at=observed_at,
            ),
            drawdown_pct=level,
            blocked=False,
            risk_multiplier=DRAWDOWN_HALF_RISK_MULTIPLIER,
            reason=(
                f"the 48h drawdown block expired at {blocked_until.isoformat()}; "
                f"resuming at half risk until the drawdown recovers below "
                f"{DRAWDOWN_BLOCK_PCT:.0%}"
            ),
            code="",
        )

    # Recovered below the block level: clear the state.
    return DrawdownVerdict(
        state=DrawdownState(
            state="normal",
            triggered_at=None,
            blocked_until=None,
            high_water=peak,
            updated_at=observed_at,
        ),
        drawdown_pct=level,
        blocked=False,
        risk_multiplier=Decimal("1"),
        reason=f"drawdown {level:.2%} is within the {DRAWDOWN_BLOCK_PCT:.0%} limit",
        code="",
    )


class DrawdownStateStore:
    """DuckDB-backed persistence for one account's drawdown state."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _paths.db_path()
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLE_SQL)

    def load(self, account_id: str) -> DrawdownState | None:
        row = self._conn.execute(
            """
            SELECT state, triggered_at, blocked_until, high_water, updated_at
            FROM ai_drawdown_state WHERE account_id = ?
            """,
            [account_id],
        ).fetchone()
        if row is None:
            return None
        state, triggered_at, blocked_until, high_water, updated_at = row
        return DrawdownState(
            state=state,
            triggered_at=triggered_at,
            blocked_until=blocked_until,
            high_water=None if high_water is None else Decimal(str(high_water)),
            updated_at=updated_at,
        )

    def save(self, account_id: str, state: DrawdownState) -> None:
        self._conn.execute(
            """
            INSERT INTO ai_drawdown_state (
                account_id, state, triggered_at, blocked_until, high_water,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (account_id) DO UPDATE SET
                state = EXCLUDED.state,
                triggered_at = EXCLUDED.triggered_at,
                blocked_until = EXCLUDED.blocked_until,
                high_water = EXCLUDED.high_water,
                updated_at = EXCLUDED.updated_at
            """,
            [
                account_id,
                state.state,
                state.triggered_at,
                state.blocked_until,
                None if state.high_water is None else str(state.high_water),
                state.updated_at or datetime.now(UTC),
            ],
        )

    def clear(self) -> None:
        """Drop the state table (test isolation only)."""
        self._conn.execute("DROP TABLE IF EXISTS ai_drawdown_state")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "DRAWDOWN_BLOCK_HOURS",
    "DRAWDOWN_BLOCK_PCT",
    "DRAWDOWN_HALT_PCT",
    "DRAWDOWN_HALF_RISK_MULTIPLIER",
    "DrawdownState",
    "DrawdownStateName",
    "DrawdownStateStore",
    "DrawdownVerdict",
    "drawdown_pct",
    "evaluate_drawdown",
]
