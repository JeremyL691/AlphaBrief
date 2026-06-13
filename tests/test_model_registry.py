import pytest
from alphabrief_models import ModelProfile, ModelRegistry, ProviderConfig
from pydantic import ValidationError


def provider_config(
    *, provider_name: str = "fake", enabled: bool = True
) -> ProviderConfig:
    return ProviderConfig(provider_name=provider_name, enabled=enabled)


def model_profile(
    *,
    profile_id: str = "fake_fast",
    provider_name: str = "fake",
    enabled: bool = True,
    priority: int = 100,
) -> ModelProfile:
    return ModelProfile(
        profile_id=profile_id,
        provider_name=provider_name,
        model_name="fake-model",
        capabilities=["text_generation", "low_cost"],
        enabled=enabled,
        priority=priority,
    )


def test_provider_config_rejects_blank_provider_name() -> None:
    with pytest.raises(ValidationError, match="provider_name"):
        ProviderConfig(provider_name=" ")


def test_provider_config_stores_env_var_names_not_secret_values() -> None:
    config = ProviderConfig(
        provider_name="openai_compatible",
        api_key_env_var="OPENAI_API_KEY",
        base_url_env_var="OPENAI_BASE_URL",
    )

    assert config.api_key_env_var == "OPENAI_API_KEY"
    assert config.base_url_env_var == "OPENAI_BASE_URL"

    with pytest.raises(ValidationError, match="secret values"):
        ProviderConfig(provider_name="bad", api_key_env_var="raw-value-with-dashes")


def test_model_profile_rejects_duplicate_capabilities() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        ModelProfile(
            profile_id="fake_fast",
            provider_name="fake",
            model_name="fake-model",
            capabilities=["text_generation", "text_generation"],
        )


def test_registry_selects_matching_profile_by_capability() -> None:
    registry = ModelRegistry(
        providers=[provider_config()],
        profiles=[model_profile()],
    )

    selected = registry.select_profile(["low_cost"])

    assert selected is not None
    assert selected.profile_id == "fake_fast"


def test_registry_excludes_disabled_provider_profiles() -> None:
    registry = ModelRegistry(
        providers=[provider_config(enabled=False)],
        profiles=[model_profile()],
    )

    assert registry.select_profile(["text_generation"]) is None


def test_registry_excludes_disabled_model_profiles() -> None:
    registry = ModelRegistry(
        providers=[provider_config()],
        profiles=[model_profile(enabled=False)],
    )

    assert registry.select_profile(["text_generation"]) is None


def test_registry_uses_lowest_priority_then_profile_id() -> None:
    registry = ModelRegistry(
        providers=[provider_config()],
        profiles=[
            model_profile(profile_id="second", priority=20),
            model_profile(profile_id="first", priority=10),
        ],
    )

    selected = registry.select_profile(["text_generation"])

    assert selected is not None
    assert selected.profile_id == "first"


def test_registry_returns_none_when_no_profile_matches() -> None:
    registry = ModelRegistry(
        providers=[provider_config()],
        profiles=[model_profile()],
    )

    assert registry.select_profile(["strong_reasoning"]) is None


def test_registry_rejects_duplicate_or_missing_references() -> None:
    with pytest.raises(ValidationError, match="provider names"):
        ModelRegistry(
            providers=[provider_config(), provider_config()],
            profiles=[],
        )

    with pytest.raises(ValidationError, match="configured providers"):
        ModelRegistry(
            providers=[provider_config(provider_name="fake")],
            profiles=[model_profile(provider_name="missing")],
        )


def test_registry_schemas_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProviderConfig.model_validate(
            {"provider_name": "fake", "unexpected": True}
        )
