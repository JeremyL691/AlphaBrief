"""Project-level acceptance verification for AlphaBrief.

The verifier is read-only. It inspects documented project invariants and
executes small deterministic boundary checks, but it never calls brokers,
models, provider SDKs, external services, or live endpoints.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from typing import Literal

from alphabrief_core import (
    Bar,
    OrderIntent,
    load_paper_execution_policy,
    load_settings,
)
from alphabrief_execution import ENV_KEY as ALPACA_ENV_KEY
from alphabrief_execution import ENV_SECRET as ALPACA_ENV_SECRET
from alphabrief_execution import load_alpaca_paper_config
from alphabrief_models import (
    DeterministicKronosRuntime,
    KronosForecastAdapter,
    KronosForecastReport,
    KronosForecastRequest,
    ModelGateway,
    build_kronos_model_request,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from pydantic import BaseModel, ConfigDict, Field

AcceptanceStatus = Literal["passed", "failed", "warning"]

_REQUIRED_DOCS = (
    "ALPHABRIEF_PRODUCT_BLUEPRINT.md",
    "ALPHABRIEF_DEVELOPMENT_CADENCE.md",
    "PROJECT_RULES.md",
    "docs/architecture.md",
    "docs/roadmap.md",
    "docs/risk_model.md",
    "docs/rewrite_policy.md",
    "docs/model_gateway.md",
    "FINAL_ACCEPTANCE_REPORT.md",
    "README.md",
)

_RUNTIME_MODULES = (
    "alphabrief_core",
    "alphabrief_data",
    "alphabrief_strategy",
    "alphabrief_backtest",
    "alphabrief_models",
    "alphabrief_research",
    "alphabrief_risk",
    "alphabrief_execution",
    "alphabrief_gym",
    "alphabrief_review",
    "alphabrief_news",
    "alphabrief_acceptance",
)

_PROVIDER_SDK_DENYLIST = frozenset(
    {
        "openai",
        "anthropic",
        "google",
        "alpaca",
        "alpaca_trade_api",
        "yfinance",
        "binance",
    }
)


class AcceptanceCheck(BaseModel):
    """One acceptance check result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: AcceptanceStatus
    evidence: str = Field(min_length=1)
    detail: str | None = None


class AcceptanceReport(BaseModel):
    """Project-level acceptance report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: datetime
    project_root: str
    passed: bool
    total: int
    passed_count: int
    failed_count: int
    warning_count: int
    checks: list[AcceptanceCheck] = Field(min_length=1)


def build_acceptance_report(project_root: Path | str | None = None) -> AcceptanceReport:
    """Run all project-level acceptance checks."""

    root = Path.cwd() if project_root is None else Path(project_root)
    root = root.resolve()
    return _build_report(root, scope="full")


def build_preflight_report(
    project_root: Path | str | None = None,
    *,
    scope: str = "full",
) -> AcceptanceReport:
    """Run a scoped subset of acceptance checks.

    Supported scopes:

    - ``"full"`` (default): identical to :func:`build_acceptance_report`.
    - ``"paper"``: only the paper-broker pre-flight check
      (``paper.preflight``).
    """

    root = Path.cwd() if project_root is None else Path(project_root)
    root = root.resolve()
    return _build_report(root, scope=scope)


def _build_report(root: Path, *, scope: str) -> AcceptanceReport:
    if scope == "paper":
        check_factories: tuple[Callable[..., AcceptanceCheck], ...] = (
            _paper_preflight_ready,
        )
    elif scope == "full":
        check_factories = (
            _required_docs_present,
            _runtime_modules_importable,
            _default_settings_are_paper_only,
            _paper_execution_policy_is_locked,
            _risk_gate_rejects_live_trading,
            _kronos_forecast_is_advisory,
            _runtime_code_does_not_import_reference_sources,
            _runtime_code_does_not_import_provider_sdks,
            _final_report_mentions_latest_phase,
            _tooling_configured,
            _paper_preflight_ready,
        )
    else:
        raise ValueError(
            f"unknown acceptance scope: {scope!r} (expected 'full' or 'paper')"
        )

    checks: list[AcceptanceCheck] = []
    for factory in check_factories:
        if inspect.signature(factory).parameters:
            checks.append(factory(root))
        else:
            checks.append(factory())
    failed_count = sum(1 for check in checks if check.status == "failed")
    warning_count = sum(1 for check in checks if check.status == "warning")
    passed_count = sum(1 for check in checks if check.status == "passed")
    return AcceptanceReport(
        generated_at=datetime.now(UTC),
        project_root=str(root),
        passed=failed_count == 0,
        total=len(checks),
        passed_count=passed_count,
        failed_count=failed_count,
        warning_count=warning_count,
        checks=checks,
    )


def _check(
    *,
    check_id: str,
    title: str,
    run: Callable[[], tuple[AcceptanceStatus, str, str | None]],
) -> AcceptanceCheck:
    try:
        status, evidence, detail = run()
    except Exception as exc:
        return AcceptanceCheck(
            check_id=check_id,
            title=title,
            status="failed",
            evidence=f"{type(exc).__name__}: {exc}",
            detail=None,
        )
    return AcceptanceCheck(
        check_id=check_id,
        title=title,
        status=status,
        evidence=evidence,
        detail=detail,
    )


def _required_docs_present(root: Path) -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        missing = [path for path in _REQUIRED_DOCS if not (root / path).is_file()]
        if missing:
            return "failed", "missing required project documents", ", ".join(missing)
        return "passed", f"{len(_REQUIRED_DOCS)} required documents present", None

    return _check(
        check_id="docs.required",
        title="Required project documents are present",
        run=run,
    )


def _runtime_modules_importable() -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        imported: list[str] = []
        for module_name in _RUNTIME_MODULES:
            import_module(module_name)
            imported.append(module_name)
        return "passed", f"{len(imported)} runtime modules importable", None

    return _check(
        check_id="runtime.imports",
        title="Runtime package surfaces are importable",
        run=run,
    )


def _default_settings_are_paper_only() -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        settings = load_settings({})
        if settings.live_trading_enabled:
            return "failed", "default live trading is enabled", None
        return "passed", "default settings keep live trading disabled", None

    return _check(
        check_id="config.paper_only_default",
        title="Default settings are paper-only",
        run=run,
    )


def _paper_execution_policy_is_locked(root: Path) -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        policy = load_paper_execution_policy(
            root / "config/paper_execution_policy.yaml"
        )
        if policy.mode != "paper":
            return "failed", f"execution policy mode is {policy.mode}", None
        if policy.max_total_exposure < policy.max_order_notional:
            return "failed", "total exposure cap is below order cap", None
        if policy.max_order_notional <= 0 or policy.max_total_exposure <= 0:
            return "failed", "exposure caps must be positive", None
        return (
            "passed",
            "paper policy is locked: paper mode with sane exposure caps "
            f"(automated_execution={policy.automated_execution})",
            None,
        )

    return _check(
        check_id="execution.paper_policy",
        title="Paper execution policy stays paper-only",
        run=run,
    )


def _risk_gate_rejects_live_trading() -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        intent = OrderIntent(
            intent_id="acceptance_intent",
            source="manual",
            symbol="SPY",
            side="buy",
            order_type="market",
            quantity=Decimal("1"),
            rationale="acceptance verification",
            created_at=datetime(2026, 6, 26, 12, tzinfo=UTC),
        )
        gate = RiskGate(
            RiskLimitConfig(
                live_trading_enabled=True,
                symbol_allowlist=frozenset({"SPY"}),
                require_data_quality_passed=False,
            ),
            decision_id_factory=lambda: "acceptance_risk_decision",
        )
        decision = gate.evaluate(intent, estimated_price=Decimal("100"))
        if decision.approved or "live_trading_locked" not in decision.risk_tags:
            return (
                "failed",
                "RiskGate did not reject a live-trading configuration",
                str(decision.model_dump()),
            )
        return "passed", "RiskGate rejects live_trading_enabled=True", None

    return _check(
        check_id="risk.live_lock",
        title="RiskGate locks live trading",
        run=run,
    )


def _kronos_forecast_is_advisory() -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        request = KronosForecastRequest(
            request_id="acceptance_kronos",
            symbol="SPY",
            bars=_sample_bars(),
            prediction_length=2,
        )
        gateway = ModelGateway(
            [
                KronosForecastAdapter(
                    runtime=DeterministicKronosRuntime(
                        clock=lambda: datetime(2026, 6, 26, 12, tzinfo=UTC),
                        forecast_id_factory=lambda: "acceptance_forecast",
                    )
                )
            ]
        )
        result = gateway.invoke(build_kronos_model_request(request))
        if result.response is None:
            return "failed", "Kronos gateway call returned no response", None
        report = KronosForecastReport.model_validate(
            result.response.structured_output
        )
        if not report.advisory_only:
            return "failed", "Kronos forecast is not advisory_only", None
        return "passed", "Kronos forecasts are structured and advisory-only", None

    return _check(
        check_id="models.kronos_advisory",
        title="Kronos forecasts remain advisory",
        run=run,
    )


def _runtime_code_does_not_import_reference_sources(root: Path) -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        offenders = _scan_imports(
            root,
            source_roots=("apps", "packages"),
            denied_modules=("_reference_sources",),
        )
        if offenders:
            return "failed", "runtime imports reference sources", "\n".join(offenders)
        return "passed", "no runtime imports from _reference_sources", None

    return _check(
        check_id="safety.reference_isolation",
        title="Reference sources are isolated",
        run=run,
    )


def _runtime_code_does_not_import_provider_sdks(root: Path) -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        offenders = _scan_imports(
            root,
            source_roots=("apps", "packages"),
            denied_modules=tuple(_PROVIDER_SDK_DENYLIST),
        )
        if offenders:
            return (
                "failed",
                "runtime imports provider SDKs directly",
                "\n".join(offenders),
            )
        return "passed", "no direct provider SDK imports in runtime code", None

    return _check(
        check_id="safety.provider_sdk_imports",
        title="Provider SDK imports stay out of runtime business code",
        run=run,
    )


def _final_report_mentions_latest_phase(root: Path) -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        final_report = (root / "FINAL_ACCEPTANCE_REPORT.md").read_text(
            encoding="utf-8"
        )
        roadmap = (root / "docs/roadmap.md").read_text(encoding="utf-8")
        required_phrases = (
            "Phase 23",
            "Kronos",
            "acceptance verifier",
        )
        missing = [
            phrase
            for phrase in required_phrases
            if phrase not in final_report and phrase not in roadmap
        ]
        if missing:
            return (
                "failed",
                "latest acceptance evidence is not documented",
                ", ".join(missing),
            )
        return "passed", "latest phase and quality evidence are documented", None

    return _check(
        check_id="docs.final_report_current",
        title="Final acceptance evidence is current",
        run=run,
    )


def _tooling_configured(root: Path) -> AcceptanceCheck:
    def run() -> tuple[AcceptanceStatus, str, str | None]:
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        required = (
            "[tool.pytest.ini_options]",
            "[tool.ruff]",
            "[tool.mypy]",
            '"_reference_sources"',
            "packages/alphabrief-acceptance/src",
        )
        missing = [token for token in required if token not in pyproject]
        if missing:
            return (
                "failed",
                "quality tooling config missing entries",
                ", ".join(missing),
            )
        return (
            "passed",
            "pytest, ruff, mypy, and acceptance package are configured",
            None,
        )

    return _check(
        check_id="quality.tooling_configured",
        title="Quality tooling is configured",
        run=run,
    )


def _paper_preflight_ready(root: Path) -> AcceptanceCheck:
    """Confirm everything the paper-broker runbook needs is in place."""

    def run() -> tuple[AcceptanceStatus, str, str | None]:
        problems: list[str] = []

        runbook = root / "docs/paper_broker_setup.md"
        if not runbook.is_file():
            problems.append("docs/paper_broker_setup.md is missing")

        env_example = root / ".env.example"
        if not env_example.is_file():
            problems.append(".env.example is missing")
        else:
            env_text = env_example.read_text(encoding="utf-8")
            if ALPACA_ENV_KEY not in env_text:
                problems.append(
                    f".env.example does not document {ALPACA_ENV_KEY}"
                )
            if ALPACA_ENV_SECRET not in env_text:
                problems.append(
                    f".env.example does not document {ALPACA_ENV_SECRET}"
                )

        try:
            policy = load_paper_execution_policy(
                root / "config/paper_execution_policy.yaml"
            )
            if policy.mode != "paper":
                problems.append(
                    f"paper_execution_policy.mode is {policy.mode!r}"
                )
            if policy.max_total_exposure < policy.max_order_notional:
                problems.append(
                    "paper_execution_policy.max_total_exposure is below "
                    "max_order_notional"
                )
        except FileNotFoundError as exc:
            problems.append(f"paper_execution_policy.yaml missing: {exc}")
        except (ValueError, TypeError) as exc:
            problems.append(f"paper_execution_policy.yaml invalid: {exc}")

        try:
            load_alpaca_paper_config(root / "config/alpaca_paper.yaml")
        except FileNotFoundError as exc:
            problems.append(f"alpaca_paper.yaml missing: {exc}")
        except (ValueError, TypeError) as exc:
            problems.append(f"alpaca_paper.yaml invalid: {exc}")

        if problems:
            return (
                "failed",
                "paper-broker pre-flight is not ready",
                "; ".join(problems),
            )
        return (
            "passed",
            "runbook, env wiring, and broker configs are ready",
            None,
        )

    return _check(
        check_id="paper.preflight",
        title="Paper-broker pre-flight is ready",
        run=run,
    )


def _sample_bars() -> list[Bar]:
    start = datetime(2026, 6, 24, 13, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="SPY",
            timestamp=start + timedelta(days=index),
            open=Decimal(str(100 + index)),
            high=Decimal(str(101 + index)),
            low=Decimal(str(99 + index)),
            close=Decimal(str(100 + index)),
            volume=Decimal("1000"),
            source="acceptance",
            data_version="acceptance_v1",
        )
        for index in range(3)
    ]


def _scan_imports(
    root: Path,
    *,
    source_roots: Iterable[str],
    denied_modules: tuple[str, ...],
) -> list[str]:
    offenders: list[str] = []
    denied = frozenset(denied_modules)
    for source_root in source_roots:
        folder = root / source_root
        if not folder.exists():
            continue
        for path in folder.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                offenders.append(f"{path.relative_to(root)}: syntax error: {exc}")
                continue
            for node in ast.walk(tree):
                module_names = _imported_modules(node)
                for module_name in module_names:
                    top_level = module_name.split(".", 1)[0]
                    if module_name in denied or top_level in denied:
                        offenders.append(
                            f"{path.relative_to(root)} imports {module_name}"
                        )
    return sorted(set(offenders))


def _imported_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return [node.module]
    return []
