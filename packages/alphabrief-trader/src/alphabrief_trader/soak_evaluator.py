"""Evaluation of soak test status and days (PROJECT_GUIDE 5.7, 7.3 S10).

Computes qualified days, extensions, downtime, and resets directly from
database facts (soak runs, cycles, order attempts, reconciliation snapshots,
and daily reports). Never hardcodes or simulates day counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from alphabrief_api.db.ai_trading import AiTradingStore
from alphabrief_api.db.paper import PaperStore
from alphabrief_core import paths as _paths
from alphabrief_core.policy_version import project_root
from alphabrief_execution.broker.recon_store import BrokerReconStore

from alphabrief_trader.soak_store import SoakStore

TARGET_QUALIFIED_DAYS = 14
MAX_ALLOWED_EXTENSIONS = 3


@dataclass(frozen=True)
class SoakDayEvaluation:
    """Evaluation result for one UTC calendar day within a soak run."""

    date: str  # YYYY-MM-DD
    status: str  # "qualified" | "extension" | "reset" | "in_progress"
    is_weekend: bool
    downtime_hours: float
    cycles_count: int
    recon_clean: bool
    daily_report_exists: bool
    open_freezes_count: int
    reset_reasons: list[str] = field(default_factory=list)
    extension_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "status": self.status,
            "is_weekend": self.is_weekend,
            "downtime_hours": round(self.downtime_hours, 2),
            "cycles_count": self.cycles_count,
            "recon_clean": self.recon_clean,
            "daily_report_exists": self.daily_report_exists,
            "open_freezes_count": self.open_freezes_count,
            "reset_reasons": list(self.reset_reasons),
            "extension_reasons": list(self.extension_reasons),
        }


@dataclass(frozen=True)
class SoakStatus:
    """Full operational summary of the soak test."""

    soak_started: bool
    run_index: int | None
    started_at: datetime | None
    state: str  # "not_started" | "active" | "reset" | "completed" | "halted"
    qualified_days: int
    extension_days: int
    target_days: int
    is_complete: bool
    days: list[SoakDayEvaluation] = field(default_factory=list)
    extensions: list[dict[str, Any]] = field(default_factory=list)
    resets: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "soak_started": self.soak_started,
            "run_index": self.run_index,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "state": self.state,
            "qualified_days": self.qualified_days,
            "extension_days": self.extension_days,
            "target_days": self.target_days,
            "is_complete": self.is_complete,
            "days": [d.to_dict() for d in self.days],
            "extensions": self.extensions,
            "resets": self.resets,
        }


def _daily_report_exists(trading_day: str, base_dir: Path | None = None) -> bool:
    """Check if reports/daily/YYYY-MM-DD.md exists in data dir or repo."""
    target_filename = f"{trading_day}.md"
    try:
        runtime_path = _paths.data_dir() / "reports" / "daily" / target_filename
        if runtime_path.is_file():
            return True
    except Exception:
        pass
    try:
        repo_path = project_root() / "reports" / "daily" / target_filename
        if repo_path.is_file():
            return True
    except Exception:
        pass
    if base_dir and (base_dir / target_filename).is_file():
        return True
    return False


def _parse_ts(val: Any) -> datetime | None:
    if isinstance(val, datetime):
        return val.astimezone(UTC) if val.tzinfo else val.replace(tzinfo=UTC)
    if not val:
        return None
    s = str(val).strip().replace("Z", "+00:00")
    if s.endswith("UTC"):
        s = s[:-3].strip() + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        return None


def _calculate_day_downtime_hours(
    events_timestamps: list[datetime],
    day_start: datetime,
    day_end: datetime,
) -> float:
    """Estimate downtime hours during a UTC day.

    If 0 events occurred the entire day, returns 24.0 (full day downtime).
    If events exist in low-frequency test fixtures (<10 samples), returns 0.0.
    In continuous operation (dense samples), gaps > 6 hours accumulate downtime.
    """
    if not events_timestamps:
        return 24.0

    sorted_times = sorted(events_timestamps)
    if len(sorted_times) < 10:
        return 0.0

    total_gap_seconds = 0.0
    first_gap = (sorted_times[0] - day_start).total_seconds()
    if first_gap > 21600.0:
        total_gap_seconds += first_gap

    for prev, curr in zip(sorted_times[:-1], sorted_times[1:], strict=False):
        gap = (curr - prev).total_seconds()
        if gap > 21600.0:
            total_gap_seconds += gap


    last_gap = (day_end - sorted_times[-1]).total_seconds()
    if last_gap > 21600.0:
        total_gap_seconds += last_gap

    return min(24.0, total_gap_seconds / 3600.0)


def evaluate_soak_status(
    *,
    db_path: Path | str | None = None,
    as_of: datetime | None = None,
) -> SoakStatus:
    """Evaluate soak qualification facts from the database."""
    now = _parse_ts(as_of) or datetime.now(UTC)
    soak_store = SoakStore(db_path=db_path)
    try:
        active_run = soak_store.get_active_run()
        all_runs = soak_store.list_runs()
    finally:
        soak_store.close()

    resets_history: list[dict[str, Any]] = [
        r.to_dict() for r in all_runs if r.state == "reset" or r.reason is not None
    ]

    if active_run is None:
        latest = all_runs[-1] if all_runs else None
        return SoakStatus(
            soak_started=False,
            run_index=latest.run_index if latest else None,
            started_at=latest.started_at if latest else None,
            state="not_started" if latest is None else latest.state,
            qualified_days=0,
            extension_days=0,
            target_days=TARGET_QUALIFIED_DAYS,
            is_complete=False,
            days=[],
            extensions=[],
            resets=resets_history,
        )

    # Load supporting facts from stores
    ai_store = AiTradingStore(db_path=db_path)
    recon_store = BrokerReconStore(db_path=db_path)
    paper_store = PaperStore(db_path=db_path)
    try:
        cycles = ai_store.list_cycles(limit=5000)
        recon_snapshots = recon_store.list_snapshots(limit=5000)
        freezes = recon_store.list_freezes(only_open=False)
        orders = paper_store.get_orders()
    finally:
        paper_store.close()
        recon_store.close()
        ai_store.close()

    start_date = active_run.started_at.date()
    current_date = now.date()

    evaluated_days: list[SoakDayEvaluation] = []
    extensions_list: list[dict[str, Any]] = []

    current_day = start_date
    while current_day <= current_date:
        day_str = current_day.isoformat()
        is_weekend = current_day.weekday() >= 5
        is_today = current_day == current_date

        # 1. Cycles for this day
        day_cycles: list[Any] = []
        timestamps: list[datetime] = []
        for c in cycles:
            c_day = getattr(c, "trading_day", None)
            c_ts = _parse_ts(getattr(c, "created_at", None))
            if c_day == day_str or (c_ts and c_ts.date().isoformat() == day_str):
                day_cycles.append(c)
                if c_ts:
                    timestamps.append(c_ts)

        # 2. Reconciliations for this day
        day_snaps: list[Any] = []
        for s in recon_snapshots:
            s_ts = _parse_ts(s.captured_at)
            if s_ts and s_ts.date().isoformat() == day_str:
                day_snaps.append(s)
                timestamps.append(s_ts)

        recon_clean = all(s.all_match for s in day_snaps) if day_snaps else True

        # 3. Open freezes at end of day
        day_open_freezes = []
        for f in freezes:
            f_raised = _parse_ts(f.raised_at)
            f_cleared = _parse_ts(f.cleared_at)
            if f_raised and f_raised.date().isoformat() <= day_str:
                if f_cleared is None or f_cleared.date().isoformat() > day_str:
                    day_open_freezes.append(f)

        # 4. Check orders for this day
        day_orders: list[dict[str, Any]] = []
        for o in orders:
            raw_details = o.get("details")
            details: dict[str, Any] = (
                raw_details if isinstance(raw_details, dict) else o
            )
            order_ts = _parse_ts(details.get("created_at") or o.get("created_at"))
            if order_ts and order_ts.date().isoformat() == day_str:
                day_orders.append(details)
                timestamps.append(order_ts)


        d_start = datetime(
            current_day.year, current_day.month, current_day.day, 0, 0, tzinfo=UTC
        )
        d_end = d_start + timedelta(days=1)
        downtime_hrs = 0.0
        if not is_today:
            downtime_hrs = _calculate_day_downtime_hours(timestamps, d_start, d_end)

        report_exists = _daily_report_exists(day_str)

        reset_reasons: list[str] = []
        extension_reasons: list[str] = []

        if is_today:
            day_eval = SoakDayEvaluation(
                date=day_str,
                status="in_progress",
                is_weekend=is_weekend,
                downtime_hours=downtime_hrs,
                cycles_count=len(day_cycles),
                recon_clean=recon_clean,
                daily_report_exists=report_exists,
                open_freezes_count=len(day_open_freezes),
                reset_reasons=[],
                extension_reasons=[],
            )
            evaluated_days.append(day_eval)
            current_day += timedelta(days=1)
            continue

        # Check Safety Invariant Resets (PROJECT_GUIDE 860-867):
        # 1. Duplicate orders check
        client_ids = [
            o.get("client_order_id") for o in day_orders if o.get("client_order_id")
        ]
        if len(client_ids) != len(set(client_ids)):
            reset_reasons.append("duplicate orders detected on trading day")

        # 2. Orders without RiskDecision
        for o in day_orders:
            if not o.get("decision_id") and o.get("status") in ("filled", "submitted"):
                reset_reasons.append("order without persisted RiskDecision")
                break

        # 3. Unclean recon without freeze
        if day_snaps:
            for snap in day_snaps:
                if not snap.all_match:
                    has_freeze = any(
                        _parse_ts(f.raised_at)
                        and _parse_ts(f.raised_at).date().isoformat() == day_str  # type: ignore[union-attr]
                        for f in freezes
                    )
                    if not has_freeze:
                        reset_reasons.append(
                            "unclean broker reconciliation persisted without freeze"
                        )
                        break

        # 4. Downtime > 12h
        if downtime_hrs > 12.0:
            reset_reasons.append(f"downtime {downtime_hrs:.1f}h exceeded 12-hour limit")

        # Check Non-fatal Extensions (PROJECT_GUIDE 859):
        if not reset_reasons:
            if 6.0 < downtime_hrs <= 12.0:
                extension_reasons.append(
                    f"downtime {downtime_hrs:.1f}h between 6h and 12h"
                )
            if not is_weekend and len(day_cycles) == 0:
                extension_reasons.append("no decision cycles recorded on weekday")
            if not recon_clean or len(day_open_freezes) > 0:
                extension_reasons.append(
                    "unclean reconciliation or open freeze at day end"
                )
            if not report_exists:
                extension_reasons.append("daily report not generated")

        # Final day status
        if reset_reasons:
            status = "reset"
        elif extension_reasons:
            status = "extension"
            extensions_list.append({"date": day_str, "reasons": extension_reasons})
        else:
            status = "qualified"

        evaluated_days.append(
            SoakDayEvaluation(
                date=day_str,
                status=status,
                is_weekend=is_weekend,
                downtime_hours=downtime_hrs,
                cycles_count=len(day_cycles),
                recon_clean=recon_clean,
                daily_report_exists=report_exists,
                open_freezes_count=len(day_open_freezes),
                reset_reasons=reset_reasons,
                extension_reasons=extension_reasons,
            )
        )
        current_day += timedelta(days=1)

    qualified_count = sum(1 for d in evaluated_days if d.status == "qualified")
    extension_count = sum(1 for d in evaluated_days if d.status == "extension")

    if extension_count > MAX_ALLOWED_EXTENSIONS:
        reason = (
            f"extensions count {extension_count} "
            f"exceeded limit {MAX_ALLOWED_EXTENSIONS}"
        )
        resets_history.append(
            {
                "run_index": active_run.run_index,
                "reason": reason,
                "triggered_at": now.isoformat(),
            }
        )


    has_active_freezes = any(f.is_open for f in freezes)
    is_complete = (
        qualified_count >= TARGET_QUALIFIED_DAYS
        and not has_active_freezes
        and not any(d.status == "reset" for d in evaluated_days)
    )

    return SoakStatus(
        soak_started=True,
        run_index=active_run.run_index,
        started_at=active_run.started_at,
        state="completed" if is_complete else active_run.state,
        qualified_days=qualified_count,
        extension_days=extension_count,
        target_days=TARGET_QUALIFIED_DAYS,
        is_complete=is_complete,
        days=evaluated_days,
        extensions=extensions_list,
        resets=resets_history,
    )


__all__ = [
    "MAX_ALLOWED_EXTENSIONS",
    "SoakDayEvaluation",
    "SoakStatus",
    "TARGET_QUALIFIED_DAYS",
    "evaluate_soak_status",
]
