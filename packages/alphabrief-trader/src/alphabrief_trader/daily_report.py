"""Daily report generation (PROJECT_GUIDE 5.12).

The report is rendered from already-gathered database facts — this module
never calls a broker, a model, or a network. It writes both
``reports/daily/YYYY-MM-DD.md`` and ``.json`` under the runtime data
directory, and every number in it comes from a store query: a section
without evidence says so instead of printing a plausible placeholder.

Sections (PROJECT_GUIDE 5.12):

* the day's cycle decisions (one row per cycle);
* orders, fills and closes (one row per attempt);
* P&L, NAV and drawdown;
* risk-rejection statistics and freeze events;
* model calls, channel and estimated cost;
* data freshness;
* the shadow-evaluation increment;
* the doctor summary (until S5 implements ``alphabrief doctor`` the
  section states that it is not available).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from alphabrief_core import paths as _paths


@dataclass(frozen=True)
class DailyReportData:
    """Every fact the report renders, all of it read from stores."""

    trading_day: str
    generated_at: datetime
    cycles: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    shadow_decisions: list[dict[str, Any]] = field(default_factory=list)
    shadow_stats: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reconciliation: dict[str, Any] = field(default_factory=dict)
    freezes: list[dict[str, Any]] = field(default_factory=list)
    equity: dict[str, Any] = field(default_factory=dict)
    market_freshness: list[dict[str, Any]] = field(default_factory=list)
    doctor_summary: str | None = None

    # ------------------------------------------------------------------
    # Derived views
    # ------------------------------------------------------------------

    def rejection_counts(self) -> dict[str, int]:
        """How many attempts each risk tag rejected."""
        counter: Counter[str] = Counter()
        for attempt in self.attempts:
            if attempt.get("outcome") == "executed":
                continue
            for tag in attempt.get("risk_tags") or []:
                counter[str(tag)] += 1
        return dict(sorted(counter.items()))

    def execution_counts(self) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for attempt in self.attempts:
            counter[str(attempt.get("outcome", "unknown"))] += 1
        return dict(sorted(counter.items()))

    def model_usage(self) -> dict[str, Any]:
        """Calls per channel, tokens and estimated cost."""
        by_channel: dict[str, dict[str, Any]] = {}
        for call in self.model_calls:
            channel = str(call.get("provider", "unknown"))
            entry = by_channel.setdefault(
                channel,
                {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0,
                 "cost_usd": Decimal("0")},
            )
            entry["calls"] += 1
            if call.get("status") != "succeeded":
                entry["failed"] += 1
            entry["input_tokens"] += int(call.get("input_tokens") or 0)
            entry["output_tokens"] += int(call.get("output_tokens") or 0)
            cost = call.get("cost_estimate")
            if cost is not None:
                entry["cost_usd"] += Decimal(str(cost))
        return {
            channel: {**entry, "cost_usd": str(entry["cost_usd"])}
            for channel, entry in sorted(by_channel.items())
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "trading_day": self.trading_day,
            "generated_at": self.generated_at.isoformat(),
            "cycles": self.cycles,
            "execution": {
                "counts": self.execution_counts(),
                "attempts": self.attempts,
            },
            "risk_rejections": self.rejection_counts(),
            "equity": self.equity,
            "reconciliation": self.reconciliation,
            "freezes": self.freezes,
            "model_usage": self.model_usage(),
            "model_calls": self.model_calls,
            "market_freshness": self.market_freshness,
            "shadow": {
                "decisions": self.shadow_decisions,
                "stats": self.shadow_stats,
            },
            "doctor": self.doctor_summary
            or "not available until S5 implements `alphabrief doctor`",
        }


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_no rows_\n"
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def render_markdown(data: DailyReportData) -> str:
    """Render the daily report as Markdown (all numbers from stores)."""
    parts: list[str] = [
        f"# AlphaBrief daily report — {data.trading_day}",
        "",
        f"Generated at {data.generated_at.isoformat()} (UTC). "
        "Every number below is read from the runtime database.",
        "",
        "## Cycles",
        "",
        _table(
            ["cycle", "outcome", "plans", "attempts", "summary"],
            [
                [
                    str(cycle.get("cycle_id", "")),
                    str(cycle.get("outcome", "")),
                    str(cycle.get("plan_count", "")),
                    str(cycle.get("attempt_count", "")),
                    str(cycle.get("summary", "")),
                ]
                for cycle in data.cycles
            ],
        ),
        "## Orders, fills and closes",
        "",
        _table(
            ["intent", "outcome", "filled", "broker order", "reason"],
            [
                [
                    str(attempt.get("intent_id", "")),
                    str(attempt.get("outcome", "")),
                    str(attempt.get("filled", "")),
                    str(attempt.get("broker_order_id") or ""),
                    str(attempt.get("reason", ""))[:120],
                ]
                for attempt in data.attempts
            ],
        ),
        "## Risk rejections",
        "",
        _table(
            ["tag", "count"],
            [[tag, str(count)] for tag, count in data.rejection_counts().items()],
        ),
        "## P&L, NAV and drawdown",
        "",
        _table(
            ["metric", "value"],
            [[key, str(value)] for key, value in data.equity.items()],
        )
        if data.equity
        else "_no equity snapshots for this day_\n",
        "## Reconciliation and freezes",
        "",
        _table(
            ["metric", "value"],
            [[key, str(value)] for key, value in data.reconciliation.items()],
        )
        if data.reconciliation
        else "_no reconciliation snapshot_\n",
        _table(
            ["freeze", "scope", "reason", "at"],
            [
                [
                    str(event.get("freeze_id", "")),
                    str(event.get("scope", "")),
                    str(event.get("reason", ""))[:120],
                    str(event.get("created_at", "")),
                ]
                for event in data.freezes
            ],
        ),
        "## Model usage",
        "",
        _table(
            ["channel", "calls", "failed", "input tokens", "output tokens", "cost USD"],
            [
                [
                    channel,
                    str(entry["calls"]),
                    str(entry["failed"]),
                    str(entry["input_tokens"]),
                    str(entry["output_tokens"]),
                    str(entry["cost_usd"]),
                ]
                for channel, entry in data.model_usage().items()
            ],
        ),
        "## Data freshness",
        "",
        _table(
            ["symbol", "latest bar (UTC)", "data version"],
            [
                [
                    str(row.get("symbol", "")),
                    str(row.get("latest_bar_at", "")),
                    str(row.get("data_version", "")),
                ]
                for row in data.market_freshness
            ],
        ),
        "## Shadow evaluation",
        "",
        f"Decisions recorded this day: {len(data.shadow_decisions)}.",
        "",
    ]
    for horizon, stats in sorted(data.shadow_stats.items()):
        parts.append(f"### {horizon}")
        parts.append("")
        parts.append(
            _table(
                ["benchmark", "samples", "mean %", "win rate", "95% CI", "caveat"],
                [
                    [
                        str(stat.get("benchmark", "")),
                        str(stat.get("samples", "")),
                        str(stat.get("mean_return_pct", "")),
                        str(stat.get("win_rate", "")),
                        (
                            f"[{stat.get('ci_low_pct', '')}, "
                            f"{stat.get('ci_high_pct', '')}]"
                        ),
                        str(stat.get("caveat", "")),
                    ]
                    for stat in stats
                ],
            )
        )
    parts.extend(
        [
            "## Doctor",
            "",
            data.doctor_summary
            or "Not available until S5 implements `alphabrief doctor`.",
            "",
        ]
    )
    return "\n".join(parts)


def write_daily_report(
    data: DailyReportData, *, directory: Path | None = None
) -> tuple[Path, Path]:
    """Write the ``.md`` and ``.json`` report files and return their paths."""
    target = Path(directory) if directory is not None else _paths.daily_reports_dir()
    target.mkdir(parents=True, exist_ok=True)
    markdown_path = target / f"{data.trading_day}.md"
    json_path = target / f"{data.trading_day}.json"
    markdown_path.write_text(render_markdown(data), encoding="utf-8")
    json_path.write_text(
        json.dumps(data.to_payload(), indent=2, default=str, sort_keys=True),
        encoding="utf-8",
    )
    return markdown_path, json_path


__all__ = [
    "DailyReportData",
    "render_markdown",
    "write_daily_report",
]
