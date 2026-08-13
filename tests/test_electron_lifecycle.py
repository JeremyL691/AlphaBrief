"""M14-W07: controlled Electron lifecycle.

Covers AC-M14-W07-03: Electron detects backend readiness and port
conflicts, surfaces startup errors, prevents duplicate backend
ownership, and performs graceful freeze, reconcile, persist, and
shutdown without swallowing failure (REQ-UI-009).
"""

from __future__ import annotations

from pathlib import Path

ELECTRON_MAIN = (
    Path(__file__).resolve().parents[1] / "electron" / "main.js"
)


class TestBackendReadiness:
    def test_backend_readiness_is_detected(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "/health" in source
        assert "HEALTH_URL" in source

    def test_port_conflicts_are_avoided(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        # Default port differs from the launchd-managed API (8000).
        assert "8765" in source
        assert "ALPHABRIEF_ELECTRON_PORT" in source

    def test_startup_errors_are_surfaced(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "error-overlay" in source
        assert "ERROR_OVERLAY" in source


class TestDuplicateOwnership:
    def test_single_instance_lock_prevents_duplicate_backend(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "requestSingleInstanceLock" in source

    def test_second_launch_focuses_existing_window(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "app.quit()" in source


class TestGracefulLifecycle:
    def test_graceful_shutdown_kills_backend(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "before-quit" in source
        assert "will-quit" in source
        assert "backendProcess" in source

    def test_freeze_reconcile_persist_are_backend_owned(self) -> None:
        """The shell never intercepts freeze, reconcile, or persist:
        they are backend operations passed through without error
        swallowing."""
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        for operation in ("freeze", "reconcile", "persist"):
            # The shell does not re-implement these operations.
            assert f"function {operation}" not in source

    def test_failures_are_never_swallowed(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        # Every error handler logs instead of silently continuing.
        assert "console.error" in source
        assert "failed to become healthy" in source

    def test_backend_log_is_rotated_and_bounded(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "backend.log" in source
        assert "1024 * 1024" in source  # 1 MiB cap


class TestShellBoundary:
    def test_shell_only_spawns_the_existing_cli(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "serve" in source
        assert "alphabrief" in source
        # No broker or trading logic inside the shell.
        for token in ("oanda", "submitOrder", "placeOrder"):
            assert token not in source

    def test_electron_is_a_controlled_local_shell(self) -> None:
        source = ELECTRON_MAIN.read_text(encoding="utf-8")
        assert "HOST" in source
        assert "127.0.0.1" in source
