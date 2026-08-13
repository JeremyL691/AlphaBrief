"""M14-W06: safe operator controls.

Covers AC-M14-W06-02: the only write controls are pause or resume
research, freeze or rule-governed unfreeze practice execution, cancel
a practice order, and reduce or close practice exposure; each requires
validation, idempotency, confirmation, and audit.
"""

from __future__ import annotations

import pytest
from alphabrief_api.dashboard.operations import (
    ControlAction,
    control_actions,
)
from alphabrief_core.write_contracts import OPERATOR_MUTATIONS


class TestBoundedControlSet:
    def test_controls_are_exactly_the_approved_seven(self) -> None:
        actions = control_actions()
        assert {action.mutation for action in actions} == set(
            OPERATOR_MUTATIONS
        )
        assert len(actions) == 7

    def test_every_control_requires_validation_idempotency_confirmation_audit(
        self,
    ) -> None:
        for action in control_actions():
            assert action.requires_validation is True
            assert action.requires_idempotency is True
            assert action.requires_confirmation is True
            assert action.audited is True

    def test_no_control_outside_the_approved_set(self) -> None:
        for action in control_actions():
            assert action.mutation in OPERATOR_MUTATIONS

    def test_controls_are_deterministic(self) -> None:
        assert control_actions() == control_actions()

    @pytest.mark.parametrize(
        "mutation",
        sorted(OPERATOR_MUTATIONS),
    )
    def test_every_approved_mutation_has_a_control_action(
        self, mutation: str
    ) -> None:
        actions = {action.mutation: action for action in control_actions()}
        assert isinstance(actions[mutation], ControlAction)
        assert actions[mutation].mutation == mutation
