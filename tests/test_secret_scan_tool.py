"""Tests for ``scripts/secret_scan.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "secret_scan", REPO_ROOT / "scripts" / "secret_scan.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["secret_scan"] = module
    spec.loader.exec_module(module)
    return module


scanner = _load_scanner()


class TestPatterns:
    def test_account_id_shape_is_detected(self) -> None:
        findings = scanner.scan_text(
            'ACCOUNT = "221-004-7654321-009"\n', location="sample.py"
        )

        assert [finding.kind for finding in findings] == ["oanda_account_id"]

    def test_openai_key_shape_is_detected(self) -> None:
        findings = scanner.scan_text(
            'key = "sk-abcdefghijklmnopqrstuvwxyz012345"\n', location="sample.py"
        )

        assert [finding.kind for finding in findings] == ["openai_api_key"]

    def test_oanda_token_shape_is_detected(self) -> None:
        token = "a" * 32 + "-" + "b" * 32
        findings = scanner.scan_text(f'TOKEN = "{token}"\n', location="sample.py")

        assert [finding.kind for finding in findings] == ["oanda_token"]

    def test_unknown_credential_assignment_is_detected(self) -> None:
        findings = scanner.scan_text(
            'api_key = "sup3r-s3cret-value"\n', location="sample.py"
        )

        assert [finding.kind for finding in findings] == ["credential_assignment"]

    def test_whitelisted_fixture_is_ignored(self) -> None:
        findings = scanner.scan_text(
            'ACCOUNT_ID = "101-004-1234567-001"\n', location="sample.py"
        )

        assert findings == []

    def test_finding_excerpt_is_redacted(self) -> None:
        findings = scanner.scan_text(
            'password = "hunter2hunter2"\n', location="sample.py"
        )

        assert len(findings) == 1
        assert findings[0].excerpt == "hu***r2"
        assert "hunter2hunter2" not in findings[0].excerpt
        assert len(findings[0].excerpt) < len("hunter2hunter2")


class TestRealCredentialComparison:
    def test_real_value_in_text_is_reported(self) -> None:
        findings = scanner.scan_real_credentials(
            "token=REAL-VALUE-1234\n",
            location="sample.py",
            secrets=["REAL-VALUE-1234"],
        )

        assert [finding.kind for finding in findings] == ["real_credential_leak"]

    def test_short_values_are_not_compared(self) -> None:
        findings = scanner.scan_real_credentials(
            "x=abc\n", location="sample.py", secrets=["abc"]
        )

        assert findings == []


class TestRepositoryState:
    def test_tracked_files_are_clean(self) -> None:
        assert scanner.scan_tracked(scanner.read_local_secrets()) == []

    def test_scanner_covers_the_repository(self) -> None:
        tracked = scanner.tracked_files()

        assert tracked
        names = {path.name for path in tracked}
        assert "AGENTS.md" in names
        assert "pyproject.toml" in names
        assert all("_reference_sources" not in path.parts for path in tracked)
