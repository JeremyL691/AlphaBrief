"""Model gateway contracts for AlphaBrief."""

from alphabrief_models.adapters import OllamaProviderAdapter
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
