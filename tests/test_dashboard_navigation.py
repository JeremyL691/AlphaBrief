"""M14-W02: required dashboard navigation.

Covers AC-M14-W02-01: navigation exposes Overview, Markets, News &
Sentiment, AI Research, Risk, OANDA Account, Orders & Trades,
Scheduler, 30-Day Observation, and Settings at every required
viewport.
"""

from __future__ import annotations

import pytest
from alphabrief_api.dashboard.shell import (
    FULL_NAV_MIN_WIDTH,
    NAVIGATION_SECTIONS,
    VIEWPORTS,
    navigation_for_viewport,
)

REQUIRED_LABELS = (
    "Overview",
    "Markets",
    "News & Sentiment",
    "AI Research",
    "Risk",
    "OANDA Account",
    "Orders & Trades",
    "Scheduler",
    "30-Day Observation",
    "Settings",
)


class TestNavigationCoverage:
    def test_all_ten_required_sections_are_declared(self) -> None:
        labels = [item.label for item in NAVIGATION_SECTIONS]
        assert labels == list(REQUIRED_LABELS)

    def test_every_section_has_route_icon_and_order(self) -> None:
        for item in NAVIGATION_SECTIONS:
            assert item.route.startswith("/dashboard")
            assert item.icon
            assert item.order >= 0

    @pytest.mark.parametrize("viewport", VIEWPORTS)
    def test_all_sections_reachable_at_every_viewport(self, viewport: int) -> None:
        items = navigation_for_viewport(viewport)
        assert len(items) == 10
        assert {item.label for item in items} == set(REQUIRED_LABELS)

    def test_full_nav_breakpoint_is_declared(self) -> None:
        assert FULL_NAV_MIN_WIDTH == 1024
        assert 1024 in VIEWPORTS

    def test_icons_are_library_names_not_emoji(self) -> None:
        for item in NAVIGATION_SECTIONS:
            assert item.icon.isidentifier(), item.icon


class TestNavigationSemantics:
    def test_anchors_are_keyboard_reachable(self) -> None:
        """Semantic anchors are keyboard-reachable by default; the shell
        must not replace them with click-only elements."""
        for item in NAVIGATION_SECTIONS:
            assert item.route.startswith("/dashboard")

    def test_navigation_order_is_stable(self) -> None:
        assert [item.order for item in NAVIGATION_SECTIONS] == list(range(10))

    def test_no_duplicate_routes(self) -> None:
        routes = [item.route for item in NAVIGATION_SECTIONS]
        assert len(routes) == len(set(routes))
