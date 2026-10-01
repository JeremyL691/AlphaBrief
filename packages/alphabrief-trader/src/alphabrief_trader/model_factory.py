"""Model provider factory for the AI Trading Committee.

All model traffic goes through :class:`~alphabrief_models.gateway.ModelGateway`
and the channel composition in :mod:`alphabrief_models.channels`:

* ``chatgpt_plan`` — the ChatGPT subscription channel (main);
* ``openai_compatible`` — the optional fallback, only when
  ``model.fallback_enabled`` is true and ``ALPHABRIEF_LLM_*`` is set;
* ``fake`` — an explicit test/dev selection, never a production fallback.

The old ``OPENAI_API_KEY``/``OPENAI_BASE_URL`` environment variables are
**not** read here: those belong to the operator's coding tools, not to
this product.
"""

from __future__ import annotations

from collections.abc import Callable

from alphabrief_models import (
    ChannelGateway,
    ChannelState,
    FakeProviderAdapter,
    ModelCallBudget,
    ModelCallRecord,
    ModelCapability,
    ModelGateway,
    ModelSettings,
    ProviderAdapter,
    build_channel_gateway,
)

from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.rules import DisciplineConfig

AI_MODEL_PROVIDER_ENV = "ALPHABRIEF_AI_MODEL_PROVIDER"
AI_MODEL_NAME_ENV = "ALPHABRIEF_AI_MODEL_NAME"

_STRUCTURED_CAPABILITIES: frozenset[ModelCapability] = frozenset(
    {"text_generation", "structured_output", "json_mode"}
)

#: Explicit provider selections. Anything else means "use the channels".
_EXPLICIT_SELECTIONS = frozenset({"fake"})


class ModelProviderUnavailableError(RuntimeError):
    """Raised when no real model channel is configured.

    Production composition must fail closed: a missing channel must never
    be silently replaced by a deterministic fake that could fabricate
    research or orders.
    """


def build_ai_trading_channels(
    *,
    record_sink: Callable[[ModelCallRecord], None] | None = None,
    budget: ModelCallBudget | None = None,
) -> ChannelGateway:
    """Return the configured channel gateway for the trading committee.

    An explicit ``fake`` selection builds a single fake provider so test
    composition never reaches the network; every other selection uses the
    real channel composition (subscription first, opt-in fallback).
    """
    if _selection() == "fake":
        gateway = ModelGateway(
            [build_conservative_fake_provider()],
            record_sink=record_sink,
            budget=budget,
        )
        return ChannelGateway(
            gateway=gateway,
            state=ChannelState(),
            settings=ModelSettings(),
            primary_channel="fake",
            fallback_channel=None,
        )
    channels = build_channel_gateway(record_sink=record_sink)
    if budget is not None:
        channels.gateway.set_budget(budget)
    return channels


def build_ai_trading_committee(
    *,
    record_sink: Callable[[ModelCallRecord], None] | None = None,
    budget: ModelCallBudget | None = None,
) -> TradingCommittee:
    """Build the AI Trading Committee on the configured channels.

    ``record_sink`` and ``budget`` are forwarded to the ModelGateway so
    production callers persist every terminal call record and bound
    per-request/cycle/daily model usage.
    """
    channels = build_ai_trading_channels(record_sink=record_sink, budget=budget)
    return TradingCommittee(
        gateway=channels.gateway, discipline=DisciplineConfig(),
        max_turns=5, challenge_rounds=0,
    )


def build_ai_trading_provider() -> ProviderAdapter:
    """Return the model provider for the committee.

    ``ALPHABRIEF_AI_MODEL_PROVIDER=fake`` is the only explicit selection
    and exists for tests; every other value (including unset) uses the
    ChatGPT subscription channel, which fails closed when not signed in.
    """
    if _selection() == "fake":
        return build_conservative_fake_provider()
    channels = build_channel_gateway()
    return channels.gateway._providers[0]  # noqa: SLF001 - single-channel wiring


def _selection() -> str:
    import os

    requested = os.environ.get(AI_MODEL_PROVIDER_ENV, "auto").strip().lower()
    if requested in {"", "auto", "chatgpt", "chatgpt_plan"}:
        return "chatgpt_plan"
    if requested in _EXPLICIT_SELECTIONS:
        return requested
    raise ValueError(
        f"{AI_MODEL_PROVIDER_ENV} must be one of auto, chatgpt, fake"
    )


def build_conservative_fake_provider() -> FakeProviderAdapter:
    """Return the deterministic fake provider for explicit test selection.

    Only reachable through an explicit ``ALPHABRIEF_AI_MODEL_PROVIDER=fake``
    environment selection or a direct test import. It is never used as a
    production fallback.
    """
    return FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-ai-committee",
        capabilities=sorted(_STRUCTURED_CAPABILITIES),
        structured_output={
            "analysis": (
                "Trend remains constructive on improving breadth; downside risks "
                "centered on macro headlines and crowded positioning."
            ),
            "view": "bullish",
            "confidence": 0.62,
            "evidence": [
                "EMA20 above EMA50 with rising volume",
                "News tone modestly positive",
            ],
            "risks": ["Macro headline tail-risk", "Crowded long positioning"],
            "suggested_action": "watch",
            "target_position_pct": "0.10",
            "veto": False,
            "needs_human_review": True,
        },
    )


__all__ = [
    "AI_MODEL_NAME_ENV",
    "AI_MODEL_PROVIDER_ENV",
    "ModelProviderUnavailableError",
    "build_ai_trading_channels",
    "build_ai_trading_committee",
    "build_ai_trading_provider",
    "build_conservative_fake_provider",
]
