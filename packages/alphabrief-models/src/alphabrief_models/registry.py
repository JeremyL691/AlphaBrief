"""Model provider and profile registry for AlphaBrief.

The registry stores provider/model metadata only. It does not read environment
variables, hold secret values, instantiate provider SDK clients, or make model
calls.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphabrief_models.gateway import ModelCapability


def _validate_env_var_name(value: str | None) -> str | None:
    if value is None:
        return value
    if value.strip() == "":
        raise ValueError("env var names must not be blank")
    first_char = value[0]
    valid_start = first_char == "_" or first_char.isalpha()
    valid_chars = all(char == "_" or char.isdigit() or char.isalpha() for char in value)
    if not valid_start or not valid_chars or value.upper() != value:
        raise ValueError("config stores env var names only, not secret values")
    return value


class RegistrySchema(BaseModel):
    """Shared strict schema configuration for registry objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderConfig(RegistrySchema):
    provider_name: str = Field(min_length=1)
    enabled: bool = True
    api_key_env_var: str | None = None
    base_url_env_var: str | None = None

    @field_validator("provider_name")
    @classmethod
    def provider_name_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("provider_name must not be blank")
        return value

    @field_validator("api_key_env_var", "base_url_env_var")
    @classmethod
    def env_var_names_must_not_contain_secret_values(
        cls, value: str | None
    ) -> str | None:
        return _validate_env_var_name(value)


class ModelProfile(RegistrySchema):
    profile_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    capabilities: list[ModelCapability] = Field(min_length=1)
    enabled: bool = True
    priority: int = Field(default=100, ge=0)

    @field_validator("profile_id", "provider_name", "model_name")
    @classmethod
    def strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value

    @field_validator("capabilities")
    @classmethod
    def capabilities_must_be_unique(
        cls, value: list[ModelCapability]
    ) -> list[ModelCapability]:
        deduplicated = list(dict.fromkeys(value))
        if len(deduplicated) != len(value):
            raise ValueError("capabilities must not contain duplicates")
        return value


class ModelRegistry(RegistrySchema):
    providers: list[ProviderConfig]
    profiles: list[ModelProfile]

    @model_validator(mode="after")
    def validate_registry(self) -> "ModelRegistry":
        provider_names = [provider.provider_name for provider in self.providers]
        if len(set(provider_names)) != len(provider_names):
            raise ValueError("provider names must be unique")

        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("profile ids must be unique")

        missing_providers = [
            profile.provider_name
            for profile in self.profiles
            if profile.provider_name not in provider_names
        ]
        if missing_providers:
            raise ValueError("model profiles must reference configured providers")

        return self

    def matching_profiles(
        self, required_capabilities: Sequence[ModelCapability]
    ) -> list[ModelProfile]:
        required = frozenset(required_capabilities)
        enabled_providers = {
            provider.provider_name for provider in self.providers if provider.enabled
        }
        matches = [
            profile
            for profile in self.profiles
            if profile.enabled
            and profile.provider_name in enabled_providers
            and required.issubset(profile.capabilities)
        ]
        return sorted(
            matches, key=lambda profile: (profile.priority, profile.profile_id)
        )

    def select_profile(
        self, required_capabilities: Sequence[ModelCapability]
    ) -> ModelProfile | None:
        matches = self.matching_profiles(required_capabilities)
        if not matches:
            return None
        return matches[0]
