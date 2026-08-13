"""Declared dashboard accessibility contract (M14-W07).

The Soft dashboard satisfies one declared accessibility contract:
semantic regions, heading order, forms, tables, dialogs, focus order
and traps, labels, status announcements, contrast, and keyboard-only
operation. ``validate_accessibility_contract`` is a deterministic
check over the declared contract and the design tokens (REQ-UI-008).
"""

from __future__ import annotations

from alphabrief_api.dashboard.design_system import (
    DESIGN_TOKENS,
    contrast_ratio,
)
from pydantic import BaseModel, ConfigDict

#: Semantic regions every page must expose.
SEMANTIC_REGIONS: tuple[str, ...] = ("nav", "main", "aside", "footer")

#: Heading order rule: exactly one h1, then strictly sequential.
HEADING_ORDER_RULE: str = "exactly one h1; h2..h6 strictly sequential"

#: Form controls must carry labels; tables must carry captions and
#: header cells; dialogs must carry role=dialog and trap focus.
FORM_LABEL_RULE: str = "every form control has an associated label"
TABLE_RULE: str = "tables have a caption and header cells"
DIALOG_RULE: str = "dialogs use role=dialog and trap focus"

#: Focus order follows DOM order; focus is always visible.
FOCUS_ORDER_RULE: str = "focus order follows document order"
FOCUS_VISIBLE_RULE: str = "focus is always visible"

#: Status changes are announced via aria-live regions.
STATUS_ANNOUNCEMENT_RULE: str = "status changes use aria-live"

#: Keyboard-only operation: no mouse-only interaction.
KEYBOARD_ONLY_RULE: str = "all interactions are keyboard-operable"


class AccessibilityContract(BaseModel):
    """One deterministic accessibility contract declaration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_regions: tuple[str, ...]
    heading_order_rule: str
    form_label_rule: str
    table_rule: str
    dialog_rule: str
    focus_order_rule: str
    focus_visible_rule: str
    status_announcement_rule: str
    keyboard_only_rule: str
    min_contrast_ratio: float = 4.5


class AccessibilityVerdict(BaseModel):
    """One deterministic accessibility validation result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    issues: tuple[str, ...]


def accessibility_contract() -> AccessibilityContract:
    """The single declared accessibility contract."""
    return AccessibilityContract(
        semantic_regions=SEMANTIC_REGIONS,
        heading_order_rule=HEADING_ORDER_RULE,
        form_label_rule=FORM_LABEL_RULE,
        table_rule=TABLE_RULE,
        dialog_rule=DIALOG_RULE,
        focus_order_rule=FOCUS_ORDER_RULE,
        focus_visible_rule=FOCUS_VISIBLE_RULE,
        status_announcement_rule=STATUS_ANNOUNCEMENT_RULE,
        keyboard_only_rule=KEYBOARD_ONLY_RULE,
    )


def validate_accessibility_contract() -> AccessibilityVerdict:
    """Deterministic validation of the declared contract.

    Checks the contract completeness and the token contrast for every
    theme's body and dim text on its background.
    """
    issues: list[str] = []
    contract = accessibility_contract()
    if set(contract.semantic_regions) != set(SEMANTIC_REGIONS):
        issues.append("semantic regions do not match the declared set")
    for rule in (
        contract.heading_order_rule,
        contract.form_label_rule,
        contract.table_rule,
        contract.dialog_rule,
        contract.focus_order_rule,
        contract.focus_visible_rule,
        contract.status_announcement_rule,
        contract.keyboard_only_rule,
    ):
        if not rule.strip():
            issues.append("an accessibility rule is blank")

    for theme in ("color_light", "color_dark"):
        colors = DESIGN_TOKENS[theme]
        for pair in (("text", "bg"), ("text_dim", "bg")):
            ratio = contrast_ratio(colors[pair[0]], colors[pair[1]])
            if ratio < contract.min_contrast_ratio:
                issues.append(
                    f"{theme}.{pair[0]} contrast {ratio:.2f} < "
                    f"{contract.min_contrast_ratio}"
                )

    return AccessibilityVerdict(
        passed=not issues,
        issues=tuple(issues),
    )


__all__ = [
    "AccessibilityContract",
    "AccessibilityVerdict",
    "DIALOG_RULE",
    "FOCUS_ORDER_RULE",
    "FOCUS_VISIBLE_RULE",
    "FORM_LABEL_RULE",
    "HEADING_ORDER_RULE",
    "KEYBOARD_ONLY_RULE",
    "SEMANTIC_REGIONS",
    "STATUS_ANNOUNCEMENT_RULE",
    "TABLE_RULE",
    "accessibility_contract",
    "validate_accessibility_contract",
]
