"""Settings and Onboarding API routes (PROJECT_GUIDE 3.3, 4.7, S6)."""

from __future__ import annotations

import logging
import os
import plistlib
import re
from typing import Any

from alphabrief_cli.service_commands import (
    SERVICE_LABEL,
    _find_alphabrief_executable,
    _launch_agents_dir,
    _launchctl,
    _plist_path,
    _service_loaded,
)
from alphabrief_core import paths as _paths
from alphabrief_core import redact
from alphabrief_core.secrets import read_secret, write_secret
from alphabrief_models.channels import load_model_settings
from alphabrief_models.chatgpt_plan import load_credentials
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_OANDA_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_OANDA_ACCOUNT_RE = re.compile(r"^\d{3}-\d{3}-\d{7}-\d{3}$")


class CredentialsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    oanda_token: str | None = Field(
        None, description="OANDA v20 practice token (64 hex)"
    )
    oanda_account_id: str | None = Field(
        None, description="OANDA practice account ID (NNN-NNN-NNNNNNN-NNN)"
    )


def _read_oanda_stored_creds() -> tuple[str, str]:
    """Read OANDA credentials from secrets/oanda.json or environment."""
    sec = read_secret("oanda") or {}
    token = str(
        sec.get("token") or os.environ.get("ALPHABRIEF_OANDA_TOKEN") or ""
    ).strip()
    account_id = str(
        sec.get("account_id") or os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID") or ""
    ).strip()
    return token, account_id


@router.get("/overview")
def get_settings_overview() -> dict[str, Any]:
    """Return overview of system configuration, credentials status, and paths."""
    # OANDA credentials
    oanda_token, oanda_account = _read_oanda_stored_creds()

    # ChatGPT subscription status
    chatgpt_creds = load_credentials()
    chatgpt_status: dict[str, Any] = {
        "configured": chatgpt_creds is not None,
        "default_model": chatgpt_creds.default_model if chatgpt_creds else None,
        "has_inference_scope": (
            chatgpt_creds.has_inference_scope() if chatgpt_creds else False
        ),
        "expired": chatgpt_creds.is_expired() if chatgpt_creds else True,
        "expires_at": (
            chatgpt_creds.expires_at.isoformat() if chatgpt_creds else None
        ),
    }

    # Model settings & daily budget
    model_settings = load_model_settings()

    # LaunchAgent service status
    try:
        plist_exists = _plist_path().exists()
        loaded, pid = _service_loaded()
        service_status = {
            "installed": plist_exists,
            "running": loaded and pid is not None,
            "pid": pid,
            "label": SERVICE_LABEL,
        }
    except Exception:
        service_status = {
            "installed": False,
            "running": False,
            "pid": None,
            "label": SERVICE_LABEL,
        }

    return {
        "app": {
            "name": "AlphaBrief",
            "version": "1.0.0",
            "environment": "practice",
            "broker": "oanda_practice",
            "base_url": "https://api-fxpractice.oanda.com",
        },
        "credentials": {
            "has_oanda_token": bool(oanda_token),
            "oanda_token_masked": redact(oanda_token) if oanda_token else None,
            "has_oanda_account_id": bool(oanda_account),
            "oanda_account_id_masked": (
                redact(oanda_account) if oanda_account else None
            ),
        },
        "model_channel": {
            "chatgpt": chatgpt_status,
            "fallback_enabled": model_settings.fallback_enabled,
            "budget": {
                "daily_call_limit": model_settings.daily_call_limit,
                "daily_cost_limit_usd": float(model_settings.daily_cost_limit_usd),
            },
        },
        "service": service_status,
        "paths": {
            "data_dir": str(_paths.data_dir()),
            "db_path": str(_paths.db_path()),
            "logs_dir": str(_paths.logs_dir()),
            "backups_dir": str(_paths.backups_dir()),
            "secrets_dir": str(_paths.secrets_dir()),
        },
    }


@router.post("/credentials")
def update_credentials(body: CredentialsUpdateRequest) -> dict[str, Any]:
    """Save OANDA practice credentials into secrets/."""
    updated: list[str] = []
    current = read_secret("oanda") or {}
    new_creds = dict(current)

    if body.oanda_token is not None:
        token = body.oanda_token.strip()
        if token:
            if not _OANDA_TOKEN_RE.match(token):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Invalid OANDA practice token format. "
                        "Must be 64 hexadecimal characters."
                    ),
                )
            new_creds["token"] = token
            updated.append("oanda_token")

    if body.oanda_account_id is not None:
        account_id = body.oanda_account_id.strip()
        if account_id:
            if not _OANDA_ACCOUNT_RE.match(account_id):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Invalid OANDA practice account ID format. "
                        "Must be NNN-NNN-NNNNNNN-NNN."
                    ),
                )
            new_creds["account_id"] = account_id
            updated.append("oanda_account_id")

    if updated:
        write_secret("oanda", new_creds)

    # Read back masked
    t, a = _read_oanda_stored_creds()

    return {
        "ok": True,
        "updated": updated,
        "has_oanda_token": bool(t),
        "oanda_token_masked": redact(t) if t else None,
        "has_oanda_account_id": bool(a),
        "oanda_account_id_masked": redact(a) if a else None,
    }


@router.post("/service/install")
def install_service(trading_mode: str = "off") -> dict[str, Any]:
    """Install and load the background LaunchAgent service."""
    cmd = [*_find_alphabrief_executable(), "run", "run", "--trading-mode", trading_mode]
    plist_data = {
        "Label": SERVICE_LABEL,
        "ProgramArguments": cmd,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(_paths.logs_dir() / "backend.stdout.log"),
        "StandardErrorPath": str(_paths.logs_dir() / "backend.stderr.log"),
        "ProcessType": "Interactive",
    }
    _launch_agents_dir().mkdir(parents=True, exist_ok=True)
    _paths.logs_dir().mkdir(parents=True, exist_ok=True)
    plist_file = _plist_path()
    with plist_file.open("wb") as fp:
        plistlib.dump(plist_data, fp)

    _launchctl("unload", str(plist_file))
    res = _launchctl("load", str(plist_file))
    loaded, pid = _service_loaded()
    return {
        "ok": res.returncode == 0 or loaded,
        "plist": str(plist_file),
        "loaded": loaded,
        "pid": pid,
    }


@router.post("/service/uninstall")
def uninstall_service() -> dict[str, Any]:
    """Unload and remove the background LaunchAgent service."""
    plist_file = _plist_path()
    if plist_file.exists():
        _launchctl("unload", str(plist_file))
        plist_file.unlink(missing_ok=True)
    loaded, _ = _service_loaded()
    return {"ok": not plist_file.exists(), "loaded": loaded}


@router.post("/service/start")
def start_service() -> dict[str, Any]:
    """Start the service via launchctl."""
    _launchctl("start", SERVICE_LABEL)
    loaded, pid = _service_loaded()
    return {"ok": True, "loaded": loaded, "pid": pid}


@router.post("/service/stop")
def stop_service() -> dict[str, Any]:
    """Stop the service via launchctl."""
    _launchctl("stop", SERVICE_LABEL)
    loaded, pid = _service_loaded()
    return {"ok": True, "loaded": loaded, "pid": pid}


__all__ = ["router"]
