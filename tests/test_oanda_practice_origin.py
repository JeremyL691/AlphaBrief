"""Only the fixed HTTPS practice REST origin can receive broker credentials."""

from __future__ import annotations

from http.client import HTTPMessage
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest
from alphabrief_execution.broker.errors import BrokerProtocolError
from alphabrief_execution.broker.oanda import client as transport
from alphabrief_execution.broker.oanda.config import (
    DEFAULT_BASE_URL,
    OandaPaperConfig,
    load_oanda_paper_config,
)
from alphabrief_execution.broker.runtime import oanda_paper_transport_config

BAD_ORIGINS = [
    "https://example.com",
    "https://api-fxtrade.oanda.com",
    "https://api-fxpractice.oanda.com.evil.test",
    "https://evil.test/api-fxpractice.oanda.com",
    "https://api-fxpractice.oanda.com@evil.test",
    "https://user:private-token@api-fxpractice.oanda.com",
    "http://api-fxpractice.oanda.com",
    "http://127.0.0.1:8000",
    "https://api-fxpractice.oanda.com:443",
    "https://api-fxpractice.oanda.com:8443",
    "https://api-fxpractice.oanda.com/alternate",
    "https://api-fxpractice.oanda.com?token=private-token",
    "https://api-fxpractice.oanda.com#alternate",
    "https://api-fxpractice.oanda.com\n",
    "https://api-fxpractice.oanda.com\t.evil.test",
    "https://[invalid",
]


def config(base_url: str = DEFAULT_BASE_URL) -> OandaPaperConfig:
    return OandaPaperConfig(
        base_url=base_url, timeout_seconds=1, max_retries=0,
        retry_backoff_seconds=0.01,
    )


@pytest.mark.parametrize("origin", BAD_ORIGINS)
def test_configuration_rejects_every_noncanonical_origin(origin: str) -> None:
    with pytest.raises(ValueError) as exc:
        config(origin)
    assert "private-token" not in str(exc.value)


@pytest.mark.parametrize("origin", [DEFAULT_BASE_URL, DEFAULT_BASE_URL + "/"])
def test_canonical_practice_origin_is_accepted(origin: str) -> None:
    assert config(origin).base_url == origin


def test_yaml_loader_rejects_a_nonpractice_origin(tmp_path: Path) -> None:
    path = tmp_path / "oanda.yaml"
    path.write_text("base_url: https://example.com\n")
    with pytest.raises(ValueError, match="practice HTTPS origin"):
        load_oanda_paper_config(path)


@pytest.mark.parametrize("origin", [DEFAULT_BASE_URL, "http://127.0.0.1:1"])
def test_obsolete_endpoint_override_is_rejected(
    origin: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHABRIEF_OANDA_BASE_URL", origin)
    with pytest.raises(ValueError, match="overrides are no longer supported"):
        oanda_paper_transport_config()


def test_forged_configuration_is_rechecked_by_the_client() -> None:
    forged = config()
    object.__setattr__(forged, "base_url", "https://example.com")
    with pytest.raises(ValueError, match="practice HTTPS origin"):
        transport.OandaHttpClient(config=forged, token="test-token", account_id="test")


def test_changed_configuration_is_rechecked_before_authenticated_send() -> None:
    settings = config()
    calls: list[Request] = []

    def send(request: Request, timeout: float) -> bytes:
        calls.append(request)
        return b"{}"

    client = transport.OandaHttpClient(
        config=settings, http_send=send, token="test-token", account_id="test",
    )
    object.__setattr__(settings, "base_url", "https://example.com")
    with pytest.raises(ValueError, match="practice HTTPS origin"):
        client.request("GET", "/v3/accounts")
    assert calls == []


def test_default_transport_rejects_nonpractice_before_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_opener(*handlers: object) -> None:
        pytest.fail("nonpractice URL reached the network opener")

    monkeypatch.setattr(transport, "build_opener", forbidden_opener)
    with pytest.raises(ValueError, match="practice HTTPS origin"):
        transport._default_http_send(Request("https://example.com"), 1)


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "destination", ["https://example.com", DEFAULT_BASE_URL + "/v3"]
)
def test_redirect_response_never_creates_a_followup_request(
    code: int, destination: str,
) -> None:
    request = Request(DEFAULT_BASE_URL + "/v3/accounts", headers={
        "Authorization": "Bearer private-token",
    })
    headers = HTTPMessage()
    headers["Location"] = destination
    handler = transport._NoRedirect()
    with pytest.raises(BrokerProtocolError, match="redirects are forbidden") as exc:
        handler.http_error_302(request, BytesIO(), code, "redirect", headers)
    assert destination not in str(exc.value)
    assert "private-token" not in str(exc.value)


def test_default_transport_installs_the_redirect_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response(BytesIO):
        def __enter__(self) -> Response:
            return self

    class Opener:
        def open(self, request: Request, *, timeout: float) -> Response:
            assert request.full_url == DEFAULT_BASE_URL + "/v3/accounts"
            assert timeout == 1
            return Response(b"{}")

    def build(*handlers: Any) -> Opener:
        assert any(isinstance(h, transport._NoRedirect) for h in handlers)
        return Opener()

    monkeypatch.setattr(transport, "build_opener", build)
    request = Request(DEFAULT_BASE_URL + "/v3/accounts")
    assert transport._default_http_send(request, 1) == b"{}"
