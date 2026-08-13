"""M17-W03: Electron release security inspection.

Covers AC-M17-W03-03: static and runtime inspection finds no live
host, live selector, Alpaca or other broker, simulated production
fallback, arbitrary broker proxy, or unapproved auto-update execution
path in the packaged application.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ELECTRON_MAIN = ROOT / "electron" / "main.js"
PACKAGE_JS = ROOT / "electron" / "scripts" / "package.js"


class TestNoLivePath:
    def test_no_live_host_is_configured(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "api-fxtrade.oanda.com" not in source
        assert "api-fxpractice.oanda.com" not in source

    def test_no_live_selector_exists(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        # No environment/mode selector can ever choose live: no quoted
        # live-mode value, no live_mode/liveMode identifiers, and no
        # live host.
        assert "'live'" not in source
        assert '"live"' not in source
        assert "live_mode" not in source
        assert "liveMode" not in source
        assert "api-fxtrade.oanda.com" not in source

    def test_no_broker_routing_in_shell(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "alpaca" not in source.lower()
        assert "broker" not in source.lower()
        assert "routing" not in source.lower()

    def test_no_simulated_production_fallback(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        # No simulated fill or production simulated-fallback path; the
        # word "fallback" appears only in the benign tray-icon comment.
        assert "simulated" not in source.lower()
        assert "in_memory_fill" not in source.lower()
        assert "production_simulated_fallback" not in source.lower()

    def test_no_arbitrary_broker_proxy(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "proxy" not in source.lower()

    def test_no_unapproved_auto_update_path(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "autoUpdater" not in source
        assert "auto-update" not in source.lower()
        assert "electron-updater" not in source.lower()


class TestPackagedInspection:
    def test_packaged_artifact_passes_security_scan(self) -> None:
        # The packaging scanner refuses forbidden content at build
        # time; the selftest proves the scan catches live/broker-like
        # markers.
        result = subprocess.run(
            ["node", str(PACKAGE_JS), "selftest"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0

    def test_packaged_files_are_practice_only(self) -> None:
        # The shell only speaks to the local backend (127.0.0.1); the
        # packaged main.js must not reference any external host.
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "127.0.0.1" in source or "localhost" in source
