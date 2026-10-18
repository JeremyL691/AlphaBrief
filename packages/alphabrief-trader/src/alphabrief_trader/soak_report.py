"""Soak test report generation (PROJECT_GUIDE 7.3 S11, Appendix D).

Gathers full soak statistics from DuckDB stores and renders the markdown report:
- Period, qualified days, extensions, resets (with reasons);
- Runtime versions, hotfixes, total downtime;
- Account metrics: start NAV, end NAV, max drawdown, realized P&L, win rate;
- Orders: submitted, filled, rejected, SUBMIT_UNKNOWN resolved;
- Risk: rejections by rule/tag, freezes and resolutions;
- Model gateways: calls by channel, failures by code, estimated cost;
- Shadow evaluation: per baseline n, mean 4h & 24h return, 95% CI;
- Safety invariants check;
- Known limitations & disclaimer.

Never prints unmasked account IDs or secrets.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from alphabrief_api.db.ai_trading import AiTradingStore
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_core import paths as _paths
from alphabrief_core.policy_version import project_root
from alphabrief_core.version import __version__
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.telemetry import redact_account_id
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_risk.decision_store import RiskDecisionStore

from alphabrief_trader.shadow_store import ShadowStore
from alphabrief_trader.soak_evaluator import (
    SoakStatus,
    evaluate_soak_status,
    snapshot_db_if_locked,
)


@dataclass(frozen=True)
class SoakReportData:
    """Full aggregate dataset for the soak report."""

    status: SoakStatus
    generated_at: datetime
    masked_account_id: str
    equity_metrics: dict[str, Any] = field(default_factory=dict)
    order_metrics: dict[str, Any] = field(default_factory=dict)
    risk_metrics: dict[str, Any] = field(default_factory=dict)
    model_metrics: dict[str, Any] = field(default_factory=dict)
    shadow_metrics: dict[str, Any] = field(default_factory=dict)
    safety_metrics: dict[str, Any] = field(default_factory=dict)
    hotfixes: list[str] = field(default_factory=list)
    version: str = __version__

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "generated_at": self.generated_at.isoformat(),
            "masked_account_id": self.masked_account_id,
            "status": self.status.to_dict(),
            "equity": self.equity_metrics,
            "orders": self.order_metrics,
            "risk": self.risk_metrics,
            "models": self.model_metrics,
            "shadow": self.shadow_metrics,
            "safety": self.safety_metrics,
            "hotfixes": self.hotfixes,
        }


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_no rows_\n"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        cleaned = [item.replace("\n", " ").replace("|", "\\|").strip() for item in row]
        lines.append("| " + " | ".join(cleaned) + " |")
    return "\n".join(lines) + "\n"


def render_soak_markdown(data: SoakReportData) -> str:
    """Render the soak report as markdown strictly following Appendix D."""
    s = data.status
    start_str = (
        s.started_at.strftime("%Y-%m-%d %H:%M UTC") if s.started_at else "Not started"
    )
    end_str = data.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    period_str = f"{start_str} to {end_str}"

    total_downtime_hrs = sum(d.downtime_hours for d in s.days)

    sections: list[str] = [
        f"# AlphaBrief v{data.version} Soak Report",
        "",
        f"**Generated at**: {data.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        f"**Account**: `{data.masked_account_id}`  ",
        f"**Period (UTC)**: {period_str}  ",
        f"**Qualified days**: {s.qualified_days} / {s.target_days}  ",
        f"**Extensions**: {s.extension_days}  ",
        f"**Resets**: {len(s.resets)}  ",
        "",
        "## Period & Qualification",
        "",
        _table(
            [
                "Date (UTC)",
                "Status",
                "Weekend",
                "Downtime (h)",
                "Cycles",
                "Rounds",
                "Ledger Orders",
                "Recon Clean",
                "Daily Report",
                "Notes",
            ],
            [
                [
                    d.date,
                    d.status,
                    "Yes" if d.is_weekend else "No",
                    f"{d.downtime_hours:.1f}",
                    str(d.cycles_count),
                    f"{d.rounds_recorded} ({d.missed_rounds} missed)",
                    str(d.ledger_orders),
                    "Clean" if d.recon_clean else "Unclean",
                    "Yes" if d.daily_report_exists else "No",
                    ("; ".join(d.reset_reasons + d.extension_reasons))[:100] or "-",
                ]
                for d in s.days
            ],
        ),
        "## Runtime & Operations",
        "",
        f"- **Tested Versions**: `v{data.version}`",
        f"- **Hotfixes Applied**: {len(data.hotfixes)}",
        f"- **Total Cumulative Downtime**: {total_downtime_hrs:.2f} hours",
        "",
    ]

    if data.hotfixes:
        sections.append(
            _table(
                ["Hotfix", "Details"],
                [[h, "Applied during soak"] for h in data.hotfixes],
            )
        )

    # Account metrics
    eq = data.equity_metrics
    sections.extend(
        [
            "## Account & Performance",
            "",
            _table(
                ["Metric", "Value"],
                [
                    ["Start NAV", str(eq.get("start_nav", "n/a"))],
                    ["End NAV", str(eq.get("end_nav", "n/a"))],
                    ["Realized P&L", str(eq.get("realized_pnl", "n/a"))],
                    ["Max Drawdown", str(eq.get("max_drawdown_pct", "n/a"))],
                    ["Total Trades / Closes", str(eq.get("total_trades", "0"))],
                    ["Win Rate", str(eq.get("win_rate_pct", "n/a"))],
                ],
            ),
            "## Orders & Execution",
            "",
        ]
    )

    om = data.order_metrics
    sections.extend(
        [
            _table(
                ["Metric", "Count"],
                [
                    ["Ledger Submits", str(om.get("submitted", 0))],
                    ["Filled Broker Orders", str(om.get("filled", 0))],
                    ["Rejected / Blocked", str(om.get("rejected", 0))],
                    ["Frozen Submits", str(om.get("frozen", 0))],
                    [
                        "SUBMIT_UNKNOWN Resolved",
                        str(om.get("submit_unknown_resolved", 0)),
                    ],
                ],
            ),
            "## Risk Gate & Safety",
            "",
        ]
    )

    rm = data.risk_metrics
    rejections = rm.get("rejections_by_rule", {})
    freezes = rm.get("freezes", [])

    sections.append("### Rejections by Rule")
    sections.append("")
    sections.append(
        _table(
            ["Rule / Tag", "Count"],
            [[k, str(v)] for k, v in sorted(rejections.items())]
            if rejections
            else [["None", "0"]],
        )
    )

    sections.append("### Freezes and Resolutions")
    sections.append("")
    sections.append(
        _table(
            ["Freeze ID", "Scope", "Reason", "Raised At", "Resolved At"],
            [
                [
                    str(f.get("freeze_id", "")),
                    str(f.get("scope", "")),
                    str(f.get("reason", ""))[:80],
                    str(f.get("raised_at", "")),
                    str(f.get("resolved_at") or "Open"),
                ]
                for f in freezes
            ]
            if freezes
            else [["None", "-", "No freeze events recorded", "-", "-"]],
        )
    )

    # Models
    mm = data.model_metrics
    sections.extend(
        [
            "## Model Gateways & Costs",
            "",
            _table(
                [
                    "Channel / Provider",
                    "Calls",
                    "Failed",
                    "Input Tokens",
                    "Output Tokens",
                    "Est. Cost (USD)",
                ],
                [
                    [
                        channel,
                        str(info.get("calls", 0)),
                        str(info.get("failed", 0)),
                        str(info.get("input_tokens", 0)),
                        str(info.get("output_tokens", 0)),
                        f"${info.get('cost_usd', '0.00')}",
                    ]
                    for channel, info in mm.get("by_channel", {}).items()
                ]
                if mm.get("by_channel")
                else [["None", "0", "0", "0", "0", "$0.00"]],
            ),
            "## Shadow Evaluation",
            "",
        ]
    )

    sh = data.shadow_metrics
    sections.append(
        _table(
            [
                "Baseline",
                "Horizon",
                "Samples (n)",
                "Mean Return (%)",
                "95% Confidence Interval",
                "Win Rate (%)",
                "Caveat",
            ],
            [
                [
                    str(row.get("benchmark", "")),
                    str(row.get("horizon", "")),
                    str(row.get("samples", 0)),
                    str(row.get("mean_return_pct", "0.0")),
                    (
                        f"[{row.get('ci_low_pct', '0.0')}, "
                        f"{row.get('ci_high_pct', '0.0')}]"
                    ),
                    f"{float(row.get('win_rate', 0.0)) * 100:.1f}%",
                    str(row.get("caveat") or "Sample size too small to infer edge"),
                ]
                for row in sh.get("scoreboard", [])
            ]
            if sh.get("scoreboard")
            else [
                [
                    "None",
                    "-",
                    "0",
                    "0.0",
                    "[0.0, 0.0]",
                    "0.0%",
                    "No shadow evaluations recorded yet",
                ]
            ],
        )
    )

    # Safety invariants, computed from persisted facts (never hardcoded).
    safety_rows = data.safety_metrics.get("invariants", [])
    sections.extend(
        [
            "## Safety Invariants Verification",
            "",
            _table(
                ["Safety Invariant", "Violations", "Status"],
                [
                    [
                        str(row.get("invariant", "")),
                        str(row.get("violations", 0)),
                        str(row.get("status", "PASSED")),
                    ]
                    for row in safety_rows
                ]
                if safety_rows
                else [["No facts available", "-", "UNKNOWN"]],
            ),
            "## Known Limitations",
            "",
            (
                "1. **Execution Environment**: Runs exclusively against OANDA v20 "
                "practice endpoints (`api-fxpractice.oanda.com`). Simulated fill "
                "conditions do not exhibit real-market partial fills or extreme "
                "liquidity vacuums."
            ),
            (
                "2. **Forex Scope**: Focuses on major currency pairs (`EUR_USD`, "
                "`GBP_USD`, `USD_JPY`, `AUD_USD`, `USD_CAD`); commodities and equity "
                "indices serve as read-only cross-asset signals."
            ),
            (
                "3. **Model Budget**: Subscriptions operate under provider rate limits "
                "and daily quota controls. Out-of-quota events fail closed gracefully "
                "to `no_trade`."
            ),
            "",
            "## Disclaimer",
            "",
            (
                "> Practice account paper-trading only. This software is not financial "
                "advice. Past performance on practice data does not guarantee future "
                "results. Operational sample size is intended to verify software "
                "reliability, execution safety invariants, and unattended stability, "
                "not statistical market edge."
            ),
            "",
        ]
    )

    return "\n".join(sections)


def _ledger_facts(
    db_path: Path | str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the durable submit ledger: reservations and events.

    The ledger is the authority for what this system actually sent: one
    row per submit identity, plus an append-only event history. The
    paper audit table is not read for order facts because the runtime
    never writes it.
    """
    if db_path is None or not Path(db_path).exists():
        return [], []
    ledger = OrderLedger(db_path=db_path)
    try:
        reservations = ledger._conn.execute(
            """SELECT submit_id, cycle_id, intent_id, decision_id, status,
                      broker_order_id, state, transaction_id, client_order_id,
                      filled_units, created_at, updated_at
               FROM order_ledger_reservations
               ORDER BY created_at ASC"""
        ).fetchall()
        events = ledger._conn.execute(
            """SELECT submit_id, kind, detail, created_at
               FROM order_ledger_events
               ORDER BY event_id ASC"""
        ).fetchall()
    finally:
        ledger.close()

    rows: list[dict[str, Any]] = []
    for row in reservations:
        rows.append(
            {
                "submit_id": str(row[0]),
                "cycle_id": str(row[1]),
                "intent_id": str(row[2]),
                "decision_id": str(row[3]),
                "status": str(row[4]),
                "broker_order_id": str(row[5]) if row[5] is not None else None,
                "state": str(row[6]) if row[6] is not None else None,
                "transaction_id": str(row[7]) if row[7] is not None else None,
                "client_order_id": str(row[8]) if row[8] is not None else str(row[0]),
                "filled_units": Decimal(str(row[9] or "0")),
                "created_at": row[10],
                "updated_at": row[11],
            }
        )
    event_rows = [
        {
            "submit_id": str(row[0]),
            "kind": str(row[1]),
            "detail": str(row[2]),
            "created_at": row[3],
        }
        for row in events
    ]
    return rows, event_rows


def _transaction_facts(db_path: Path | str | None) -> list[dict[str, Any]]:
    """Broker transaction facts (fills, closes, financing) as persisted."""
    if db_path is None or not Path(db_path).exists():
        return []
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        table = conn.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_name = 'transaction_facts'"""
        ).fetchone()
        if table is None:
            return []
        rows = conn.execute(
            """SELECT account_id, transaction_id, transaction_type, time,
                      instrument, units, price, realized_pl, financing
               FROM transaction_facts
               ORDER BY transaction_id ASC"""
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "account_id": str(row[0]),
            "transaction_id": str(row[1]),
            "transaction_type": str(row[2]),
            "time": row[3],
            "instrument": str(row[4]) if row[4] is not None else None,
            "units": Decimal(str(row[5])) if row[5] is not None else None,
            "price": Decimal(str(row[6])) if row[6] is not None else None,
            "realized_pl": (
                Decimal(str(row[7])) if row[7] is not None else Decimal("0")
            ),
            "financing": (
                Decimal(str(row[8])) if row[8] is not None else Decimal("0")
            ),
        }
        for row in rows
    ]


def _equity_snapshots(db_path: Path | str | None) -> list[tuple[datetime, Decimal]]:
    """Persisted account equity snapshots, oldest first."""
    if db_path is None or not Path(db_path).exists():
        return []
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        table = conn.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_name = 'account_equity_snapshots'"""
        ).fetchone()
        if table is None:
            return []
        rows = conn.execute(
            """SELECT captured_at, equity FROM account_equity_snapshots
               ORDER BY captured_at ASC"""
        ).fetchall()
    finally:
        conn.close()
    snapshots: list[tuple[datetime, Decimal]] = []
    for captured_at, equity in rows:
        parsed = (
            captured_at.astimezone(UTC)
            if isinstance(captured_at, datetime) and captured_at.tzinfo
            else captured_at
        )
        if isinstance(parsed, datetime):
            snapshots.append((parsed, Decimal(str(equity))))
    return snapshots


def _safety_invariants(
    ledger_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    decision_ids: set[str],
    *,
    db_path: Path | str | None,
) -> dict[str, Any]:
    """Compute each safety invariant from persisted facts.

    Every count is derived from the durable ledger and the persisted
    decision store; nothing is assumed. The network-boundary invariants
    are proven structurally by the composition scan
    (:func:`alphabrief_execution.broker.safety.production_safety_violations`)
    rather than by request logs, which this system does not keep.
    """
    del db_path  # kept for signature symmetry with the other readers

    # 1. Duplicate submits: the ledger's unique (cycle_id, intent_id) key
    # makes a duplicate reservation impossible; a duplicate broker-facing
    # client identity across distinct submits is the observable signal.
    client_ids = [row["client_order_id"] for row in ledger_rows]
    duplicate_client_ids = len(client_ids) - len(set(client_ids))

    # 2. Every submit identity carries the decision it was bound to.
    without_decision = sum(
        1 for row in ledger_rows if not row.get("decision_id")
    )

    # 3. Submits that reached the broker without the decision record the
    # binding service persisted before the network call.
    broker_sent = [row for row in ledger_rows if row["status"] != "RESERVED"]
    sent_without_persisted_decision = sum(
        1
        for row in broker_sent
        if row["decision_id"] not in decision_ids
    )

    # 4. Freezes: unresolved submit outcomes freeze the ledger.
    frozen = sum(1 for row in ledger_rows if row["status"] == "FROZEN")

    # 5. Network boundary: the structural scan proves production code can
    # reach only the OANDA practice host and no other broker.
    from alphabrief_execution.broker.safety import (
        production_safety_violations,
    )

    boundary_violations = production_safety_violations(project_root())

    return {
        "duplicate_client_ids": duplicate_client_ids,
        "orders_without_decision": without_decision,
        "sent_without_persisted_decision": sent_without_persisted_decision,
        "frozen_submits": frozen,
        "boundary_violations": len(boundary_violations),
        "boundary_details": boundary_violations[:20],
        "invariants": [
            {
                "invariant": "Duplicate orders across all runs",
                "violations": duplicate_client_ids,
                "status": "PASSED" if duplicate_client_ids == 0 else "FAILED",
            },
            {
                "invariant": "Orders without persisted RiskDecision",
                "violations": sent_without_persisted_decision,
                "status": (
                    "PASSED" if sent_without_persisted_decision == 0 else "FAILED"
                ),
            },
            {
                "invariant": "Live endpoint / other-broker reachability",
                "violations": len(boundary_violations),
                "status": "PASSED" if not boundary_violations else "FAILED",
            },
            {
                "invariant": "Unresolved submits left frozen",
                "violations": frozen,
                "status": "PASSED" if frozen == 0 else "FAILED",
            },
        ],
    }


def generate_soak_report_data(
    *,
    db_path: Path | str | None = None,
    as_of: datetime | None = None,
) -> SoakReportData:
    """Gather all soak facts and build SoakReportData."""
    with snapshot_db_if_locked(db_path) as effective_db:
        return _generate_soak_report_data_impl(db_path=effective_db, as_of=as_of)


def _generate_soak_report_data_impl(
    *,
    db_path: Path | str | None = None,
    as_of: datetime | None = None,
) -> SoakReportData:
    """Gather all soak facts and build SoakReportData implementation."""
    now = as_of or datetime.now(UTC)
    status = evaluate_soak_status(db_path=db_path, as_of=now)

    # Read account creds to mask account ID
    from alphabrief_execution.broker.oanda.config import read_oanda_credentials
    from alphabrief_execution.broker.runtime import oanda_is_configured

    masked_acc = "None"
    real_acc: str | None = None
    if oanda_is_configured():
        try:
            _, real_acc = read_oanda_credentials()
            masked_acc = redact_account_id(real_acc)
        except Exception:
            masked_acc = "101-***-***"

    # Gather facts
    ai_store = AiTradingStore(db_path=db_path)
    recon_store = BrokerReconStore(db_path=db_path)
    model_store = ModelCallStore(db_path=db_path)
    shadow_store = ShadowStore(db_path=db_path)
    decision_store = RiskDecisionStore(db_path=db_path)

    try:
        cycles = ai_store.list_cycles(limit=5000)
        freezes = recon_store.list_freezes(only_open=False)
        calls = model_store.list_calls(limit=5000)
        shadow_stats = shadow_store.scoreboard()
        decision_ids = {
            str(row[0])
            for row in decision_store._conn.execute(
                "SELECT decision_id FROM risk_decisions"
            ).fetchall()
        }
    finally:
        decision_store.close()
        shadow_store.close()
        model_store.close()
        recon_store.close()
        ai_store.close()

    ledger_rows, event_rows = _ledger_facts(db_path)
    tx_facts = _transaction_facts(db_path)
    equity_snapshots = _equity_snapshots(db_path)

    # Account/equity facts come from persisted broker facts: the first
    # equity snapshot of the run is the start NAV, the latest is the end.
    start_nav = equity_snapshots[0][1] if equity_snapshots else None
    end_nav = equity_snapshots[-1][1] if equity_snapshots else None
    peak = max((value for _, value in equity_snapshots), default=None)
    realized_pnl = sum(
        (fact["realized_pl"] + fact["financing"] for fact in tx_facts),
        Decimal("0"),
    )
    closes = [
        fact
        for fact in tx_facts
        if fact["transaction_type"] in ("TRADE_CLOSE", "TRADE_REDUCE")
        and fact["realized_pl"] != 0
    ]
    wins = sum(1 for fact in closes if fact["realized_pl"] > 0)
    if end_nav is not None and start_nav is not None:
        realized_pnl = end_nav - start_nav

    dd_pct: str | None = None
    if peak is not None and end_nav is not None and peak > 0:
        dd_pct = f"{(peak - end_nav) / peak * 100:.2f}%"

    equity_metrics = {
        "start_nav": f"{start_nav:.2f}" if start_nav is not None else "n/a",
        "end_nav": f"{end_nav:.2f}" if end_nav is not None else "n/a",
        "realized_pnl": (
            f"{realized_pnl:.2f}"
            if (start_nav is not None or tx_facts)
            else "n/a"
        ),
        "max_drawdown_pct": dd_pct if dd_pct is not None else "n/a",
        "total_trades": len(closes),
        "win_rate_pct": (
            f"{wins / len(closes) * 100:.2f}%" if closes else "n/a"
        ),
    }

    # Order facts from the durable ledger (never the always-empty paper
    # audit table the runtime does not write).
    completed = [row for row in ledger_rows if row["status"] == "COMPLETED"]
    filled = [
        row
        for row in completed
        if (row["state"] or "").upper() == "FILLED"
    ]
    frozen = [row for row in ledger_rows if row["status"] == "FROZEN"]
    resolved_unknown = [
        event
        for event in event_rows
        if event["kind"] == "BROKER_RESULT"
        and event["submit_id"] in {row["submit_id"] for row in frozen}
    ]
    rejected = sum(
        1
        for c in cycles
        for attempt in (c.model_dump(mode="json").get("attempts") or [])
        if attempt.get("outcome") != "executed"
    )
    order_metrics = {
        "submitted": len(ledger_rows),
        "filled": len(filled),
        "rejected": rejected,
        "frozen": len(frozen),
        "submit_unknown_resolved": len(resolved_unknown),
    }

    # Risk metrics
    risk_counter: Counter[str] = Counter()
    for c in cycles:
        c_dict = c if isinstance(c, dict) else c.model_dump(mode="json")
        for attempt in c_dict.get("attempts", []):
            if attempt.get("outcome") != "executed":
                for tag in attempt.get("risk_tags", []):
                    risk_counter[str(tag)] += 1

    risk_metrics = {
        "rejections_by_rule": dict(risk_counter),
        "freezes": [
            {
                "freeze_id": f.event_id,
                "scope": f.scope,
                "reason": f.reason,
                "raised_at": str(f.raised_at),
                "resolved_at": str(f.cleared_at) if f.cleared_at else None,
            }
            for f in freezes
        ],
    }

    # Model metrics
    by_channel: dict[str, dict[str, Any]] = {}
    for call in calls:
        prov = str(call.get("provider", "unknown"))
        ch = by_channel.setdefault(
            prov,
            {
                "calls": 0,
                "failed": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": Decimal("0"),
            },
        )
        ch["calls"] += 1
        if call.get("status") != "succeeded":
            ch["failed"] += 1
        ch["input_tokens"] += int(call.get("input_tokens") or 0)
        ch["output_tokens"] += int(call.get("output_tokens") or 0)
        cost = call.get("cost_estimate")
        if cost is not None:
            ch["cost_usd"] += Decimal(str(cost))

    model_metrics = {
        "by_channel": {
            k: {**v, "cost_usd": str(v["cost_usd"])} for k, v in by_channel.items()
        }
    }

    # Shadow scoreboard
    flattened_shadow: list[dict[str, Any]] = []
    for horizon, items in shadow_stats.items():
        for item in items:
            flattened_shadow.append({**item, "horizon": horizon})

    shadow_metrics = {"scoreboard": flattened_shadow}

    safety_metrics = _safety_invariants(
        ledger_rows, event_rows, decision_ids, db_path=db_path
    )

    return SoakReportData(
        status=status,
        generated_at=now,
        masked_account_id=masked_acc,
        equity_metrics=equity_metrics,
        order_metrics=order_metrics,
        risk_metrics=risk_metrics,
        model_metrics=model_metrics,
        shadow_metrics=shadow_metrics,
        safety_metrics=safety_metrics,
        hotfixes=[],
        version=__version__,
    )


class SoakReportNotReadyError(RuntimeError):
    """Raised when a final report is requested before the soak qualifies."""


def write_soak_report(
    data: SoakReportData,
    *,
    out_file: Path | None = None,
    final: bool = False,
) -> tuple[Path, Path]:
    """Write soak report as markdown and json files.

    ``final=True`` is the release artifact and is gated: it refuses to
    write until the soak actually qualifies (14 qualified days, no open
    freeze, no reset event, extensions within the limit). A preliminary
    report is always available without the gate.
    """
    if final:
        problems: list[str] = []
        if not data.status.soak_started:
            problems.append("the soak has not started")
        if not data.status.is_complete:
            problems.append(
                f"{data.status.qualified_days}/{data.status.target_days} "
                "qualified days"
            )
        if data.status.state != "completed":
            problems.append(f"run state is {data.status.state!r}")
        if data.status.safety_findings:
            problems.extend(data.status.safety_findings)
        failed = [
            row
            for row in data.safety_metrics.get("invariants", [])
            if row.get("status") == "FAILED"
        ]
        if failed:
            problems.append(
                "safety invariant failures: "
                + ", ".join(str(row.get("invariant")) for row in failed)
            )
        if problems:
            raise SoakReportNotReadyError(
                "refusing to write the final soak report: " + "; ".join(problems)
            )
        target_md = project_root() / "reports" / f"soak-report-v{data.version}.md"
        target_json = project_root() / "reports" / f"soak-report-v{data.version}.json"

    elif out_file is not None:
        target_md = out_file
        target_json = out_file.with_suffix(".json")
    else:
        out_dir = _paths.data_dir() / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        date_str = data.generated_at.strftime("%Y-%m-%d")
        target_md = out_dir / f"soak-report-{date_str}.md"
        target_json = out_dir / f"soak-report-{date_str}.json"

    target_md.parent.mkdir(parents=True, exist_ok=True)

    markdown_content = render_soak_markdown(data)
    target_md.write_text(markdown_content, encoding="utf-8")
    target_json.write_text(
        json.dumps(data.to_dict(), indent=2, default=str), encoding="utf-8"
    )

    return target_md, target_json


__all__ = [
    "SoakReportData",
    "SoakReportNotReadyError",
    "generate_soak_report_data",
    "render_soak_markdown",
    "write_soak_report",
]
