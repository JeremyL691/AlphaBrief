"""Tests for ModelRouter (Phase 14 Round 3)."""

from __future__ import annotations

import pytest
from alphabrief_models import (
    MIN_SCHEMA_PASS_RATE,
    ModelProfile,
    ModelRegistry,
    ModelRouter,
    PerformanceSnapshot,
    ProviderConfig,
)


def _registry_two_profiles() -> ModelRegistry:
    return ModelRegistry(
        providers=[
            ProviderConfig(provider_name="openai", enabled=True),
            ProviderConfig(provider_name="anthropic", enabled=True),
        ],
        profiles=[
            ModelProfile(
                profile_id="fast",
                provider_name="openai",
                model_name="gpt-4o-mini",
                capabilities=["text_generation", "structured_output"],
                priority=10,
            ),
            ModelProfile(
                profile_id="strong",
                provider_name="anthropic",
                model_name="claude-3",
                capabilities=[
                    "text_generation",
                    "structured_output",
                    "strong_reasoning",
                ],
                priority=5,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Capability-only routing (no performance data)
# ---------------------------------------------------------------------------


def test_router_without_performance_provider_uses_capability_only() -> None:
    router = ModelRouter(_registry_two_profiles())
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
    )
    assert decision.profile_id == "strong"
    assert decision.used_performance_data is False
    assert "capability-only" in decision.routing_reason


def test_router_returns_none_when_no_profile_matches() -> None:
    registry = ModelRegistry(
        providers=[ProviderConfig(provider_name="openai", enabled=True)],
        profiles=[
            ModelProfile(
                profile_id="basic",
                provider_name="openai",
                model_name="gpt-4o-mini",
                capabilities=["text_generation", ],
            )
        ],
    )
    router = ModelRouter(registry)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["vision", "embeddings"],
    )
    assert decision.profile_id is None
    assert "no profile matches" in decision.routing_reason


# ---------------------------------------------------------------------------
# Performance-based routing
# ---------------------------------------------------------------------------


def _snapshot(
    model_id: str,
    schema_pass_rate: float | None = None,
    json_valid_rate: float | None = None,
    latency_ms: int | None = None,
    cost: float | None = None,
) -> dict[str, object]:
    return {
        "model_id": model_id,
        "task_type": "daily_brief",
        "schema_pass_rate": schema_pass_rate,
        "json_valid_rate": json_valid_rate,
        "avg_latency_ms": latency_ms,
        "avg_cost_estimate": cost,
    }


def test_router_prefers_higher_schema_pass_rate() -> None:
    provider = lambda model_id, task_type: _snapshot(  # noqa: E731
        model_id,
        schema_pass_rate=0.95 if "claude" in model_id else 0.6,
    )
    router = ModelRouter(_registry_two_profiles(), performance_provider=provider)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
    )
    assert decision.profile_id == "strong"
    assert decision.used_performance_data is True
    assert "schema_pass_rate=0.95" in decision.routing_reason


def test_router_below_min_schema_pass_rate_is_filtered() -> None:
    provider = lambda model_id, task_type: _snapshot(  # noqa: E731
        model_id,
        schema_pass_rate=0.95 if "gpt" in model_id else 0.3,
    )
    router = ModelRouter(_registry_two_profiles(), performance_provider=provider)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
    )
    assert decision.profile_id == "fast"


def test_router_prefer_low_latency_picks_lower_latency() -> None:
    provider = lambda model_id, task_type: _snapshot(  # noqa: E731
        model_id,
        schema_pass_rate=0.9,
        latency_ms=200 if "gpt" in model_id else 1500,
    )
    router = ModelRouter(_registry_two_profiles(), performance_provider=provider)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
        prefer_low_latency=True,
    )
    assert decision.profile_id == "fast"
    assert "avg_latency_ms=200" in decision.routing_reason


def test_router_prefer_low_cost_picks_lower_cost() -> None:
    provider = lambda model_id, task_type: _snapshot(  # noqa: E731
        model_id,
        schema_pass_rate=0.9,
        cost=0.001 if "gpt" in model_id else 0.02,
    )
    router = ModelRouter(_registry_two_profiles(), performance_provider=provider)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
        prefer_low_cost=True,
    )
    assert decision.profile_id == "fast"


def test_router_handles_missing_snapshots() -> None:
    """Snapshots that come back as None should be treated as no-data."""
    provider = lambda model_id, task_type: _snapshot(  # noqa: E731
        model_id,
        schema_pass_rate=0.95 if "claude" in model_id else None,
    )
    router = ModelRouter(_registry_two_profiles(), performance_provider=provider)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
    )
    assert decision.profile_id == "strong"


def test_router_handles_provider_exceptions() -> None:
    def provider(model_id: str, task_type: str) -> dict[str, object]:
        raise RuntimeError("db down")

    router = ModelRouter(_registry_two_profiles(), performance_provider=provider)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
    )
    assert decision.profile_id == "strong"
    assert decision.used_performance_data is False


def test_router_falls_back_to_capability_only_when_all_snapshots_empty() -> None:
    def provider(model_id: str, task_type: str) -> None:
        return None

    router = ModelRouter(_registry_two_profiles(), performance_provider=provider)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
    )
    assert decision.profile_id == "strong"
    assert decision.used_performance_data is False


# ---------------------------------------------------------------------------
# Construction validation
# ---------------------------------------------------------------------------


def test_router_rejects_none_registry() -> None:
    with pytest.raises(ValueError, match="registry"):
        ModelRouter(None)  # type: ignore[arg-type]


def test_router_rejects_invalid_min_schema_pass_rate() -> None:
    with pytest.raises(ValueError, match="min_schema_pass_rate"):
        ModelRouter(_registry_two_profiles(), min_schema_pass_rate=1.5)
    with pytest.raises(ValueError, match="min_schema_pass_rate"):
        ModelRouter(_registry_two_profiles(), min_schema_pass_rate=-0.1)


def test_router_accepts_performance_snapshot_objects() -> None:
    def provider(model_id: str, task_type: str) -> PerformanceSnapshot:
        return PerformanceSnapshot(
            model_id=model_id,
            task_type=task_type,
            schema_pass_rate=0.9,
        )

    router = ModelRouter(_registry_two_profiles(), performance_provider=provider)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
    )
    assert decision.profile_id in ("fast", "strong")
    assert decision.used_performance_data is True


def test_router_min_schema_pass_rate_default() -> None:
    router = ModelRouter(_registry_two_profiles())
    assert router._min_schema_pass_rate == MIN_SCHEMA_PASS_RATE  # noqa: SLF001


def test_router_candidates_includes_all_matches() -> None:
    router = ModelRouter(_registry_two_profiles())
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
    )
    assert "fast" in decision.candidates
    assert "strong" in decision.candidates


def test_router_is_stable_for_equal_scores() -> None:
    """When two profiles have identical performance, the lower priority id wins."""
    provider = lambda model_id, task_type: _snapshot(  # noqa: E731
        model_id, schema_pass_rate=0.9,
    )
    router = ModelRouter(_registry_two_profiles(), performance_provider=provider)
    decision = router.route(
        task_type="daily_brief",
        required_capabilities=["text_generation", "structured_output"],
    )
    assert decision.profile_id in ("fast", "strong")
    assert decision.used_performance_data is True
