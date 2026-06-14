"""Versioned prompt templates for AlphaBrief model requests."""

import re
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphabrief_models.gateway import ModelTaskType

_VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class PromptTemplateError(ValueError):
    """Raised when a prompt template cannot be rendered or registered."""


class PromptTemplate(BaseModel):
    """A versioned prompt template with explicit string variables."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    task_type: ModelTaskType
    body: str = Field(min_length=1)
    required_variables: list[str]

    @field_validator("template_id", "version", "body")
    @classmethod
    def _strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value

    @field_validator("required_variables")
    @classmethod
    def _variables_must_be_unique_and_non_blank(
        cls,
        value: list[str],
    ) -> list[str]:
        if any(variable.strip() == "" for variable in value):
            raise ValueError("required_variables must not contain blank entries")
        if len(value) != len(list(dict.fromkeys(value))):
            raise ValueError("required_variables must not contain duplicates")
        for variable in value:
            if _VARIABLE_PATTERN.fullmatch(f"{{{{ {variable} }}}}") is None:
                raise ValueError("required_variables must be valid identifiers")
        return value

    @model_validator(mode="after")
    def _body_must_contain_required_variables(self) -> "PromptTemplate":
        body_variables = set(_VARIABLE_PATTERN.findall(self.body))
        missing = [
            variable
            for variable in self.required_variables
            if variable not in body_variables
        ]
        if missing:
            missing_variables = ", ".join(missing)
            raise ValueError(
                f"body is missing required variables: {missing_variables}"
            )
        return self

    @property
    def prompt_version(self) -> str:
        """Stable prompt version value for ModelRequest."""

        return f"{self.template_id}:{self.version}"

    def render(self, variables: Mapping[str, str]) -> "RenderedPrompt":
        """Render the template with explicit string variables."""

        _validate_render_variables(self.required_variables, variables)

        def replace(match: re.Match[str]) -> str:
            variable = match.group(1)
            if variable not in variables:
                return match.group(0)
            return variables[variable]

        return RenderedPrompt(
            template_id=self.template_id,
            version=self.version,
            prompt_version=self.prompt_version,
            task_type=self.task_type,
            input_text=_VARIABLE_PATTERN.sub(replace, self.body),
        )


class RenderedPrompt(BaseModel):
    """Rendered prompt text ready to be passed to ModelRequest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    task_type: ModelTaskType
    input_text: str = Field(min_length=1)


class PromptTemplateRegistry:
    """In-memory registry for versioned prompt templates."""

    def __init__(self, templates: Sequence[PromptTemplate]) -> None:
        self._templates: dict[tuple[str, str], PromptTemplate] = {}
        for template in templates:
            key = (template.template_id, template.version)
            if key in self._templates:
                raise PromptTemplateError(
                    f"duplicate prompt template version: {template.prompt_version}"
                )
            self._templates[key] = template

    def get(self, template_id: str, version: str) -> PromptTemplate:
        """Return a specific prompt template version."""

        key = (template_id, version)
        try:
            return self._templates[key]
        except KeyError as exc:
            raise PromptTemplateError(
                f"unknown prompt template version: {template_id}:{version}"
            ) from exc

    def render(
        self,
        template_id: str,
        version: str,
        variables: Mapping[str, str],
    ) -> RenderedPrompt:
        """Render a registered template version."""

        return self.get(template_id, version).render(variables)


def _validate_render_variables(
    required_variables: Sequence[str],
    variables: Mapping[str, str],
) -> None:
    missing = [variable for variable in required_variables if variable not in variables]
    if missing:
        missing_variables = ", ".join(missing)
        raise PromptTemplateError(f"missing prompt variables: {missing_variables}")

    extra = [variable for variable in variables if variable not in required_variables]
    if extra:
        extra_variables = ", ".join(extra)
        raise PromptTemplateError(f"unexpected prompt variables: {extra_variables}")

    blank = [variable for variable, value in variables.items() if value.strip() == ""]
    if blank:
        blank_variables = ", ".join(blank)
        raise PromptTemplateError(f"blank prompt variables: {blank_variables}")
