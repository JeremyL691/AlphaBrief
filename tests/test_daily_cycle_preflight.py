"""M11-W03: deterministic execution-readiness preflight gate.

Covers AC-M11-W03-02/03: missing credentials, stale account truth,
failed reconciliation, stale data, failed backup, unhealthy model, or an
active kill switch produce a blocked verdict with stable reasons before
any broker invocation; research-only, execution-disabled, blocked, and
executable are distinct machine-readable modes.
"""

from __future__ import annotations

from alphabrief_trader.execution_gate import (
    ExecutionGate,
    ExecutionMode,
    PreflightFacts,
)

GATE = ExecutionGate()


def _facts(**overrides: bool) -> PreflightFacts:
    return PreflightFacts(**overrides)


class TestExecutable:
    def test_all_gates_pass_yields_executable(self) -> None:
        verdict = GATE.evaluate(_facts())
        assert verdict.mode == ExecutionMode.EXECUTABLE
        assert verdict.reasons == ()

    def test_kill_switch_dominates_everything(self) -> None:
        verdict = GATE.evaluate(_facts(kill_switch_active=True))
        assert verdict.mode == ExecutionMode.BLOCKED
        assert verdict.reasons == ("kill_switch_active",)


class TestBlocked:
    def test_missing_credentials_blocks(self) -> None:
        verdict = GATE.evaluate(_facts(credentials_present=False))
        assert verdict.mode == ExecutionMode.BLOCKED
        assert "missing_credentials" in verdict.reasons

    def test_stale_account_truth_blocks(self) -> None:
        verdict = GATE.evaluate(_facts(account_truth_fresh=False))
        assert verdict.mode == ExecutionMode.BLOCKED
        assert "stale_account_truth" in verdict.reasons

    def test_failed_reconciliation_blocks(self) -> None:
        verdict = GATE.evaluate(_facts(reconciliation_clean=False))
        assert verdict.mode == ExecutionMode.BLOCKED
        assert "reconciliation_failed" in verdict.reasons

    def test_stale_data_blocks(self) -> None:
        verdict = GATE.evaluate(_facts(data_fresh=False))
        assert verdict.mode == ExecutionMode.BLOCKED
        assert "stale_data" in verdict.reasons

    def test_failed_backup_blocks(self) -> None:
        verdict = GATE.evaluate(_facts(backup_ok=False))
        assert verdict.mode == ExecutionMode.BLOCKED
        assert "backup_failed" in verdict.reasons

    def test_unhealthy_model_blocks(self) -> None:
        verdict = GATE.evaluate(_facts(model_healthy=False))
        assert verdict.mode == ExecutionMode.BLOCKED
        assert "unhealthy_model" in verdict.reasons

    def test_multiple_conditions_list_all_reasons(self) -> None:
        verdict = GATE.evaluate(
            _facts(
                credentials_present=False,
                data_fresh=False,
                backup_ok=False,
            )
        )
        assert verdict.mode == ExecutionMode.BLOCKED
        assert set(verdict.reasons) == {
            "missing_credentials",
            "stale_data",
            "backup_failed",
        }


class TestDisabledAndResearchOnly:
    def test_trading_disabled_yields_execution_disabled(self) -> None:
        verdict = GATE.evaluate(_facts(trading_enabled=False))
        assert verdict.mode == ExecutionMode.EXECUTION_DISABLED
        assert verdict.reasons == ("trading_disabled",)

    def test_research_only_mode_is_distinct(self) -> None:
        verdict = GATE.evaluate(_facts(research_only=True))
        assert verdict.mode == ExecutionMode.RESEARCH_ONLY
        assert verdict.reasons == ("research_only",)

    def test_blocking_condition_dominates_research_only(self) -> None:
        verdict = GATE.evaluate(
            _facts(research_only=True, credentials_present=False)
        )
        assert verdict.mode == ExecutionMode.BLOCKED
        assert "missing_credentials" in verdict.reasons

    def test_modes_are_machine_readable_and_distinct(self) -> None:
        modes = {ExecutionMode.EXECUTABLE, ExecutionMode.EXECUTION_DISABLED,
                 ExecutionMode.RESEARCH_ONLY, ExecutionMode.BLOCKED}
        assert len(modes) == 4
        assert ExecutionMode.EXECUTABLE.value == "executable"
        assert ExecutionMode.EXECUTION_DISABLED.value == "execution_disabled"
        assert ExecutionMode.RESEARCH_ONLY.value == "research_only"
        assert ExecutionMode.BLOCKED.value == "blocked"
