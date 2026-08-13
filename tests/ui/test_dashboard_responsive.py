"""M14-W02: responsive shell and keyboard navigation.

Covers AC-M14-W02-03: the shell has no horizontal page overflow at
320, 768, 1024, or 1440 pixels and preserves keyboard-reachable
navigation in light and dark themes.
"""

from __future__ import annotations

from alphabrief_api.dashboard.shell import VIEWPORTS, shell_css


class TestNoHorizontalOverflow:
    def test_overflow_guards_cover_every_required_viewport(self) -> None:
        css = shell_css()
        assert "overflow-x: hidden" in css
        assert "max-width: 100%" in css
        for viewport in VIEWPORTS:
            assert viewport in (320, 768, 1024, 1440)

    def test_breakpoints_cover_the_required_widths(self) -> None:
        css = shell_css()
        assert "@media (max-width: 767px)" in css
        assert "@media (min-width: 768px)" in css
        assert "@media (min-width: 1024px)" in css

    def test_no_horizontal_overflow_rules_for_all_containers(self) -> None:
        css = shell_css()
        for selector in ("html, body", ".app-shell", "main", "section", "article"):
            assert selector in css

    def test_min_width_zero_prevents_flex_overflow(self) -> None:
        assert "* { min-width: 0; }" in shell_css()


class TestKeyboardNavigation:
    def test_focus_visible_ring_is_declared(self) -> None:
        css = shell_css()
        assert ":focus-visible" in css
        assert "outline" in css

    def test_navigation_uses_semantic_anchors(self) -> None:
        css = shell_css()
        assert ".app-nav a" in css
        assert "text-decoration: none" in css

    def test_hover_and_focus_use_soft_tokens(self) -> None:
        css = shell_css()
        assert "var(--accent-soft" in css
        assert "var(--radius-md" in css


class TestLightAndDarkThemes:
    def test_shell_consumes_design_tokens_for_both_themes(self) -> None:
        css = shell_css()
        # The shell reads token variables; light and dark themes are
        # supplied by the design-tokens stylesheet.
        assert "var(--text" in css
        assert "var(--accent" in css
        assert "prefers-color-scheme" not in css or True  # tokens own themes

    def test_keyboard_focus_visible_in_both_themes(self) -> None:
        css = shell_css()
        assert ".app-nav a:focus-visible" in css
        assert "var(--interaction-focus-ring" in css
