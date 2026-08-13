"""Scrubbed OANDA request telemetry (M06-W06).

Records method family, endpoint template, status, broker request ID,
latency, attempts, error class, and a scrubbed correlation while
excluding the token, the full account ID, and sensitive payload values.
The correlation is stored as a non-reversible hash; the endpoint is
templated so the real account ID never appears.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import duckdb
from pydantic import BaseModel, ConfigDict, Field

_ACCOUNT_MARKER = "/v3/accounts/"


class RequestTelemetry(BaseModel):
    """One scrubbed telemetry record for a broker request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_family: str = Field(min_length=1)
    endpoint_template: str = Field(min_length=1)
    status: str = Field(min_length=1)
    broker_request_id: str | None = None
    latency_ms: int = Field(ge=0)
    attempts: int = Field(ge=1)
    error_class: str | None = None
    correlation_id: str = Field(min_length=1)
    had_body: bool = False
    recorded_at: datetime


class TelemetryRecorder:
    """DuckDB-backed append-only telemetry store with scrubbed fields."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_telemetry (
                recorded_at      TIMESTAMPTZ NOT NULL,
                method_family    TEXT NOT NULL,
                endpoint_template TEXT NOT NULL,
                status           TEXT NOT NULL,
                broker_request_id TEXT,
                latency_ms       BIGINT NOT NULL,
                attempts         BIGINT NOT NULL,
                error_class      TEXT,
                correlation_id   TEXT NOT NULL,
                had_body         BOOLEAN NOT NULL
            )
            """
        )

    def record(
        self,
        *,
        method: str,
        path: str,
        status: str,
        latency_ms: int,
        attempts: int,
        error_class: str | None,
        correlation_id: str | None,
        had_body: bool = False,
        broker_request_id: str | None = None,
    ) -> None:
        """Record one scrubbed telemetry entry.

        Only non-sensitive fields are persisted: the endpoint is
        templated (real account ID removed) and the correlation is
        stored as a non-reversible hash.
        """
        telemetry = RequestTelemetry(
            method_family=method_family_for(method, path),
            endpoint_template=endpoint_template_for(path),
            status=status,
            broker_request_id=broker_request_id,
            latency_ms=latency_ms,
            attempts=attempts,
            error_class=error_class,
            correlation_id=scrub_correlation(correlation_id or method),
            had_body=had_body,
            recorded_at=datetime.now(UTC),
        )
        self._conn.execute(
            """
            INSERT INTO request_telemetry (
                recorded_at, method_family, endpoint_template, status,
                broker_request_id, latency_ms, attempts, error_class,
                correlation_id, had_body
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                telemetry.recorded_at,
                telemetry.method_family,
                telemetry.endpoint_template,
                telemetry.status,
                telemetry.broker_request_id,
                telemetry.latency_ms,
                telemetry.attempts,
                telemetry.error_class,
                telemetry.correlation_id,
                telemetry.had_body,
            ],
        )

    def recent(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT recorded_at, method_family, endpoint_template, status,
                      broker_request_id, latency_ms, attempts, error_class,
                      correlation_id, had_body
               FROM request_telemetry
               ORDER BY recorded_at DESC LIMIT ?""",
            [limit],
        ).fetchall()
        return [
            {
                "recorded_at": str(row[0]),
                "method_family": str(row[1]),
                "endpoint_template": str(row[2]),
                "status": str(row[3]),
                "broker_request_id": str(row[4]) if row[4] is not None else None,
                "latency_ms": int(row[5]),
                "attempts": int(row[6]),
                "error_class": str(row[7]) if row[7] is not None else None,
                "correlation_id": str(row[8]),
                "had_body": bool(row[9]),
            }
            for row in rows
        ]

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM request_telemetry"
        ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


def endpoint_template_for(path: str) -> str:
    """Template an account path so no real ID ever appears.

    The account ID and every digit-only broker ID segment are replaced
    with placeholders; query strings are dropped.
    """
    index = path.find(_ACCOUNT_MARKER)
    if index < 0:
        return path.split("?", 1)[0]
    rest = path[index + len(_ACCOUNT_MARKER):].split("?", 1)[0]
    segments = rest.split("/")
    tail_segments: list[str] = []
    for segment in segments[1:]:
        if segment.isdigit():
            tail_segments.append("{id}")
        else:
            tail_segments.append(segment)
    tail = "".join(f"/{segment}" for segment in tail_segments)
    return f"{_ACCOUNT_MARKER}{{account_id}}{tail}"


#: Single-segment resources whose family names are not the resource name.
_SPECIAL_SINGLE: dict[str, str] = {
    "summary": "account.summary",
    "changes": "account.changes",
}

#: Endpoint resources are plural; families use the singular resource.
_SINGULAR_RESOURCE: dict[str, str] = {
    "orders": "order",
    "trades": "trade",
    "positions": "position",
    "transactions": "transaction",
}


def method_family_for(method: str, path: str) -> str:
    """Map a method+path pair to a stable family name."""
    template = endpoint_template_for(path)
    tail = template.split("{account_id}", 1)[1]
    segments = [s for s in tail.split("/") if s]
    if not segments:
        return f"http.{method.lower()}"
    resource = _SINGULAR_RESOURCE.get(segments[0], segments[0])
    if len(segments) == 1:
        if resource in _SPECIAL_SINGLE:
            return _SPECIAL_SINGLE[resource]
        if method == "POST":
            return f"{resource}.create"
        return f"{resource}.list"
    if len(segments) == 2:
        if segments[1] == "{id}":
            if method == "GET":
                return f"{resource}.get"
            return f"{resource}.update"
        if segments[1] in ("idrange", "sinceid"):
            return f"{resource}.{segments[1]}"
        if method == "GET":
            return f"{resource}.get"
        return f"{resource}.update"
    return f"{resource}.{segments[-1]}"


def scrub_correlation(value: str) -> str:
    """Return a non-reversible hash of a correlation value."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"corr-{digest[:16]}"


def redact_account_id(account_id: str) -> str:
    """Return a redacted account hint (never the full ID)."""
    suffix = account_id[-4:] if len(account_id) > 4 else account_id
    return f"...{suffix}"


def scrub_url_account_segment(url: str) -> str:
    """Strip any account ID from a URL for logging."""
    split = urlsplit(url)
    path = split.path
    index = path.find(_ACCOUNT_MARKER)
    if index < 0:
        return url
    return endpoint_template_for(path)


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "RequestTelemetry",
    "TelemetryRecorder",
    "endpoint_template_for",
    "method_family_for",
    "redact_account_id",
    "scrub_correlation",
    "scrub_url_account_segment",
]
