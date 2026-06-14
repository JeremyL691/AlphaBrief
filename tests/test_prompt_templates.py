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
