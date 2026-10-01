"""Interactive "Sign in with ChatGPT" flow for the local app.

The flow follows OpenAI's documented public-client OAuth sequence:

1. prepare a host identifier, a loopback listener, and fresh
   ``state`` / ``nonce`` / PKCE (S256) values;
2. open the authorization URL in the system browser and wait for the
   loopback redirect;
3. exchange the authorization code (form-encoded, no client secret) at
   the token endpoint;
4. verify the ID token against the published JWKS (signature, issuer,
   audience, expiry, nonce) and require the
   ``chatgpt.tokens.use.direct`` scope;
5. store the credentials with mode 0600.

Every step is injectable (HTTP sender, browser opener, JWKS loader) so
the whole flow is testable without a network or a browser.
"""

from __future__ import annotations

import secrets as py_secrets
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urlparse

from alphabrief_core.jwt_verify import JwtVerificationError, verify_id_token

from alphabrief_models.chatgpt_plan import (
    CALLBACK_HOST,
    CALLBACK_PATH,
    DEFAULT_CALLBACK_PORT,
    DYNAMIC_CLIENT_ID,
    REQUIRED_SCOPE,
    RESOURCE,
    SCOPES,
    TOKEN_URL,
    USER_AGENT,
    ChatGptCredentials,
    ChatGptPlanError,
    HttpResponse,
    HttpSend,
    build_authorize_url,
    code_challenge_for,
    create_code_verifier,
    default_http_send,
    host_id_for_this_machine,
    save_credentials,
)

JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
ISSUER = "https://auth.openai.com"

#: Loopback ports tried in order when the default is busy.
CALLBACK_PORT_ATTEMPTS = 5

#: How long the interactive sign-in waits for the browser callback.
CALLBACK_TIMEOUT_SECONDS = 300.0


class CallbackSource(Protocol):
    """Anything that can supply one OAuth redirect for an attempt."""

    redirect_uri: str

    def __enter__(self) -> CallbackSource: ...

    def __exit__(self, *exc: object) -> None: ...

    def wait(self, *, timeout: float = CALLBACK_TIMEOUT_SECONDS) -> CallbackResult: ...


@dataclass
class CallbackResult:
    """One loopback redirect payload."""

    code: str | None
    state: str | None
    client_id: str | None
    error: str | None


class _CallbackHandler(BaseHTTPRequestHandler):
    """Capture exactly one OAuth redirect and answer with a short page."""

    server_version = "AlphaBriefOAuth/1.0"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        params = parse_qs(parsed.query)

        def first(name: str) -> str | None:
            values = params.get(name)
            return values[0] if values else None

        result: CallbackResult = self.server.callback_result  # type: ignore[attr-defined]
        result.code = first("code")
        result.state = first("state")
        result.client_id = first("client_id")
        result.error = first("error")
        self.server.callback_event.set()  # type: ignore[attr-defined]
        body = b"AlphaBrief sign-in complete. You can close this tab."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence the default stderr logging (no secrets in logs)."""


class LoopbackListener:
    """Loopback HTTP server that receives the OAuth redirect."""

    def __init__(self, *, port: int = DEFAULT_CALLBACK_PORT) -> None:
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.redirect_uri = ""
        for offset in range(CALLBACK_PORT_ATTEMPTS):
            candidate = port + offset
            try:
                server = HTTPServer((CALLBACK_HOST, candidate), _CallbackHandler)
            except OSError:
                continue
            server.callback_result = CallbackResult(  # type: ignore[attr-defined]
                code=None, state=None, client_id=None, error=None
            )
            server.callback_event = threading.Event()  # type: ignore[attr-defined]
            self._server = server
            self.redirect_uri = (
                f"http://{CALLBACK_HOST}:{candidate}{CALLBACK_PATH}"
            )
            break
        if self._server is None:
            raise ChatGptPlanError(
                "transport_error", "no free loopback port for the OAuth callback"
            )

    def __enter__(self) -> LoopbackListener:
        assert self._server is not None
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def result(self) -> CallbackResult:
        assert self._server is not None
        return self._server.callback_result  # type: ignore[attr-defined,no-any-return]

    def wait(self, *, timeout: float = CALLBACK_TIMEOUT_SECONDS) -> CallbackResult:
        assert self._server is not None
        event: threading.Event = self._server.callback_event  # type: ignore[attr-defined]
        if not event.wait(timeout):
            raise ChatGptPlanError(
                "transport_error", "timed out waiting for the browser callback"
            )
        return self.result

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None


def _fetch_jwks(http_send: HttpSend, *, timeout: float = 30.0) -> Any:
    response = http_send(
        "GET",
        JWKS_URL,
        {"Accept": "application/json", "User-Agent": USER_AGENT},
        None,
        timeout,
    )
    if response.status != 200:
        raise ChatGptPlanError(
            "transport_error", f"JWKS request failed with HTTP {response.status}"
        )
    return response.json()


def _form_post(
    http_send: HttpSend,
    url: str,
    form: dict[str, str],
    *,
    timeout: float = 30.0,
) -> HttpResponse:
    return http_send(
        "POST",
        url,
        {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        urlencode(form).encode("ascii"),
        timeout,
    )


@dataclass
class TokenPayload:
    """Normalized token-endpoint response."""

    access_token: str
    refresh_token: str
    id_token: str
    scopes: tuple[str, ...]
    expires_at: datetime
    client_id: str | None


def parse_token_response(
    payload: Any,
    *,
    now: datetime,
    default_client_id: str | None = None,
) -> TokenPayload:
    """Validate and normalize a token-endpoint response body."""
    if not isinstance(payload, dict) or "access_token" not in payload:
        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("error") or payload.get("detail") or "")
        raise ChatGptPlanError(
            "reauthorization_required",
            f"token endpoint rejected the request: {message[:200]}",
        )
    scope_value = payload.get("scope")
    scopes: tuple[str, ...] = ()
    if isinstance(scope_value, str) and scope_value.strip():
        scopes = tuple(scope_value.split())
    elif isinstance(scope_value, list):
        scopes = tuple(str(item) for item in scope_value)
    expires_in = payload.get("expires_in")
    seconds = int(expires_in) if isinstance(expires_in, (int, float)) else 3600
    return TokenPayload(
        access_token=str(payload["access_token"]),
        refresh_token=str(payload.get("refresh_token") or ""),
        id_token=str(payload.get("id_token") or ""),
        scopes=scopes,
        expires_at=now + timedelta(seconds=max(seconds, 60)),
        client_id=payload.get("client_id") or default_client_id,
    )


def refresh_credentials(
    credentials: ChatGptCredentials,
    *,
    http_send: HttpSend | None = None,
    clock: Callable[[], datetime] | None = None,
    timeout: float = 30.0,
) -> ChatGptCredentials:
    """Exchange the refresh token for a new token set (atomic update)."""
    if not credentials.refresh_token:
        raise ChatGptPlanError(
            "reauthorization_required", "no refresh token stored; sign in again"
        )
    sender = http_send or default_http_send
    now = (clock or (lambda: datetime.now(UTC)))()
    response = _form_post(
        sender,
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": credentials.refresh_token,
            "client_id": credentials.client_id,
            "resource": RESOURCE,
        },
        timeout=timeout,
    )
    if response.status != 200:
        payload = response.json()
        code = ""
        if isinstance(payload, dict):
            code = str(payload.get("error") or payload.get("code") or "")
        raise ChatGptPlanError(
            "reauthorization_required",
            f"refresh rejected ({code or f'HTTP {response.status}'}); sign in again",
        )
    tokens = parse_token_response(
        response.json(), now=now, default_client_id=credentials.client_id
    )
    updated = ChatGptCredentials(
        client_id=tokens.client_id or credentials.client_id,
        agent_host_id=credentials.agent_host_id,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token or credentials.refresh_token,
        id_token=tokens.id_token or credentials.id_token,
        scopes=tokens.scopes or credentials.scopes,
        expires_at=tokens.expires_at,
        account_id=credentials.account_id,
        models=list(credentials.models),
        default_model=credentials.default_model,
        authorized_at=credentials.authorized_at,
    )
    save_credentials(updated)
    return updated


def login(
    *,
    http_send: HttpSend | None = None,
    clock: Callable[[], datetime] | None = None,
    open_browser: Callable[[str], bool] | None = None,
    listener_factory: Callable[[], CallbackSource] | None = None,
    credentials_loader: Callable[[], ChatGptCredentials | None] | None = None,
    announce: Callable[[str], None] | None = None,
) -> ChatGptCredentials:
    """Run one interactive sign-in and persist the resulting credentials."""
    sender = http_send or default_http_send
    current = (clock or (lambda: datetime.now(UTC)))()
    opener = open_browser or webbrowser.open
    existing = credentials_loader() if credentials_loader is not None else None
    host_id = host_id_for_this_machine()
    client_id = existing.client_id if existing is not None else DYNAMIC_CLIENT_ID

    state = py_secrets.token_urlsafe(32)
    nonce = py_secrets.token_urlsafe(32)
    verifier = create_code_verifier()

    make_listener: Callable[[], CallbackSource] = (
        listener_factory or LoopbackListener
    )
    with make_listener() as listener:
        redirect_uri = listener.redirect_uri
        url = build_authorize_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=code_challenge_for(verifier),
            agent_host_id=host_id,
            id_token_hint=existing.id_token if existing is not None else None,
        )
        if announce is not None:
            announce(url)
        opener(url)
        callback = listener.wait()

    if callback.error:
        raise ChatGptPlanError(
            "reauthorization_required", f"authorization denied: {callback.error}"
        )
    if not callback.code or callback.state != state:
        raise ChatGptPlanError(
            "transport_error", "callback state did not match this attempt"
        )
    issued_client_id = callback.client_id or client_id
    if (
        callback.client_id
        and existing is not None
        and callback.client_id != existing.client_id
    ):
        raise ChatGptPlanError(
            "reauthorization_required",
            "callback returned a different client id than the stored one",
        )

    response = _form_post(
        sender,
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": issued_client_id,
            "code": callback.code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "resource": RESOURCE,
        },
    )
    tokens = parse_token_response(
        response.json() if response.status == 200 else None,
        now=current,
        default_client_id=issued_client_id,
    )
    if response.status != 200:
        raise ChatGptPlanError(
            "reauthorization_required",
            f"code exchange failed with HTTP {response.status}",
        )

    jwks = _fetch_jwks(sender)
    try:
        claims = verify_id_token(
            tokens.id_token,
            jwks=jwks,
            issuer=ISSUER,
            audience=issued_client_id,
            nonce=nonce,
            now=current,
        )
    except JwtVerificationError as exc:
        raise ChatGptPlanError("reauthorization_required", str(exc)) from exc

    granted = tokens.scopes
    if REQUIRED_SCOPE not in granted:
        raise ChatGptPlanError(
            "scope_missing",
            f"the authorization did not grant {REQUIRED_SCOPE}",
        )

    credentials = ChatGptCredentials(
        client_id=issued_client_id,
        agent_host_id=host_id,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        id_token=tokens.id_token,
        scopes=granted,
        expires_at=tokens.expires_at,
        account_id=str(claims.get("sub") or ""),
        authorized_at=current,
    )
    save_credentials(credentials)
    return credentials


def scope_summary(credentials: ChatGptCredentials) -> dict[str, bool]:
    """Return the scope checks surfaced by ``model status``."""
    return {
        "inference_scope": credentials.has_inference_scope(),
        "offline_access": "offline_access" in credentials.scopes,
        "resource_invoke": "resource.invoke" in credentials.scopes,
    }


__all__ = [
    "CALLBACK_PORT_ATTEMPTS",
    "CALLBACK_TIMEOUT_SECONDS",
    "CallbackSource",
    "ISSUER",
    "JWKS_URL",
    "SCOPES",
    "CallbackResult",
    "LoopbackListener",
    "TokenPayload",
    "login",
    "parse_token_response",
    "refresh_credentials",
    "scope_summary",
]
