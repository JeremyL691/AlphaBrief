"""Model channel composition: subscription first, optional explicit fallback.

Rules from the product spec:

* the main channel is the ChatGPT subscription (``chatgpt_plan``);
* the fallback channel is used **only** when the configuration says
  ``model.fallback_enabled: true`` — billing channels never switch
  silently, so every switch is recorded and surfaced;
* when neither channel can serve a request the caller gets no response
  and must record ``NO_TRADE_MODEL_UNAVAILABLE`` (no synthetic model);
* an endpoint whose host contains ``opencode.ai`` is refused outright.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from alphabrief_models.chatgpt_oauth import refresh_credentials
from alphabrief_models.chatgpt_plan import (
    ChatGptCredentials,
    ChatGptPlanAdapter,
    ChatGptPlanError,
    HttpSend,
    load_credentials,
)
from alphabrief_models.gateway import (
    ModelCallRecord,
    ModelGateway,
    ProviderAdapter,
)
from alphabrief_models.model_budget import (
    CHATGPT_PLAN_CHANNEL,
    DEFAULT_CHATGPT_DAILY_CALLS,
    DEFAULT_FALLBACK_DAILY_USD,
    OPENAI_COMPATIBLE_CHANNEL,
    ModelBudgetGuard,
    ModelBudgetPolicy,
)
from alphabrief_models.openai_compatible import (
    FallbackConfig,
    OpenAiCompatibleAdapter,
    load_fallback_config,
)

CONFIG_PATH = Path("config/alphabrief.yaml")


@dataclass(frozen=True)
class ModelSettings:
    """Resolved ``model:`` configuration section."""

    fallback_enabled: bool = False
    primary_model: str | None = None
    #: PROJECT_GUIDE 5.13 daily limits, configurable per installation.
    daily_call_limit: int = DEFAULT_CHATGPT_DAILY_CALLS
    daily_cost_limit_usd: Decimal = DEFAULT_FALLBACK_DAILY_USD
    input_cost_per_million: Decimal | None = None
    output_cost_per_million: Decimal | None = None
    max_output_tokens: int = 2048

    def budget_policy(self) -> ModelBudgetPolicy:
        """The per-channel daily budget policy this configuration implies."""
        return ModelBudgetPolicy(
            daily_call_limits={CHATGPT_PLAN_CHANNEL: self.daily_call_limit},
            daily_cost_limits={OPENAI_COMPATIBLE_CHANNEL: self.daily_cost_limit_usd},
        )


def load_model_settings(path: Path | None = None) -> ModelSettings:
    """Read the ``model:`` section of ``config/alphabrief.yaml``.

    A missing file yields the defaults (fallback disabled); a malformed
    section raises so a typo cannot silently disable the subscription
    channel.
    """
    config_path = path or CONFIG_PATH
    if not config_path.is_file():
        return ModelSettings()
    document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if document is None:
        return ModelSettings()
    if not isinstance(document, dict):
        raise ValueError(f"{config_path} must contain a YAML mapping")
    section = document.get("model") or {}
    if not isinstance(section, dict):
        raise ValueError(f"{config_path}: model section must be a mapping")
    fallback = section.get("fallback_enabled", False)
    if not isinstance(fallback, bool):
        raise ValueError(f"{config_path}: model.fallback_enabled must be true or false")
    primary_model = section.get("primary_model")
    if primary_model is not None and not isinstance(primary_model, str):
        raise ValueError(f"{config_path}: model.primary_model must be a string")
    daily_call_limit = section.get("daily_call_limit", DEFAULT_CHATGPT_DAILY_CALLS)
    if isinstance(daily_call_limit, bool) or not isinstance(daily_call_limit, int):
        raise ValueError(f"{config_path}: model.daily_call_limit must be an integer")
    if daily_call_limit <= 0:
        raise ValueError(f"{config_path}: model.daily_call_limit must be positive")
    raw_cost_limit = section.get(
        "daily_cost_limit_usd", str(DEFAULT_FALLBACK_DAILY_USD)
    )
    try:
        daily_cost_limit = Decimal(str(raw_cost_limit))
    except (ArithmeticError, ValueError) as exc:
        raise ValueError(
            f"{config_path}: model.daily_cost_limit_usd must be a decimal"
        ) from exc
    if not daily_cost_limit.is_finite() or daily_cost_limit <= 0:
        raise ValueError(f"{config_path}: model.daily_cost_limit_usd must be positive")
    prices: dict[str, Decimal | None] = {}
    for key in ("input_cost_per_million", "output_cost_per_million"):
        raw = section.get(key)
        if raw is None:
            prices[key] = None
            continue
        if not isinstance(raw, str):
            raise ValueError(f"{config_path}: model.{key} must be a decimal string")
        try:
            value = Decimal(raw)
        except ArithmeticError as exc:
            raise ValueError(f"{config_path}: model.{key} must be a decimal") from exc
        if not value.is_finite() or value < 0:
            raise ValueError(
                f"{config_path}: model.{key} must be nonnegative and finite"
            )
        prices[key] = value
    output_limit = section.get("max_output_tokens", 2048)
    if (
        isinstance(output_limit, bool)
        or not isinstance(output_limit, int)
        or output_limit <= 0
    ):
        raise ValueError("model.max_output_tokens must be a positive integer")
    return ModelSettings(
        fallback_enabled=fallback,
        primary_model=primary_model,
        daily_call_limit=daily_call_limit,
        daily_cost_limit_usd=daily_cost_limit,
        input_cost_per_million=prices["input_cost_per_million"],
        output_cost_per_million=prices["output_cost_per_million"],
        max_output_tokens=output_limit,
    )


@dataclass
class ChannelSwitch:
    """One recorded transition between model channels."""

    at: datetime
    from_channel: str
    to_channel: str
    reason: str


@dataclass
class ChannelState:
    """Mutable view of which channel served which call."""

    switches: list[ChannelSwitch] = field(default_factory=list)


class _RecordingAdapter:
    """Delegate that records which channel actually served a call."""

    def __init__(
        self,
        inner: ProviderAdapter,
        *,
        state: ChannelState,
        clock: Callable[[], datetime],
    ) -> None:
        self._inner = inner
        self._state = state
        self._clock = clock
        self.provider_name = inner.provider_name
        self.model_name = inner.model_name
        self.capabilities = inner.capabilities

    def call(self, request: Any) -> Any:
        try:
            return self._inner.call(request)
        except ChatGptPlanError as exc:
            self._state.switches.append(
                ChannelSwitch(
                    at=self._clock(),
                    from_channel=self._inner.provider_name,
                    to_channel="fallback",
                    reason=exc.code,
                )
            )
            raise


class ChannelGateway:
    """Model gateway plus the channel-selection policy."""

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        state: ChannelState,
        settings: ModelSettings,
        primary_channel: str,
        fallback_channel: str | None,
    ) -> None:
        self._gateway = gateway
        self.state = state
        self.settings = settings
        self.primary_channel = primary_channel
        self.fallback_channel = fallback_channel

    @property
    def gateway(self) -> ModelGateway:
        return self._gateway

    def invoke(self, request: Any) -> Any:
        """Invoke the gateway.

        Channel selection (including the opt-in fallback) is owned by the
        gateway's provider order and ``fallback_enabled`` flag, so exactly
        one record is emitted per attempt.
        """
        return self._gateway.invoke(request)

    def switch_report(self) -> list[dict[str, object]]:
        """JSON-safe view of the recorded channel switches."""
        return [
            {
                "at": switch.at.isoformat(),
                "from": switch.from_channel,
                "to": switch.to_channel,
                "reason": switch.reason,
            }
            for switch in self.state.switches
        ]


def build_channel_gateway(
    *,
    settings: ModelSettings | None = None,
    config_path: Path | None = None,
    environ: dict[str, str] | None = None,
    http_send: HttpSend | None = None,
    credentials: ChatGptCredentials | None = None,
    primary_model: str | None = None,
    clock: Callable[[], datetime] | None = None,
    record_sink: Callable[[ModelCallRecord], None] | None = None,
    allow_fallback: bool | None = None,
    daily_budget: ModelBudgetGuard | None = None,
) -> ChannelGateway:
    """Build the gateway with the subscription channel first.

    ``allow_fallback`` overrides the configuration flag for tests; the
    product path always reads the configuration.
    """
    resolved = settings or load_model_settings(config_path)
    current = clock or (lambda: datetime.now(UTC))
    state = ChannelState()

    stored = credentials
    if stored is None:
        stored = load_credentials()

    def _refresh(credentials_to_refresh: ChatGptCredentials) -> ChatGptCredentials:
        return refresh_credentials(
            credentials_to_refresh, http_send=http_send, clock=current
        )

    primary: ProviderAdapter = ChatGptPlanAdapter(
        credentials=stored,
        model_name=primary_model or resolved.primary_model,
        http_send=http_send,
        clock=current,
        refresh_handler=_refresh,
    )
    providers: Sequence[ProviderAdapter] = [
        _RecordingAdapter(primary, state=state, clock=current)
    ]

    fallback_configured = allow_fallback
    if fallback_configured is None:
        fallback_configured = resolved.fallback_enabled
    fallback_channel: str | None = None
    if fallback_configured:
        fallback: FallbackConfig | None = load_fallback_config(environ)
        if fallback is None:
            raise ValueError(
                "model.fallback_enabled is true but no fallback channel is "
                "configured (set ALPHABRIEF_LLM_BASE_URL, ALPHABRIEF_LLM_API_KEY, "
                "ALPHABRIEF_LLM_MODEL)"
            )
        fallback = replace(
            fallback,
            input_cost_per_million=resolved.input_cost_per_million,
            output_cost_per_million=resolved.output_cost_per_million,
            max_output_tokens=resolved.max_output_tokens,
        )
        adapter = OpenAiCompatibleAdapter(fallback, http_send=http_send, clock=current)
        fallback_channel = adapter.provider_name
        providers = [*providers, adapter]

    gateway = ModelGateway(
        providers,
        clock=current,
        record_sink=record_sink,
        fallback_enabled=fallback_channel is not None,
        daily_budget=daily_budget,
    )
    return ChannelGateway(
        gateway=gateway,
        state=state,
        settings=resolved,
        primary_channel=primary.provider_name,
        fallback_channel=fallback_channel,
    )


__all__ = [
    "CONFIG_PATH",
    "ChannelGateway",
    "ChannelState",
    "ChannelSwitch",
    "ModelSettings",
    "build_channel_gateway",
    "load_model_settings",
]
