"""Static boundary gate: production model calls resolve ModelGateway only.

Covers AC-M10-W01-01: production research, brief, committee, and trading
paths resolve the same ``ModelGateway`` boundary and contain no direct
provider SDK call. This is a source-scan test: it inspects the checked-in
runtime modules, not runtime behavior.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Modules that implement the production research/brief/committee/trading
# model paths. Every one must reference the ModelGateway boundary
# (directly or through the shared provider factory) and must never import
# a provider SDK.
_MODEL_PATH_MODULES = (
    "apps/api/src/alphabrief_api/routes/research.py",
    "apps/api/src/alphabrief_api/routes/brief.py",
    "apps/api/src/alphabrief_api/routes/models.py",
    "apps/api/src/alphabrief_api/routes/ai_trading.py",
    "apps/cli/src/alphabrief_cli/model_commands.py",
    "apps/cli/src/alphabrief_cli/brief_commands.py",
    "packages/alphabrief-trader/src/alphabrief_trader/committee.py",
    "packages/alphabrief-trader/src/alphabrief_trader/daily_cycle.py",
    "packages/alphabrief-trader/src/alphabrief_trader/model_factory.py",
    "packages/alphabrief-research/src/alphabrief_research/orchestrator.py",
)

# Provider SDK modules that must never be imported by runtime business
# code (mirrors the acceptance verifier's denylist; broker SDKs are
# covered by the verifier's global scan and are omitted here).
_PROVIDER_SDK_MODULES = frozenset(
    {
        "openai",
        "anthropic",
        "google",
    }
)


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
        and ".venv" not in path.parts
        and "_reference_sources" not in path.parts
    )


def _imported_module(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("import "):
        return stripped.split()[1].split(".")[0]
    if stripped.startswith("from "):
        return stripped.split()[1].split(".")[0]
    return None


def _find_provider_sdk_imports(paths: list[Path]) -> list[str]:
    offenders: list[str] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            module = _imported_module(line)
            if module in _PROVIDER_SDK_MODULES:
                offenders.append(f"{path.relative_to(_REPO_ROOT)}: {line.strip()}")
    return offenders


def test_runtime_code_has_no_direct_provider_sdk_imports() -> None:
    source_roots = [
        _REPO_ROOT / "apps",
        _REPO_ROOT / "packages",
    ]
    paths: list[Path] = []
    for root in source_roots:
        if root.is_dir():
            paths.extend(_iter_python_files(root))
    offenders = _find_provider_sdk_imports(paths)
    assert offenders == [], (
        "runtime code imports provider SDKs directly:\n" + "\n".join(offenders)
    )


def test_model_path_modules_resolve_the_model_gateway_boundary() -> None:
    # A module may reference ModelGateway directly or resolve it through
    # the single production composition point (the AI trading provider
    # factory). Either way the call boundary is the gateway; providers
    # are never constructed ad hoc.
    boundary_markers = (
        "ModelGateway",
        "build_ai_trading_committee",
        "build_ai_trading_provider",
    )
    missing: list[str] = []
    for relative in _MODEL_PATH_MODULES:
        path = _REPO_ROOT / relative
        text = path.read_text(encoding="utf-8")
        if not any(marker in text for marker in boundary_markers):
            missing.append(relative)
    assert missing == [], (
        "production model-path modules do not resolve the ModelGateway "
        "boundary or the shared provider factory: "
        + ", ".join(missing)
    )


def test_model_path_modules_have_no_direct_provider_sdk_imports() -> None:
    paths = [_REPO_ROOT / relative for relative in _MODEL_PATH_MODULES]
    offenders = _find_provider_sdk_imports(paths)
    assert offenders == [], (
        "production model-path modules import provider SDKs directly:\n"
        + "\n".join(offenders)
    )
