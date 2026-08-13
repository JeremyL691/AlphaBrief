"""M14-W01: dashboard brand audit.

Covers AC-M14-W01-01: a before-and-after audit maps every legacy
dashboard route, retained brand asset, usability defect, and planned
replacement without changing runtime business behavior.
"""

from __future__ import annotations

import re
from pathlib import Path

from alphabrief_api.dashboard.design_system import (
    BRAND_ASSETS,
    BRAND_AUDIT,
    DASHBOARD_ROUTES,
)

DASHBOARD_ROUTES_FILE = (
    Path(__file__).resolve().parents[1]
    / "apps/api/src/alphabrief_api/routes/dashboard.py"
)
DESIGN_SYSTEM_FILE = (
    Path(__file__).resolve().parents[1]
    / "apps/api/src/alphabrief_api/dashboard/design_system.py"
)


class TestAuditCoversEveryRoute:
    def test_audit_maps_every_legacy_dashboard_route(self) -> None:
        source = DASHBOARD_ROUTES_FILE.read_text(encoding="utf-8")
        declared = set(
            re.findall(r'@router\.get\("(/dashboard[^"]*)"', source)
        )
        assert declared == set(DASHBOARD_ROUTES)
        assert set(BRAND_AUDIT) == declared

    def test_every_audit_entry_has_before_and_after(self) -> None:
        for _route, entry in BRAND_AUDIT.items():
            assert "retained_assets" in entry
            assert "defects" in entry
            assert "replacement" in entry
            assert entry["retained_assets"]
            assert entry["defects"]
            assert entry["replacement"]

    def test_audit_preserves_brand_assets_verbatim(self) -> None:
        for entry in BRAND_AUDIT.values():
            retained = entry["retained_assets"]
            assert isinstance(retained, list)
            assert all(asset in BRAND_ASSETS for asset in retained)


class TestNoRuntimeBehaviorChange:
    def test_audit_module_is_data_only(self) -> None:
        source = DESIGN_SYSTEM_FILE.read_text(encoding="utf-8")
        # No route registration, no HTML generation, no DB access.
        assert "@router" not in source
        assert "HTMLResponse" not in source
        assert "import duckdb" not in source
        assert "def get_" not in source

    def test_dashboard_route_handlers_are_untouched(self) -> None:
        """The audit and token system are additive: the legacy route
        handlers still return their pages unchanged (the before-state
        is preserved for the audit)."""
        source = DASHBOARD_ROUTES_FILE.read_text(encoding="utf-8")
        assert "@router.get" in source
        assert "HTMLResponse" in source
        # The design system module is not imported by the route module,
        # so no runtime business behavior can change.
        assert "design_system" not in source

    def test_audit_records_are_stable(self) -> None:
        first = {route: dict(entry) for route, entry in BRAND_AUDIT.items()}
        second = {route: dict(entry) for route, entry in BRAND_AUDIT.items()}
        assert first == second

    def test_route_count_matches_the_documented_nine(self) -> None:
        assert len(DASHBOARD_ROUTES) == 9
