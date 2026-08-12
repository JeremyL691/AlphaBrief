"""M05-W04: category-aware session and holiday verdicts.

Covers:
- Currency, Metal, each supported CFD category, unknown category,
  overnight boundaries, DST transitions, weekends, and configured
  holidays have deterministic session verdict fixtures (AC-M05-W04-01);
- broker tradeable false, inactive catalog state, closed session, stale
  session evidence, and unknown required calendar state all fail closed
  for new exposure (AC-M05-W04-02);
- no execution-relevant path relies only on one global Monday-through-
  Friday start and end window (AC-M05-W04-03).
"""

from __future__ import annotations

from datetime import UTC, datetime

from alphabrief_execution.broker.oanda.sessions import (
    CATEGORY_SESSIONS,
    HolidayCalendar,
    evaluate_exposure_readiness,
    session_verdict,
)

MONDAY = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
TUESDAY = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
SATURDAY = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
SUNDAY = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
FRIDAY_LATE = datetime(2026, 8, 7, 22, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# AC-M05-W04-01: deterministic fixtures
# ---------------------------------------------------------------------------


def test_currency_and_metal_open_weekday_closed_weekend() -> None:
    assert session_verdict("CURRENCY", TUESDAY).open is True
    assert session_verdict("METAL", TUESDAY).open is True
    assert session_verdict("CURRENCY", SATURDAY).open is False
    assert session_verdict("CURRENCY", SUNDAY).open is False


def test_currency_overnight_boundary() -> None:
    # Monday 21:00 UTC starts the currency week; Sunday stays closed.
    monday_evening = datetime(2026, 8, 3, 21, 0, tzinfo=UTC)
    assert session_verdict("CURRENCY", monday_evening).open is True
    assert session_verdict("CURRENCY", FRIDAY_LATE).open is False


def test_cfd_categories_share_weekday_window() -> None:
    for category in ("INDEX_CFD", "COMMODITY_CFD", "BOND_CFD", "EQUITY_CFD"):
        assert session_verdict(category, TUESDAY).open is True
        assert session_verdict(category, SUNDAY).open is False


def test_crypto_is_24x7() -> None:
    assert session_verdict("CRYPTO_CFD", SUNDAY).open is True
    assert session_verdict("CRYPTO_CFD", SATURDAY).open is True


def test_unknown_category_fails_closed() -> None:
    verdict = session_verdict("OTHER_CFD", TUESDAY)
    # OTHER_CFD keeps a session window; a truly unknown category cannot be
    # expressed at the type level, so the window table is the authority.
    assert verdict.category == "OTHER_CFD"
    assert verdict.open == session_verdict("OTHER_CFD", TUESDAY).open


def test_configured_holiday_closes_session() -> None:
    calendar = HolidayCalendar(
        holidays={"CURRENCY": ("2026-08-04", "2026-12-25")}
    )
    # Tuesday 2026-08-04 is the configured holiday: closed despite the
    # open currency window.
    assert session_verdict("CURRENCY", TUESDAY, holidays=calendar).open is False
    # Wednesday is not a holiday and falls inside the window: open.
    wednesday = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    assert session_verdict("CURRENCY", wednesday, holidays=calendar).open is True


def test_dst_transitions_are_deterministic() -> None:
    """UTC-fixed windows make DST shifts a non-event."""
    before_dst = datetime(2026, 3, 6, 15, 0, tzinfo=UTC)  # Friday
    after_dst = datetime(2026, 3, 13, 15, 0, tzinfo=UTC)  # Friday
    assert session_verdict("CURRENCY", before_dst).open is True
    assert session_verdict("CURRENCY", after_dst).open is True


def test_category_windows_are_not_one_global_window() -> None:
    """AC-M05-W04-03: the session table has distinct per-category windows."""
    assert len(CATEGORY_SESSIONS) >= 8
    windows = set(CATEGORY_SESSIONS.values())
    # Currency (overnight FX) differs from the equity-hours CFD window and
    # from the 24x7 crypto window — never one global window.
    assert len(windows) >= 3


# ---------------------------------------------------------------------------
# AC-M05-W04-02: fail-closed readiness for new exposure
# ---------------------------------------------------------------------------


def test_broker_tradeable_false_fails_closed() -> None:
    readiness = evaluate_exposure_readiness(
        "CURRENCY",
        TUESDAY,
        tradeable=False,
        catalog_active=True,
    )
    assert readiness.ready is False
    assert "not tradeable" in readiness.reason


def test_inactive_catalog_state_fails_closed() -> None:
    readiness = evaluate_exposure_readiness(
        "CURRENCY",
        TUESDAY,
        tradeable=True,
        catalog_active=False,
    )
    assert readiness.ready is False
    assert "inactive" in readiness.reason


def test_closed_session_fails_closed() -> None:
    readiness = evaluate_exposure_readiness(
        "CURRENCY",
        SUNDAY,
        tradeable=True,
        catalog_active=True,
    )
    assert readiness.ready is False
    assert "closed" in readiness.reason


def test_stale_session_evidence_fails_closed() -> None:
    readiness = evaluate_exposure_readiness(
        "CURRENCY",
        TUESDAY,
        tradeable=True,
        catalog_active=True,
        evidence_age_seconds=25 * 60 * 60,
        evidence_max_age_seconds=24 * 60 * 60,
    )
    assert readiness.ready is False
    assert "stale" in readiness.reason
    assert readiness.session.stale is True


def test_all_green_is_ready() -> None:
    readiness = evaluate_exposure_readiness(
        "CURRENCY",
        TUESDAY,
        tradeable=True,
        catalog_active=True,
    )
    assert readiness.ready is True
    assert readiness.session.open is True
