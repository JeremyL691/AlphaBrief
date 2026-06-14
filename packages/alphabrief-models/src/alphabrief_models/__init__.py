"""Model gateway contracts for AlphaBrief."""

from alphabrief_models.adapters import OllamaProviderAdapter
from alphabrief_models.briefs import (
    BriefHorizon,
    DailyAlphaBrief,
    MarketBrief,
    MarketRegime,
    SymbolBrief,
    SymbolDirection,
    SymbolVerdict,
)
from alphabrief_models.daily import (
    DailyBriefGenerationErrorCode,
    DailyBriefGenerationResult,
    generate_daily_alpha_brief,
)
from alphabrief_models.gateway import (
    FakeProviderAdapter,
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
)
from alphabrief_models.openai_adapter import OpenAIProviderAdapter
from alphabrief_models.prompts import (
    PromptTemplate,
    PromptTemplateError,
    PromptTemplateRegistry,
    RenderedPrompt,
)
from alphabrief_models.registry import ModelProfile, ModelRegistry, ProviderConfig
from alphabrief_models.structured_output import (
    StructuredOutputErrorCode,
    StructuredOutputResult,
    parse_structured_output,
)

__all__ = [
    "BriefHorizon",
    "DailyAlphaBrief",
    "DailyBriefGenerationErrorCode",
    "DailyBriefGenerationResult",
    "FakeProviderAdapter",
    "MarketBrief",
    "MarketRegime",
    "ModelCallRecord",
    "ModelCallStatus",
    "ModelCapability",
    "ModelGateway",
    "ModelGatewayResult",
    "ModelProviderError",
    "ModelProfile",
    "ModelRequest",
    "ModelResponse",
    "ModelResponseStatus",
    "ModelRegistry",
    "ModelTaskType",
    "OllamaProviderAdapter",
    "OpenAIProviderAdapter",
    "ProviderAdapter",
    "ProviderConfig",
    "PromptTemplate",
    "PromptTemplateError",
    "PromptTemplateRegistry",
    "RenderedPrompt",
    "StructuredOutputErrorCode",
    "StructuredOutputResult",
    "SymbolBrief",
    "SymbolDirection",
    "SymbolVerdict",
    "generate_daily_alpha_brief",
    "parse_structured_output",
]
