"""M02-W04: safety gate (AC-M02-W04-02).

Live hosts, other-broker or removed execution surfaces, reference-source
imports, and seeded secrets in changed content all fail the safety gate.
"""

from __future__ import annotations

from alphabrief_acceptance.autonomous_gates import safety_gate_violations


def test_live_host_reference_fails() -> None:
    violations = safety_gate_violations(
        changed_files={
            "apps/api/src/alphabrief_api/config.py": (
                'BASE_URL = "https://api-fxtrade.oanda.com"\n'
            )
        }
    )
    assert any("live trading reference" in v for v in violations)


def test_live_trading_enabled_selection_fails() -> None:
    violations = safety_gate_violations(
        changed_files={
            "config/paper_execution_policy.yaml": (
                "mode: paper\nlive_trading_enabled: true\n"
            )
        }
    )
    assert any("live trading reference" in v for v in violations)


def test_other_broker_reference_fails() -> None:
    violations = safety_gate_violations(
        changed_files={
            "packages/alphabrief-execution/src/alphabrief_execution/broker/venus.py": (
                "import alpaca_trade_api\n"
            )
        }
    )
    assert any("another broker" in v for v in violations)


def test_removed_execution_surface_reference_fails() -> None:
    violations = safety_gate_violations(
        changed_files={
            "apps/api/src/alphabrief_api/broker_adapter.py": (
                "from alphabrief_execution.broker.routing import RoutingBrokerAdapter\n"
            )
        }
    )
    assert any("another broker or removed execution surface" in v for v in violations)


def test_reference_source_import_fails() -> None:
    violations = safety_gate_violations(
        changed_files={
            "packages/alphabrief-execution/src/alphabrief_execution/thing.py": (
                "from _reference_sources.tradingagents import strategy\n"
            )
        }
    )
    assert any("_reference_sources" in v for v in violations)


def test_seeded_secret_fails() -> None:
    violations = safety_gate_violations(
        changed_files={
            "config/oanda_paper.yaml": (
                "token: abcdef1234567890abcdef1234567890\n"
            )
        }
    )
    assert any("seeded secret pattern" in v for v in violations)


def test_full_account_id_fails() -> None:
    violations = safety_gate_violations(
        changed_files={
            "docs/runbook.md": "account 101-004-1234567-001 ready\n"
        }
    )
    assert any("seeded secret pattern" in v for v in violations)


def test_clean_changes_pass() -> None:
    violations = safety_gate_violations(
        changed_files={
            "docs/progress.yaml": "updated_at: 2026-08-13\n",
            "packages/alphabrief-acceptance/src/gates_module.py": (
                "def gate() -> None:\n    pass\n"
            ),
        }
    )
    assert violations == []
