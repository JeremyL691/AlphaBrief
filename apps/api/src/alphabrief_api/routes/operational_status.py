"""Read-only operational status the dashboard needs but never had.

The static SPA talks only to ``127.0.0.1``. Two of its panels had no
backend route at all:

* the soak panel needs the same qualification facts the CLI prints from
  ``alphabrief soak status``;
* the settings page needs to say whether the configured model channel is
  actually usable today, and how much of its daily allowance is spent.

Both endpoints are strictly read-only. They open their stores per request
and always close them, they expose no credential value, and they never
mutate durable state. Everything they return is computed from the same
helpers the CLI uses, so the terminal and the dashboard can never disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["operational-status"])


@router.get("/api/v1/soak/status")
def get_soak_status() -> dict[str, Any]:
    """Return the soak qualification facts for the dashboard.

    The evaluator opens the single DuckDB writer database. It takes a
    byte-for-byte snapshot when the resident backend holds the write lock,
    so this endpoint works whether it is served by the resident process
    (which owns the lock itself) or by a separate read-only process.
    """
    from alphabrief_trader.soak_evaluator import evaluate_soak_status

    try:
        status = evaluate_soak_status()
    except Exception as exc:  # noqa: BLE001 - never fabricate a soak state
        raise HTTPException(
            status_code=503,
            detail=f"soak status unavailable: {type(exc).__name__}",
        ) from exc
    return status.to_dict()


@router.get("/api/v1/models")
def get_model_channel_status() -> dict[str, Any]:
    """Return the configured model channel and today's budget usage.

    No credential is read into the response: only whether one is present,
    which channel is primary and how many calls remain today.
    """
    from alphabrief_core import paths as _paths
    from alphabrief_models.channels import load_model_settings
    from alphabrief_models.model_budget import OPENROUTER_FREE_CHANNEL, ModelBudgetGuard

    from alphabrief_api.db.model_call import ModelCallStore

    settings = load_model_settings()
    now = datetime.now(UTC)
    store = ModelCallStore(db_path=_paths.db_path())
    try:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        usage = store.daily_usage(day_start)
        disabled_reason = store.disabled_channel_reason(
            settings.primary_channel, now.date().isoformat()
        )
        budget = ModelBudgetGuard(store, policy=settings.budget_policy())
        limit = budget.call_limit(settings.primary_channel)
        verdict = budget.admit(settings.primary_channel)
    finally:
        store.close()

    channel_usage = usage.get(settings.primary_channel)
    calls_today = channel_usage.calls if channel_usage is not None else 0
    return {
        "primary_channel": settings.primary_channel,
        "primary_model": settings.primary_model,
        "fallback_enabled": settings.fallback_enabled,
        "daily_call_limit": limit,
        "daily_cost_limit_usd": str(settings.daily_cost_limit_usd),
        "calls_today": calls_today,
        "calls_remaining": None if limit is None else max(0, limit - calls_today),
        "available": verdict.allowed,
        "unavailable_reason": None if verdict.allowed else verdict.reason,
        "disabled_for_today": disabled_reason,
        # Whether a usable credential exists, never the credential itself.
        "credential_configured": _credential_is_configured(
            settings.primary_channel == OPENROUTER_FREE_CHANNEL
        ),
        "observed_at": now.isoformat(),
    }


def _credential_is_configured(free_channel: bool) -> bool:
    """True when the primary channel has a credential it can use."""
    try:
        if free_channel:
            from alphabrief_models.openai_compatible import load_openrouter_api_key

            return bool(load_openrouter_api_key())
        from alphabrief_models.chatgpt_plan import load_credentials

        credentials = load_credentials()
        return credentials is not None and not credentials.is_expired()
    except Exception:  # noqa: BLE001 - an unreadable credential is not usable
        return False


__all__ = ["get_model_channel_status", "get_soak_status", "router"]
