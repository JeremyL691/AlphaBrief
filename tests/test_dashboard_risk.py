"""M14-W04: Risk workspace.

Covers AC-M14-W04-02: Risk displays policy version, kill and freeze
state, daily loss, drawdown, gross and net exposure, category and
currency concentration, data freshness, and rule-level decisions.
"""

from __future__ import annotations

from alphabrief_api.dashboard.workspaces import build_risk_view


class TestRiskView:
    def test_displays_policy_and_safety_state(self) -> None:
        view = build_risk_view(
            policy_version="2026-08-13.1",
            kill_switch_active=True,
            frozen=False,
        )
        assert view.policy_version == "2026-08-13.1"
        assert view.kill_switch_active is True
        assert view.frozen is False

    def test_displays_loss_drawdown_and_exposure(self) -> None:
        view = build_risk_view(
            daily_loss="250.00",
            drawdown="0.04",
            gross_exposure="15800.00",
            net_exposure="15800.00",
        )
        assert view.daily_loss == "250.00"
        assert view.drawdown == "0.04"
        assert view.gross_exposure == "15800.00"
        assert view.net_exposure == "15800.00"

    def test_concentrations_are_sorted_and_stringified(self) -> None:
        view = build_risk_view(
            category_concentration={"CURRENCY": "0.7", "METAL": "0.3"},
            currency_concentration={"USD": "1.0"},
        )
        assert view.category_concentration == {
            "CURRENCY": "0.7",
            "METAL": "0.3",
        }
        assert view.currency_concentration == {"USD": "1.0"}

    def test_freshness_is_exposed(self) -> None:
        view = build_risk_view(freshness="stale")
        assert view.freshness == "stale"

    def test_rule_level_decisions_are_carried(self) -> None:
        view = build_risk_view(
            rule_decisions=[
                {"rule": "margin", "decision": "reject",
                 "detail": "margin exceeded"},
                {"rule": "concentration", "decision": "pass"},
            ]
        )
        assert len(view.rule_decisions) == 2
        assert view.rule_decisions[0].rule == "margin"
        assert view.rule_decisions[0].decision == "reject"
        assert view.rule_decisions[0].detail == "margin exceeded"
        assert view.rule_decisions[1].detail is None

    def test_missing_state_is_explicit_null(self) -> None:
        view = build_risk_view()
        assert view.policy_version is None
        assert view.kill_switch_active is None
        assert view.daily_loss is None
        assert view.rule_decisions == ()

    def test_deterministic(self) -> None:
        first = build_risk_view(policy_version="v1", kill_switch_active=False)
        second = build_risk_view(policy_version="v1", kill_switch_active=False)
        assert first.model_dump() == second.model_dump()
