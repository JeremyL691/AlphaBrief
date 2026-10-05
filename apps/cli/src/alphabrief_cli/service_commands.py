"""LaunchAgent service management commands (PROJECT_GUIDE S5)."""

from __future__ import annotations

import json
import os
import platform
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
from alphabrief_core import paths as _paths
from alphabrief_core.runtime_lock import lock_status

from alphabrief_cli.api_client import is_api_running

service_app = typer.Typer(
    help="Manage macOS LaunchAgent background service (ai.alphabrief.backend).",
    no_args_is_help=True,
)

SERVICE_LABEL = "ai.alphabrief.backend"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _plist_path() -> Path:
    return _launch_agents_dir() / f"{SERVICE_LABEL}.plist"


def _dump(payload: Any, *, pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _find_alphabrief_executable() -> list[str]:
    """Find command arguments to run alphabrief run."""
    # Look for alphabrief binary in current venv
    venv_bin = Path(sys.executable).parent / "alphabrief"
    if venv_bin.is_file() and os.access(venv_bin, os.X_OK):
        return [str(venv_bin)]
    # Fallback to python -m alphabrief_cli
    return [sys.executable, "-m", "alphabrief_cli"]


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Run launchctl with args."""
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _service_loaded() -> tuple[bool, int | None]:
    """Check if the service is loaded in launchctl and return (loaded, pid)."""
    proc = _launchctl("list")
    if proc.returncode != 0:
        return False, None
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip() == SERVICE_LABEL:
            pid_str = parts[0].strip()
            pid = int(pid_str) if pid_str.isdigit() else None
            return True, pid
    return False, None


@service_app.command("install")
def install_cmd(
    trading_mode: str = typer.Option(
        "off", "--trading-mode", help="Initial trading mode: on or off."
    ),
    port: int = typer.Option(8000, "--port", help="HTTP port to bind."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host IP to bind."),
    catch_up_minutes: int = typer.Option(
        90, "--catch-up-minutes", help="Clock schedule catch-up window."
    ),
    units: str = typer.Option(
        "",
        "--units",
        help=(
            "Fixed order size in units for every intent (GUIDE 5.6 S9 "
            "pre-run); empty means risk-based sizing."
        ),
    ),
    executable: Path | None = typer.Option(
        None,
        "--executable",
        help=(
            "Backend command override (e.g. the packaged onedir binary); "
            "defaults to the venv's alphabrief console script."
        ),
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """Generate and load ~/Library/LaunchAgents/ai.alphabrief.backend.plist."""
    if platform.system() != "Darwin":
        typer.secho(
            "error: LaunchAgent service is only supported on macOS",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    if trading_mode not in {"on", "off"}:
        typer.secho(
            f"error: --trading-mode must be 'on' or 'off', got {trading_mode!r}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    plist_file = _plist_path()
    _launch_agents_dir().mkdir(parents=True, exist_ok=True)
    logs_directory = _paths.logs_dir()
    logs_directory.mkdir(parents=True, exist_ok=True)

    stdout_path = str(logs_directory / "backend.out.log")
    stderr_path = str(logs_directory / "backend.err.log")

    if executable is not None:
        if not executable.is_file():
            typer.secho(
                f"error: --executable {executable} is not a file",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        exec_cmd = [str(executable)]
    else:
        exec_cmd = _find_alphabrief_executable()
    program_args = [
        *exec_cmd,
        "run",
        "run",
        "--host",
        host,
        "--port",
        str(port),
        "--trading-mode",
        trading_mode,
        "--catch-up-minutes",
        str(catch_up_minutes),
    ]
    if units.strip():
        program_args += ["--units", units.strip()]

    env_vars = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "ALPHABRIEF_DATA_DIR": str(_paths.data_dir()),
        "ALPHABRIEF_API_URL": f"http://{host}:{port}",
        "ALPHABRIEF_AI_TRADING_ENABLED": "true",
    }
    if "ALPHABRIEF_OANDA_TOKEN" in os.environ:
        env_vars["ALPHABRIEF_OANDA_TOKEN"] = os.environ["ALPHABRIEF_OANDA_TOKEN"]
    if "ALPHABRIEF_OANDA_ACCOUNT_ID" in os.environ:
        env_vars["ALPHABRIEF_OANDA_ACCOUNT_ID"] = os.environ[
            "ALPHABRIEF_OANDA_ACCOUNT_ID"
        ]

    plist_data: dict[str, Any] = {
        "Label": SERVICE_LABEL,
        "ProgramArguments": program_args,
        "RunAtLoad": True,
        "KeepAlive": {
            "SuccessfulExit": False,
            "Crashed": True,
        },
        "ThrottleInterval": 10,
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
        "WorkingDirectory": str(_paths.data_dir()),
        "EnvironmentVariables": env_vars,
    }

    # If previously loaded, unload first
    loaded, _ = _service_loaded()
    if loaded or plist_file.exists():
        _launchctl("unload", str(plist_file))

    with plist_file.open("wb") as fp:
        plistlib.dump(plist_data, fp)

    # Load via launchctl
    proc = _launchctl("load", "-w", str(plist_file))
    if proc.returncode != 0:
        typer.secho(
            f"error loading service with launchctl: {proc.stderr}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    is_loaded, pid = _service_loaded()
    _dump(
        {
            "label": SERVICE_LABEL,
            "installed": True,
            "plist_path": str(plist_file),
            "loaded": is_loaded,
            "pid": pid,
            "trading_mode": trading_mode,
            "port": port,
        },
        pretty=pretty,
    )


@service_app.command("uninstall")
def uninstall_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """Unload and remove ~/Library/LaunchAgents/ai.alphabrief.backend.plist."""
    if platform.system() != "Darwin":
        typer.secho(
            "error: LaunchAgent service is only supported on macOS",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    plist_file = _plist_path()
    was_loaded, _ = _service_loaded()

    if plist_file.exists() or was_loaded:
        _launchctl("unload", str(plist_file))

    if plist_file.exists():
        plist_file.unlink()

    _dump(
        {
            "label": SERVICE_LABEL,
            "installed": False,
            "unloaded": True,
        },
        pretty=pretty,
    )


@service_app.command("status")
def status_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """Check the status of the background service."""
    plist_file = _plist_path()
    installed = plist_file.exists()
    loaded, pid = _service_loaded()
    api_online = is_api_running()
    current_lock = lock_status()

    result = {
        "label": SERVICE_LABEL,
        "platform": platform.system(),
        "installed": installed,
        "plist_path": str(plist_file) if installed else None,
        "loaded": loaded,
        "pid": pid,
        "api_online": api_online,
        "lock": current_lock,
    }
    _dump(result, pretty=pretty)


@service_app.command("start")
def start_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """Start the service via launchctl."""
    plist_file = _plist_path()
    if not plist_file.exists():
        typer.secho(
            f"error: {plist_file} does not exist. "
            "Run 'alphabrief service install' first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    proc = _launchctl("start", SERVICE_LABEL)
    loaded, pid = _service_loaded()
    _dump(
        {
            "label": SERVICE_LABEL,
            "started": proc.returncode == 0,
            "loaded": loaded,
            "pid": pid,
        },
        pretty=pretty,
    )


@service_app.command("stop")
def stop_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """Stop the service via launchctl."""
    proc = _launchctl("stop", SERVICE_LABEL)
    loaded, pid = _service_loaded()
    _dump(
        {
            "label": SERVICE_LABEL,
            "stopped": proc.returncode == 0,
            "loaded": loaded,
            "pid": pid,
        },
        pretty=pretty,
    )


__all__ = ["service_app"]
