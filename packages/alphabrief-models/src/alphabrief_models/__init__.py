"""Model gateway contracts for AlphaBrief."""

from alphabrief_models.adapters import OllamaProviderAdapter
from alphabrief_models.channels import (
    ChannelGateway,
    ChannelState,
    ChannelSwitch,
    ModelSettings,
    build_channel_gateway,
    load_model_settings,
)
from alphabrief_models.chatgpt_oauth import (
    refresh_credentials,
    scope_summary,
)
from alphabrief_models.chatgpt_plan import (
    ChatGptCredentials,
    ChatGptPlanAdapter,
    ChatGptPlanError,
    clear_credentials,
    fetch_model_slugs,
    load_credentials,
    save_credentials,
)
from alphabrief_models.gateway import (
    FakeProviderAdapter,
    ModelCallBudget,
    ModelCallClassification,
    ModelCallRecord,
    ModelCallStatus,
    ModelCapability,
    ModelGateway,
    ModelGatewayResult,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelTaskType,
    ProviderAdapter,
    classify_provider_error,
)
from alphabrief_models.openai_adapter import OpenAIProviderAdapter
from alphabrief_models.openai_compatible import (
    FallbackConfig,
    OpenAiCompatibleAdapter,
    load_fallback_config,
)
from alphabrief_models.repair import (
    RepairVerdict,
    StructuredRepairResult,
    default_repair_prompt_builder,
    repair_structured_output,
)
from alphabrief_models.structured_output import (
    StructuredOutputErrorCode,
    StructuredOutputResult,
    parse_structured_output,
)

__all__ = [
    "ChannelGateway",
    "ChannelState",
    "ChannelSwitch",
    "ChatGptCredentials",
    "ChatGptPlanAdapter",
    "ChatGptPlanError",
    "FallbackConfig",
    "ModelSettings",
    "OpenAiCompatibleAdapter",
    "build_channel_gateway",
    "clear_credentials",
    "fetch_model_slugs",
    "load_credentials",
    "load_fallback_config",
    "load_model_settings",
    "refresh_credentials",
    "save_credentials",
    "scope_summary",
    "FakeProviderAdapter",
    "ModelCallBudget",
    "ModelCallClassification",
    "ModelCallRecord",
    "ModelCallStatus",
    "ModelCapability",
    "ModelGateway",
    "ModelGatewayResult",
    "ModelProviderError",
    "ModelRequest",
    "ModelResponse",
    "ModelResponseStatus",
    "ModelTaskType",
    "OllamaProviderAdapter",
    "OpenAIProviderAdapter",
    "ProviderAdapter",
    "RepairVerdict",
    "StructuredOutputErrorCode",
    "StructuredRepairResult",
    "StructuredOutputResult",
    "default_repair_prompt_builder",
    "classify_provider_error",
    "parse_structured_output",
    "repair_structured_output",
]
