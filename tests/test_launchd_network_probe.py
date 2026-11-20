"""LaunchAgent startup checks reachability, not credentials or trading readiness."""

from __future__ import annotations

import errno
import io
import logging
import plistlib
import signal
import socket
import ssl
import subprocess
from email.message import Message
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.error import HTTPError, URLError
from urllib.request import BaseHandler, Request, build_opener

import pytest
from alphabrief_api.routes import settings
from alphabrief_cli import network_probe, run_commands, scheduler_commands
from alphabrief_cli.main import app
from alphabrief_core import paths
from typer.testing import CliRunner


@pytest.fixture
def open_https(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    open_request = MagicMock()
    monkeypatch.setattr(
        network_probe, "build_opener", lambda *handlers: MagicMock(open=open_request)
    )
    return open_request


def test_http_error_from_origin_still_confirms_connectivity(
    open_https: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    body = io.BytesIO(b"not logged")

    def respond(request: Request, *, timeout: float) -> Any:
        assert request.get_method() == "HEAD"
        assert not request.has_header("Authorization")
        assert timeout <= 5
        assert request.host == "api-fxpractice.oanda.com"
        raise HTTPError(request.full_url, 401, "not logged", Message(), body)

    open_https.side_effect = respond
    with caplog.at_level(logging.INFO):
        network_probe.probe_launchd_network()
    assert "OANDA practice: HTTP 401" in caplog.text
    assert "not logged" not in caplog.text
    assert body.closed
    assert all(record.levelno == logging.INFO for record in caplog.records)
    assert open_https.call_count == 1


def test_outbound_failure_logs_host_policy_hint_and_errno(
    open_https: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    open_https.side_effect = URLError(OSError(errno.EDEADLK, "private proxy details"))
    network_probe.probe_launchd_network()
    os_name = errno.errorcode[errno.EDEADLK]
    assert f"{os_name} (errno {errno.EDEADLK})" in caplog.text
    assert "If the same host is reachable from Terminal" in caplog.text
    assert "firewall, VPN, or proxy rules" in caplog.text
    assert "private proxy details" not in caplog.text


def test_broker_redirect_does_not_send_another_request(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    requests: list[str] = []

    class RedirectTransport(BaseHandler):
        handler_order = 400

        def https_open(self, request: Request) -> Any:
            requests.append(request.host)
            headers = Message()
            headers["Location"] = "https://outside-allowlist.invalid/"
            return MagicMock(code=302, msg="Found", info=lambda: headers)

    def make_opener(*handlers: Any) -> Any:
        return build_opener(RedirectTransport(), *handlers)

    monkeypatch.setattr(network_probe, "build_opener", make_opener)
    with caplog.at_level(logging.INFO):
        network_probe.probe_launchd_network()
    assert requests == ["api-fxpractice.oanda.com"]
    assert "OANDA practice: HTTP 302" in caplog.text


@pytest.mark.parametrize(
    ("failure", "diagnostic"),
    [
        (socket.gaierror(8, "private DNS details"), "DNS resolution failed"),
        (
            ssl.SSLCertVerificationError("private TLS details"),
            "TLS certificate verification failed",
        ),
    ],
)
def test_transport_failure_reports_safe_diagnostic(
    failure: OSError,
    diagnostic: str,
    open_https: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    open_https.side_effect = URLError(failure)
    network_probe.probe_launchd_network()
    assert diagnostic in caplog.text
    assert "If the same host is reachable from Terminal" in caplog.text
    assert "private" not in caplog.text


def test_stalled_dns_does_not_hold_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    unblock = Event()

    def probe() -> tuple[bool, str]:
        unblock.wait(2)
        return True, "HTTP 200"

    monkeypatch.setattr(network_probe, "_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(network_probe, "_probe_oanda", probe)
    try:
        network_probe.probe_launchd_network()
    finally:
        unblock.set()
    assert "api-fxpractice.oanda.com failed: timed out" in caplog.text
    assert "Continuing startup" in caplog.text


def test_settings_installer_enables_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plist_path = tmp_path / "ai.alphabrief.backend.plist"
    monkeypatch.setattr(settings, "_launch_agents_dir", lambda: tmp_path)
    monkeypatch.setattr(settings, "_plist_path", lambda: plist_path)
    monkeypatch.setattr(paths, "logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(
        settings, "_launchctl", lambda *args: subprocess.CompletedProcess(args, 0)
    )
    monkeypatch.setattr(settings, "_service_loaded", lambda: (True, 1234))

    assert settings.install_service()["ok"]
    plist = plistlib.loads(plist_path.read_bytes())
    assert "--probe-network" in plist["ProgramArguments"]


@pytest.mark.parametrize("flags", [[], ["--probe-network"]])
def test_run_checks_network_before_runtime_start_only_when_enabled(
    flags: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def record_probe() -> None:
        calls.append("probe")

    async def start() -> None:
        calls.append("start")

    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(network_probe, "probe_launchd_network", record_probe)
    monkeypatch.setattr(scheduler_commands, "_ai_scheduler_universe", lambda: ())
    monkeypatch.setattr(signal, "signal", MagicMock())
    runtime = MagicMock(start=start, run_forever=AsyncMock())
    monkeypatch.setattr(run_commands, "Runtime", lambda **kwargs: runtime)

    result = CliRunner().invoke(app, ["run", "run", "--trading-mode", "off", *flags])
    assert result.exit_code == 0, result.exception
    assert calls == (["probe", "start"] if flags else ["start"])
