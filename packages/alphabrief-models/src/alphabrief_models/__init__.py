"""Model gateway contracts for AlphaBrief."""

from alphabrief_models.briefs import (
    BriefHorizon,
    MarketBrief,
    MarketRegime,
    SymbolBrief,
    SymbolDirection,
    SymbolVerdict,
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
from alphabrief_models.registry import ModelProfile, ModelRegistry, ProviderConfig
from alphabrief_models.structured_output import (
    StructuredOutputErrorCode,
    StructuredOutputResult,
    parse_structured_output,
)

__all__ = [
    "BriefHorizon",
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
    "ProviderAdapter",
    "ProviderConfig",
    "StructuredOutputErrorCode",
    "StructuredOutputResult",
    "SymbolBrief",
    "SymbolDirection",
    "SymbolVerdict",
    "parse_structured_output",
]
