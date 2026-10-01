"""Deterministic tests for the ChatGPT subscription channel.

The OAuth flow, the Responses streaming parser and the error mapping are
exercised with an injected HTTP sender and an injected JWKS document, so
no network, browser, or credential is required.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alphabrief_core.jwt_verify import b64url_encode
from alphabrief_models.chatgpt_oauth import (
    ISSUER,
    LoopbackListener,
    login,
    parse_token_response,
    refresh_credentials,
)
from alphabrief_models.chatgpt_plan import (
    AUTHORIZE_URL,
    DYNAMIC_CLIENT_ID,
    RESPONSES_URL,
    ChatGptCredentials,
    ChatGptPlanAdapter,
    ChatGptPlanError,
    HttpResponse,
    build_authorize_url,
    classify_error_code,
    code_challenge_for,
    create_code_verifier,
    parse_response_stream,
)
from alphabrief_models.gateway import ModelRequest

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

# ---- RSA test key (generated once for this module) ------------------------

_RSA_E = 65537


def _is_probable_prime(value: int, rounds: int = 32) -> bool:
    if value < 2:
        return False
    for small in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if value % small == 0:
            return value == small
    d, r = value - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for base in range(2, 2 + rounds):
        x = pow(base, d, value)
        if x in (1, value - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, value)
            if x == value - 1:
                break
        else:
            return False
    return True


def _generate_rsa(bits: int = 512) -> tuple[int, int, int]:
    import random

    rng = random.Random(20260930)
    while True:
        p = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(p):
            break
    while True:
        q = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if q != p and _is_probable_prime(q):
            break
    n = p * q
    d = pow(_RSA_E, -1, (p - 1) * (q - 1))
    return n, _RSA_E, d


_KEY_N, _KEY_E, _KEY_D = _generate_rsa()
_KEY_BYTES = (_KEY_N.bit_length() + 7) // 8
_KID = "test-key-1"

_DIGEST_INFO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


def _sign_rs256(header: dict[str, Any], claims: dict[str, Any]) -> str:
    encoded_header = b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    encoded_claims = b64url_encode(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    digest = hashlib.sha256(signing_input).digest()
    block = (
        b"\x00\x01"
        + b"\xff" * (_KEY_BYTES - 3 - len(_DIGEST_INFO_SHA256 + digest))
        + b"\x00"
        + _DIGEST_INFO_SHA256
        + digest
    )
    signature = pow(int.from_bytes(block, "big"), _KEY_D, _KEY_N).to_bytes(
        _KEY_BYTES, "big"
    )
    return f"{encoded_header}.{encoded_claims}.{b64url_encode(signature)}"


def _jwks() -> dict[str, Any]:
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": _KID,
                "alg": "RS256",
                "n": b64url_encode(_KEY_N.to_bytes(_KEY_BYTES, "big")),
                "e": b64url_encode(_RSA_E.to_bytes(3, "big")),
            }
        ]
    }


def _id_token(*, nonce: str, audience: str, expires_in: int = 3600) -> str:
    return _sign_rs256(
        {"alg": "RS256", "kid": _KID, "typ": "JWT"},
        {
            "iss": ISSUER,
            "aud": audience,
            "sub": "acct_test_subject",
            "nonce": nonce,
            "exp": int((NOW + timedelta(seconds=expires_in)).timestamp()),
        },
    )


# ---- HTTP doubles ---------------------------------------------------------


class FakeHttp:
    """Records requests and serves programmed responses in order."""

    def __init__(self, responses: list[HttpResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        self.requests.append((method, url, headers, body))
        if not self._responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        return self._responses.pop(0)


def _sse(*events: dict[str, Any]) -> bytes:
    return "".join(
        f"data: {json.dumps(event, separators=(',', ':'))}\n\n" for event in events
    ).encode()


def _credentials(**overrides: Any) -> ChatGptCredentials:
    payload: dict[str, Any] = {
        "client_id": "client_issued_1",
        "agent_host_id": "urn:uuid:00000000-0000-4000-8000-000000000000",
        "access_token": "access-token-1",
        "refresh_token": "refresh-token-1",
        "id_token": "id-token-1",
        "scopes": (
            "openid",
            "profile",
            "email",
            "offline_access",
            "resource.invoke",
            "chatgpt.tokens.use.direct",
        ),
        "expires_at": NOW + timedelta(hours=1),
        "account_id": "acct_test_subject",
        "default_model": "gpt-test-1",
    }
    payload.update(overrides)
    return ChatGptCredentials(**payload)


class TestPkceAndAuthorizeUrl:
    def test_verifier_and_challenge_are_url_safe_and_s256(self) -> None:
        verifier = create_code_verifier()
        challenge = code_challenge_for(verifier)

        assert len(verifier) == 43
        assert "=" not in verifier and "+" not in verifier and "/" not in verifier
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        assert challenge == expected

    def test_first_registration_url_uses_dynamic_client_id(self) -> None:
        url = build_authorize_url(
            client_id=DYNAMIC_CLIENT_ID,
            redirect_uri="http://127.0.0.1:1455/auth/callback",
            state="state-1",
            nonce="nonce-1",
            code_challenge="challenge-1",
            agent_host_id="urn:uuid:abc",
        )

        assert url.startswith(AUTHORIZE_URL)
        assert "client_id=dynamic_agent_client" in url
        assert "agent_name_hint=AlphaBrief" in url
        assert "ext_agent_host_id=urn%3Auuid%3Aabc" in url
        assert "resource=https%3A%2F%2Fapi.openai.com%2Fv1" in url
        assert "chatgpt.tokens.use.direct" in url.replace("%2E", ".")
        assert "code_challenge_method=S256" in url

    def test_reauthorization_uses_issued_client_id_and_id_token_hint(self) -> None:
        url = build_authorize_url(
            client_id="client_issued_1",
            redirect_uri="http://127.0.0.1:1455/auth/callback",
            state="state-1",
            nonce="nonce-1",
            code_challenge="challenge-1",
            id_token_hint="stored-id-token",
        )

        assert "client_id=client_issued_1" in url
        assert "agent_name_hint" not in url
        assert "ext_agent_host_id" not in url
        assert "id_token_hint=stored-id-token" in url


class TestStreamParsing:
    def test_completed_stream_yields_text_and_usage(self) -> None:
        body = _sse(
            {"type": "response.output_text.delta", "delta": "{\"ok\": "},
            {"type": "response.output_text.delta", "delta": "true}"},
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "model": "gpt-test-1",
                    "usage": {"input_tokens": 11, "output_tokens": 4},
                },
            },
        )

        outcome = parse_response_stream(body)

        assert outcome.output_text == '{"ok": true}'
        assert outcome.model == "gpt-test-1"
        assert outcome.input_tokens == 11
        assert outcome.output_tokens == 4

    def test_stream_without_completed_event_fails(self) -> None:
        body = _sse({"type": "response.output_text.delta", "delta": "partial"})

        with pytest.raises(ChatGptPlanError) as exc:
            parse_response_stream(body)

        assert exc.value.code == "stream_failed"

    def test_failed_event_maps_the_usage_limit_code(self) -> None:
        body = _sse(
            {
                "type": "response.failed",
                "response": {
                    "error": {
                        "code": "subscription_sharing_usage_limit_exceeded",
                        "message": "plan limit reached",
                    }
                },
            }
        )

        with pytest.raises(ChatGptPlanError) as exc:
            parse_response_stream(body)

        assert exc.value.code == "usage_limit_exceeded"

    def test_deltas_and_the_completed_item_do_not_duplicate_text(self) -> None:
        """The real stream sends both; the text must appear once."""
        body = _sse(
            {"type": "response.output_text.delta", "delta": '{"ok": true}'},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "content": [{"text": '{"ok": true}'}],
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "model": "gpt-test-1",
                    "output": [
                        {"type": "message", "content": [{"text": '{"ok": true}'}]}
                    ],
                },
            },
        )

        assert parse_response_stream(body).output_text == '{"ok": true}'

    def test_completed_output_array_is_used_when_no_deltas(self) -> None:
        body = _sse(
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "model": "gpt-test-1",
                    "output": [
                        {"type": "message", "content": [{"text": "hello"}]}
                    ],
                },
            }
        )

        assert parse_response_stream(body).output_text == "hello"


class TestErrorClassification:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("subscription_sharing_usage_limit_exceeded", "usage_limit_exceeded"),
            ("subscription_sharing_usage_unavailable", "usage_unavailable"),
            ("subscription_sharing_unsupported_capability", "unsupported_capability"),
            ("subscription_sharing_user_not_eligible", "not_eligible"),
            ("subscription_sharing_invalid_user", "invalid_user"),
            ("subscription_sharing_route_not_supported", "route_not_supported"),
            ("chatpass_v2_scope_not_authorized", "scope_missing"),
        ],
    )
    def test_known_codes_map_to_channel_codes(self, code: str, expected: str) -> None:
        assert classify_error_code({"error": {"code": code}}) == expected

    def test_unknown_code_is_not_guessed(self) -> None:
        assert classify_error_code({"error": {"code": "something_new"}}) is None


class TestAdapter:
    def _request(self) -> ModelRequest:
        return ModelRequest(
            request_id="req-1",
            task_type="test",
            prompt_version="v1",
            input_text="hello",
            required_capabilities=["text_generation"],
        )

    def test_call_uses_store_false_stream_true_and_returns_tokens(self) -> None:
        http = FakeHttp(
            [
                HttpResponse(
                    status=200,
                    body=_sse(
                        {"type": "response.output_text.delta", "delta": '{"ok": true}'},
                        {
                            "type": "response.completed",
                            "response": {
                                "status": "completed",
                                "model": "gpt-test-1",
                                "usage": {"input_tokens": 3, "output_tokens": 2},
                            },
                        },
                    ),
                )
            ]
        )
        adapter = ChatGptPlanAdapter(
            credentials=_credentials(), http_send=http, clock=lambda: NOW
        )

        response = adapter.call(self._request())

        assert response.output_text == '{"ok": true}'
        assert response.input_tokens == 3
        method, url, headers, body = http.requests[0]
        assert (method, url) == ("POST", RESPONSES_URL)
        assert headers["Authorization"] == "Bearer access-token-1"
        payload = json.loads((body or b"").decode())
        assert payload["store"] is False
        assert payload["stream"] is True
        assert payload["model"] == "gpt-test-1"
        assert "instructions" not in payload

    def test_missing_credentials_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        # An isolated home so a real sign-in on this machine cannot leak in.
        monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
        monkeypatch.delenv("ALPHABRIEF_DATA_DIR", raising=False)
        adapter = ChatGptPlanAdapter(
            credentials=None, http_send=FakeHttp([]), clock=lambda: NOW
        )

        with pytest.raises(ChatGptPlanError) as exc:
            adapter.call(self._request())

        assert exc.value.code == "not_configured"

    def test_scope_without_inference_permission_fails_closed(self) -> None:
        adapter = ChatGptPlanAdapter(
            credentials=_credentials(scopes=("openid", "profile")),
            http_send=FakeHttp([]),
            clock=lambda: NOW,
        )

        with pytest.raises(ChatGptPlanError) as exc:
            adapter.call(self._request())

        assert exc.value.code == "scope_missing"

    def test_expired_token_without_refresh_handler_requires_login(self) -> None:
        adapter = ChatGptPlanAdapter(
            credentials=_credentials(expires_at=NOW - timedelta(minutes=5)),
            http_send=FakeHttp([]),
            clock=lambda: NOW,
        )

        with pytest.raises(ChatGptPlanError) as exc:
            adapter.call(self._request())

        assert exc.value.code == "reauthorization_required"

    def test_http_error_status_is_classified(self) -> None:
        http = FakeHttp(
            [
                HttpResponse(
                    status=429,
                    body=json.dumps(
                        {
                            "error": {
                                "code": "subscription_sharing_usage_limit_exceeded",
                                "message": "limit",
                            }
                        }
                    ).encode(),
                )
            ]
        )
        adapter = ChatGptPlanAdapter(
            credentials=_credentials(), http_send=http, clock=lambda: NOW
        )

        with pytest.raises(ChatGptPlanError) as exc:
            adapter.call(self._request())

        assert exc.value.code == "usage_limit_exceeded"


class TestTokenResponses:
    def test_parse_token_response_requires_an_access_token(self) -> None:
        with pytest.raises(ChatGptPlanError) as exc:
            parse_token_response({"error": "invalid_grant"}, now=NOW)

        assert exc.value.code == "reauthorization_required"

    def test_scope_string_is_split_and_expiry_applied(self) -> None:
        payload = parse_token_response(
            {
                "access_token": "a",
                "refresh_token": "r",
                "id_token": "i",
                "scope": "openid chatgpt.tokens.use.direct",
                "expires_in": 1800,
            },
            now=NOW,
            default_client_id="client-1",
        )

        assert payload.scopes == ("openid", "chatgpt.tokens.use.direct")
        assert payload.expires_at == NOW + timedelta(seconds=1800)
        assert payload.client_id == "client-1"

    def test_refresh_replaces_tokens_and_keeps_identity(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
        saved: list[ChatGptCredentials] = []
        monkeypatch.setattr(
            "alphabrief_models.chatgpt_oauth.save_credentials", saved.append
        )
        http = FakeHttp(
            [
                HttpResponse(
                    status=200,
                    body=json.dumps(
                        {
                            "access_token": "access-2",
                            "refresh_token": "refresh-2",
                            "id_token": "id-2",
                            "scope": "openid offline_access chatgpt.tokens.use.direct",
                            "expires_in": 3600,
                        }
                    ).encode(),
                )
            ]
        )

        updated = refresh_credentials(
            _credentials(), http_send=http, clock=lambda: NOW
        )

        assert updated.access_token == "access-2"
        assert updated.refresh_token == "refresh-2"
        assert updated.account_id == "acct_test_subject"
        assert updated.client_id == "client_issued_1"
        assert saved and saved[0].access_token == "access-2"

    def test_refresh_failure_requires_reauthorization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "alphabrief_models.chatgpt_oauth.save_credentials", lambda _c: None
        )
        http = FakeHttp(
            [HttpResponse(status=400, body=b'{"error": "invalid_grant"}')]
        )

        with pytest.raises(ChatGptPlanError) as exc:
            refresh_credentials(_credentials(), http_send=http, clock=lambda: NOW)

        assert exc.value.code == "reauthorization_required"


class TestLoopbackListener:
    def test_listener_exposes_a_loopback_redirect_uri(self) -> None:
        with LoopbackListener(port=0) as listener:
            uri = listener.redirect_uri

        assert uri.startswith("http://127.0.0.1:")
        assert uri.endswith("/auth/callback")


class _StubCallbackSource:
    """Callback source that never touches a socket."""

    def __init__(self, result_factory: Any) -> None:
        self.redirect_uri = "http://127.0.0.1:1455/auth/callback"
        self._result_factory = result_factory

    def __enter__(self) -> _StubCallbackSource:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def wait(self, *, timeout: float = 300.0) -> Any:
        return self._result_factory()


class TestLoginFlow:
    """End-to-end sign-in with injected browser, callback and HTTP."""

    def test_login_validates_id_token_and_stores_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from alphabrief_models.chatgpt_oauth import CallbackResult

        monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
        saved: list[ChatGptCredentials] = []
        monkeypatch.setattr(
            "alphabrief_models.chatgpt_oauth.save_credentials", saved.append
        )
        state_holder: dict[str, str] = {}

        class RespondingHttp(FakeHttp):
            def __call__(self, method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
                self.requests.append((method, url, headers, body))
                if url.endswith("/.well-known/jwks.json"):
                    return HttpResponse(
                        status=200, body=json.dumps(_jwks()).encode()
                    )
                return HttpResponse(
                    status=200,
                    body=json.dumps(
                        {
                            "access_token": "access-1",
                            "refresh_token": "refresh-1",
                            "id_token": _id_token(
                                nonce=state_holder["nonce"],
                                audience="client_issued_1",
                            ),
                            "scope": "openid profile email offline_access "
                            "resource.invoke chatgpt.tokens.use.direct",
                            "expires_in": 3600,
                            "client_id": "client_issued_1",
                        }
                    ).encode(),
                )

        http = RespondingHttp([])

        def fake_opener(url: str) -> bool:
            from urllib.parse import parse_qs, urlparse

            params = parse_qs(urlparse(url).query)
            state_holder["nonce"] = params["nonce"][0]
            state_holder["state"] = params["state"][0]
            return True

        def result_factory() -> CallbackResult:
            return CallbackResult(
                code="auth-code-1",
                state=state_holder["state"],
                client_id="client_issued_1",
                error=None,
            )

        credentials = login(
            http_send=http,
            clock=lambda: NOW,
            open_browser=fake_opener,
            listener_factory=lambda: _StubCallbackSource(result_factory),
            credentials_loader=lambda: None,
        )

        assert credentials.client_id == "client_issued_1"
        assert credentials.account_id == "acct_test_subject"
        assert credentials.has_inference_scope()
        assert saved and saved[0].access_token == "access-1"
        exchange = [
            request
            for request in http.requests
            if request[0] == "POST" and "oauth/token" in request[1]
        ]
        assert exchange, "the code exchange must be attempted"
        body = (exchange[0][3] or b"").decode()
        assert "grant_type=authorization_code" in body
        assert "code_verifier=" in body
        assert "code=auth-code-1" in body

    def test_login_rejects_a_callback_with_the_wrong_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from alphabrief_models.chatgpt_oauth import CallbackResult

        monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
        monkeypatch.setattr(
            "alphabrief_models.chatgpt_oauth.save_credentials", lambda _c: None
        )

        with pytest.raises(ChatGptPlanError) as exc:
            login(
                http_send=FakeHttp([]),
                clock=lambda: NOW,
                open_browser=lambda url: True,
                listener_factory=lambda: _StubCallbackSource(
                    lambda: CallbackResult(
                        code="abc", state="forged", client_id=None, error=None
                    )
                ),
                credentials_loader=lambda: None,
            )

        assert exc.value.code == "transport_error"
        assert "state" in str(exc.value)

    def test_login_reports_a_denied_authorization(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from alphabrief_models.chatgpt_oauth import CallbackResult

        monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
        monkeypatch.setattr(
            "alphabrief_models.chatgpt_oauth.save_credentials", lambda _c: None
        )

        with pytest.raises(ChatGptPlanError) as exc:
            login(
                http_send=FakeHttp([]),
                clock=lambda: NOW,
                open_browser=lambda url: True,
                listener_factory=lambda: _StubCallbackSource(
                    lambda: CallbackResult(
                        code=None, state=None, client_id=None, error="access_denied"
                    )
                ),
                credentials_loader=lambda: None,
            )

        assert exc.value.code == "reauthorization_required"

    def test_login_refuses_a_different_issued_client_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from alphabrief_models.chatgpt_oauth import CallbackResult

        monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
        monkeypatch.setattr(
            "alphabrief_models.chatgpt_oauth.save_credentials", lambda _c: None
        )
        stored = _credentials()
        state_holder: dict[str, str] = {}

        def fake_opener(url: str) -> bool:
            from urllib.parse import parse_qs, urlparse

            params = parse_qs(urlparse(url).query)
            state_holder["state"] = params["state"][0]
            return True

        with pytest.raises(ChatGptPlanError) as exc:
            login(
                http_send=FakeHttp([]),
                clock=lambda: NOW,
                open_browser=fake_opener,
                listener_factory=lambda: _StubCallbackSource(
                    lambda: CallbackResult(
                        code="abc",
                        state=state_holder["state"],
                        client_id="client_someone_else",
                        error=None,
                    )
                ),
                credentials_loader=lambda: stored,
            )

        assert exc.value.code == "reauthorization_required"
        assert "different client id" in str(exc.value)

    def test_login_requires_the_inference_scope(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from alphabrief_models.chatgpt_oauth import CallbackResult

        monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
        saved: list[ChatGptCredentials] = []
        monkeypatch.setattr(
            "alphabrief_models.chatgpt_oauth.save_credentials", saved.append
        )
        state_holder: dict[str, str] = {}

        class ScopeHttp(FakeHttp):
            def __call__(self, method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
                self.requests.append((method, url, headers, body))
                if url.endswith("/.well-known/jwks.json"):
                    return HttpResponse(
                        status=200, body=json.dumps(_jwks()).encode()
                    )
                return HttpResponse(
                    status=200,
                    body=json.dumps(
                        {
                            "access_token": "access-1",
                            "refresh_token": "refresh-1",
                            "id_token": _id_token(
                                nonce=state_holder["nonce"],
                                audience="client_issued_1",
                            ),
                            "scope": "openid profile email offline_access",
                            "expires_in": 3600,
                            "client_id": "client_issued_1",
                        }
                    ).encode(),
                )

        def fake_opener(url: str) -> bool:
            from urllib.parse import parse_qs, urlparse

            params = parse_qs(urlparse(url).query)
            state_holder["nonce"] = params["nonce"][0]
            state_holder["state"] = params["state"][0]
            return True

        with pytest.raises(ChatGptPlanError) as exc:
            login(
                http_send=ScopeHttp([]),
                clock=lambda: NOW,
                open_browser=fake_opener,
                listener_factory=lambda: _StubCallbackSource(
                    lambda: CallbackResult(
                        code="auth-code-1",
                        state=state_holder["state"],
                        client_id="client_issued_1",
                        error=None,
                    )
                ),
                credentials_loader=lambda: None,
            )

        assert exc.value.code == "scope_missing"
        assert not saved, "credentials without the inference scope must not be stored"
