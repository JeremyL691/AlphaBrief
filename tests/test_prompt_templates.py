import pytest
from alphabrief_models import (
    ModelRequest,
    PromptTemplate,
    PromptTemplateError,
    PromptTemplateRegistry,
)
from pydantic import ValidationError


def _template(**overrides: object) -> PromptTemplate:
    payload: dict[str, object] = {
        "template_id": "daily_alpha_brief",
        "version": "v1",
        "task_type": "daily_brief",
        "body": "Write a daily brief for {{ trading_day }} using {{ market_note }}.",
        "required_variables": ["trading_day", "market_note"],
    }
    payload.update(overrides)
    return PromptTemplate.model_validate(payload)


def test_prompt_template_renders_versioned_prompt() -> None:
    template = _template()

    rendered = template.render(
        {
            "trading_day": "2026-06-14",
            "market_note": "Risk assets are mixed.",
        }
    )

    assert rendered.template_id == "daily_alpha_brief"
    assert rendered.version == "v1"
    assert rendered.prompt_version == "daily_alpha_brief:v1"
    assert rendered.task_type == "daily_brief"
    assert "2026-06-14" in rendered.input_text
    assert "{{" not in rendered.input_text


def test_rendered_prompt_can_build_model_request() -> None:
    rendered = _template().render(
        {
            "trading_day": "2026-06-14",
            "market_note": "Risk assets are mixed.",
        }
    )

    request = ModelRequest(
        request_id="request_1",
        task_type=rendered.task_type,
        prompt_version=rendered.prompt_version,
        input_text=rendered.input_text,
        required_capabilities=["structured_output"],
    )

    assert request.task_type == "daily_brief"
    assert request.prompt_version == "daily_alpha_brief:v1"


def test_prompt_template_rejects_blank_strings() -> None:
    with pytest.raises(ValidationError, match="blank"):
        _template(template_id=" ")

    with pytest.raises(ValidationError, match="blank"):
        _template(body=" ")


def test_prompt_template_rejects_duplicate_variables() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        _template(required_variables=["trading_day", "trading_day"])


def test_prompt_template_rejects_invalid_variable_names() -> None:
    with pytest.raises(ValidationError, match="valid identifiers"):
        _template(required_variables=["trading-day"])


def test_prompt_template_requires_body_placeholders() -> None:
    with pytest.raises(ValidationError, match="missing required variables"):
        _template(body="Write a brief for {{ trading_day }}.")


def test_prompt_template_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PromptTemplate.model_validate(
            {
                "template_id": "daily_alpha_brief",
                "version": "v1",
                "task_type": "daily_brief",
                "body": "Write {{ market_note }}.",
                "required_variables": ["market_note"],
                "unexpected": "nope",
            }
        )


def test_prompt_template_rejects_missing_render_variables() -> None:
    with pytest.raises(PromptTemplateError, match="missing"):
        _template().render({"trading_day": "2026-06-14"})


def test_prompt_template_rejects_extra_render_variables() -> None:
    with pytest.raises(PromptTemplateError, match="unexpected"):
        _template().render(
            {
                "trading_day": "2026-06-14",
                "market_note": "Risk assets are mixed.",
                "extra": "not allowed",
            }
        )


def test_prompt_template_rejects_blank_render_variables() -> None:
    with pytest.raises(PromptTemplateError, match="blank"):
        _template().render({"trading_day": " ", "market_note": "note"})


def test_prompt_template_registry_returns_specific_version() -> None:
    v1 = _template(version="v1", body="Brief {{ trading_day }} {{ market_note }}")
    v2 = _template(version="v2", body="Detailed {{ trading_day }} {{ market_note }}")
    registry = PromptTemplateRegistry([v1, v2])

    rendered = registry.render(
        "daily_alpha_brief",
        "v2",
        {"trading_day": "2026-06-14", "market_note": "mixed"},
    )

    assert rendered.prompt_version == "daily_alpha_brief:v2"
    assert rendered.input_text.startswith("Detailed")


def test_prompt_template_registry_rejects_duplicate_versions() -> None:
    with pytest.raises(PromptTemplateError, match="duplicate"):
        PromptTemplateRegistry([_template(), _template()])


def test_prompt_template_registry_rejects_unknown_version() -> None:
    registry = PromptTemplateRegistry([_template()])

    with pytest.raises(PromptTemplateError, match="unknown"):
        registry.get("daily_alpha_brief", "v2")


def test_phase11_templates_define_v2_versions() -> None:
    from alphabrief_models import PHASE11_PROMPT_TEMPLATES

    template_ids = {(t.template_id, t.version) for t in PHASE11_PROMPT_TEMPLATES}
    assert ("daily_alpha_brief", "v2") in template_ids
    assert ("market_brief", "v2") in template_ids
    assert ("symbol_brief", "v2") in template_ids
    assert ("debate_context", "v1") in template_ids


def test_default_registry_renders_daily_brief_v2() -> None:
    from alphabrief_models import build_default_prompt_registry

    registry = build_default_prompt_registry()
    rendered = registry.render(
        "daily_alpha_brief",
        "v2",
        {
            "trading_day": "2026-06-14",
            "market_data_context": "SPY up 0.4%",
            "news_context": "Tech earnings beat",
            "macro_context": "CPI 3.1%",
            "sentiment_summary": "Positive on tech",
        },
    )

    assert rendered.prompt_version == "daily_alpha_brief:v2"
    assert "2026-06-14" in rendered.input_text
    assert "Tech earnings beat" in rendered.input_text
    assert "CPI 3.1%" in rendered.input_text
    assert "{{" not in rendered.input_text


def test_default_registry_renders_symbol_brief_v2() -> None:
    from alphabrief_models import build_default_prompt_registry

    registry = build_default_prompt_registry()
    rendered = registry.render(
        "symbol_brief",
        "v2",
        {
            "symbol": "NVDA",
            "horizon": "1w",
            "market_data_context": "NVDA up 2%",
            "news_context": "Strong data center demand",
            "macro_context": "Rate cut expectations",
        },
    )

    assert rendered.prompt_version == "symbol_brief:v2"
    assert "NVDA" in rendered.input_text
    assert "1w" in rendered.input_text


def test_default_registry_renders_market_brief_v2() -> None:
    from alphabrief_models import build_default_prompt_registry

    registry = build_default_prompt_registry()
    rendered = registry.render(
        "market_brief",
        "v2",
        {
            "trading_day": "2026-06-14",
            "market_data_context": "SPY flat",
            "news_context": "Mixed earnings",
            "macro_context": "Fed pause",
        },
    )

    assert rendered.prompt_version == "market_brief:v2"
    assert "Fed pause" in rendered.input_text


def test_default_registry_renders_debate_context_v1() -> None:
    from alphabrief_models import build_default_prompt_registry

    registry = build_default_prompt_registry()
    rendered = registry.render(
        "debate_context",
        "v1",
        {
            "question": "How will AAPL trade next week?",
            "symbol": "AAPL",
            "time_horizon": "5 trading days",
            "context": "Earnings season",
            "news_context": "iPhone sales strong",
            "macro_context": "Rates stable",
            "perspective": "technical",
        },
    )

    assert rendered.prompt_version == "debate_context:v1"
    assert "AAPL" in rendered.input_text
    assert "iPhone sales strong" in rendered.input_text
    assert "technical" in rendered.input_text


def test_render_brief_prompt_v2_helper() -> None:
    from alphabrief_models import render_brief_prompt_v2

    rendered = render_brief_prompt_v2(
        "daily_alpha_brief",
        "v2",
        {
            "trading_day": "2026-06-14",
            "market_data_context": "data",
            "news_context": "news",
            "macro_context": "macro",
            "sentiment_summary": "sentiment",
        },
    )

    assert rendered.prompt_version == "daily_alpha_brief:v2"


def test_render_brief_prompt_v2_rejects_missing_variables() -> None:
    from alphabrief_models import render_brief_prompt_v2

    with pytest.raises(PromptTemplateError, match="missing"):
        render_brief_prompt_v2(
            "daily_alpha_brief",
            "v2",
            {
                "trading_day": "2026-06-14",
                "market_data_context": "data",
                "news_context": "news",
                "macro_context": "macro",
            },
        )


def test_v2_templates_reject_blank_variables() -> None:
    from alphabrief_models import build_default_prompt_registry

    registry = build_default_prompt_registry()
    with pytest.raises(PromptTemplateError, match="blank"):
        registry.render(
            "daily_alpha_brief",
            "v2",
            {
                "trading_day": " ",
                "market_data_context": "data",
                "news_context": "news",
                "macro_context": "macro",
                "sentiment_summary": "sentiment",
            },
        )
