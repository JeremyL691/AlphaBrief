"""M15-W01: structured observability signals.

Covers AC-M15-W01-01: ingestion, news, models, scheduler, cycle, risk,
OANDA, reconciliation, backup, API, and Electron publish structured
health, readiness, heartbeat, latency, success, failure, and freshness
signals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from alphabrief_core import (
    COMPONENTS,
    ComponentHealth,
    HealthRegistry,
    MetricRecord,
    StructuredLogRecord,
    account_id_hash,
    build_health_registry,
    redact_observable,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)


def _by_component(registry: HealthRegistry, component: str) -> ComponentHealth:
    return next(h for h in registry.components if h.component == component)


def _component_truth(component: str) -> dict[str, object]:
    return {
        "status": "healthy",
        "ready": True,
        "heartbeat_at": "2026-08-14T00:00:00+00:00",
        "last_success_at": "2026-08-14T00:00:00+00:00",
        "last_failure_at": None,
        "freshness": "fresh",
    }


class TestEveryComponent:
    @pytest.mark.parametrize("component", COMPONENTS)
    def test_every_component_publishes_health_signals(
        self, component: str
    ) -> None:
        registry = build_health_registry(
            {component: _component_truth(component)}, now=NOW
        )
        health = _by_component(registry, component)
        assert isinstance(health, ComponentHealth)
        assert health.status == "healthy"
        assert health.ready is True
        assert health.heartbeat_at is not None
        assert health.last_success_at is not None
        assert health.freshness == "fresh"

    def test_all_eleven_components_are_declared(self) -> None:
        assert COMPONENTS == (
            "ingestion",
            "news",
            "models",
            "scheduler",
            "cycle",
            "risk",
            "oanda",
            "reconciliation",
            "backup",
            "api",
            "electron",
        )

    def test_missing_component_stays_unknown_not_ready(self) -> None:
        registry = build_health_registry({}, now=NOW)
        assert len(registry.components) == 11
        for health in registry.components:
            assert health.status == "unknown"
            assert health.ready is False

    def test_health_registry_is_typed_and_deterministic(self) -> None:
        truth = {c: _component_truth(c) for c in COMPONENTS}
        first = build_health_registry(truth, now=NOW)
        second = build_health_registry(truth, now=NOW)
        assert isinstance(first, HealthRegistry)
        assert first.model_dump() == second.model_dump()


class TestMetrics:
    @pytest.mark.parametrize("metric", ("latency", "success", "failure", "freshness"))
    def test_every_metric_kind_is_typed(self, metric: str) -> None:
        record = MetricRecord(
            timestamp=NOW,
            component="oanda",
            metric=cast(Any, metric),
            value="1",
            unit="count",
            correlation_id="order-1",
        )
        assert isinstance(record, MetricRecord)
        assert record.metric == metric

    def test_structured_log_record_carries_correlation(self) -> None:
        record = StructuredLogRecord(
            timestamp=NOW,
            component="cycle",
            level="info",
            event="cycle.completed",
            correlation_id="cycle-1",
            correlation_kind="cycle",
            message="cycle completed",
            fields={"outcome": "executed"},
        )
        assert record.correlation_id == "cycle-1"
        assert record.correlation_kind == "cycle"

    def test_naive_log_timestamps_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StructuredLogRecord(
                timestamp=datetime(2026, 8, 14),
                component="api",
                level="info",
                event="e",
                message="m",
            )


class TestRedaction:
    def test_tokens_and_authorization_are_scrubbed(self) -> None:
        text = "Bearer " + "abc123def456 request with Authorization: xyz"
        redacted = redact_observable(text)
        assert "abc123def456" not in redacted
        assert "[REDACTED]" in redacted

    def test_full_account_ids_are_scrubbed(self) -> None:
        full_id = "account-" + "12345678901234567890"
        redacted = redact_observable(f"user {full_id} logged in")
        assert full_id not in redacted
        assert "[REDACTED]" in redacted

    def test_configured_secret_patterns_are_scrubbed(self) -> None:
        text = "key=super-secret-value"
        redacted = redact_observable(text, secret_patterns=(r"key=\S+",))
        assert "super-secret-value" not in redacted

    def test_model_sensitive_content_is_scrubbed(self) -> None:
        redacted = redact_observable("the system prompt was exposed")
        assert "[MODEL-REDACTED]" in redacted

    def test_unlicensed_news_text_is_scrubbed(self) -> None:
        redacted = redact_observable("full article body follows")
        assert "[NEWS-REDACTED]" in redacted

    def test_redaction_is_deterministic(self) -> None:
        text = "Bearer " + "abc123"
        assert redact_observable(text) == redact_observable(text)

    def test_account_id_hash_is_non_reversible(self) -> None:
        full_id = "account-" + "12345678901234567890"
        digest = account_id_hash(full_id)
        assert len(digest) == 12
        assert digest != full_id
