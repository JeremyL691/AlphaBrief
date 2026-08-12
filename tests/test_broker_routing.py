"""M01-W03 negative gates: routing and simulated composition are gone.

The routed broker adapter and the in-memory simulated fallback were
removed from production (AC-M01-W03-01). Every production entry point
resolves either a real OANDA practice adapter or a fail-closed not-ready
null adapter (AC-M01-W03-02). Test fakes live behind an explicit test
composition root — ``tests/_helpers`` and in-test classes — that
production settings can never reach (AC-M01-W03-03).
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_execution.broker.port import (
    BrokerOrderSide,
    BrokerOrderType,
    SubmitRequest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PRODUCTION_ROOTS = ("apps", "packages")
_ROUTING_MODULE = (
    "packages/alphabrief-execution/src/alphabrief_execution/broker/routing.py"
)


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    """Ensure the shared runtime cannot leak an adapter between tests."""
    from alphabrief_execution.broker.runtime import reset_broker_runtime

    reset_broker_runtime()
    yield
    reset_broker_runtime()


def _production_source_files() -> list[Path]:
    files: list[Path] = []
    for root in _PRODUCTION_ROOTS:
        folder = PROJECT_ROOT / root
        if folder.exists():
            files.extend(folder.rglob("*.py"))
    return files


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def test_routing_module_is_absent() -> None:
    """AC-M01-W03-01: the routed adapter module no longer exists."""
    assert not (PROJECT_ROOT / _ROUTING_MODULE).is_file()


def test_production_sources_do_not_import_routing() -> None:
    """AC-M01-W03-01: no production source can reach the routing module."""
    offenders: list[str] = []
    for path in _production_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree):
            if "broker.routing" in module or module.endswith(".routing"):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == []


def test_production_settings_cannot_reach_test_fakes() -> None:
    """AC-M01-W03-03: test fakes are unreachable from production settings."""
    offenders: list[str] = []
    for path in _production_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree):
            if module == "tests" or module.startswith("tests.") or module == "_helpers":
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
    assert offenders == []


# ---------------------------------------------------------------------------
# M01-W05: milestone-wide safety scan (SAFE-001..004)
# ---------------------------------------------------------------------------


def test_production_safety_gate_passes_on_checked_in_repository() -> None:
    """SAFE-001..003: the checked-in repository passes the milestone scan."""
    from alphabrief_execution.broker.safety import production_safety_violations

    assert production_safety_violations(PROJECT_ROOT) == []


def test_production_safety_gate_flags_forbidden_imports(
    tmp_path: Path,
) -> None:
    """SAFE-001: other-broker / routing / simulated imports are flagged."""
    from alphabrief_execution.broker.safety import production_safety_violations

    source = tmp_path / "apps" / "demo"
    source.mkdir(parents=True)
    (source / "bad.py").write_text(
        "import alphabrief_execution.broker.routing as routing\n",
        encoding="utf-8",
    )

    violations = production_safety_violations(tmp_path)

    assert any("routing" in violation for violation in violations)


def test_production_safety_gate_flags_non_practice_execution_host(
    tmp_path: Path,
) -> None:
    """SAFE-002: execution code must only reference the practice host."""
    from alphabrief_execution.broker.safety import production_safety_violations

    source = tmp_path / "packages" / "alphabrief-execution" / "src"
    source.mkdir(parents=True)
    (source / "bad.py").write_text(
        'BASE = "https://api-fxtrade.oanda.com"\n',
        encoding="utf-8",
    )

    violations = production_safety_violations(tmp_path)

    assert any("api-fxtrade.oanda.com" in violation for violation in violations)


def test_production_safety_gate_flags_forbidden_config_selection(
    tmp_path: Path,
) -> None:
    """SAFE-003: configuration cannot select routing or another venue."""
    from alphabrief_execution.broker.safety import production_safety_violations

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    policy_text = Path("config/paper_execution_policy.yaml").read_text(
        encoding="utf-8"
    )
    (config_dir / "paper_execution_policy.yaml").write_text(
        policy_text.replace("provider: oanda_paper", "provider: routed"),
        encoding="utf-8",
    )
    (config_dir / "oanda_paper.yaml").write_text(
        Path("config/oanda_paper.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    violations = production_safety_violations(tmp_path)

    assert any("provider" in violation for violation in violations)


def test_unconfigured_scheduler_runtime_reports_not_ready_and_cannot_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M01-W03-02: unconfigured broker runtime is not ready, cannot submit."""
    from alphabrief_cli.scheduler_commands import _build_adapter

    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_BASE_URL", raising=False)

    adapter = _build_adapter()
    health = asyncio.run(adapter.health())
    assert health.healthy is False
    assert "not configured" in health.detail
    with pytest.raises(NotImplementedError):
        asyncio.run(
            adapter.submit(
                SubmitRequest(
                    symbol="EUR_USD",
                    side=BrokerOrderSide.BUY,
                    order_type=BrokerOrderType.MARKET,
                    quantity=Decimal("1000"),
                ),
                client_order_id="unconfigured",
            )
        )


def test_configured_scheduler_runtime_is_oanda_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M01-W03-02: with credentials the runtime is the OANDA adapter."""
    from alphabrief_cli.scheduler_commands import _build_adapter
    from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter

    monkeypatch.setenv("ALPHABRIEF_OANDA_TOKEN", "test-token")
    monkeypatch.setenv("ALPHABRIEF_OANDA_ACCOUNT_ID", "test-account")

    adapter = _build_adapter()

    assert isinstance(adapter, OandaPaperAdapter)
