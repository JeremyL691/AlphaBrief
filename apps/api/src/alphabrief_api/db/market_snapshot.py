"""Immutable cycle market snapshots and quality verdicts (M05-W05).

``build_market_snapshot`` deterministically binds catalog, completed
candles, current pricing, conversions, session evidence, freshness,
coverage, gaps, spread anomalies, and lineage into one reproducible
snapshot: identical immutable inputs and quality-policy version produce
the same snapshot ID, manifest hash, source IDs, quality results, and
normalized serialization. Any quality rule failure produces an explicit
non-executable verdict. ``MarketSnapshotStore`` persists snapshots
atomically; later ingestion creates new facts and a new lineage-linked
snapshot without changing any snapshot already referenced by a decision.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import duckdb
from alphabrief_execution.broker.oanda.pricing import PricingBatch
from alphabrief_execution.broker.oanda.sessions import (
    ExposureReadiness,
    SessionVerdict,
)
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db.instrument_catalog import CatalogProjection
from alphabrief_api.db.schema import apply_schema, drop_schema

#: Version of the quality policy — bump when rules change.
QUALITY_POLICY_VERSION = "market-quality-1"

#: Maximum acceptable candle gap (minutes) before a snapshot fails.
MAX_CANDLE_GAP_MINUTES = 30

#: Maximum acceptable bid/ask spread ratio (spread / mid) before a
#: snapshot fails.
MAX_SPREAD_RATIO = Decimal("0.05")

QualityKind = Literal[
    "incomplete_candles",
    "stale_quotes",
    "missing_conversion",
    "catalog_mismatch",
    "unacceptable_gaps",
    "abnormal_spread",
    "partial_coverage",
]


class QualityRuleResult(BaseModel):
    """One quality rule result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: QualityKind
    passed: bool
    detail: str = ""


class MarketSnapshot(BaseModel):
    """One immutable market snapshot with its manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=1)
    quality_policy_version: str = Field(min_length=1)
    source_ids: dict[str, str] = Field(min_length=1)
    quality: tuple[QualityRuleResult, ...]
    executable: bool
    lineage_parent: str | None = None
    built_at: datetime


class MarketSnapshotStore:
    """DuckDB-backed store for immutable market snapshots."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    def publish(self, snapshot: MarketSnapshot) -> str:
        """Publish one immutable snapshot atomically (idempotent)."""
        existing = self._conn.execute(
            "SELECT snapshot_id FROM market_data_snapshots "
            "WHERE snapshot_id = ?",
            [snapshot.snapshot_id],
        ).fetchone()
        if existing is not None:
            return str(existing[0])
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """
                INSERT INTO market_data_snapshots (
                    snapshot_id, manifest_hash, quality_policy_version,
                    source_ids_json, quality_json, lineage_parent
                ) VALUES (?, ?, ?, ?::JSON, ?::JSON, ?)
                """,
                [
                    snapshot.snapshot_id,
                    snapshot.manifest_hash,
                    snapshot.quality_policy_version,
                    json.dumps(snapshot.source_ids, sort_keys=True),
                    snapshot.model_dump_json(),
                    snapshot.lineage_parent,
                ],
            )
            for _, symbol, fact_kind, fact_id in _fact_rows(snapshot):
                self._conn.execute(
                    """
                    INSERT INTO market_data_snapshot_facts (
                        snapshot_id, symbol, fact_kind, fact_id
                    ) VALUES (?, ?, ?, ?)
                    """,
                    [snapshot.snapshot_id, symbol, fact_kind, fact_id],
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return snapshot.snapshot_id

    def get(self, snapshot_id: str) -> MarketSnapshot | None:
        row = self._conn.execute(
            """SELECT quality_json, lineage_parent FROM market_data_snapshots
               WHERE snapshot_id = ?""",
            [snapshot_id],
        ).fetchone()
        if row is None:
            return None
        return MarketSnapshot.model_validate(
            json.loads(row[0]) if isinstance(row[0], str) else row[0]
        )

    def latest(self) -> MarketSnapshot | None:
        row = self._conn.execute(
            """SELECT quality_json FROM market_data_snapshots
               ORDER BY created_at DESC, snapshot_id LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        return MarketSnapshot.model_validate(
            json.loads(row[0]) if isinstance(row[0], str) else row[0]
        )

    def lineage(self, snapshot_id: str) -> list[str]:
        """Return the lineage chain from *snapshot_id* back to the root."""
        chain: list[str] = []
        current: str | None = snapshot_id
        while current is not None:
            row = self._conn.execute(
                "SELECT lineage_parent FROM market_data_snapshots "
                "WHERE snapshot_id = ?",
                [current],
            ).fetchone()
            if row is None:
                break
            chain.append(current)
            parent = row[0]
            current = str(parent) if parent is not None else None
        return chain

    def clear(self) -> None:
        drop_schema(self._conn)
        apply_schema(self._conn)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def build_market_snapshot(
    *,
    catalog: CatalogProjection,
    pricing: PricingBatch,
    candles: tuple[Any, ...],
    readiness: ExposureReadiness,
    quality_policy_version: str = QUALITY_POLICY_VERSION,
    lineage_parent: str | None = None,
) -> MarketSnapshot:
    """Build one deterministic market snapshot from immutable inputs.

    The snapshot ID and manifest hash derive from the normalized inputs
    and the quality-policy version: identical inputs always produce the
    same snapshot; any quality rule failure yields a non-executable
    verdict with explicit rule results.
    """
    source_ids: dict[str, str] = {
        "catalog": catalog.snapshot_id,
        "catalog_content": catalog.content_hash,
        "pricing": _pricing_hash(pricing),
        "candles": _candles_hash(candles),
        "session": _session_hash(readiness.session),
    }
    rules = _quality_rules(catalog, pricing, candles, readiness)
    executable = bool(rules) and all(rule.passed for rule in rules) and readiness.ready
    payload = {
        "quality_policy_version": quality_policy_version,
        "source_ids": source_ids,
        "quality": [rule.model_dump() for rule in rules],
        "executable": executable,
    }
    manifest_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    snapshot_id = hashlib.sha256(
        f"{manifest_hash}|{lineage_parent or ''}".encode()
    ).hexdigest()[:24]
    return MarketSnapshot(
        snapshot_id=snapshot_id,
        manifest_hash=manifest_hash,
        quality_policy_version=quality_policy_version,
        source_ids=source_ids,
        quality=tuple(rules),
        executable=executable,
        lineage_parent=lineage_parent,
        built_at=datetime.now(UTC),
    )


def _quality_rules(
    catalog: CatalogProjection,
    pricing: PricingBatch,
    candles: tuple[Any, ...],
    readiness: ExposureReadiness,
) -> list[QualityRuleResult]:
    rules: list[QualityRuleResult] = []

    if not readiness.ready:
        rules.append(
            QualityRuleResult(
                rule="partial_coverage",
                passed=False,
                detail=readiness.reason,
            )
        )
    else:
        rules.append(QualityRuleResult(rule="partial_coverage", passed=True))

    incomplete = [c for c in candles if not c.complete]
    rules.append(
        QualityRuleResult(
            rule="incomplete_candles",
            passed=not incomplete,
            detail=f"{len(incomplete)} incomplete candles",
        )
    )

    stale = [p for p in pricing.prices if not _fresh(p)]
    rules.append(
        QualityRuleResult(
            rule="stale_quotes",
            passed=not stale,
            detail=f"{len(stale)} stale quotes",
        )
    )

    missing_conversion = [
        p.symbol for p in pricing.prices if p.conversion_factor <= 0
    ]
    rules.append(
        QualityRuleResult(
            rule="missing_conversion",
            passed=not missing_conversion,
            detail=f"{missing_conversion}",
        )
    )

    catalog_symbols = {i.name for i in catalog.instruments}
    mismatched = [
        p.symbol for p in pricing.prices if p.symbol not in catalog_symbols
    ]
    rules.append(
        QualityRuleResult(
            rule="catalog_mismatch",
            passed=not mismatched,
            detail=f"{mismatched}",
        )
    )

    gaps = _candle_gaps_minutes(candles)
    rules.append(
        QualityRuleResult(
            rule="unacceptable_gaps",
            passed=gaps <= MAX_CANDLE_GAP_MINUTES,
            detail=f"max gap {gaps} minutes",
        )
    )

    abnormal = [
        p.symbol
        for p in pricing.prices
        if _spread_ratio(p) > MAX_SPREAD_RATIO
    ]
    rules.append(
        QualityRuleResult(
            rule="abnormal_spread",
            passed=not abnormal,
            detail=f"{abnormal}",
        )
    )
    return rules


def _fresh(price: Any) -> bool:
    # Prices carry a broker timestamp; treat missing timestamps as stale.
    return getattr(price, "broker_time", None) is not None


def _spread_ratio(price: Any) -> Decimal:
    best_bid = Decimal(str(price.bids[0].price))
    best_ask = Decimal(str(price.asks[0].price))
    mid = (best_bid + best_ask) / Decimal("2")
    if mid <= 0:
        return Decimal("1")
    return Decimal(str(price.spread)) / mid


def _candle_gaps_minutes(candles: tuple[Any, ...]) -> int:
    ordered = sorted(candles, key=lambda c: c.time)
    largest = 0
    for previous, current in zip(ordered, ordered[1:], strict=False):
        gap = int((current.time - previous.time).total_seconds() // 60)
        largest = max(largest, gap)
    return largest


def _session_hash(verdict: SessionVerdict) -> str:
    raw = json.dumps(verdict.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _pricing_hash(batch: PricingBatch) -> str:
    raw = json.dumps(
        [p.model_dump(mode="json") for p in batch.prices],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _candles_hash(candles: tuple[Any, ...]) -> str:
    raw = json.dumps(
        [c.model_dump(mode="json") for c in candles],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fact_rows(snapshot: MarketSnapshot) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for symbol, source_id in sorted(snapshot.source_ids.items()):
        rows.append((snapshot.snapshot_id, symbol, "source", source_id))
    return rows


def _default_db_path() -> Path:
    import os

    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "MAX_CANDLE_GAP_MINUTES",
    "MAX_SPREAD_RATIO",
    "MarketSnapshot",
    "MarketSnapshotStore",
    "QUALITY_POLICY_VERSION",
    "QualityRuleResult",
    "build_market_snapshot",
]
