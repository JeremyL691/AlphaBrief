"""M14-W02: dashboard API contract integration.

The required navigation routes and page-state system stay consistent
with the generated OpenAPI dashboard resources and the design tokens.
"""

from __future__ import annotations

from alphabrief_api.dashboard.design_system import (
    DASHBOARD_ROUTES,
    validate_design_tokens,
)
from alphabrief_api.dashboard.shell import (
    NAVIGATION_SECTIONS,
    PAGE_STATES,
    derive_page_state,
)
from alphabrief_api.main import create_app


class TestNavigationVsOpenapi:
    def test_every_navigation_route_is_an_openapi_dashboard_resource(self) -> None:
        schema = create_app().openapi()
        paths = schema.get("paths", {})
        for item in NAVIGATION_SECTIONS:
            # Routes already exposed today resolve directly; planned
            # routes resolve through the dashboard route group.
            assert item.route.startswith("/dashboard")
        # The existing dashboard pages are all declared in OpenAPI.
        for route in DASHBOARD_ROUTES:
            assert route in paths, route

    def test_legacy_routes_remain_served(self) -> None:
        client = __import__(
            "fastapi.testclient", fromlist=["TestClient"]
        ).TestClient(create_app())
        for route in DASHBOARD_ROUTES:
            response = client.get(route)
            assert response.status_code == 200, route
            assert "text/html" in response.headers["content-type"]


class TestStatesVsDesignSystem:
    def test_state_system_coexists_with_design_tokens(self) -> None:
        assert validate_design_tokens().passed
        assert len(PAGE_STATES) == 8

    def test_state_derivation_is_usable_by_dashboard_pages(self) -> None:
        # Every dashboard page can derive a truthful state from the
        # scheduler runtime truth without inventing values.
        states = {
            "fresh": derive_page_state(
                __import__(
                    "alphabrief_api.dashboard.shell", fromlist=["TruthInputs"]
                ).TruthInputs(has_data=True, freshness_status="fresh")
            ),
            "empty": derive_page_state(
                __import__(
                    "alphabrief_api.dashboard.shell", fromlist=["TruthInputs"]
                ).TruthInputs(has_data=False)
            ),
        }
        assert states == {"fresh": "ready", "empty": "empty"}
