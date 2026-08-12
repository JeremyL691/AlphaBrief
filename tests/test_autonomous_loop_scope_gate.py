"""M02-W04: scope gate (AC-M02-W04-01) and test-delta gate (AC-M02-W04-03).

The scope gate rejects any changed path outside the current resolved
allowlist or inside the resolved forbidden set. The test-delta gate
rejects deleted tests and new skip/xfail/noqa/type-ignore markers or
weakened quality configuration unless explicitly authorized.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_acceptance.autonomous_gates import (
    delta_gate_violations,
    path_matches_glob,
    scope_gate_violations,
)
from alphabrief_acceptance.autonomous_schemas import (
    ExecutionContractSchema,
    WorkQueueSchema,
    load_work_queue,
    resolve_execution_contract,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def queue() -> WorkQueueSchema:
    return load_work_queue(PROJECT_ROOT / "docs/work_items.yaml")


def _contract(queue: WorkQueueSchema, item_id: str) -> ExecutionContractSchema:
    return resolve_execution_contract(queue, item_id)


# ---------------------------------------------------------------------------
# AC-M02-W04-01: scope gate
# ---------------------------------------------------------------------------


def test_glob_matching_across_directories() -> None:
    assert path_matches_glob(
        "packages/alphabrief-core/src/alphabrief_core/execution_policy.py",
        "packages/alphabrief-core/**",
    )
    assert path_matches_glob("tests/test_oanda_adapter.py", "tests/test_oanda*.py")
    assert path_matches_glob("config/oanda_paper.yaml", "config/**")
    assert not path_matches_glob("docs/progress.yaml", "config/**")


def test_changed_path_inside_allowlist_passes(queue: WorkQueueSchema) -> None:
    contract = _contract(queue, "M02-W04")
    violations = scope_gate_violations(
        contract=contract,
        changed_paths=[
            "packages/alphabrief-acceptance/src/alphabrief_acceptance/autonomous_gates.py",
            "docs/progress.yaml",
            "tests/test_autonomous_loop_scope_gate.py",
        ],
    )
    assert violations == []


def test_changed_path_outside_allowlist_fails(queue: WorkQueueSchema) -> None:
    """Any changed path outside the resolved allowlist fails the gate."""
    contract = _contract(queue, "M02-W04")
    violations = scope_gate_violations(
        contract=contract,
        changed_paths=["packages/alphabrief-execution/src/alphabrief_execution/broker/runtime.py"],
    )
    assert any("outside the resolved allowlist" in v for v in violations)


def test_changed_path_inside_forbidden_paths_fails(
    queue: WorkQueueSchema,
) -> None:
    """Paths inside the resolved forbidden set always fail."""
    contract = _contract(queue, "M02-W04")
    violations = scope_gate_violations(
        contract=contract,
        changed_paths=["_reference_sources/tradingagents/something.py"],
    )
    assert any("forbidden paths" in v for v in violations)


# ---------------------------------------------------------------------------
# AC-M02-W04-03: test-delta gate
# ---------------------------------------------------------------------------


def test_deleted_test_requires_authorization() -> None:
    violations = delta_gate_violations(
        deleted_paths=["tests/test_old_behavior.py"],
        changed_files={},
    )
    assert any("deletes a test" in v for v in violations)


def test_deleted_test_with_authorization_passes() -> None:
    violations = delta_gate_violations(
        deleted_paths=["tests/test_old_behavior.py"],
        changed_files={},
        authorized_paths=["tests/test_old_behavior.py"],
    )
    assert violations == []


def test_new_skip_marker_fails_without_authorization() -> None:
    violations = delta_gate_violations(
        deleted_paths=[],
        changed_files={
            "tests/test_example.py": (
                "import pytest\n"
                "@pytest.mark.skip(reason='x')\n"
                "def test_x() -> None: ...\n"
            ),
        },
    )
    assert any("skip" in v for v in violations)


def test_new_noqa_and_type_ignore_fail_without_authorization() -> None:
    violations = delta_gate_violations(
        deleted_paths=[],
        changed_files={
            "tests/test_example.py": (
                "import pytest  # noqa: F401\n"
                "x: int = 1  # type: ignore[assignment]\n"
            )
        },
    )
    assert any("noqa" in v for v in violations)
    assert any("type-ignore" in v for v in violations)


def test_authorized_markers_pass() -> None:
    violations = delta_gate_violations(
        deleted_paths=[],
        changed_files={
            "tests/test_example.py": "import pytest  # noqa: F401\n"
        },
        authorized_markers=["noqa"],
    )
    assert violations == []


def test_quality_config_change_fails_without_authorization() -> None:
    violations = delta_gate_violations(
        deleted_paths=[],
        changed_files={"pyproject.toml": "[tool.ruff]\nline-length = 200\n"},
    )
    assert any("quality configuration" in v for v in violations)


def test_authorized_quality_config_change_passes() -> None:
    violations = delta_gate_violations(
        deleted_paths=[],
        changed_files={"pyproject.toml": "[tool.ruff]\n"},
        authorized_paths=["pyproject.toml"],
    )
    assert violations == []


def test_plain_test_changes_pass() -> None:
    violations = delta_gate_violations(
        deleted_paths=[],
        changed_files={
            "tests/test_example.py": "def test_ok() -> None:\n    assert True\n"
        },
    )
    assert violations == []
