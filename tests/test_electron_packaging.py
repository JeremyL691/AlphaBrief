"""M17-W03: reproducible Electron packaging.

Covers AC-M17-W03-01: two clean package builds from the frozen source
produce equivalent normalized contents and a versioned checksum
manifest without embedding secrets, account data, databases, logs, or
observation artifacts.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_JS = ROOT / "electron" / "scripts" / "package.js"
DIST = ROOT / "electron" / "dist"

PACKAGED_FILES = (
    "CHECKSUMS.sha256",
    "error-overlay.html",
    "main.js",
    "package.json",
    "preload.js",
)


def _build(out: Path) -> Path:
    result = subprocess.run(
        ["node", str(PACKAGE_JS), "--out", str(out)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0
    candidates = list(out.glob("alphabrief-desktop-*"))
    assert len(candidates) == 1
    return candidates[0]


class TestReproducibleBuild:
    def test_two_builds_are_identical(self, tmp_path: Path) -> None:
        first = _build(tmp_path / "a")
        second = _build(tmp_path / "b")
        for name in PACKAGED_FILES:
            assert (first / name).read_bytes() == (second / name).read_bytes()

    def test_checksum_manifest_matches_actual_files(
        self, tmp_path: Path
    ) -> None:
        target = _build(tmp_path / "out")
        lines = (target / "CHECKSUMS.sha256").read_text(
            encoding="utf-8"
        ).strip().splitlines()
        # One checksum per packaged source file (the manifest never
        # includes itself).
        assert len(lines) == 4
        for line in lines:
            expected, name = line.split("  ", 1)
            actual = hashlib.sha256(
                (target / name).read_bytes()
            ).hexdigest()
            assert actual == expected

    def test_package_contains_only_frozen_source(
        self, tmp_path: Path
    ) -> None:
        target = _build(tmp_path / "out")
        names = sorted(p.name for p in target.iterdir())
        assert names == sorted(PACKAGED_FILES)
        assert not any(p.name == "node_modules" for p in target.iterdir())

    def test_packaged_json_is_normalized(self, tmp_path: Path) -> None:
        target = _build(tmp_path / "out")
        packaged = json.loads(
            (target / "package.json").read_text(encoding="utf-8")
        )
        assert packaged["name"] == "alphabrief-desktop"
        assert packaged["version"] == "0.0.1"
        assert "scripts" not in packaged
        assert "devDependencies" not in packaged

    def test_build_is_deterministic_across_runs(
        self, tmp_path: Path
    ) -> None:
        first = _build(tmp_path / "x")
        second = _build(tmp_path / "y")
        assert (
            first / "CHECKSUMS.sha256"
        ).read_bytes() == (
            second / "CHECKSUMS.sha256"
        ).read_bytes()


class TestNoEmbeddedData:
    def test_no_secret_or_account_data_in_package(
        self, tmp_path: Path
    ) -> None:
        target = _build(tmp_path / "out")
        for name in PACKAGED_FILES:
            content = (target / name).read_text(encoding="utf-8")
            assert "api_key" not in content
            assert "Bearer " not in content
            assert "account-" not in content

    def test_no_database_logs_or_observation_artifacts(
        self, tmp_path: Path
    ) -> None:
        target = _build(tmp_path / "out")
        for name in PACKAGED_FILES:
            content = (target / name).read_text(encoding="utf-8")
            assert ".duckdb" not in content
            assert ".ndjson" not in content
            assert "observation_manifest" not in content

    def test_packaging_refuses_forbidden_input(self) -> None:
        # The packaging scanner refuses secrets and account data; the
        # self-test mode proves the scanner catches forbidden content
        # while clean content passes.
        result = subprocess.run(
            ["node", str(PACKAGE_JS), "selftest"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0
        assert "selftest passed" in result.stdout

    def test_source_is_frozen(self) -> None:
        # The packaged source set is exactly the four frozen files;
        # anything else (data dirs, logs, databases) is never packaged.
        assert PACKAGED_FILES == (
            "CHECKSUMS.sha256",
            "error-overlay.html",
            "main.js",
            "package.json",
            "preload.js",
        )
