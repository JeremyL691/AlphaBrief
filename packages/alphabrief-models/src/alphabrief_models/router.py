"""Model router for AlphaBrief (Phase 14 Round 3).

Routes a task to the best available model profile by combining the
existing :class:`ModelRegistry` capability-based lookup with optional
performance history from :class:`alphabrief_api.db.model_eval.ModelEvalStore`.

Routing is **advisory only** — it never forces a model choice, never
overrides a user-supplied model, and is no-op when no performance
data is available (the system behaves identically to today).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from alphabrief_models.gateway import ModelCapability
from alphabrief_models.registry import ModelProfile, ModelRegistry

MIN_SCHEMA_PASS_RATE: float = 0.7
MIN_JSON_VALID_RATE: float = 0.7


@dataclass(frozen=True)
class ModelRouteDecision:
    """The result of a routing decision.

    Attributes
    ----------
    profile_id
        The selected profile, or ``None`` if no profile matched.
    provider_name
        The provider name for the selected profile.
    model_name
        The model name for the selected profile.
    routing_reason
        Human-readable explanation of why this profile was selected.
    candidates
        All candidate profile ids considered (in selection order).
    used_performance_data
        Whether the decision was informed by performance data.
    """

    profile_id: str | None
    provider_name: str
    model_name: str
    routing_reason: str
    candidates: tuple[str, ...] = ()
    used_performance_data: bool = False


@dataclass(frozen=True)
class PerformanceSnapshot:
    """A minimal view of a model evaluation for routing.

    Only the fields relevant to routing are retained. The router
    treats higher schema_pass_rate as better, lower latency and
    lower cost as better. Missing fields fall back to safe defaults
    (pass-rate → 0.0, latency → +inf, cost → +inf).
    """

    model_id: str
    task_type: str
    schema_pass_rate: float | None = None
    json_valid_rate: float | None = None
    avg_latency_ms: int | None = None
    avg_cost_estimate: float | None = None


PerformanceProvider = Callable[[str, str], Any]


class ModelRouter:
    """Capability + performance-aware model router.

    Parameters
    ----------
    registry
        The :class:`ModelRegistry` to draw capability-based
        candidates from.
    performance_provider
        Optional callable returning performance snapshots for a
        given ``(model_id, task_type)`` pair. When ``None``, routing
        is capability-only and preserves legacy behavior.
    min_schema_pass_rate
        Minimum acceptable ``schema_pass_rate`` for structured tasks.
        Profiles below this threshold are deprioritized. Defaults to
        :data:`MIN_SCHEMA_PASS_RATE`.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        performance_provider: PerformanceProvider | None = None,
        min_schema_pass_rate: float = MIN_SCHEMA_PASS_RATE,
    ) -> None:
        if registry is None:
            raise ValueError("registry must not be None")
        if not (0.0 <= min_schema_pass_rate <= 1.0):
            raise ValueError("min_schema_pass_rate must be in [0.0, 1.0]")
        self._registry = registry
        self._performance_provider = performance_provider
        self._min_schema_pass_rate = min_schema_pass_rate

    def route(
        self,
        *,
        task_type: str,
        required_capabilities: Iterable[ModelCapability],
        prefer_low_cost: bool = False,
        prefer_low_latency: bool = False,
    ) -> ModelRouteDecision:
        """Select the best profile for a task, considering performance.

        Returns
        -------
        ModelRouteDecision
            Contains the selected profile, candidates, and rationale.
            When no profile matches the required capabilities, the
            returned decision has ``profile_id=None``.
        """
        caps = list(required_capabilities)
        matches = self._registry.matching_profiles(caps)
        if not matches:
            return ModelRouteDecision(
                profile_id=None,
                provider_name="",
                model_name="",
                routing_reason=(
                    f"no profile matches required capabilities {caps!r}"
                ),
                candidates=(),
                used_performance_data=False,
            )

        performance_provider = self._performance_provider
        if performance_provider is None:
            return self._capability_only_decision(matches)

        snapshots = self._collect_snapshots(matches, task_type, performance_provider)
        has_any = any(s is not None for s in snapshots)
        if not has_any:
            return self._capability_only_decision(matches)

        scored = self._score_profiles(
            matches, snapshots, task_type,
            prefer_low_cost=prefer_low_cost,
            prefer_low_latency=prefer_low_latency,
        )
        best = scored[0]
        profile, score_snapshot = best
        reason = self._format_reason(
            profile, score_snapshot, prefer_low_cost, prefer_low_latency
        )
        return ModelRouteDecision(
            profile_id=profile.profile_id,
            provider_name=profile.provider_name,
            model_name=profile.model_name,
            routing_reason=reason,
            candidates=tuple(p.profile_id for p, _ in scored),
            used_performance_data=True,
        )

    def _capability_only_decision(
        self, matches: list[ModelProfile]
    ) -> ModelRouteDecision:
        profile = matches[0]
        return ModelRouteDecision(
            profile_id=profile.profile_id,
            provider_name=profile.provider_name,
            model_name=profile.model_name,
            routing_reason=(
                f"capability-only selection (priority={profile.priority})"
            ),
            candidates=tuple(p.profile_id for p in matches),
            used_performance_data=False,
        )

    def _collect_snapshots(
        self,
        matches: list[ModelProfile],
        task_type: str,
        performance_provider: PerformanceProvider,
    ) -> list[PerformanceSnapshot | None]:
        results: list[PerformanceSnapshot | None] = []
        for profile in matches:
            model_id = f"{profile.provider_name}:{profile.model_name}"
            snapshot = self._safe_fetch_snapshot(
                model_id, task_type, performance_provider
            )
            results.append(snapshot)
        return results

    def _safe_fetch_snapshot(
        self, model_id: str, task_type: str,
        performance_provider: PerformanceProvider,
    ) -> PerformanceSnapshot | None:
        try:
            payload = performance_provider(model_id, task_type)
        except Exception:
            return None
        if payload is None:
            return None
        if isinstance(payload, PerformanceSnapshot):
            return payload
        if isinstance(payload, dict):
            return PerformanceSnapshot(
                model_id=model_id,
                task_type=task_type,
                schema_pass_rate=payload.get("schema_pass_rate"),
                json_valid_rate=payload.get("json_valid_rate"),
                avg_latency_ms=payload.get("avg_latency_ms"),
                avg_cost_estimate=payload.get("avg_cost_estimate"),
            )
        return None

    def _score_profiles(
        self,
        matches: list[ModelProfile],
        snapshots: Sequence[PerformanceSnapshot | None],
        task_type: str,
        *,
        prefer_low_cost: bool,
        prefer_low_latency: bool,
    ) -> list[tuple[ModelProfile, PerformanceSnapshot | None]]:
        is_structured = "structured_output" in task_type or task_type in (
            "daily_brief",
            "strategy_review",
            "symbol_research",
            "risk_review",
            "market_summary",
        )

        def score(
            profile: ModelProfile,
            snap: PerformanceSnapshot | None,
        ) -> tuple[int, float, float, float, int, str]:
            eligible = 1
            if is_structured and snap is not None:
                rate = snap.schema_pass_rate
                if rate is not None and rate < self._min_schema_pass_rate:
                    eligible = 0
            rate_score = (
                -(snap.schema_pass_rate or 0.0) if snap is not None else 0.0
            )
            json_score = (
                -(snap.json_valid_rate or 0.0) if snap is not None else 0.0
            )
            latency = (
                float(snap.avg_latency_ms)
                if snap is not None and snap.avg_latency_ms is not None
                else float("inf")
            )
            cost = (
                snap.avg_cost_estimate
                if snap is not None and snap.avg_cost_estimate is not None
                else float("inf")
            )
            if not prefer_low_latency:
                latency = 0.0
            if not prefer_low_cost:
                cost = 0.0
            return (
                -eligible,
                rate_score,
                json_score,
                latency + cost,
                profile.priority,
                profile.profile_id,
            )

        scored = [
            (profile, snap)
            for profile, snap in zip(matches, snapshots, strict=True)
        ]
        scored.sort(key=lambda pair: score(*pair))
        return scored

    def _format_reason(
        self,
        profile: ModelProfile,
        snap: PerformanceSnapshot | None,
        prefer_low_cost: bool,
        prefer_low_latency: bool,
    ) -> str:
        parts: list[str] = []
        if snap is not None and snap.schema_pass_rate is not None:
            parts.append(f"schema_pass_rate={snap.schema_pass_rate:.2f}")
        if snap is not None and snap.json_valid_rate is not None:
            parts.append(f"json_valid_rate={snap.json_valid_rate:.2f}")
        if prefer_low_latency and snap is not None and snap.avg_latency_ms is not None:
            parts.append(f"avg_latency_ms={snap.avg_latency_ms}")
        if prefer_low_cost and snap is not None and snap.avg_cost_estimate is not None:
            parts.append(f"avg_cost={snap.avg_cost_estimate:.4f}")
        parts.append(f"priority={profile.priority}")
        if not parts:
            return f"performance: priority={profile.priority}"
        return "performance: " + ", ".join(parts)


__all__ = [
    "MIN_JSON_VALID_RATE",
    "MIN_SCHEMA_PASS_RATE",
    "ModelRouteDecision",
    "ModelRouter",
    "PerformanceSnapshot",
]
