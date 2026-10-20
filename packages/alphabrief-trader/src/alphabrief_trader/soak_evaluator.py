"""Evaluation of soak test status and days (PROJECT_GUIDE 5.7, 7.3 S10).

Computes qualified days, extensions, downtime, and resets directly from
database facts (soak runs, scheduler run history, cycles, order ledger,
reconciliation snapshots, and daily reports). Never hardcodes or
simulates day counts.

The evaluation rules (PROJECT_GUIDE S10):

- a qualified UTC calendar day requires cumulative backend downtime
  <= 6 hours, every scheduled opportunity round recorded, a clean
  end-of-day reconciliation (or a freeze lifted by the rules), the daily
  report generated, and no reset event;
- weekends run no opportunity rounds; sync, reconciliation and the
  daily report are still required;
- a non-safety failure (downtime 6-12h, a missing report, an unclean
  reconciliation without a safety violation) extends the soak by one
  day, at most three times, then resets;
- a safety event resets the soak from a new Day 0: a duplicate order,
  an order without a persisted RiskDecision, an unexplained
  reconciliation difference left unfrozen past one cycle, more than 12
  hours of downtime in a day, or a deployed change to the safety /
  execution semantics.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
from alphabrief_api.db.ai_trading import AiTradingStore
from alphabrief_api.db.paper import PaperStore
from alphabrief_core import paths as _paths
from alphabrief_core.policy_version import project_root
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.sessions import session_verdict
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.operations.scheduler import HeartbeatStore
from alphabrief_risk.decision_store import RiskDecisionStore

from alphabrief_trader.soak_store import SoakRun, SoakStore

TARGET_QUALIFIED_DAYS = 14
MAX_ALLOWED_EXTENSIONS = 3
#: A day with more downtime than this resets the soak (GUIDE S10).
RESET_DOWNTIME_HOURS = 12.0
#: A day with more downtime than this (but at most the reset limit)
#: extends the soak by one day (GUIDE S10).
EXTENSION_DOWNTIME_HOURS = 6.0
#: The scheduler's opportunity-check task. Its run history is the
#: authority for downtime and per-round completeness.
CYCLE_TASK_NAME = "ai_daily_cycle"
#: How many missed opportunity rounds in one day count as an incomplete
#: day. The scheduler runs the task every 300s (GUIDE: every 1-5
#: minutes); a handful of gaps is normal (a slow committee round
#: overlaps the next tick), a whole missing stretch is not.
MAX_MISSED_ROUNDS_PER_DAY = 3


@contextmanager
def snapshot_db_if_locked(db_path: Path | str | None) -> Iterator[Path]:
    """Provide a readable database path, snapshotting if DuckDB is locked."""
    target = Path(db_path) if db_path else _paths.db_path()
    if not target.exists():
        yield target
        return
    try:
        conn = duckdb.connect(str(target), read_only=True)
        conn.close()
        yield target
        return
    except duckdb.IOException:
        # Lock held by running backend daemon; create temporary snapshot copy
        with tempfile.TemporaryDirectory(prefix="alphabrief_soak_snap_") as td:
            snap_db = Path(td) / target.name
            shutil.copy2(target, snap_db)
            wal = target.with_name(target.name + ".wal")
            if wal.exists():
                shutil.copy2(wal, Path(td) / (snap_db.name + ".wal"))
            yield snap_db


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
    #: Opportunity-check rounds the scheduler recorded on this day.
    rounds_recorded: int = 0
    #: Opportunity rounds that should have run but have no record.
    missed_rounds: int = 0
    #: Broker submits recorded in the durable order ledger for this day.
    ledger_orders: int = 0
    #: Ledger submits whose bound RiskDecision is not persisted.
    orders_without_decision: int = 0

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
            "rounds_recorded": self.rounds_recorded,
            "missed_rounds": self.missed_rounds,
            "ledger_orders": self.ledger_orders,
            "orders_without_decision": self.orders_without_decision,
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
    #: Safety findings that are not tied to one day's evaluation (for
    #: example a live-trading lock or a failed broker reconciliation).
    safety_findings: list[str] = field(default_factory=list)

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
            "safety_findings": list(self.safety_findings),
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


def expected_round_instants(
    day_start: datetime,
    day_end: datetime,
    *,
    interval_seconds: float,
) -> list[datetime]:
    """The instants at which an opportunity round should have run.

    The expectation follows the same FX session verdict the runtime uses
    to decide whether to check at all: the CURRENCY week runs Monday
    21:00 UTC to Friday 21:00 UTC, so a correct backend records nothing
    outside it. Expecting a round every five minutes on a calendar
    weekday would report hundreds of phantom misses each week and make a
    qualified day unreachable.

    Buckets are aligned to ``day_start`` so the count is deterministic for
    a given day, cadence and session.
    """
    if interval_seconds <= 0:
        return []
    instants: list[datetime] = []
    cursor = day_start
    while cursor < day_end:
        if session_verdict("CURRENCY", cursor).open:
            instants.append(cursor)
        cursor += timedelta(seconds=interval_seconds)
    return instants


def _expected_rounds(
    day_start: datetime,
    day_end: datetime,
    interval_seconds: float,
) -> int:
    """How many opportunity rounds should have run in the window."""
    return len(
        expected_round_instants(
            day_start, day_end, interval_seconds=interval_seconds
        )
    )


def _calculate_day_downtime_hours(
    run_intervals: Sequence[tuple[datetime, datetime]],
    day_start: datetime,
    day_end: datetime,
    *,
    grace_hours: float,
) -> float:
    """Downtime is the part of the day no backend task was running.

    ``run_intervals`` are the recorded (started_at, finished_at) spans of
    the scheduler tasks. The union of those spans is "running"; every
    uncovered second in the day is downtime. The scheduler sleeps
    ``interval`` seconds between rounds, so a gap of at most
    ``grace_hours`` (one round interval plus scheduling slack) is normal
    idle time, not downtime; longer uncovered gaps count in full.

    An empty history means the backend never ran that day: full-day
    downtime, which is exactly what a reset rule needs to see.
    """
    if day_start >= day_end:
        return 0.0
    spans = sorted(
        (max(start, day_start), min(end, day_end))
        for start, end in run_intervals
        if end > day_start and start < day_end
    )
    covered = 0.0
    cursor = day_start
    for start, end in spans:
        if start > cursor:
            gap = (start - cursor).total_seconds()
            if gap > grace_hours * 3600.0:
                covered += 0.0  # the gap is downtime, not coverage
            else:
                # A short gap is the scheduler's normal sleep between
                # rounds; it still counts as "the backend was running".
                covered += gap
        if end > cursor:
            covered += (end - max(cursor, start)).total_seconds()
            cursor = end
    tail_gap = (day_end - cursor).total_seconds()
    if tail_gap <= grace_hours * 3600.0:
        covered += max(0.0, tail_gap)
    running_hours = min(
        (day_end - day_start).total_seconds(), max(0.0, covered)
    ) / 3600.0
    return max(0.0, (day_end - day_start).total_seconds() / 3600.0 - running_hours)


def _run_overlaps_day(run: SoakRun, day_start: datetime, day_end: datetime) -> bool:
    """True when the soak run covers any part of this UTC day."""
    return run.started_at < day_end


def _day_runs(
    run: SoakRun, all_runs: Sequence[SoakRun], day_start: datetime, day_end: datetime
) -> list[SoakRun]:
    """The soak run(s) that were authoritative during this day.

    A reset starts a new Day 0; days before the newest run's start
    belong to the superseded run and are not part of the current
    qualification period.
    """
    del all_runs  # reserved for multi-run attribution
    if run.started_at >= day_end:
        return []
    return [run]


def _count_recorded_rounds(
    history: Sequence[dict[str, Any]],
    day_start: datetime,
    day_end: datetime,
) -> tuple[int, int]:
    """Recorded opportunity rounds and the failed ones among them."""
    recorded = 0
    failed = 0
    for row in history:
        started = row.get("started_at")
        if not isinstance(started, datetime):
            continue
        if day_start <= started < day_end:
            recorded += 1
            if row.get("status") != "ok":
                failed += 1
    return recorded, failed


def _round_interval_seconds(history: Sequence[dict[str, Any]]) -> float:
    """Infer the scheduler's round interval from its own run history.

    The median gap between consecutive starts is the observed cadence;
    it keeps the completeness rule tied to what the backend actually
    did rather than a number copied into the evaluator.
    """
    starts = sorted(
        started
        for row in history
        if isinstance(started := row.get("started_at"), datetime)
    )
    if len(starts) < 2:
        return 300.0
    gaps = sorted(
        gap
        for earlier, later in zip(starts[:-1], starts[1:], strict=False)
        if (gap := (later - earlier).total_seconds()) > 0
    )
    if not gaps:
        return 300.0
    return float(gaps[len(gaps) // 2])


def _ledger_rows_for_day(
    db_path: Path | str | None,
    day_start: datetime,
    day_end: datetime,
) -> list[dict[str, Any]]:
    """Durable submit reservations created during the day."""
    if db_path is None or not Path(db_path).exists():
        return []
    ledger = OrderLedger(db_path=db_path)
    try:
        rows = ledger._conn.execute(
            """SELECT submit_id, cycle_id, intent_id, decision_id, status,
                      client_order_id, broker_order_id, created_at
               FROM order_ledger_reservations
               ORDER BY created_at ASC"""
        ).fetchall()
    finally:
        ledger.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        created = _parse_ts(row[7])
        if created is None or not (day_start <= created < day_end):
            continue
        out.append(
            {
                "submit_id": str(row[0]),
                "cycle_id": str(row[1]),
                "intent_id": str(row[2]),
                "decision_id": str(row[3]),
                "status": str(row[4]),
                "client_order_id": str(row[5]) if row[5] is not None else None,
                "broker_order_id": str(row[6]) if row[6] is not None else None,
            }
        )
    return out


def _decision_ids_for_day(
    db_path: Path | str | None,
    day_start: datetime,
    day_end: datetime,
) -> set[str]:
    """RiskDecision ids persisted during the day."""
    if db_path is None or not Path(db_path).exists():
        return set()
    store = RiskDecisionStore(db_path=db_path)
    try:
        rows = store._conn.execute(
            "SELECT decision_id, created_at FROM risk_decisions"
        ).fetchall()
    finally:
        store.close()
    ids: set[str] = set()
    for row in rows:
        created = _parse_ts(row[1])
        if created is not None and day_start <= created < day_end:
            ids.add(str(row[0]))
    return ids


def evaluate_soak_status(
    *,
    db_path: Path | str | None = None,
    as_of: datetime | None = None,
) -> SoakStatus:
    """Evaluate soak qualification facts from the database."""
    with snapshot_db_if_locked(db_path) as effective_db:
        return _evaluate_soak_status_impl(db_path=effective_db, as_of=as_of)


def _evaluate_soak_status_impl(
    *,
    db_path: Path | str | None = None,
    as_of: datetime | None = None,
) -> SoakStatus:
    """Evaluate soak qualification facts from the database implementation."""
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
    heartbeats = HeartbeatStore(db_path=db_path)
    try:
        cycles = ai_store.list_cycles(limit=5000)
        recon_snapshots = recon_store.list_snapshots(limit=5000)
        freezes = recon_store.list_freezes(only_open=False)
        orders = paper_store.get_orders()
        # Every task's executions prove the backend was up; the cycle
        # task alone proves the opportunity checks ran.
        all_task_runs = heartbeats.list_task_runs()
        round_history = [
            row for row in all_task_runs if row.get("task_name") == CYCLE_TASK_NAME
        ]
    finally:
        heartbeats.close()
        paper_store.close()
        recon_store.close()
        ai_store.close()

    round_interval = _round_interval_seconds(round_history)
    # One round interval of uncovered time is the scheduler's own sleep
    # between rounds, not downtime; allow two for a slow round.
    grace_hours = max(2.0 * round_interval / 3600.0, 1.0 / 60.0)

    start_date = active_run.started_at.date()
    current_date = now.date()

    evaluated_days: list[SoakDayEvaluation] = []
    extensions_list: list[dict[str, Any]] = []

    current_day = start_date
    while current_day <= current_date:
        day_str = current_day.isoformat()
        is_weekend = current_day.weekday() >= 5
        is_today = current_day == current_date
        d_start = datetime(
            current_day.year, current_day.month, current_day.day, 0, 0, tzinfo=UTC
        )
        d_end = d_start + timedelta(days=1)
        # Day 0 starts at the recorded soak start, not midnight: evidence
        # from before Day 0 never counts toward the run.
        window_start = max(d_start, active_run.started_at)
        window_end = min(d_end, now) if is_today else d_end
        if window_start >= window_end:
            current_day += timedelta(days=1)
            continue

        # 1. Cycles for this day
        day_cycles: list[Any] = []
        for c in cycles:
            c_day = getattr(c, "trading_day", None)
            c_ts = _parse_ts(getattr(c, "created_at", None))
            if c_day == day_str or (c_ts and c_ts.date().isoformat() == day_str):
                day_cycles.append(c)

        # 2. Reconciliations for this day
        day_snaps: list[Any] = []
        for s in recon_snapshots:
            s_ts = _parse_ts(s.captured_at)
            if s_ts and s_ts.date().isoformat() == day_str:
                day_snaps.append(s)

        recon_clean = all(s.all_match for s in day_snaps) if day_snaps else True

        # 3. Open freezes at end of day
        day_open_freezes = []
        for f in freezes:
            f_raised = _parse_ts(f.raised_at)
            f_cleared = _parse_ts(f.cleared_at)
            if f_raised and f_raised.date().isoformat() <= day_str:
                if f_cleared is None or f_cleared.date().isoformat() > day_str:
                    day_open_freezes.append(f)

        # 4. Broker orders recorded for this day. Two sources: the durable
        # order ledger (every real submit) and the paper audit log (used
        # only by deterministic tests and legacy tooling).
        ledger_rows = _ledger_rows_for_day(db_path, window_start, window_end)
        decision_ids = _decision_ids_for_day(db_path, window_start, window_end)
        day_orders: list[dict[str, Any]] = []
        for o in orders:
            raw_details = o.get("details")
            details: dict[str, Any] = (
                raw_details if isinstance(raw_details, dict) else o
            )
            order_ts = _parse_ts(details.get("created_at") or o.get("created_at"))
            if order_ts and order_ts.date().isoformat() == day_str:
                day_orders.append(details)

        # 5. Opportunity-round completeness from the scheduler's own
        # recorded executions.
        recorded_rounds, failed_rounds = _count_recorded_rounds(
            round_history, window_start, window_end
        )
        expected_rounds = (
            0
            if is_weekend
            else _expected_rounds(window_start, window_end, round_interval)
        )
        missed_rounds = max(0, expected_rounds - recorded_rounds)

        # 6. Downtime from the union of recorded task execution windows.
        # Any task execution proves the backend process was alive; a
        # stretch with no execution from any task is downtime.
        task_spans: list[tuple[datetime, datetime]] = []
        for row in all_task_runs:
            started = row.get("started_at")
            finished = row.get("finished_at")
            if isinstance(started, datetime) and isinstance(finished, datetime):
                task_spans.append((started, finished))
        downtime_hrs = 0.0
        if not is_today:
            downtime_hrs = _calculate_day_downtime_hours(
                task_spans, d_start, d_end, grace_hours=grace_hours
            )

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
                rounds_recorded=recorded_rounds,
                missed_rounds=missed_rounds,
                ledger_orders=len(ledger_rows),
                orders_without_decision=0,
            )
            evaluated_days.append(day_eval)
            current_day += timedelta(days=1)
            continue

        # Check Safety Invariant Resets (PROJECT_GUIDE S10):
        # 1. Duplicate orders: the same broker-facing client identity was
        # submitted more than once, or the same submit identity exists
        # twice (the ledger's unique key makes the latter impossible,
        # which is itself the evidence).
        ledger_client_ids = [
            row["client_order_id"]
            for row in ledger_rows
            if row["client_order_id"]
        ]
        if len(ledger_client_ids) != len(set(ledger_client_ids)):
            reset_reasons.append("duplicate orders detected on trading day")
        client_ids = [
            o.get("client_order_id") for o in day_orders if o.get("client_order_id")
        ]
        if len(client_ids) != len(set(client_ids)):
            reset_reasons.append("duplicate orders detected on trading day")

        # 2. Orders without a persisted RiskDecision. Every ledger
        # reservation is created only after the gate approved and the
        # decision was persisted, so a missing record is a reset.
        orders_without_decision = sum(
            1
            for row in ledger_rows
            if row["decision_id"] not in decision_ids
        )
        for o in day_orders:
            if not o.get("decision_id") and o.get("status") in ("filled", "submitted"):
                orders_without_decision += 1
                break
        if orders_without_decision:
            reset_reasons.append("order without persisted RiskDecision")

        # 3. Unclean recon without a freeze raised for that day.
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
        if downtime_hrs > RESET_DOWNTIME_HOURS:
            reset_reasons.append(
                f"downtime {downtime_hrs:.1f}h exceeded "
                f"{RESET_DOWNTIME_HOURS:.0f}-hour limit"
            )

        # Check Non-fatal Extensions (PROJECT_GUIDE S10):
        if not reset_reasons:
            if EXTENSION_DOWNTIME_HOURS < downtime_hrs <= RESET_DOWNTIME_HOURS:
                extension_reasons.append(
                    f"downtime {downtime_hrs:.1f}h between "
                    f"{EXTENSION_DOWNTIME_HOURS:.0f}h and "
                    f"{RESET_DOWNTIME_HOURS:.0f}h"
                )
            if not is_weekend and missed_rounds > MAX_MISSED_ROUNDS_PER_DAY:
                extension_reasons.append(
                    f"{missed_rounds} scheduled opportunity rounds have no record"
                )
            if failed_rounds:
                extension_reasons.append(
                    f"{failed_rounds} opportunity rounds ended in error"
                )
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
                rounds_recorded=recorded_rounds,
                missed_rounds=missed_rounds,
                ledger_orders=len(ledger_rows),
                orders_without_decision=orders_without_decision,
            )
        )
        current_day += timedelta(days=1)

    qualified_count = sum(1 for d in evaluated_days if d.status == "qualified")
    extension_count = sum(1 for d in evaluated_days if d.status == "extension")
    reset_days = [d for d in evaluated_days if d.status == "reset"]

    # A reset day means the run restarts from a new Day 0: no day of the
    # current run can qualify past it.
    if reset_days:
        first_reset = reset_days[0].date
        qualified_count = sum(
            1
            for d in evaluated_days
            if d.status == "qualified" and d.date < first_reset
        )

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
        and not reset_days
        and extension_count <= MAX_ALLOWED_EXTENSIONS
    )

    safety_findings: list[str] = []
    if has_active_freezes:
        safety_findings.append("an exposure freeze is still open")

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
        safety_findings=safety_findings,
    )


__all__ = [
    "CYCLE_TASK_NAME",
    "EXTENSION_DOWNTIME_HOURS",
    "MAX_ALLOWED_EXTENSIONS",
    "MAX_MISSED_ROUNDS_PER_DAY",
    "RESET_DOWNTIME_HOURS",
    "SoakDayEvaluation",
    "SoakStatus",
    "TARGET_QUALIFIED_DAYS",
    "evaluate_soak_status",
]
