"""Doctor API route — one-shot system diagnostics (PROJECT_GUIDE 4.9)."""

from __future__ import annotations

import logging
from typing import Any

from alphabrief_cli.doctor_commands import run_checks
from fastapi import APIRouter, Query

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/doctor", tags=["doctor"])

DEFAULT_SYMBOLS = ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD")


@router.get("/run")
def run_doctor_checks(
    offline: bool = Query(False, description="Run only local offline checks"),
    expect_daemon: bool = Query(True, description="Expect daemon to be running"),
) -> dict[str, Any]:
    """Execute one-shot doctor checks and return PASS/WARN/FAIL status."""
    report = run_checks(
        symbols=DEFAULT_SYMBOLS,
        expect_daemon=expect_daemon,
        include_network=not offline,
    )
    return report.to_dict()


__all__ = ["router"]
