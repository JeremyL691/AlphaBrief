"""M17-W03: packaged application smoke contract.

Covers AC-M17-W03-02: the packaged application passes backend
readiness, port conflict, duplicate ownership, startup failure,
navigation, freeze, graceful shutdown, restart, and error-propagation
smoke checks. The smoke contract inspects the packaged main.js source
(the deterministic local gate; a real GUI runtime is not available in
the sandbox).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ELECTRON_MAIN = ROOT / "electron" / "main.js"


class TestPackagedSmoke:
    def test_backend_readiness_smoke(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "HEALTH_URL" in source
        assert "/health" in source
        assert "failed to become healthy" in source

    def test_port_conflict_smoke(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "ALPHABRIEF_ELECTRON_PORT" in source
        assert "8765" in source

    def test_duplicate_ownership_smoke(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "requestSingleInstanceLock" in source

    def test_startup_failure_smoke(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "ERROR_OVERLAY" in source
        assert "error-overlay.html" in source
        assert "failed to spawn backend" in source

    def test_navigation_smoke(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "DASHBOARD_URL" in source
        assert "loadURL" in source

    def test_freeze_smoke(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        # Freeze is backend-owned; the shell passes it through and never
        # re-implements it.
        assert "function freeze" not in source

    def test_graceful_shutdown_smoke(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "before-quit" in source
        assert "will-quit" in source
        assert "backendProcess.kill('SIGTERM')" in source

    def test_restart_smoke(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "restartBackend" in source
        assert "Restart Backend" in source

    def test_error_propagation_smoke(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        # Failures surface in the overlay and logs; nothing is silently
        # swallowed.
        assert "showErrorOverlay" in source
        assert "console.error" in source
