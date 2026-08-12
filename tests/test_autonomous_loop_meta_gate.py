"""M02-W06: loop-controller meta-gate.

Builds a synthetic two-milestone repository and proves the deterministic
controller:

- a synthetic passing item advances, commits with trailers, appends one
  ledger row, and selects the correct next item (AC-M02-W06-01);
- a synthetic failing or acceptance-mutating item cannot mark itself
  DONE (AC-M02-W06-02);
- full repository and acceptance gates pass with controller enforcement
  enabled in progress (AC-M02-W06-03).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from alphabrief_acceptance.autonomous_schemas import (
    load_progress,
    load_work_queue,
)
from alphabrief_acceptance.loop_controller import controller_run

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Synthetic milestone/item ids used by the meta-gate repository.
M99_GATE = "M99-W01"
M98_GATE = "M98-W01"

_MILESTONES = [
    {
        "id": "M99",
        "title": "synthetic milestone one",
        "depends_on": [],
        "gate_work_item": M99_GATE,
    },
    {
        "id": "M98",
        "title": "synthetic milestone two",
        "depends_on": ["M99"],
        "gate_work_item": M98_GATE,
    },
]


def _synthetic_item(item_id: str, milestone_id: str, command: str) -> dict[str, object]:
    return {
        "id": item_id,
        "milestone_id": milestone_id,
        "title": f"synthetic {item_id}",
        "objective": "prove the loop controller meta-gate",
        "requirement_ids": ["REQ-SYN-001"],
        "depends_on": [],
        "priority": 10,
        "initial_status": "BACKLOG",
        "risk_class": "normal",
        "scope_profile": "loop_controller",
        "size_budget": {
            "max_production_files": 2,
            "max_total_files": 4,
            "max_changed_lines": 200,
        },
        "acceptance": [
            {
                "id": f"AC-{item_id}-01",
                "predicate": "synthetic acceptance predicate",
                "evidence_type": "automated_test",
            }
        ],
        "test_commands": {
            "targeted": [command],
            "integration": [],
            "static": [],
            "regression": [],
            "runtime": [],
        },
        "documentation": {"update": ["docs/progress.yaml"]},
    }


def _build_synthetic_repo(tmp_path: Path, *, failing: bool = False) -> Path:
    """Create a git repository with a minimal queue and progress authority."""
    import yaml

    real_queue = load_work_queue(PROJECT_ROOT / "docs/work_items.yaml")
    real_progress = load_progress(PROJECT_ROOT / "docs/progress.yaml")

    queue_dict = real_queue.model_dump()
    queue_dict["milestones"] = _MILESTONES
    queue_dict["work_items"] = [
        _synthetic_item(M99_GATE, "M99", "exit 1" if failing else "true"),
        _synthetic_item(M98_GATE, "M98", "true"),
    ]
    queue_dict["policy"]["engineering_ready_requires_all_m01_m15_done"] = False

    progress_dict = real_progress.model_dump(mode="json")
    progress_dict["milestones"] = {"M99": "ACTIVE", "M98": "BACKLOG"}
    progress_dict["work_item_states"] = {M99_GATE: "COMMITTING", M98_GATE: "READY"}
    progress_dict["current"] = {
        "round_id": None,
        "milestone_id": "M99",
        "work_item_id": M99_GATE,
        "phase": "COMMITTING",
        "base_commit": None,
        "attempt": 0,
        "last_verified_gate": None,
        "next_action": "controller meta-gate test",
    }
    progress_dict["known_gaps"] = []
    progress_dict["blockers"] = []
    progress_dict["last_completed_round"] = None
    progress_dict["last_ledger_record"] = None

    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "work_items.yaml").write_text(
        yaml.safe_dump(queue_dict), encoding="utf-8"
    )
    (repo / "docs" / "progress.yaml").write_text(
        yaml.safe_dump(progress_dict), encoding="utf-8"
    )
    (repo / "docs" / "development_ledger.ndjson").write_text("", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "controller@test"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Controller"], cwd=repo, check=True
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
    return repo


def _artifacts(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


# ---------------------------------------------------------------------------
# AC-M02-W06-01: synthetic passing item
# ---------------------------------------------------------------------------


def test_passing_item_advances_commits_and_selects_next(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path)
    (repo / "packages").mkdir(parents=True)
    implementation = repo / "packages" / "alphabrief-acceptance" / "src" / "impl.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("VALUE = 1\n", encoding="utf-8")

    outcome = controller_run(
        repo_root=repo,
        work_item_id=M99_GATE,
        round_id="R-SYN-001",
        commit_message="M99-W01: synthetic pass",
        artifacts_dir=_artifacts(tmp_path),
        timeout_seconds=10.0,
    )

    assert outcome.status == "DONE"
    assert outcome.commit_ref is not None
    assert outcome.ledger_round_id == "R-SYN-001"

    # Commit carries the protocol trailers.
    log = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--format=%s|%(trailers:key=AlphaBrief-Round,valueonly)"
            "|%(trailers:key=AlphaBrief-Work-Item,valueonly)",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("|")
    assert log[0] == "M99-W01: synthetic pass"
    assert log[1].strip() == "R-SYN-001"
    assert log[2].strip() == M99_GATE

    # Exactly one ledger row was appended.
    rows = (repo / "docs" / "development_ledger.ndjson").read_text().splitlines()
    assert len(rows) == 1
    record = json.loads(rows[0])
    assert record["round_id"] == "R-SYN-001"
    assert record["result"] == "DONE"
    assert record["work_item_id"] == M99_GATE

    # Progress advanced: M99 DONE, M98 ACTIVE, next item selected.
    progress = load_progress(repo / "docs/progress.yaml")
    assert progress.work_item_states[M99_GATE] == "DONE"
    assert progress.milestones["M99"] == "DONE"
    assert progress.milestones["M98"] == "ACTIVE"
    assert outcome.next_work_item == M98_GATE
    assert progress.current.work_item_id == M98_GATE

    # Working tree is clean after the controller commit.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status == ""


# ---------------------------------------------------------------------------
# AC-M02-W06-02: failing and acceptance-mutating items cannot self-certify
# ---------------------------------------------------------------------------


def test_failing_item_cannot_mark_itself_done(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path, failing=True)
    (repo / "packages").mkdir(parents=True)
    implementation = repo / "packages" / "alphabrief-acceptance" / "src" / "impl.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("VALUE = 1\n", encoding="utf-8")

    outcome = controller_run(
        repo_root=repo,
        work_item_id=M99_GATE,
        round_id="R-SYN-FAIL",
        commit_message="M99-W01: synthetic fail",
        artifacts_dir=_artifacts(tmp_path),
        timeout_seconds=10.0,
    )

    assert outcome.status == "FAILED"
    assert outcome.commit_ref is None
    assert not any(item.passed for item in outcome.evidence)
    # No ledger row, no progress mutation, no commit.
    rows = (repo / "docs" / "development_ledger.ndjson").read_text().splitlines()
    assert rows == []
    progress = load_progress(repo / "docs/progress.yaml")
    assert progress.work_item_states[M99_GATE] == "COMMITTING"
    commits = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert commits == "1"


def test_acceptance_mutation_cannot_mark_itself_done(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path)
    (repo / "packages").mkdir(parents=True)
    implementation = repo / "packages" / "alphabrief-acceptance" / "src" / "impl.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("VALUE = 1\n", encoding="utf-8")

    # The round mutates its own acceptance in the queue authority.
    import yaml

    queue_path = repo / "docs" / "work_items.yaml"
    queue_dict = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    for item in queue_dict["work_items"]:
        if item["id"] == M99_GATE:
            item["acceptance"][0]["predicate"] = "mutated acceptance predicate"
    queue_path.write_text(yaml.safe_dump(queue_dict), encoding="utf-8")

    outcome = controller_run(
        repo_root=repo,
        work_item_id=M99_GATE,
        round_id="R-SYN-MUT",
        commit_message="M99-W01: synthetic mutation",
        artifacts_dir=_artifacts(tmp_path),
        timeout_seconds=10.0,
    )

    assert outcome.status == "BLOCKED_ACCEPTANCE_MUTATION"
    assert outcome.commit_ref is None
    rows = (repo / "docs" / "development_ledger.ndjson").read_text().splitlines()
    assert rows == []
    progress = load_progress(repo / "docs/progress.yaml")
    assert progress.work_item_states[M99_GATE] == "COMMITTING"


def test_scope_violating_item_is_blocked(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path)
    # A changed file outside the loop_controller allowlist.
    touched_dir = repo / "apps" / "api" / "src" / "alphabrief_api" / "routes"
    touched_dir.mkdir(parents=True)
    (touched_dir / "touched.py").write_text("x = 1\n", encoding="utf-8")

    outcome = controller_run(
        repo_root=repo,
        work_item_id=M99_GATE,
        round_id="R-SYN-SCOPE",
        commit_message="M99-W01: synthetic scope violation",
        artifacts_dir=_artifacts(tmp_path),
        timeout_seconds=10.0,
    )

    assert outcome.status == "BLOCKED_SCOPE"
    assert outcome.gate_violations
    assert outcome.commit_ref is None


# ---------------------------------------------------------------------------
# AC-M02-W06-03: controller enforcement in progress
# ---------------------------------------------------------------------------


def test_controller_enforcement_flag_is_recorded_in_ledger(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path)
    (repo / "packages").mkdir(parents=True)
    implementation = repo / "packages" / "alphabrief-acceptance" / "src" / "impl.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("VALUE = 1\n", encoding="utf-8")

    outcome = controller_run(
        repo_root=repo,
        work_item_id=M99_GATE,
        round_id="R-SYN-ENF",
        commit_message="M99-W01: synthetic enforced",
        artifacts_dir=_artifacts(tmp_path),
        timeout_seconds=10.0,
    )

    assert outcome.status == "DONE"
    record = json.loads(
        (repo / "docs" / "development_ledger.ndjson").read_text().splitlines()[0]
    )
    assert record["controller_enforced"] is True
