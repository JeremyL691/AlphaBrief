"""Bundled gold-standard evaluation datasets for AlphaBrief.

These datasets are **local Python definitions** — no network calls,
no secrets, no file I/O. They exist to seed :class:`ModelEvaluator`
with reproducible evaluation material.

Each dataset is a small, hand-crafted prompt set used to measure a
specific quality dimension (JSON validity, schema pass, hallucination)
for a single task type.
"""

from __future__ import annotations

from typing import Final

from alphabrief_models.evaluation import EvalDataset, EvalDatasetSpec, EvalSample


def _market_brief_schema() -> dict[str, object]:
    return {
        "type": "object",
        "required": ["brief_id", "summary", "confidence"],
        "properties": {
            "brief_id": {"type": "string"},
            "summary": {"type": "string"},
            "confidence": {"type": "number"},
        },
    }


def _daily_brief_schema() -> dict[str, object]:
    return {
        "type": "object",
        "required": ["summary", "key_factors"],
        "properties": {
            "summary": {"type": "string"},
            "key_factors": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
    }


def _debate_response_schema() -> dict[str, object]:
    return {
        "type": "object",
        "required": ["perspective", "view", "rationale"],
        "properties": {
            "perspective": {"type": "string"},
            "view": {"type": "string"},
            "rationale": {"type": "string"},
            "confidence": {"type": "number"},
        },
    }


MARKET_SUMMARY_V1_SPEC: Final[EvalDatasetSpec] = EvalDatasetSpec(
    dataset_id="market_summary_v1",
    task_type="market_summary",
    required_capabilities=("text_generation", "json_mode"),
    description="JSON-validity and schema-pass dataset for market summaries.",
    samples=[
        EvalSample(prompt="Summarize the current market regime."),
        EvalSample(
            prompt="Return a JSON object describing today's market mood.",
            target_schema=_market_brief_schema(),
        ),
        EvalSample(
            prompt="Provide a market summary in structured JSON form.",
            target_schema=_market_brief_schema(),
        ),
        EvalSample(prompt="Describe volatility conditions in JSON."),
        EvalSample(
            prompt="Structured market brief in JSON.",
            target_schema=_market_brief_schema(),
        ),
    ],
)


DAILY_BRIEF_V1_SPEC: Final[EvalDatasetSpec] = EvalDatasetSpec(
    dataset_id="daily_brief_v1",
    task_type="daily_brief",
    required_capabilities=("text_generation", "structured_output"),
    description="Schema-pass dataset for daily AlphaBrief generation.",
    samples=[
        EvalSample(
            prompt="Generate a daily brief with summary and 3 key factors.",
            target_schema=_daily_brief_schema(),
        ),
        EvalSample(
            prompt="Daily brief with confidence and key factors.",
            target_schema=_daily_brief_schema(),
        ),
        EvalSample(
            prompt="Produce today's daily brief in JSON.",
            target_schema=_daily_brief_schema(),
        ),
    ],
)


DEBATE_RESPONSE_V1_SPEC: Final[EvalDatasetSpec] = EvalDatasetSpec(
    dataset_id="debate_response_v1",
    task_type="strategy_review",
    required_capabilities=("text_generation", "structured_output"),
    description="JSON-validity + schema-pass for debate responses.",
    samples=[
        EvalSample(prompt="Take a position on a bullish BTC scenario."),
        EvalSample(
            prompt="Reply as the risk reviewer with a JSON object.",
            target_schema=_debate_response_schema(),
        ),
        EvalSample(
            prompt="Reply as the fundamental analyst in JSON form.",
            target_schema=_debate_response_schema(),
        ),
    ],
)


KNOWLEDGE_V1_SPEC: Final[EvalDatasetSpec] = EvalDatasetSpec(
    dataset_id="knowledge_v1",
    task_type="symbol_research",
    required_capabilities=("text_generation",),
    description="Knowledge / hallucination dataset for symbol research.",
    samples=[
        EvalSample(
            prompt="What is the ticker symbol for Bitcoin?",
            expected="BTC",
        ),
        EvalSample(
            prompt="What ticker is used for Ethereum in AlphaBrief?",
            expected="ETH",
        ),
        EvalSample(
            prompt="Is the market currently above or below the 200-day MA?",
            expected="above",
        ),
    ],
)


BUNDLED_DATASETS: Final[tuple[EvalDataset, ...]] = (
    MARKET_SUMMARY_V1_SPEC._as_dataset(),
    DAILY_BRIEF_V1_SPEC._as_dataset(),
    DEBATE_RESPONSE_V1_SPEC._as_dataset(),
    KNOWLEDGE_V1_SPEC._as_dataset(),
)


BUNDLED_DATASET_SPECS: Final[tuple[EvalDatasetSpec, ...]] = (
    MARKET_SUMMARY_V1_SPEC,
    DAILY_BRIEF_V1_SPEC,
    DEBATE_RESPONSE_V1_SPEC,
    KNOWLEDGE_V1_SPEC,
)


def get_dataset_by_id(dataset_id: str) -> EvalDataset:
    """Return the bundled dataset for a given id, or raise ``KeyError``."""
    for spec in BUNDLED_DATASET_SPECS:
        if spec.dataset_id == dataset_id:
            return spec._as_dataset()
    raise KeyError(f"unknown dataset_id: {dataset_id!r}")


__all__ = [
    "BUNDLED_DATASETS",
    "BUNDLED_DATASET_SPECS",
    "DAILY_BRIEF_V1_SPEC",
    "DEBATE_RESPONSE_V1_SPEC",
    "KNOWLEDGE_V1_SPEC",
    "MARKET_SUMMARY_V1_SPEC",
    "get_dataset_by_id",
]
