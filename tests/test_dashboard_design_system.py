"""M14-W01: Soft 5/5/5 design token system.

Covers AC-M14-W01-02/03: one documented Soft 5/5/5 token system
controls color, typography, spacing, radius, elevation, interaction,
motion, light theme, dark theme, and reduced-motion behavior; shared
styles contain no emoji icons, fake content, low-contrast body text,
gradient buttons, or unapproved animation dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

from alphabrief_api.dashboard.design_system import (
    BRAND_ASSETS,
    DESIGN_TOKENS,
    FORBIDDEN_UI_COPY_CHARACTERS,
    THEMES,
    contrast_ratio,
    validate_design_tokens,
)

CSS_PATH = (
    Path(__file__).resolve().parents[1]
    / "apps/api/src/alphabrief_api/static/design-tokens.css"
)


class TestTokenCoverage:
    def test_all_required_categories_are_controlled(self) -> None:
        required = {
            "color_light",
            "color_dark",
            "typography",
            "spacing",
            "radius",
            "elevation",
            "interaction",
            "motion",
        }
        assert required <= set(DESIGN_TOKENS)

    def test_light_and_dark_themes_are_declared(self) -> None:
        assert THEMES == {"light": "color_light", "dark": "color_dark"}
        for theme in THEMES:
            assert set(DESIGN_TOKENS[THEMES[theme]]) == set(
                DESIGN_TOKENS["color_light"]
            )

    def test_reduced_motion_behavior_is_declared(self) -> None:
        assert "reduce_motion" in DESIGN_TOKENS["motion"]
        assert "prefers-reduced-motion" in DESIGN_TOKENS["motion"][
            "reduce_motion"
        ]

    def test_motion_uses_css_only_no_animation_library(self) -> None:
        motion_text = " ".join(DESIGN_TOKENS["motion"].values())
        for library in ("framer", "gsap", "anime", "velocity", "lottie"):
            assert library not in motion_text

    def test_css_file_declares_the_same_tokens(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        for category, values in DESIGN_TOKENS.items():
            for key, value in values.items():
                if key == "reduce_motion":
                    continue
                assert str(value) in css, f"{category}.{key} missing from CSS"


class TestContrast:
    def test_light_theme_body_text_passes_wcag_aa(self) -> None:
        ratio = contrast_ratio(
            DESIGN_TOKENS["color_light"]["text"],
            DESIGN_TOKENS["color_light"]["bg"],
        )
        assert ratio >= 4.5

    def test_light_theme_dim_text_passes_wcag_aa(self) -> None:
        ratio = contrast_ratio(
            DESIGN_TOKENS["color_light"]["text_dim"],
            DESIGN_TOKENS["color_light"]["bg"],
        )
        assert ratio >= 4.5

    def test_dark_theme_body_text_passes_wcag_aa(self) -> None:
        ratio = contrast_ratio(
            DESIGN_TOKENS["color_dark"]["text"],
            DESIGN_TOKENS["color_dark"]["bg"],
        )
        assert ratio >= 4.5

    def test_contrast_ratio_is_deterministic(self) -> None:
        first = contrast_ratio("#3d3a34", "#faf7f2")
        second = contrast_ratio("#3d3a34", "#faf7f2")
        assert first == second
        assert first > 1.0


class TestForbiddenPatterns:
    def test_no_gradient_buttons(self) -> None:
        for category, values in DESIGN_TOKENS.items():
            for key, value in values.items():
                assert "linear-gradient" not in value, (
                    f"{category}.{key} uses a gradient"
                )

    def test_no_animation_dependency_in_shared_styles(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        assert "@keyframes" not in css
        # The only animation declaration is the reduced-motion disable.
        reduced_motion_disable = "animation: none !important;"
        assert reduced_motion_disable in css
        remaining = css.replace(reduced_motion_disable, "")
        assert "animation:" not in remaining

    def test_no_emoji_in_ui_copy(self) -> None:
        text = " ".join(
            value
            for values in DESIGN_TOKENS.values()
            for value in values.values()
        )
        for character in FORBIDDEN_UI_COPY_CHARACTERS:
            assert character not in text

    def test_no_em_dash_in_ui_copy(self) -> None:
        # The em dash is forbidden in UI copy; token values are plain.
        for values in DESIGN_TOKENS.values():
            for value in values.values():
                assert "\u2014" not in value

    def test_validation_passes(self) -> None:
        verdict = validate_design_tokens()
        assert verdict.passed, verdict.issues

    def test_brand_assets_are_preserved(self) -> None:
        assert "alphabrief-wordmark" in BRAND_ASSETS
        assert "oanda-practice-badge" in BRAND_ASSETS
        assert "paper-only-badge" in BRAND_ASSETS


class TestCssFile:
    def test_css_has_light_and_dark_theme_blocks(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        assert "prefers-color-scheme: dark" in css
        assert ":root {" in css

    def test_css_has_reduced_motion_block(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        assert "prefers-reduced-motion: reduce" in css
        assert "transition: none" in css

    def test_css_contains_no_emoji_or_placeholder_content(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        assert not re.search(r"[\U0001F300-\U0001FAFF]", css)
        for placeholder in ("lorem", "ipsum", "TODO", "FIXME"):
            assert placeholder not in css.lower()
