import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_required_root_files_exist() -> None:
    required_files = [
        "ALPHABRIEF_PRODUCT_BLUEPRINT.md",
        "AGENTS.md",
        "README.md",
        "pyproject.toml",
        ".env.example",
    ]

    missing = [path for path in required_files if not (ROOT / path).is_file()]

    assert missing == []


def test_required_directories_exist() -> None:
    required_directories = [
        "apps",
        "packages",
        "strategies",
        "tests",
        "scripts",
        "reports",
        "notebooks",
    ]

    missing = [path for path in required_directories if not (ROOT / path).is_dir()]

    assert missing == []


def test_reference_sources_are_isolated_under_expected_name() -> None:
    assert not (ROOT / "Source projects").exists()

    reference_root = ROOT / "_reference_sources"
    if reference_root.exists():
        expected_reference_projects = {
            "QuantDinger",
            "TradingGym",
            "tradingagents",
        }
        actual_reference_projects = {
            path.name for path in reference_root.iterdir() if path.is_dir()
        }

        assert expected_reference_projects.issubset(actual_reference_projects)


def test_reference_sources_are_not_committed_by_default() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "_reference_sources/" in gitignore


def test_required_docs_exist() -> None:
    required_docs = [
        "docs/architecture.md",
        "docs/work_items.yaml",
        "docs/progress.yaml",
        "docs/acceptance.md",
        "docs/oanda_30_day_runbook.md",
        "docs/autonomous_loop.md",
        "docs/development_ledger.ndjson",
    ]

    missing = [path for path in required_docs if not (ROOT / path).is_file()]

    assert missing == []


def test_obsolete_development_documents_are_absent() -> None:
    obsolete = [
        "ALPHABRIEF_DEVELOPMENT_CADENCE.md",
        "PROJECT_RULES.md",
        "FINAL_ACCEPTANCE_REPORT.md",
        "docs/roadmap.md",
        "docs/development_log.md",
        "docs/risk_model.md",
        "docs/model_gateway.md",
        "docs/agent_protocol.md",
        "docs/backtest_standard.md",
        "docs/strategy_spec.md",
        "docs/rewrite_policy.md",
        "docs/paper_broker_setup.md",
        "docs/development_plans",
        "docs/reference_notes",
        "electron/README.md",
        "reports/pre_flight_check_2026-06-26.md",
        ".hermes/phase8-plan.md",
        ".hermes/claude_prompt_oanda.txt",
        ".hermes/run_oanda_adapter.sh",
        ".mimocode/skills/continue-round",
        ".mimocode/skills/plan-next-round",
        ".omo/plans",
        ".zcode/plans",
    ]

    present = [path for path in obsolete if (ROOT / path).exists()]

    assert present == []


def test_live_trading_is_disabled_by_default() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "ALPHABRIEF_LIVE_TRADING_ENABLED=false" in env_example


def test_authoritative_machine_state_files_parse() -> None:
    work_queue = yaml.safe_load(
        (ROOT / "docs/work_items.yaml").read_text(encoding="utf-8")
    )
    progress = yaml.safe_load(
        (ROOT / "docs/progress.yaml").read_text(encoding="utf-8")
    )
    ledger_lines = [
        line
        for line in (ROOT / "docs/development_ledger.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    assert work_queue["schema_version"] == 1
    assert progress["schema_version"] == 1
    assert ledger_lines
    assert all(isinstance(json.loads(line), dict) for line in ledger_lines)


def test_authoritative_markdown_local_links_resolve() -> None:
    markdown_files = [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "ALPHABRIEF_PRODUCT_BLUEPRINT.md",
        ROOT / "docs/architecture.md",
        ROOT / "docs/acceptance.md",
        ROOT / "docs/oanda_30_day_runbook.md",
        ROOT / "docs/autonomous_loop.md",
    ]
    missing: list[str] = []
    for document in markdown_files:
        for raw_target in re.findall(
            r"(?<!!)\[[^\]]+\]\(([^)]+)\)",
            document.read_text(encoding="utf-8"),
        ):
            target = raw_target.strip().split("#", maxsplit=1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (document.parent / target).resolve().exists():
                missing.append(f"{document.relative_to(ROOT)} -> {raw_target}")

    assert missing == []


def test_machine_work_queue_is_structurally_closed() -> None:
    queue = yaml.safe_load(
        (ROOT / "docs/work_items.yaml").read_text(encoding="utf-8")
    )
    milestones = queue["milestones"]
    work_items = queue["work_items"]
    milestone_ids = [entry["id"] for entry in milestones]
    work_item_ids = [entry["id"] for entry in work_items]
    acceptance_ids = [
        acceptance["id"]
        for entry in work_items
        for acceptance in entry["acceptance"]
    ]
    blueprint_requirements = set(
        re.findall(
            r"REQ-[A-Z]+-[0-9]{3}",
            (ROOT / "ALPHABRIEF_PRODUCT_BLUEPRINT.md").read_text(encoding="utf-8"),
        )
    )
    queue_requirements = {
        requirement
        for entry in work_items
        for requirement in entry["requirement_ids"]
    }
    scope_profiles = set(queue["scope_profiles"])

    assert len(milestone_ids) == len(set(milestone_ids)) == 18
    assert len(work_item_ids) == len(set(work_item_ids))
    assert len(acceptance_ids) == len(set(acceptance_ids))
    assert {entry["milestone_id"] for entry in work_items} == set(milestone_ids)
    assert {entry["gate_work_item"] for entry in milestones}.issubset(work_item_ids)
    assert {
        dependency
        for entry in work_items
        for dependency in entry.get("depends_on", [])
    }.issubset(work_item_ids)
    assert queue_requirements == blueprint_requirements
    assert all(entry["scope_profile"] in scope_profiles for entry in work_items)
    assert all(len(entry["acceptance"]) >= 3 for entry in work_items)
    assert all(
        set(acceptance) == {"id", "predicate", "evidence_type"}
        for entry in work_items
        for acceptance in entry["acceptance"]
    )
    assert all(
        acceptance["evidence_type"]
        in {"automated_test", "static_gate", "practice_e2e", "observation"}
        for entry in work_items
        for acceptance in entry["acceptance"]
    )
    assert all(
        isinstance(acceptance["predicate"], str)
        and len(acceptance["predicate"]) >= 40
        for entry in work_items
        for acceptance in entry["acceptance"]
    )
    assert all(
        set(entry["test_commands"])
        == {"targeted", "integration", "static", "regression", "runtime"}
        for entry in work_items
    )

    unresolved = {
        entry["id"]: set(entry.get("depends_on", [])) for entry in work_items
    }
    resolved: set[str] = set()
    while unresolved:
        ready = sorted(
            item_id
            for item_id, dependencies in unresolved.items()
            if dependencies.issubset(resolved)
        )
        assert ready, f"cyclic work-item dependencies: {sorted(unresolved)}"
        for item_id in ready:
            resolved.add(item_id)
            del unresolved[item_id]


def test_zero_intervention_contract_is_machine_readable() -> None:
    queue = yaml.safe_load(
        (ROOT / "docs/work_items.yaml").read_text(encoding="utf-8")
    )
    progress = yaml.safe_load(
        (ROOT / "docs/progress.yaml").read_text(encoding="utf-8")
    )

    assert queue["policy"]["auto_continue"] is True
    assert queue["policy"]["allow_waivers"] is False
    assert queue["policy"]["engineering_code_dependency_states"] == [
        "DONE",
        "CODE_COMPLETE",
    ]
    assert queue["policy"]["observation_dependency_states"] == ["DONE"]
    assert progress["project"]["human_step_approval_required"] is False
    assert progress["project"]["agent_questions_allowed"] is False
