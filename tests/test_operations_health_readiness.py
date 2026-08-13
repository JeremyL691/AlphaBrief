"""M15-W01: component health and readiness.

Covers AC-M15-W01-01 health/readiness semantics: every critical
subsystem reports a typed status and readiness; missing truth is
unknown and not ready, never assumed healthy.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from alphabrief_core import (
    COMPONENTS,
    ComponentHealth,
    HealthRegistry,
    build_health_registry,
)

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)


def _by_component(registry: HealthRegistry, component: str) -> ComponentHealth:
    return next(h for h in registry.components if h.component == component)


class TestHealthStatuses:
    @pytest.mark.parametrize(
        "status,ready",
        [
            ("healthy", True),
            ("degraded", True),
            ("unhealthy", False),
            ("unknown", False),
        ],
    )
    def test_status_matrix(self, status: str, ready: bool) -> None:
        registry = build_health_registry(
            {"api": {"status": status, "ready": ready}}, now=NOW
        )
        health = _by_component(registry, "api")
        assert health.status == status
        assert health.ready is ready

    def test_invalid_status_falls_back_to_unknown(self) -> None:
        registry = build_health_registry(
            {"api": {"status": "banana", "ready": True}}, now=NOW
        )
        assert _by_component(registry, "api").status == "unknown"

    def test_unknown_status_is_never_ready(self) -> None:
        registry = build_health_registry({}, now=NOW)
        for health in registry.components:
            assert health.ready is False

    def test_every_component_is_typed(self) -> None:
        for component in COMPONENTS:
            registry = build_health_registry(
                {component: {"status": "healthy", "ready": True}}, now=NOW
            )
            assert isinstance(_by_component(registry, component), ComponentHealth)
            assert _by_component(registry, component).component == component


class TestReadiness:
    def test_healthy_component_is_ready(self) -> None:
        registry = build_health_registry(
            {
                "scheduler": {
                    "status": "healthy",
                    "ready": True,
                    "heartbeat_at": "2026-08-14T00:00:00+00:00",
                }
            },
            now=NOW,
        )
        assert _by_component(registry, "scheduler").ready is True
        assert _by_component(registry, "scheduler").heartbeat_at is not None

    def test_freshness_is_carried(self) -> None:
        registry = build_health_registry(
            {"news": {"status": "healthy", "ready": True,
                      "freshness": "stale"}},
            now=NOW,
        )
        assert _by_component(registry, "news").freshness == "stale"

    def test_deterministic(self) -> None:
        truth = {c: {"status": "healthy", "ready": True} for c in COMPONENTS}
        first = build_health_registry(truth, now=NOW)
        second = build_health_registry(truth, now=NOW)
        assert first.model_dump() == second.model_dump()
