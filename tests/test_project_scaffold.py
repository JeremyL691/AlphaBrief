"""Repository scaffold contract for the v1.0 documentation set.

The single source of truth is ``AGENTS.md`` plus the three documents it
names: ``docs/PROJECT_GUIDE.md`` (spec), ``docs/STATUS.md`` (mutable
state) and ``docs/AGENT_PROMPT.md`` (startup prompt). Old process
documents, milestone plans and development logs were deleted; this test
keeps them deleted and keeps local markdown links resolvable.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Documents that must exist and stay authoritative.
REQUIRED_DOCS = (
    "AGENTS.md",
    "docs/PROJECT_GUIDE.md",
    "docs/STATUS.md",
    "docs/AGENT_PROMPT.md",
)

#: Documents deleted on 2026-09-30 (PROJECT_GUIDE appendix F) plus the
#: earlier ceremony documents. They must not come back.
OBSOLETE_DOCS = (
    "ALPHABRIEF_PRODUCT_BLUEPRINT.md",
    "ALPHABRIEF_DEVELOPMENT_CADENCE.md",
    "PROJECT_RULES.md",
    "FINAL_ACCEPTANCE_REPORT.md",
    "docs/architecture.md",
    "docs/acceptance.md",
    "docs/autonomous_loop.md",
    "docs/oanda_30_day_runbook.md",
    "docs/progress.yaml",
    "docs/work_items.yaml",
    "docs/development_ledger.ndjson",
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
    "reports/pre_flight_check_2026-06-26.md",
    ".hermes",
    ".zcode/plans",
)

#: ``docs/`` may contain only these entries (plus README screenshots).
ALLOWED_DOCS_ENTRIES = frozenset(
    {
        "PROJECT_GUIDE.md",
        "STATUS.md",
        "AGENT_PROMPT.md",
        "images",
    }
)

STATUS_VALUES = frozenset(
    {"READY", "IN_PROGRESS", "WAITING_OWNER_LOGIN", "BLOCKED", "SOAKING", "RELEASED"}
)

STAGE_VALUES = frozenset(f"S{n}" for n in range(12))


def _markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "AGENTS.md"]
    files.extend(
        ROOT / "docs" / name
        for name in ("PROJECT_GUIDE.md", "STATUS.md", "AGENT_PROMPT.md")
    )
    return [path for path in files if path.is_file()]


def test_required_root_files_exist() -> None:
    required_files = [
        "AGENTS.md",
        "README.md",
        "LICENSE",
        "pyproject.toml",
        ".env.example",
    ]

    missing = [path for path in required_files if not (ROOT / path).is_file()]

    assert missing == []


def test_required_directories_exist() -> None:
    required_directories = [
        "apps/api",
        "apps/cli",
        "config",
        "docs",
        "electron",
        "packages",
        "scripts",
        "tests",
    ]

    missing = [path for path in required_directories if not (ROOT / path).is_dir()]

    assert missing == []


def test_required_docs_exist() -> None:
    missing = [path for path in REQUIRED_DOCS if not (ROOT / path).is_file()]

    assert missing == []


def test_obsolete_documents_are_absent() -> None:
    present = [path for path in OBSOLETE_DOCS if (ROOT / path).exists()]

    assert present == []


def test_docs_directory_contains_only_the_authoritative_set() -> None:
    """Progress goes into STATUS and specs into PROJECT_GUIDE.

    No new roadmap, phase plan, design note, acceptance report or
    development log may be added under ``docs/``.
    """
    extra = sorted(
        path.name
        for path in (ROOT / "docs").iterdir()
        if path.name not in ALLOWED_DOCS_ENTRIES
    )

    assert extra == []


def test_deleted_packages_and_placeholder_dirs_are_absent() -> None:
    removed_paths = [
        "packages/alphabrief-acceptance",
        "packages/alphabrief-research",
        "apps/api/src/alphabrief_api/dashboard",
        "notebooks",
        "strategies",
        "scripts/deployment",
    ]

    present = [path for path in removed_paths if (ROOT / path).exists()]

    assert present == []


def test_authoritative_markdown_local_links_resolve() -> None:
    missing: list[str] = []
    for document in _markdown_files():
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


def test_status_declares_one_current_stage_and_status() -> None:
    status = (ROOT / "docs/STATUS.md").read_text(encoding="utf-8")
    stage_matches = re.findall(r"^\| 当前阶段 \| \*\*(S\d+) ", status, re.MULTILINE)
    status_matches = re.findall(r"^\| 状态 \| `([A-Z_]+)` \|$", status, re.MULTILINE)

    assert len(stage_matches) == 1
    assert len(status_matches) == 1
    assert stage_matches[0] in STAGE_VALUES
    assert status_matches[0] in STATUS_VALUES


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
