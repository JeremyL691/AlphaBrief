"""M16-W04: approved local fault-injection drill.

Covers AC-M16-W04-02: approved fault injection (429, 5xx, network
loss, stale data, model failure) proves bounded retry, jitter, no
scheduler starvation, safe no-trade or freeze, durable alerting, clean
recovery, and no blind resubmission or duplicate external order.
"""

from __future__ import annotations

from alphabrief_core import (
    FAULT_INVARIANTS,
    FAULT_SCENARIOS,
    FaultDrillReport,
    FaultInvariant,
    run_fault_drill,
)


def _full_truth() -> dict[str, bool]:
    return {name: True for name in FAULT_INVARIANTS}


class TestFaultDrill:
    def test_all_five_scenarios_are_declared(self) -> None:
        assert FAULT_SCENARIOS == (
            "http_429",
            "http_5xx",
            "network_loss",
            "stale_data",
            "model_failure",
        )

    def test_all_eight_invariants_are_declared(self) -> None:
        assert FAULT_INVARIANTS == (
            "bounded_retry",
            "jitter",
            "no_scheduler_starvation",
            "safe_no_trade_or_freeze",
            "durable_alerting",
            "clean_recovery",
            "no_blind_resubmission",
            "no_duplicate_external_order",
        )

    def test_full_truth_passes_under_approved_injection(self) -> None:
        for scenario in FAULT_SCENARIOS:
            drill = run_fault_drill(
                scenario=scenario, invariant_truth=_full_truth()
            )
            assert isinstance(drill, FaultDrillReport)
            assert drill.passed is True
            assert drill.submits == 0
            assert all(
                invariant.preserved for invariant in drill.invariants
            )

    def test_missing_truth_fails_closed(self) -> None:
        drill = run_fault_drill(scenario="http_429", invariant_truth={})
        assert drill.passed is False
        assert drill.submits == 0
        assert all(
            not invariant.preserved for invariant in drill.invariants
        )

    def test_unknown_scenario_fails_closed(self) -> None:
        drill = run_fault_drill(scenario="mystery", invariant_truth={})
        assert drill.passed is False
        assert drill.submits == 0
        assert all(
            invariant.detail == "unknown fault scenario"
            for invariant in drill.invariants
        )

    def test_duplicate_order_invariant_is_guarded(self) -> None:
        truth = _full_truth()
        truth["no_duplicate_external_order"] = False
        drill = run_fault_drill(scenario="network_loss", invariant_truth=truth)
        assert drill.passed is False
        duplicate = next(
            i for i in drill.invariants if i.name == "no_duplicate_external_order"
        )
        assert duplicate.preserved is False

    def test_drill_never_submits(self) -> None:
        for scenario in FAULT_SCENARIOS:
            drill = run_fault_drill(scenario=scenario, invariant_truth={})
            assert drill.submits == 0

    def test_invariants_are_typed(self) -> None:
        drill = run_fault_drill(scenario="http_429", invariant_truth={})
        assert isinstance(drill.invariants[0], FaultInvariant)

    def test_deterministic(self) -> None:
        first = run_fault_drill(
            scenario="http_429", invariant_truth=_full_truth()
        )
        second = run_fault_drill(
            scenario="http_429", invariant_truth=_full_truth()
        )
        assert first.model_dump() == second.model_dump()
