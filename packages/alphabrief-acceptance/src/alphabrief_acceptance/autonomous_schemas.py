"""Strict, versioned schemas for the autonomous development loop (M02-W01).

Parses and validates the machine state of the loop: the blueprint work
queue (``docs/work_items.yaml``), progress state (``docs/progress.yaml``),
the round checkpoint (``.agent-state/current.yaml``), the append-only
ledger (``docs/development_ledger.ndjson``), and evidence records.

Every model is frozen and rejects unknown fields, so a schema drift in
any authority file fails validation instead of being silently ignored
(REQ-PLAT-001 style strictness applied to the loop's own machine state).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Evidence and acceptance predicates
# ---------------------------------------------------------------------------

EvidenceType = Literal["automated_test", "static_gate", "practice_e2e", "observation"]

ItemStatus = Literal[
    "BACKLOG",
    "READY",
    "PLANNING",
    "PLAN_GATE",
    "IMPLEMENTING",
    "TESTING",
    "SELF_REVIEW",
    "DOCUMENTING",
    "FINAL_GATE",
    "COMMITTING",
    "DONE",
    "CODE_COMPLETE",
    "RUNTIME_VALIDATING",
    "BLOCKED_EXTERNAL",
    "BLOCKED_DECISION",
    "BLOCKED_SAFETY",
    "QUARANTINED",
    "FAILED",
    "SUPERSEDED",
]

MilestoneStatus = Literal[
    "BACKLOG",
    "ACTIVE",
    "CODE_COMPLETE",
    "RUNTIME_VALIDATING",
    "DONE",
    "BLOCKED",
]

RiskClass = Literal[
    "normal",
    "data-critical",
    "model-critical",
    "execution-critical",
    "safety-critical",
]


class AcceptancePredicateSchema(BaseModel):
    """One acceptance predicate of a work item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    evidence_type: EvidenceType


class SizeBudgetSchema(BaseModel):
    """Change budget of a work item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_production_files: int = Field(ge=0)
    max_total_files: int = Field(ge=0)
    max_changed_lines: int = Field(ge=0)


class TestCommandsSchema(BaseModel):
    """Declared test layers of a work item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    targeted: tuple[str, ...] = Field(min_length=1)
    integration: tuple[str, ...] = ()
    static: tuple[str, ...] = ()
    regression: tuple[str, ...] = ()
    runtime: tuple[str, ...] = ()


class DocumentationSchema(BaseModel):
    """Documentation paths a work item may update."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    update: tuple[str, ...] = Field(min_length=1)


class CompletionGateSchema(BaseModel):
    """Optional per-item completion gate overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    require_clean_tree_after_commit: bool | None = None
    require_all_acceptance_pass: bool | None = None
    allow_waivers: bool | None = None


class WorkItemSchema(BaseModel):
    """One required work item of the blueprint queue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=r"^M\d+-W\d+[A-Z]?$")
    milestone_id: str = Field(min_length=1, pattern=r"^M\d+$")
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    requirement_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    priority: int
    initial_status: ItemStatus
    risk_class: RiskClass
    scope_profile: str = Field(min_length=1)
    allowed_paths: tuple[str, ...] | None = None
    forbidden_paths: tuple[str, ...] | None = None
    untouched_modules: tuple[str, ...] | None = None
    size_budget: SizeBudgetSchema
    acceptance: tuple[AcceptancePredicateSchema, ...] = Field(min_length=1)
    test_commands: TestCommandsSchema
    documentation: DocumentationSchema
    completion_gate: CompletionGateSchema | None = None

    @model_validator(mode="after")
    def depends_on_must_be_unique(self) -> WorkItemSchema:
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"{self.id} depends_on contains duplicates")
        if len(set(self.requirement_ids)) != len(self.requirement_ids):
            raise ValueError(f"{self.id} requirement_ids contains duplicates")
        return self


class MilestoneSchema(BaseModel):
    """One milestone of the blueprint queue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=r"^M\d+$")
    title: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    gate_work_item: str = Field(min_length=1)


class PolicySchema(BaseModel):
    """Queue-level execution policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    branch: str
    selection: str
    auto_continue: bool
    auto_commit: bool
    auto_push: bool
    allow_waivers: bool
    live_trading: Literal["forbidden"]
    production_broker: str
    production_simulated_fallback: Literal["forbidden"]
    reference_source_access_during_implementation: Literal["forbidden"]
    state_source: str
    artifact_root: str
    checkpoint_file: str
    engineering_code_dependency_states: tuple[str, ...] = Field(min_length=1)
    runtime_gate_dependency_states: tuple[str, ...] = Field(min_length=1)
    observation_dependency_states: tuple[str, ...] = Field(min_length=1)
    engineering_ready_requires_all_m01_m15_done: bool


class CompletionDefaultsSchema(BaseModel):
    """Queue-level completion gate defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    require_all_acceptance_pass: bool
    require_clean_tree_after_commit: bool
    allow_waivers: bool
    max_same_failure_repairs: int = Field(ge=1)
    max_total_repair_cycles: int = Field(ge=1)
    max_external_retries: int = Field(ge=0)


class ScopeProfileSchema(BaseModel):
    """One scope profile shared by work items."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_paths: tuple[str, ...] = Field(min_length=1)
    untouched_modules: tuple[str, ...] = ()
    static_commands: tuple[str, ...] = ()


class WorkQueueSchema(BaseModel):
    """The complete blueprint work queue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = SCHEMA_VERSION
    blueprint_version: str = Field(min_length=1)
    queue_id: str = Field(min_length=1)
    policy: PolicySchema
    global_forbidden_paths: tuple[str, ...] = ()
    completion_defaults: CompletionDefaultsSchema
    scope_profiles: dict[str, ScopeProfileSchema] = Field(min_length=1)
    milestones: tuple[MilestoneSchema, ...] = Field(min_length=1)
    work_items: tuple[WorkItemSchema, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def references_must_resolve(self) -> WorkQueueSchema:
        item_ids = {item.id for item in self.work_items}
        if len(item_ids) != len(self.work_items):
            raise ValueError("work item IDs must be unique")
        milestone_ids = {milestone.id for milestone in self.milestones}
        if len(milestone_ids) != len(self.milestones):
            raise ValueError("milestone IDs must be unique")

        for item in self.work_items:
            if item.milestone_id not in milestone_ids:
                raise ValueError(
                    f"{item.id} references unknown milestone {item.milestone_id}"
                )
            for dependency in item.depends_on:
                if dependency not in item_ids:
                    raise ValueError(
                        f"{item.id} depends on unknown work item {dependency}"
                    )
            if item.scope_profile not in self.scope_profiles:
                raise ValueError(
                    f"{item.id} references unknown scope profile "
                    f"{item.scope_profile}"
                )
            if item.id in item.depends_on:
                raise ValueError(f"{item.id} depends on itself")

        for milestone in self.milestones:
            for dependency in milestone.depends_on:
                if dependency not in milestone_ids:
                    raise ValueError(
                        f"{milestone.id} depends on unknown milestone {dependency}"
                    )
            gate = milestone.gate_work_item
            if gate not in item_ids:
                raise ValueError(
                    f"{milestone.id} gate work item {gate} does not exist"
                )
            gate_item = next(item for item in self.work_items if item.id == gate)
            if gate_item.milestone_id != milestone.id:
                raise ValueError(
                    f"{milestone.id} gate work item {gate} belongs to "
                    f"{gate_item.milestone_id}"
                )
        return self


# ---------------------------------------------------------------------------
# Progress state
# ---------------------------------------------------------------------------


class ProjectStateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    execution_mode: str
    controller_enforced: bool
    approved_mode: str
    human_step_approval_required: bool
    agent_questions_allowed: bool
    branch: str
    auto_continue: bool
    auto_commit: bool
    auto_push: bool


class TargetPolicySchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    broker: str
    oanda_environment: str
    live_trading: Literal["forbidden"]
    other_brokers: Literal["forbidden"]
    production_simulated_fallback: Literal["forbidden"]
    model_calls_through_gateway_only: bool
    risk_decision_required_before_order: bool
    real_observation_calendar_days: int
    ui_preset: dict[str, Any]


class QualitySummarySchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pytest: dict[str, Any]
    ruff: str
    mypy: str
    legacy_acceptance: str | None = None


class CurrentExecutionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_provider: str
    oanda_adapter_present: bool
    alpaca_adapter_present: bool
    production_simulated_fallback_present: bool
    oanda_complete_instrument_discovery: bool
    durable_oanda_transaction_cursor: bool
    complete_reconciliation: bool
    formal_observation_started: bool


class CurrentBaselineSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    captured_at: str
    commit: str
    branch: str
    statement: str
    surfaces: dict[str, Any]
    quality: QualitySummarySchema
    current_execution: CurrentExecutionSchema


class CurrentRoundSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    round_id: str | None = None
    milestone_id: str
    work_item_id: str
    phase: str
    base_commit: str | None = None
    attempt: int = 0
    last_verified_gate: str | None = None
    next_action: str | None = None


class LatestValidationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    completed_at: str
    controller_enforced: bool
    targeted_docs_acceptance: dict[str, Any]
    full_pytest: dict[str, Any]
    ruff: str
    mypy: str
    acceptance: str
    work_queue: dict[str, Any] | None = None


class KnownGapSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    severity: str
    owner_milestone: str
    summary: str
    status: Literal["OPEN", "CLOSED"]


class ObservationStateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    eligibility: str
    observation_id: str | None = None
    frozen_commit: str | None = None
    required_calendar_days: int
    elapsed_calendar_days: int
    qualified_calendar_days: int
    active_market_days: int
    no_trade_days: int
    failed_days: int
    reset_count: int
    duplicate_orders: Any = None
    unapproved_orders: Any = None
    unexplained_cross_day_diffs: Any = None
    live_or_other_broker_attempts: Any = None


class ProgressSchema(BaseModel):
    """The mutable project progress authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = SCHEMA_VERSION
    blueprint_version: str = Field(min_length=1)
    queue_id: str = Field(min_length=1)
    updated_at: str
    project: ProjectStateSchema
    target_policy: TargetPolicySchema
    current_baseline: CurrentBaselineSchema
    current: CurrentRoundSchema
    milestones: dict[str, MilestoneStatus]
    work_item_states: dict[str, ItemStatus]
    latest_validation: LatestValidationSchema
    known_gaps: tuple[KnownGapSchema, ...] = ()
    blockers: tuple[Any, ...] = ()
    observation: ObservationStateSchema
    last_completed_round: str | None = None
    last_ledger_record: str | None = None


# ---------------------------------------------------------------------------
# Round checkpoint
# ---------------------------------------------------------------------------


class LastActionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str | None = None
    command: str | None = None
    exit_code: int | None = None
    artifact: str | None = None
    artifact_sha256: str | None = None
    failure_signature: str | None = None


class CheckpointSchema(BaseModel):
    """The gitignored in-flight round checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = SCHEMA_VERSION
    round_id: str = Field(min_length=1)
    work_item_id: str = Field(min_length=1)
    phase: str
    base_commit: str
    branch: str
    attempt: int = 0
    last_action: LastActionSchema = LastActionSchema()
    last_verified_gate: str | None = None
    next_action: str | None = None
    changed_paths: tuple[str, ...] = ()
    repair_cycles: int = 0
    same_failure_count: int = 0
    recovered_from_compaction: bool = False
    updated_at: str | None = None


# ---------------------------------------------------------------------------
# Append-only ledger
# ---------------------------------------------------------------------------

LedgerRecordType = Literal["BASELINE", "ROUND", "CORRECTION"]


class CommandRecordSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: str
    exit_code: int
    summary: str | None = None
    environment: str | None = None


class LedgerRecordSchema(BaseModel):
    """One append-only line of the development ledger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: LedgerRecordType
    schema_version: int = SCHEMA_VERSION
    round_id: str = Field(min_length=1)
    work_item_id: str | None = None
    result: str
    base_commit: str | None = None
    commit_ref: str | None = None
    commit: str | None = None
    blueprint_version: str | None = None
    evidence: dict[str, Any] | None = None
    captured_at: str | None = None
    controller_enforced: bool | None = None
    changed_path_count: int | None = None
    acceptance: dict[str, str] | None = None
    commands: tuple[CommandRecordSchema, ...] | None = None
    scope_gate: str | None = None
    safety_gate: str | None = None
    documentation_gate: str | None = None
    external_evidence: str | None = None
    milestone: str | None = None
    next_work_item: str | None = None
    completed_at: str | None = None


# ---------------------------------------------------------------------------
# Resolved execution contract
# ---------------------------------------------------------------------------


class ExecutionContractSchema(BaseModel):
    """A work item merged with its profile and queue defaults.

    The resolved contract is immutable: every field a round may rely on
    (allowlist, forbidden paths, untouched modules, static commands,
    budget, acceptance, test commands, completion defaults) is present
    after resolution, so rounds never interpret queue defaults loosely.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    work_item: WorkItemSchema
    resolved_allowed_paths: tuple[str, ...]
    resolved_forbidden_paths: tuple[str, ...]
    resolved_untouched_modules: tuple[str, ...]
    static_commands: tuple[str, ...]
    completion_defaults: CompletionDefaultsSchema


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_work_queue(path: Path | str) -> WorkQueueSchema:
    """Parse and strictly validate the blueprint work queue."""
    import yaml

    queue_path = Path(path)
    raw = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{queue_path} must be a YAML mapping")
    return WorkQueueSchema.model_validate(raw)


def load_progress(path: Path | str) -> ProgressSchema:
    """Parse and strictly validate the progress authority."""
    import yaml

    progress_path = Path(path)
    raw = yaml.safe_load(progress_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{progress_path} must be a YAML mapping")
    return ProgressSchema.model_validate(raw)


def load_checkpoint(path: Path | str) -> CheckpointSchema:
    """Parse and strictly validate a round checkpoint."""
    import yaml

    checkpoint_path = Path(path)
    raw = yaml.safe_load(checkpoint_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{checkpoint_path} must be a YAML mapping")
    return CheckpointSchema.model_validate(raw)


def load_ledger(path: Path | str) -> tuple[LedgerRecordSchema, ...]:
    """Parse every NDJSON line strictly; malformed lines fail with a number."""
    ledger_path = Path(path)
    records: list[LedgerRecordSchema] = []
    for index, line in enumerate(
        ledger_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{ledger_path} line {index} is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{ledger_path} line {index} is not a JSON object")
        try:
            records.append(LedgerRecordSchema.model_validate(raw))
        except Exception as exc:  # noqa: BLE001 — wrap pydantic validation
            raise ValueError(
                f"{ledger_path} line {index} fails the ledger schema: {exc}"
            ) from exc
    return tuple(records)


def resolve_execution_contract(
    queue: WorkQueueSchema,
    work_item_id: str,
) -> ExecutionContractSchema:
    """Resolve one work item into its complete immutable execution contract.

    The resolved allowlist is the scope-profile allowlist plus any item
    additions; the resolved forbidden paths are the global queue
    forbidden paths plus any item additions; untouched modules and static
    commands come from the profile plus item additions. Completion
    defaults inherit the queue defaults unless the item overrides them.
    """
    item = next(
        (candidate for candidate in queue.work_items if candidate.id == work_item_id),
        None,
    )
    if item is None:
        raise ValueError(f"unknown work item {work_item_id}")
    profile = queue.scope_profiles[item.scope_profile]

    allowed = list(profile.allowed_paths)
    if item.allowed_paths is not None:
        allowed.extend(item.allowed_paths)

    forbidden = list(queue.global_forbidden_paths)
    if item.forbidden_paths is not None:
        forbidden.extend(item.forbidden_paths)

    untouched = list(profile.untouched_modules)
    if item.untouched_modules is not None:
        untouched.extend(item.untouched_modules)

    defaults = queue.completion_defaults
    if item.completion_gate is not None:
        gate = item.completion_gate
        defaults = CompletionDefaultsSchema(
            require_all_acceptance_pass=(
                gate.require_all_acceptance_pass
                if gate.require_all_acceptance_pass is not None
                else defaults.require_all_acceptance_pass
            ),
            require_clean_tree_after_commit=(
                gate.require_clean_tree_after_commit
                if gate.require_clean_tree_after_commit is not None
                else defaults.require_clean_tree_after_commit
            ),
            allow_waivers=(
                gate.allow_waivers
                if gate.allow_waivers is not None
                else defaults.allow_waivers
            ),
            max_same_failure_repairs=defaults.max_same_failure_repairs,
            max_total_repair_cycles=defaults.max_total_repair_cycles,
            max_external_retries=defaults.max_external_retries,
        )

    return ExecutionContractSchema(
        work_item=item,
        resolved_allowed_paths=tuple(allowed),
        resolved_forbidden_paths=tuple(forbidden),
        resolved_untouched_modules=tuple(untouched),
        static_commands=profile.static_commands,
        completion_defaults=defaults,
    )


def resolve_all_execution_contracts(
    queue: WorkQueueSchema,
) -> dict[str, ExecutionContractSchema]:
    """Resolve every work item in the queue into its immutable contract."""
    return {
        item.id: resolve_execution_contract(queue, item.id)
        for item in queue.work_items
    }


__all__ = [
    "AcceptancePredicateSchema",
    "CheckpointSchema",
    "CommandRecordSchema",
    "CompletionDefaultsSchema",
    "CompletionGateSchema",
    "DocumentationSchema",
    "EvidenceType",
    "ExecutionContractSchema",
    "ItemStatus",
    "KnownGapSchema",
    "LastActionSchema",
    "LatestValidationSchema",
    "LedgerRecordSchema",
    "LedgerRecordType",
    "MilestoneSchema",
    "MilestoneStatus",
    "ObservationStateSchema",
    "PolicySchema",
    "ProgressSchema",
    "ProjectStateSchema",
    "RiskClass",
    "ScopeProfileSchema",
    "SizeBudgetSchema",
    "TargetPolicySchema",
    "TestCommandsSchema",
    "WorkItemSchema",
    "WorkQueueSchema",
    "load_checkpoint",
    "load_ledger",
    "load_progress",
    "load_work_queue",
    "resolve_all_execution_contracts",
    "resolve_execution_contract",
]
