from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_required_root_files_exist() -> None:
    required_files = [
        "ALPHABRIEF_PRODUCT_BLUEPRINT.md",
        "ALPHABRIEF_DEVELOPMENT_CADENCE.md",
        "PROJECT_RULES.md",
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
        "docs/reference_notes",
        "docs/development_plans",
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
        "docs/roadmap.md",
        "docs/risk_model.md",
        "docs/rewrite_policy.md",
        "docs/model_gateway.md",
        "docs/agent_protocol.md",
        "docs/development_log.md",
        "docs/reference_notes/README.md",
        "docs/development_plans/0001-repo-scaffold.md",
    ]

    missing = [path for path in required_docs if not (ROOT / path).is_file()]

    assert missing == []


def test_live_trading_is_disabled_by_default() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "ALPHABRIEF_LIVE_TRADING_ENABLED=false" in env_example
