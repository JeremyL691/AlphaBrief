"""M14-W07: dashboard accessibility contract.

Covers AC-M14-W07-02: semantic regions, heading order, forms, tables,
dialogs, focus order, focus traps, labels, status announcements,
contrast, and keyboard-only operation satisfy the declared
accessibility contract.
"""

from __future__ import annotations

import pytest
from alphabrief_api.dashboard.accessibility import (
    SEMANTIC_REGIONS,
    AccessibilityContract,
    accessibility_contract,
    validate_accessibility_contract,
)
from alphabrief_api.dashboard.design_system import (
    DESIGN_TOKENS,
    contrast_ratio,
)


class TestDeclaredContract:
    def test_semantic_regions_are_declared(self) -> None:
        assert set(SEMANTIC_REGIONS) == {"nav", "main", "aside", "footer"}

    def test_heading_order_rule(self) -> None:
        assert "exactly one h1" in accessibility_contract().heading_order_rule

    def test_form_table_dialog_rules(self) -> None:
        contract = accessibility_contract()
        assert "label" in contract.form_label_rule
        assert "caption" in contract.table_rule
        assert "role=dialog" in contract.dialog_rule
        assert "trap focus" in contract.dialog_rule

    def test_focus_and_keyboard_rules(self) -> None:
        contract = accessibility_contract()
        assert "document order" in contract.focus_order_rule
        assert "visible" in contract.focus_visible_rule
        assert "aria-live" in contract.status_announcement_rule
        assert "keyboard" in contract.keyboard_only_rule

    def test_contract_is_typed(self) -> None:
        assert isinstance(accessibility_contract(), AccessibilityContract)


class TestContrast:
    @pytest.mark.parametrize("theme", ("color_light", "color_dark"))
    def test_body_and_dim_text_pass_wcag_aa(self, theme: str) -> None:
        colors = DESIGN_TOKENS[theme]
        for pair in (("text", "bg"), ("text_dim", "bg")):
            ratio = contrast_ratio(colors[pair[0]], colors[pair[1]])
            assert ratio >= 4.5, f"{theme}.{pair[0]}"

    def test_contrast_is_deterministic(self) -> None:
        assert contrast_ratio("#3d3a34", "#faf7f2") == contrast_ratio(
            "#3d3a34", "#faf7f2"
        )


class TestValidation:
    def test_validation_passes(self) -> None:
        verdict = validate_accessibility_contract()
        assert verdict.passed, verdict.issues

    def test_min_contrast_is_aa(self) -> None:
        assert accessibility_contract().min_contrast_ratio == 4.5

    def test_validation_is_deterministic(self) -> None:
        first = validate_accessibility_contract()
        second = validate_accessibility_contract()
        assert first.model_dump() == second.model_dump()
