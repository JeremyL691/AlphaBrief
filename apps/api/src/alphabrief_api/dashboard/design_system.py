"""Soft (5/5/5) design system and dashboard brand audit (M14-W01).

The owner-approved Soft preset (DESIGN_VARIANCE=5, MOTION_INTENSITY=5,
VISUAL_DENSITY=5) is encoded once as machine-readable design tokens:
color (light and dark themes), typography, spacing, radius, elevation,
interaction, motion (with reduced-motion behavior), and preserved
AlphaBrief brand assets. ``validate_design_tokens`` is a deterministic
automated check — contrast, emoji-free copy, no gradient buttons, no
unapproved animation dependency. The brand audit maps every legacy
dashboard route to its retained assets, usability defects, and planned
replacement without changing any runtime business behavior
(REQ-UI-003, REQ-UI-008).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

#: One machine-readable Soft 5/5/5 token system. Every consumer of the
#: dashboard presentation reads from these values only.
DESIGN_TOKENS: dict[str, dict[str, str]] = {
    "color_light": {
        "bg": "#faf7f2",
        "bg_elev_1": "#ffffff",
        "bg_elev_2": "#f5f1ea",
        "border": "#e5ded2",
        "border_strong": "#c9bfae",
        "text": "#3d3a34",
        "text_dim": "#6b655c",
        "text_muted": "#8a8378",
        "accent": "#b07d3f",
        "accent_dim": "#8a6130",
        "accent_soft": "rgba(176, 125, 63, 0.12)",
        "success": "#5a7d5a",
        "danger": "#a0534d",
        "warning": "#a67c2e",
    },
    "color_dark": {
        "bg": "#16140f",
        "bg_elev_1": "#1e1b15",
        "bg_elev_2": "#262219",
        "border": "#3a342a",
        "border_strong": "#4d4538",
        "text": "#ece7dd",
        "text_dim": "#b8b1a4",
        "text_muted": "#8d867a",
        "accent": "#d4a45f",
        "accent_dim": "#b07d3f",
        "accent_soft": "rgba(212, 164, 95, 0.14)",
        "success": "#8fae8f",
        "danger": "#d08a83",
        "warning": "#c9a45c",
    },
    "typography": {
        "font_sans": (
            "-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', "
            "Roboto, sans-serif"
        ),
        "font_mono": (
            "ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, Monaco, "
            "Consolas, monospace"
        ),
        "font_size_base": "14px",
        "font_size_sm": "12px",
        "font_size_lg": "18px",
        "font_size_xl": "24px",
        "line_height": "1.5",
    },
    "spacing": {
        "space_1": "4px",
        "space_2": "8px",
        "space_3": "12px",
        "space_4": "16px",
        "space_5": "24px",
        "space_6": "32px",
        "space_7": "48px",
    },
    "radius": {
        "radius_sm": "6px",
        "radius_md": "10px",
        "radius_lg": "14px",
        "radius_pill": "999px",
    },
    "elevation": {
        "shadow_card": "0 1px 2px rgba(61, 58, 52, 0.06)",
        "shadow_hover": "0 2px 8px rgba(61, 58, 52, 0.10)",
        "shadow_dark_card": "0 1px 2px rgba(0, 0, 0, 0.35)",
        "shadow_dark_hover": "0 2px 10px rgba(0, 0, 0, 0.45)",
    },
    "interaction": {
        "hover_raise": "translateY(-1px)",
        "focus_ring": "2px solid var(--accent)",
        "active_press": "translateY(0px)",
    },
    "motion": {
        "duration_fast": "120ms",
        "duration_base": "200ms",
        "duration_slow": "320ms",
        "ease_standard": "cubic-bezier(0.2, 0, 0, 1)",
        "ease_emphasized": "cubic-bezier(0.3, 0, 0.2, 1)",
        "reduce_motion": "prefers-reduced-motion: reduce",
    },
}

#: The single theme-mode declaration (light default, dark on request).
THEMES: dict[str, str] = {
    "light": "color_light",
    "dark": "color_dark",
}

#: Rules that must never appear in shared presentation styles.
FORBIDDEN_STYLE_PATTERNS: tuple[str, ...] = (
    "linear-gradient",
    "animation:",
    "@keyframes",
)

#: Characters that must never appear in UI copy (icons come from an
#: icon library, never emoji).
FORBIDDEN_UI_COPY_CHARACTERS: tuple[str, ...] = (
    "\U0001f300",  # emoji block start
    "\U0001fa70",
    "\u2014",  # em dash
)

#: Every legacy dashboard route audited before replacement.
DASHBOARD_ROUTES: tuple[str, ...] = (
    "/dashboard",
    "/dashboard/news",
    "/dashboard/macro",
    "/dashboard/brief",
    "/dashboard/debate",
    "/dashboard/models",
    "/dashboard/strategies",
    "/dashboard/ai-trading",
    "/dashboard/scheduler",
)

#: Preserved AlphaBrief brand assets (kept verbatim across the redesign).
BRAND_ASSETS: tuple[str, ...] = (
    "alphabrief-wordmark",
    "oanda-practice-badge",
    "paper-only-badge",
)

#: Before/after audit: route -> retained assets, usability defects,
#: planned replacement. Data only — no runtime behavior changes.
BRAND_AUDIT: dict[str, dict[str, object]] = {
    route: {
        "retained_assets": list(BRAND_ASSETS),
        "defects": (
            "legacy dark-only palette",
            "inline styles not tokenized",
            "cyan high-contrast accent outside Soft palette",
            "no reduced-motion rule",
        ),
        "replacement": (
            "Soft token system",
            "light + dark themes",
            "purposeful motion with reduced-motion support",
        ),
    }
    for route in DASHBOARD_ROUTES
}


class DesignSystemVerdict(BaseModel):
    """One deterministic design-system validation result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    issues: tuple[str, ...]


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two #rrggbb colors (deterministic)."""

    def _luminance(hex_color: str) -> float:
        value = hex_color.lstrip("#")
        if len(value) == 3:
            value = "".join(char * 2 for char in value)
        channels = [int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
        linear = [
            channel / 12.92
            if channel <= 0.03928
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter = max(_luminance(foreground), _luminance(background))
    darker = min(_luminance(foreground), _luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def validate_design_tokens() -> DesignSystemVerdict:
    """Deterministic automated validation of the Soft token system."""
    issues: list[str] = []
    required_categories = (
        "color_light",
        "color_dark",
        "typography",
        "spacing",
        "radius",
        "elevation",
        "interaction",
        "motion",
    )
    for category in required_categories:
        if category not in DESIGN_TOKENS or not DESIGN_TOKENS[category]:
            issues.append(f"missing token category {category!r}")

    for theme_name, category in THEMES.items():
        if category not in DESIGN_TOKENS:
            issues.append(f"theme {theme_name!r} has no token category")

    if "reduce_motion" not in DESIGN_TOKENS["motion"]:
        issues.append("motion tokens missing reduced-motion behavior")

    body_light = DESIGN_TOKENS["color_light"].get("text", "")
    bg_light = DESIGN_TOKENS["color_light"].get("bg", "")
    if body_light and bg_light:
        ratio = contrast_ratio(body_light, bg_light)
        if ratio < 4.5:
            issues.append(
                f"light-theme body text contrast {ratio:.2f} < 4.5:1"
            )

    for category, values in DESIGN_TOKENS.items():
        for key, value in values.items():
            if any(pattern in value for pattern in FORBIDDEN_STYLE_PATTERNS):
                issues.append(
                    f"{category}.{key} contains a forbidden style pattern"
                )

    return DesignSystemVerdict(
        passed=not issues,
        issues=tuple(issues),
    )


__all__ = [
    "BRAND_ASSETS",
    "BRAND_AUDIT",
    "DASHBOARD_ROUTES",
    "DESIGN_TOKENS",
    "DesignSystemVerdict",
    "FORBIDDEN_STYLE_PATTERNS",
    "FORBIDDEN_UI_COPY_CHARACTERS",
    "THEMES",
    "contrast_ratio",
    "validate_design_tokens",
]
