"""M02-W01: strict versioned schemas for the autonomous loop machine state.

Covers:
- current work_items.yaml and progress.yaml parse under strict schemas and
  unknown fields are rejected (AC-M02-W01-01);
- every required work item resolves its scope profile into a complete
  immutable execution contract (AC-M02-W01-02);
- malformed NDJSON, duplicate IDs, missing dependencies, and requirement
  gaps fail validation (AC-M02-W01-03).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_acceptance.autonomous_schemas import (
    ExecutionContractSchema,
    ProgressSchema,
    WorkItemSchema,
    WorkQueueSchema,
    load_checkpoint,
    load_ledger,
    load_progress,
    load_work_queue,
    resolve_all_execution_contracts,
    resolve_execution_contract,
)
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def queue() -> WorkQueueSchema:
    return load_work_queue(PROJECT_ROOT / "docs/work_items.yaml")


@pytest.fixture(scope="module")
def progress() -> ProgressSchema:
    return load_progress(PROJECT_ROOT / "docs/progress.yaml")


def test_current_work_queue_parses_under_strict_schema(queue: WorkQueueSchema) -> None:
    """AC-M02-W01-01: the current queue satisfies the versioned schema."""
    assert queue.schema_version == 1
    assert queue.queue_id == "alphabrief-oanda-final"
    assert len(queue.work_items) >= 100
    assert len(queue.milestones) == 18
    assert len(queue.scope_profiles) >= 10


def test_current_progress_parses_under_strict_schema(
    progress: ProgressSchema,
) -> None:
    """AC-M02-W01-01: the current progress file satisfies the schema."""
    assert progress.schema_version == 1
    assert progress.current.work_item_id == "M02-W01"
    assert progress.milestones["M01"] == "DONE"
    assert progress.work_item_states["M01-W05"] == "DONE"


def test_current_checkpoint_and_ledger_parse() -> None:
    """AC-M02-W01-01: checkpoint and ledger schemas validate real state."""
    checkpoint_path = PROJECT_ROOT / ".agent-state" / "current.yaml"
    if checkpoint_path.is_file():
        checkpoint = load_checkpoint(checkpoint_path)
        assert checkpoint.round_id
    records = load_ledger(PROJECT_ROOT / "docs/development_ledger.ndjson")
    assert len(records) >= 5
    assert records[0].record_type == "BASELINE"
    assert all(record.schema_version == 1 for record in records)


def test_unknown_fields_are_rejected_in_work_queue(tmp_path: Path) -> None:
    """AC-M02-W01-01: unknown queue fields fail instead of being ignored."""
    import yaml

    raw = yaml.safe_load(
        (PROJECT_ROOT / "docs/work_items.yaml").read_text(encoding="utf-8")
    )
    raw["mystery_field"] = "nope"
    mutated = tmp_path / "queue.yaml"
    mutated.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_work_queue(mutated)


def test_unknown_fields_are_rejected_in_progress(tmp_path: Path) -> None:
    """AC-M02-W01-01: unknown progress fields fail instead of being ignored."""
    import yaml

    raw = yaml.safe_load(
        (PROJECT_ROOT / "docs/progress.yaml").read_text(encoding="utf-8")
    )
    raw["mystery_field"] = "nope"
    mutated = tmp_path / "progress.yaml"
    mutated.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_progress(mutated)


def test_every_work_item_resolves_a_complete_contract(
    queue: WorkQueueSchema,
) -> None:
    """AC-M02-W01-02: all required items resolve immutable contracts."""
    contracts = resolve_all_execution_contracts(queue)
    assert len(contracts) == len(queue.work_items)

    for contract in contracts.values():
        assert isinstance(contract, ExecutionContractSchema)
        assert contract.resolved_allowed_paths
        assert contract.work_item.acceptance
        assert contract.work_item.size_budget.max_total_files > 0
        assert contract.completion_defaults.allow_waivers is False
        assert contract.completion_defaults.require_all_acceptance_pass is True
        # Global forbidden paths always apply.
        assert "_reference_sources/**" in contract.resolved_forbidden_paths


def test_item_level_paths_merge_into_profile_allowlist(
    queue: WorkQueueSchema,
) -> None:
    """AC-M02-W01-02: item-level allowed_paths extend the profile allowlist."""
    contract = resolve_execution_contract(queue, "M00-W01")
    profile_paths = set(queue.scope_profiles["governance"].allowed_paths)
    assert ".env.example" in contract.resolved_allowed_paths
    assert set(contract.resolved_allowed_paths) >= profile_paths


def test_completion_gate_override_merges_into_defaults(
    queue: WorkQueueSchema,
) -> None:
    """AC-M02-W01-02: completion_gate overrides merge without losing defaults."""
    synthetic_milestone = {
        "id": "M99",
        "title": "synthetic milestone",
        "depends_on": [],
        "gate_work_item": "M99-W01",
    }
    item = WorkItemSchema.model_validate(
        {
            "id": "M99-W01",
            "milestone_id": "M99",
            "title": "synthetic gate item",
            "objective": "prove completion gate merging",
            "requirement_ids": [],
            "depends_on": [],
            "priority": 10,
            "initial_status": "BACKLOG",
            "risk_class": "normal",
            "scope_profile": "governance",
            "size_budget": {
                "max_production_files": 1,
                "max_total_files": 2,
                "max_changed_lines": 100,
            },
            "acceptance": [
                {
                    "id": "AC-M99-W01-01",
                    "predicate": "synthetic acceptance",
                    "evidence_type": "automated_test",
                }
            ],
            "test_commands": {
                "targeted": ["pytest tests/test_x.py"],
                "integration": [],
                "static": [],
                "regression": [],
                "runtime": [],
            },
            "documentation": {"update": ["docs/progress.yaml"]},
            "completion_gate": {
                "allow_waivers": False,
                "require_clean_tree_after_commit": True,
            },
        }
    )
    synthetic = WorkQueueSchema.model_validate(
        {
            **queue.model_dump(),
            "work_items": list(queue.work_items) + [item],
            "milestones": list(queue.milestones) + [synthetic_milestone],
        }
    )
    contract = resolve_execution_contract(synthetic, "M99-W01")
    defaults = contract.completion_defaults
    assert defaults.require_clean_tree_after_commit is True
    assert defaults.require_all_acceptance_pass is True  # inherited from queue
    assert defaults.allow_waivers is False


def test_malformed_ndjson_fails_with_line_number(tmp_path: Path) -> None:
    """AC-M02-W01-03: malformed ledger lines fail validation."""
    ledger = tmp_path / "ledger.ndjson"
    ledger.write_text(
        "{\"record_type\":\"ROUND\",\"schema_version\":1,\"round_id\":\"r1\","
        "\"result\":\"DONE\"}\nnot-json\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="line 2"):
        load_ledger(ledger)


def test_invalid_ledger_record_fails_validation(tmp_path: Path) -> None:
    """AC-M02-W01-03: schema-invalid NDJSON lines fail with a line number."""
    ledger = tmp_path / "ledger.ndjson"
    ledger.write_text(
        "{\"record_type\":\"ROUND\",\"schema_version\":1,\"round_id\":\"r1\","
        "\"result\":\"DONE\",\"mystery\":true}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="line 1"):
        load_ledger(ledger)


def test_duplicate_work_item_ids_fail_validation(
    queue: WorkQueueSchema,
) -> None:
    """AC-M02-W01-03: duplicate work item IDs are rejected."""
    duplicate = list(queue.work_items) + [queue.work_items[0]]

    with pytest.raises(ValidationError, match="must be unique"):
        WorkQueueSchema.model_validate(
            {
                **queue.model_dump(),
                "work_items": duplicate,
            }
        )


def test_missing_dependency_fails_validation(
    queue: WorkQueueSchema,
) -> None:
    """AC-M02-W01-03: dependencies on unknown work items are rejected."""
    items = list(queue.work_items)
    broken = WorkItemSchema.model_validate(
        {
            **items[0].model_dump(),
            "id": "M99-W99",
            "depends_on": ("M01-W01", "M98-W01"),
        }
    )

    with pytest.raises(ValidationError, match="M98-W01"):
        WorkQueueSchema.model_validate(
            {
                **queue.model_dump(),
                "work_items": items + [broken],
                "milestones": list(queue.milestones),
            }
        )


def test_requirement_gap_fails_validation() -> None:
    """AC-M02-W01-03: an item without acceptance predicates is a gap."""
    with pytest.raises(ValidationError, match="at least 1 item"):
        WorkItemSchema.model_validate(
            {
                "id": "M99-W02",
                "milestone_id": "M99",
                "title": "gap item",
                "objective": "missing acceptance",
                "requirement_ids": [],
                "depends_on": [],
                "priority": 10,
                "initial_status": "BACKLOG",
                "risk_class": "normal",
                "scope_profile": "governance",
                "size_budget": {
                    "max_production_files": 1,
                    "max_total_files": 2,
                    "max_changed_lines": 100,
                },
                "acceptance": [],
                "test_commands": {"targeted": ["pytest tests/test_x.py"]},
                "documentation": {"update": ["docs/progress.yaml"]},
            }
        )


def test_blank_acceptance_predicate_fails_validation() -> None:
    """AC-M02-W01-03: blank acceptance predicates are rejected."""
    with pytest.raises(ValidationError, match="at least 1 character"):
        WorkItemSchema.model_validate(
            {
                "id": "M99-W03",
                "milestone_id": "M99",
                "title": "blank predicate item",
                "objective": "blank acceptance predicate",
                "requirement_ids": [],
                "depends_on": [],
                "priority": 10,
                "initial_status": "BACKLOG",
                "risk_class": "normal",
                "scope_profile": "governance",
                "size_budget": {
                    "max_production_files": 1,
                    "max_total_files": 2,
                    "max_changed_lines": 100,
                },
                "acceptance": [
                    {
                        "id": "AC-M99-W03-01",
                        "predicate": "",
                        "evidence_type": "automated_test",
                    }
                ],
                "test_commands": {"targeted": ["pytest tests/test_x.py"]},
                "documentation": {"update": ["docs/progress.yaml"]},
            }
        )
