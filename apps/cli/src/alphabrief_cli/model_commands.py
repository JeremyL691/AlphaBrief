"""CLI commands for the model channels.

``alphabrief model login``  — run the ChatGPT authorization flow
``alphabrief model status`` — show channel state (never prints secrets)
``alphabrief model logout`` — remove the stored ChatGPT credentials
``alphabrief model test``   — one real call through the active channel,
                              printing a strict JSON view of the result
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

import typer
from alphabrief_core import paths as _paths
from alphabrief_core import redact
from alphabrief_models.channels import (
    build_channel_gateway,
    load_model_settings,
)
from alphabrief_models.chatgpt_oauth import refresh_credentials
from alphabrief_models.chatgpt_plan import (
    ChannelErrorCode,
    ChatGptPlanAdapter,
    ChatGptPlanError,
    clear_credentials,
    load_credentials,
)
from alphabrief_models.model_budget import ModelBudgetGuard
from pydantic import BaseModel, ConfigDict

model_app = typer.Typer(help="ChatGPT subscription channel and fallback channel.")


class _JsonEnvelope(BaseModel):
    """Loose envelope so any strict JSON object validates."""

    model_config = ConfigDict(extra="allow")


def _strict_json(text: str) -> dict[str, Any] | None:
    """Return the parsed object when ``text`` is exactly one JSON object."""
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _dump(payload: dict[str, Any], *, pretty: bool) -> None:
    json.dump(
        payload,
        sys.stdout,
        indent=2 if pretty else None,
        sort_keys=True,
        default=str,
    )
    sys.stdout.write("\n")


def _error_payload(code: str, detail: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "detail": detail}


def _mono_nonce() -> str:
    """Return a fresh nonce for one authorization attempt."""
    import secrets as py_secrets

    return py_secrets.token_urlsafe(32)


@model_app.command("login")
def login_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Sign in with the ChatGPT subscription (opens the browser once)."""
    from alphabrief_models.chatgpt_oauth import login

    def _announce(url: str) -> None:
        print("Open this URL to authorize AlphaBrief:", file=sys.stderr)
        print(url, file=sys.stderr)

    try:
        credentials = login(announce=_announce)
    except ChatGptPlanError as exc:
        _dump(_error_payload(exc.code, str(exc)), pretty=pretty)
        sys.exit(1)

    adapter = ChatGptPlanAdapter(credentials=credentials)
    try:
        default_model = adapter.ensure_default_model(credentials)
    except ChatGptPlanError as exc:
        _dump(_error_payload(exc.code, str(exc)), pretty=pretty)
        sys.exit(1)

    _dump(
        {
            "ok": True,
            "channel": "chatgpt_plan",
            "account": redact(credentials.account_id),
            "scopes": list(credentials.scopes),
            "default_model": default_model,
            "model_count": len(credentials.models),
            "expires_at": credentials.expires_at.isoformat(),
        },
        pretty=pretty,
    )


@model_app.command("status")
def status_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Show channel state; never prints tokens."""
    settings = load_model_settings()
    credentials = load_credentials()
    primary: dict[str, Any] = {
        "channel": "chatgpt_plan",
        "authorized": credentials is not None,
    }
    if credentials is not None:
        now = datetime.now(UTC)
        primary.update(
            {
                "account": redact(credentials.account_id),
                "scopes": list(credentials.scopes),
                "inference_scope": credentials.has_inference_scope(),
                "default_model": credentials.default_model,
                "expires_at": credentials.expires_at.isoformat(),
                "expired": credentials.is_expired(now=now),
                "refresh_token_present": bool(credentials.refresh_token),
            }
        )
    payload = {
        "ok": True,
        "primary": primary,
        "fallback": {
            "enabled": settings.fallback_enabled,
            "configured": bool(
                __import__("os").environ.get("ALPHABRIEF_LLM_BASE_URL", "").strip()
            ),
        },
    }
    _dump(payload, pretty=pretty)


@model_app.command("logout")
def logout_cmd() -> None:
    """Remove the stored ChatGPT credentials."""
    removed = clear_credentials()
    print("signed out" if removed else "no stored credentials")


@model_app.command("test")
def test_cmd(
    prompt: str = typer.Option(  # noqa: B008
        "Reply with a single JSON object: {\"ok\": true}",
        "--prompt",
        help="Prompt sent through the active channel.",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Run one real call and print the parsed result plus the call record."""
    from alphabrief_api.db.model_call import ModelCallStore
    from alphabrief_models.gateway import ModelCallRecord, ModelRequest
    from alphabrief_models.structured_output import parse_structured_output

    records: list[ModelCallRecord] = []
    call_store = ModelCallStore(db_path=_paths.db_path())

    def _persist(record: ModelCallRecord) -> None:
        records.append(record)
        call_store.save_call(record)

    channels = build_channel_gateway(
        record_sink=_persist,
        credentials=load_credentials(),
        daily_budget=ModelBudgetGuard(
            call_store, policy=load_model_settings().budget_policy()
        ),
    )
    credentials = load_credentials()
    if credentials is not None and credentials.is_expired():
        try:
            refresh_credentials(credentials)
        except ChatGptPlanError as exc:
            _dump(_error_payload(exc.code, str(exc)), pretty=pretty)
            sys.exit(1)

    request = ModelRequest(
        request_id="cli_model_test",
        task_type="test",
        prompt_version="model-test-v1",
        input_text=prompt,
        required_capabilities=["text_generation"],
    )
    try:
        result = channels.invoke(request)
    finally:
        call_store.close()
    if result.response is None:
        _dump(
            _error_payload(
                str(result.record.classification or "channel_failed"),
                str(result.record.error_type or ""),
            ),
            pretty=pretty,
        )
        sys.exit(1)

    parsed = _strict_json(result.response.output_text)
    structured = parse_structured_output(
        result.response, target=_JsonEnvelope
    ) if parsed is not None else None
    _dump(
        {
            "ok": True,
            "channel": result.record.provider,
            "model": result.record.model,
            "text": result.response.output_text,
            "parsed_ok": structured.ok if structured is not None else False,
            "parsed": (
                structured.parsed.model_dump(mode="json")
                if structured is not None and structured.parsed is not None
                else parsed
            ),
            "input_tokens": result.record.input_tokens,
            "output_tokens": result.record.output_tokens,
            "latency_ms": result.record.latency_ms,
            "record": result.record.model_dump(mode="json"),
            "switches": channels.switch_report(),
        },
        pretty=pretty,
    )


__all__ = ["model_app"]


def _channel_codes() -> tuple[ChannelErrorCode, ...]:
    """Expose the channel error codes for the CLI help text."""
    return ("not_configured", "not_authorized", "scope_missing")
