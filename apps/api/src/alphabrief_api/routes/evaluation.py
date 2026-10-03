"""Evaluation routes — shadow benchmark evaluation and scoreboard.

PROJECT_GUIDE 5.11.
"""

from __future__ import annotations

import logging
from typing import Any

from alphabrief_core import paths as _paths
from alphabrief_trader.shadow_store import ShadowStore
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])


class ScoreboardResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    scoreboard: dict[str, list[dict[str, Any]]]


@router.get("/scoreboard", response_model=ScoreboardResponse)
def get_scoreboard() -> ScoreboardResponse:
    """Return the 4h and 24h forward-return scoreboard for all benchmarks."""
    store = ShadowStore(db_path=_paths.db_path())
    try:
        board = store.scoreboard()
        return ScoreboardResponse(scoreboard=board)
    finally:
        store.close()


@router.get("/decisions")
def get_recent_decisions(
    limit: int = Query(50, ge=1, le=500),
    symbol: str | None = Query(None),
) -> dict[str, Any]:
    """Return recent shadow decisions."""
    store = ShadowStore(db_path=_paths.db_path())
    try:
        query = (
            "SELECT cycle_id, symbol, benchmark, side, source, detail, "
            "entry_mid, decided_at FROM ai_shadow_decisions "
        )
        params: list[Any] = []
        if symbol:
            query += "WHERE symbol = ? "
            params.append(symbol)
        query += "ORDER BY decided_at DESC LIMIT ?"
        params.append(limit)
        rows = store._conn.execute(query, params).fetchall()
        decisions = [
            {
                "cycle_id": r[0],
                "symbol": r[1],
                "benchmark": r[2],
                "side": r[3],
                "source": r[4],
                "detail": r[5],
                "entry_mid": str(r[6]) if r[6] is not None else None,
                "decided_at": (
                    r[7].isoformat() if hasattr(r[7], "isoformat") else str(r[7])
                ),
            }
            for r in rows
        ]
        return {"decisions": decisions}
    finally:
        store.close()


__all__ = ["router"]
