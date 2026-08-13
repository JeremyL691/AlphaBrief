"""M14-W06: Settings workspace.

Covers AC-M14-W06-03: Settings reveals non-secret provider and version
health but cannot edit broker hosts, unlock live trading, select
another broker, expose credentials, or send an arbitrary broker
request.
"""

from __future__ import annotations

from alphabrief_api.dashboard.operations import build_settings_view


def _health() -> dict[str, object]:
    return {
        "provider": "oanda-practice",
        "provider_health": "healthy",
        "blueprint_version": "2026-08-13.1",
        "schema_version": "read-v1",
    }


class TestSettingsView:
    def test_reveals_non_secret_health(self) -> None:
        view = build_settings_view(_health())
        assert view.provider == "oanda-practice"
        assert view.provider_health == "healthy"
        assert view.blueprint_version == "2026-08-13.1"
        assert view.schema_version == "read-v1"

    def test_cannot_edit_broker_hosts(self) -> None:
        assert build_settings_view(_health()).editable_broker_hosts is False

    def test_cannot_unlock_live_trading(self) -> None:
        assert build_settings_view(_health()).live_unlock_available is False

    def test_cannot_select_another_broker(self) -> None:
        assert build_settings_view(_health()).broker_selection_available is False

    def test_never_exposes_credentials(self) -> None:
        assert build_settings_view(_health()).credentials_exposed is False

    def test_never_sends_arbitrary_broker_requests(self) -> None:
        assert build_settings_view(_health()).arbitrary_broker_request is False

    def test_missing_health_is_explicit_null(self) -> None:
        view = build_settings_view(None)
        assert view.provider is None
        assert view.blueprint_version is None

    def test_deterministic(self) -> None:
        first = build_settings_view(_health())
        second = build_settings_view(_health())
        assert first.model_dump() == second.model_dump()
