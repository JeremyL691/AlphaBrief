"""ChatGPT subscription channel (``chatgpt_plan``) — OAuth and inference.

Implements OpenAI's "Sign in with ChatGPT" flow for a local open-source
app exactly as documented:

* dynamic client registration on first sign-in
  (``client_id=dynamic_agent_client`` + ``agent_name_hint`` +
  ``ext_agent_host_id``), then reuse of the issued client ID;
* authorization code + PKCE (S256) against
  ``https://auth.openai.com/api/accounts/authorize`` with a loopback
  redirect on ``127.0.0.1``;
* code exchange and refresh at
  ``https://auth.openai.com/api/accounts/oauth/token``;
* ID token validation against the published JWKS (signature, issuer,
  audience, expiry, nonce) and a check that
  ``chatgpt.tokens.use.direct`` was granted;
* inference through the public Responses API with ``store=false`` and
  ``stream=true``, counting a call as successful only after
  ``response.completed``.

Credentials are stored under ``<data_dir>/secrets/chatgpt_oauth.json``
with mode 0600 and are never logged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets as py_secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode
from uuid import uuid4

from alphabrief_core import paths
from alphabrief_core.secrets import (
    SecretStoreError,
    delete_secret,
    read_secret,
    write_secret,
)

from alphabrief_models.gateway import (
    ModelCapability,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
)

SECRET_NAME = "chatgpt_oauth"

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESPONSES_URL = "https://api.openai.com/v1/responses"
MODELS_URL = "https://api.openai.com/v1/models"

#: Dynamic-registration client id used for the very first sign-in.
DYNAMIC_CLIENT_ID = "dynamic_agent_client"

AGENT_NAME_HINT = "AlphaBrief"

RESOURCE = "https://api.openai.com/v1"

SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"

#: Scope that must be present before inference is attempted.
REQUIRED_SCOPE = "chatgpt.tokens.use.direct"

CALLBACK_HOST = "127.0.0.1"

DEFAULT_CALLBACK_PORT = 1455

CALLBACK_PATH = "/auth/callback"

USER_AGENT = "AlphaBrief/1.0.0"

#: Refresh this long before the access token expires.
REFRESH_MARGIN = timedelta(seconds=120)

ChannelErrorCode = Literal[
    "not_configured",
    "not_authorized",
    "scope_missing",
    "usage_limit_exceeded",
    "usage_unavailable",
    "unsupported_capability",
    "invalid_user",
    "not_eligible",
    "route_not_supported",
    "reauthorization_required",
    "stream_failed",
    "transport_error",
]


class ChatGptPlanError(ModelProviderError):
    """Channel failure carrying a stable machine-readable code."""

    def __init__(self, code: ChannelErrorCode, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def create_code_verifier() -> str:
    """Return a fresh RFC 7636 code verifier (43 URL-safe characters)."""
    return base64.urlsafe_b64encode(py_secrets.token_bytes(32)).decode().rstrip("=")


def code_challenge_for(verifier: str) -> str:
    """Return the S256 code challenge for ``verifier``."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
    agent_host_id: str | None = None,
    id_token_hint: str | None = None,
    login_hint: str | None = None,
) -> str:
    """Build the authorization URL for one sign-in attempt."""
    params: dict[str, str] = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if client_id == DYNAMIC_CLIENT_ID:
        params["agent_name_hint"] = AGENT_NAME_HINT
        if agent_host_id:
            params["ext_agent_host_id"] = agent_host_id
    if id_token_hint:
        params["id_token_hint"] = id_token_hint
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Credential record
# ---------------------------------------------------------------------------


@dataclass
class ChatGptCredentials:
    """One stored sign-in record bound to an issued client ID."""

    client_id: str
    agent_host_id: str
    access_token: str
    refresh_token: str
    id_token: str
    scopes: tuple[str, ...]
    expires_at: datetime
    account_id: str
    models: list[str] = field(default_factory=list)
    default_model: str | None = None
    authorized_at: datetime | None = None

    def has_inference_scope(self) -> bool:
        return REQUIRED_SCOPE in self.scopes

    def is_expired(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return current >= self.expires_at - REFRESH_MARGIN

    def to_payload(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "agent_host_id": self.agent_host_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "id_token": self.id_token,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at.isoformat(),
            "account_id": self.account_id,
            "models": list(self.models),
            "default_model": self.default_model,
            "authorized_at": (
                self.authorized_at.isoformat()
                if self.authorized_at is not None
                else None
            ),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ChatGptCredentials:
        try:
            return cls(
                client_id=str(payload["client_id"]),
                agent_host_id=str(payload.get("agent_host_id", "")),
                access_token=str(payload["access_token"]),
                refresh_token=str(payload.get("refresh_token", "")),
                id_token=str(payload.get("id_token", "")),
                scopes=tuple(str(scope) for scope in payload.get("scopes", ())),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
                account_id=str(payload.get("account_id", "")),
                models=[str(model) for model in payload.get("models", ())],
                default_model=payload.get("default_model"),
                authorized_at=(
                    datetime.fromisoformat(str(payload["authorized_at"]))
                    if payload.get("authorized_at")
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SecretStoreError(
                "stored ChatGPT credentials are unreadable; sign in again"
            ) from exc


def load_credentials() -> ChatGptCredentials | None:
    """Return stored credentials, or ``None`` when not signed in."""
    payload = read_secret(SECRET_NAME)
    if payload is None:
        return None
    return ChatGptCredentials.from_payload(payload)


def save_credentials(credentials: ChatGptCredentials) -> None:
    """Store credentials atomically with owner-only permissions."""
    write_secret(SECRET_NAME, credentials.to_payload())


def clear_credentials() -> bool:
    """Remove stored credentials (sign out)."""
    return delete_secret(SECRET_NAME)


def host_id_for_this_machine() -> str:
    """Return a stable ``urn:uuid:`` host identifier for this machine."""
    payload = read_secret(SECRET_NAME)
    if payload and payload.get("agent_host_id"):
        return str(payload["agent_host_id"])
    marker = paths.data_dir() / "host-id"
    if marker.is_file():
        existing = marker.read_text(encoding="utf-8").strip()
        if existing.startswith("urn:"):
            return existing
    host_id = f"urn:uuid:{uuid4()}"
    marker.write_text(f"{host_id}\n", encoding="utf-8")
    marker.chmod(0o600)
    return host_id


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpResponse:
    """One HTTP response from the channel transport."""

    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


HttpSend = Callable[[str, str, dict[str, str], bytes | None, float], HttpResponse]


def default_http_send(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> HttpResponse:
    """Send one HTTPS request with urllib (stdlib only, no SDK)."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=int(response.status),
                body=response.read(),
                headers=dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status=int(exc.code),
            body=exc.read(),
            headers=dict(exc.headers.items()) if exc.headers else {},
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ChatGptPlanError("transport_error", type(exc).__name__) from exc


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

_ERROR_CODES: dict[str, ChannelErrorCode] = {
    "subscription_sharing_usage_limit_exceeded": "usage_limit_exceeded",
    "subscription_sharing_usage_unavailable": "usage_unavailable",
    "subscription_sharing_unsupported_capability": "unsupported_capability",
    "subscription_sharing_user_not_eligible": "not_eligible",
    "subscription_sharing_invalid_user": "invalid_user",
    "subscription_sharing_route_not_supported": "route_not_supported",
    "subscription_sharing_user_unavailable": "usage_unavailable",
    "chatpass_v2_scope_not_authorized": "scope_missing",
    "chatpass_v2_invalid_authorization_context": "scope_missing",
}

#: Refresh-token failures that require a fresh sign-in.
_TERMINAL_REFRESH_CODES = frozenset(
    {
        "invalid_grant",
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    }
)


def classify_error_code(payload: Any) -> ChannelErrorCode | None:
    """Map a Responses error payload to a channel error code."""
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "")
        if code in _ERROR_CODES:
            return _ERROR_CODES[code]
        if code:
            return None
    code = str(payload.get("code") or "")
    if code in _ERROR_CODES:
        return _ERROR_CODES[code]
    return None


def _extract_error_text(payload: Any, fallback: str) -> str:
    """Return a bounded, redacted error description."""
    message = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "")
        elif payload.get("detail"):
            message = str(payload["detail"])
        elif payload.get("code"):
            message = str(payload["code"])
    if not message:
        message = fallback
    return message[:300]


# ---------------------------------------------------------------------------
# Streaming Responses parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StreamOutcome:
    """Result of parsing one Responses SSE stream."""

    output_text: str
    status: str
    finish_reason: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def parse_response_stream(body: bytes) -> StreamOutcome:
    """Parse a Responses SSE body, requiring ``response.completed``.

    Raises :class:`ChatGptPlanError` for ``response.failed`` payloads and
    for streams that end without a terminal event.
    """
    completed: dict[str, Any] | None = None
    failed: dict[str, Any] | None = None
    model = ""
    delta_parts: list[str] = []
    item_parts: list[str] = []
    for raw_line in body.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[len("data:") :].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            event = json.loads(chunk)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        if event_type == "response.output_text.delta":
            delta_parts.append(str(event.get("delta") or ""))
        elif event_type == "response.output_item.done":
            # The completed item repeats the text already delivered as
            # deltas, so it is only a fallback for streams that send no
            # deltas at all.
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "message":
                for content in item.get("content") or ():
                    if isinstance(content, dict) and content.get("text"):
                        item_parts.append(str(content["text"]))
        elif event_type == "response.completed":
            raw = event.get("response")
            completed = raw if isinstance(raw, dict) else event
            model = str((completed or {}).get("model") or model)
        elif event_type == "response.failed":
            raw_failed = event.get("response")
            failed = raw_failed if isinstance(raw_failed, dict) else event
        elif event_type == "error":
            failed = event

    if failed is not None:
        code = classify_error_code(failed) or "stream_failed"
        raise ChatGptPlanError(code, _extract_error_text(failed, "stream failed"))
    if completed is None:
        raise ChatGptPlanError(
            "stream_failed", "stream ended without response.completed"
        )

    usage = completed.get("usage")
    input_tokens = output_tokens = None
    if isinstance(usage, dict):
        raw_in = usage.get("input_tokens")
        raw_out = usage.get("output_tokens")
        input_tokens = int(raw_in) if isinstance(raw_in, int) else None
        output_tokens = int(raw_out) if isinstance(raw_out, int) else None

    text = "".join(delta_parts).strip() or "".join(item_parts).strip()
    if not text:
        text = _collect_output_text(completed)
    return StreamOutcome(
        output_text=text,
        status=str(completed.get("status") or "completed"),
        finish_reason=str(completed.get("status") or "completed"),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _collect_output_text(response: dict[str, Any]) -> str:
    """Read text from a completed response's ``output`` array."""
    parts: list[str] = []
    for item in response.get("output") or ():
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or ():
            if isinstance(content, dict) and content.get("text"):
                parts.append(str(content["text"]))
    return "".join(parts).strip()


# ---------------------------------------------------------------------------
# Channel adapter
# ---------------------------------------------------------------------------


class ChatGptPlanAdapter:
    """Provider adapter for the ChatGPT subscription channel.

    The adapter never refreshes credentials silently into a different
    billing channel: it only uses the stored ChatGPT subscription tokens
    and fails closed when they are missing, expired beyond refresh, or
    lack ``chatgpt.tokens.use.direct``.
    """

    provider_name = "chatgpt_plan"

    def __init__(
        self,
        *,
        credentials: ChatGptCredentials | None = None,
        model_name: str | None = None,
        http_send: HttpSend | None = None,
        timeout_seconds: float = 120.0,
        clock: Callable[[], datetime] | None = None,
        refresh_handler: Callable[[ChatGptCredentials], ChatGptCredentials]
        | None = None,
    ) -> None:
        self._credentials = credentials
        self._http_send = http_send or default_http_send
        self._timeout = timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._refresh_handler = refresh_handler
        stored_default = credentials.default_model if credentials else None
        self._explicit_model = model_name
        # ``model_name`` is a plain attribute because the provider
        # protocol requires a settable member; it is resolved at call
        # time when the account's catalog is the authority.
        self.model_name = model_name or stored_default or "unknown"
        capabilities: frozenset[ModelCapability] = frozenset(
            {"text_generation", "structured_output", "long_context", "strong_reasoning"}
        )
        self.capabilities = capabilities

    # -- credentials ---------------------------------------------------

    def _current(self) -> ChatGptCredentials:
        credentials = self._credentials or load_credentials()
        if credentials is None:
            raise ChatGptPlanError(
                "not_configured", "run 'alphabrief model login' first"
            )
        if not credentials.has_inference_scope():
            raise ChatGptPlanError(
                "scope_missing",
                f"{REQUIRED_SCOPE} was not granted; run 'alphabrief model login'",
            )
        if credentials.is_expired(now=self._clock()):
            credentials = self._refresh(credentials)
        return credentials

    def _refresh(self, credentials: ChatGptCredentials) -> ChatGptCredentials:
        if self._refresh_handler is None:
            raise ChatGptPlanError(
                "reauthorization_required",
                "access token expired; run 'alphabrief model login'",
            )
        refreshed = self._refresh_handler(credentials)
        self._credentials = refreshed
        return refreshed

    def ensure_default_model(self, credentials: ChatGptCredentials) -> str:
        """Return the account's default model, discovering it if needed."""
        if credentials.default_model:
            return credentials.default_model
        models = fetch_model_slugs(self._http_send, credentials, timeout=self._timeout)
        if not models:
            raise ChatGptPlanError(
                "unsupported_capability", "no listable model for this account"
            )
        credentials.models = models
        credentials.default_model = models[0]
        save_credentials(credentials)
        self.model_name = credentials.default_model
        return credentials.default_model

    # -- inference -----------------------------------------------------

    def call(self, request: ModelRequest) -> ModelResponse:
        credentials = self._current()
        model = self._explicit_model or credentials.default_model
        if not model:
            model = self.ensure_default_model(credentials)
        payload = {
            "model": model,
            "input": [{"role": "user", "content": request.input_text}],
            "store": False,
            "stream": True,
        }
        response = self._http_send(
            "POST",
            RESPONSES_URL,
            {
                "Authorization": f"Bearer {credentials.access_token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": USER_AGENT,
            },
            json.dumps(payload).encode("utf-8"),
            self._timeout,
        )
        if response.status != 200:
            payload_json = response.json()
            code = classify_error_code(payload_json)
            if code is None:
                code = (
                    "invalid_user"
                    if response.status == 401
                    else "usage_unavailable"
                    if response.status == 503
                    else "stream_failed"
                )
            raise ChatGptPlanError(
                code, _extract_error_text(payload_json, f"HTTP {response.status}")
            )

        self.model_name = model
        outcome = parse_response_stream(response.body)
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=outcome.model or model,
            output_text=outcome.output_text,
            structured_output=None,
            status="succeeded",
            finish_reason=outcome.finish_reason,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
        )


def fetch_model_slugs(
    http_send: HttpSend,
    credentials: ChatGptCredentials,
    *,
    timeout: float = 30.0,
) -> list[str]:
    """Return the account's listable model slugs, in catalog order."""
    response = http_send(
        "GET",
        MODELS_URL,
        {
            "Authorization": f"Bearer {credentials.access_token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        None,
        timeout,
    )
    if response.status != 200:
        payload = response.json()
        code = classify_error_code(payload) or "usage_unavailable"
        raise ChatGptPlanError(
            code, _extract_error_text(payload, f"HTTP {response.status}")
        )
    body = response.json()
    if not isinstance(body, dict):
        raise ChatGptPlanError(
            "unsupported_capability", "model catalog is not a JSON object"
        )
    # The live subscription catalog returns {"models": [{"slug", "visibility",
    # "display_name", ...}]}; the OpenAI-style {"data": [{"id"}]} shape is
    # accepted too so either documented form works.
    entries = body.get("models")
    if entries is None:
        entries = body.get("data")
    slugs: list[str] = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        visibility = entry.get("visibility")
        if visibility is not None and visibility != "list":
            continue
        slug = entry.get("slug") or entry.get("id")
        if isinstance(slug, str) and slug:
            slugs.append(slug)
    return slugs
