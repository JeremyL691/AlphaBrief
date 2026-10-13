"""Pinned free primary routing: deterministic transport, no live credentials."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import Any
from urllib.request import Request

import pytest
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_models.channels import (
    ModelSettings,
    build_channel_gateway,
    load_model_settings,
)
from alphabrief_models.chatgpt_plan import HttpResponse
from alphabrief_models.model_budget import (
    ModelBudgetGuard,
    ModelBudgetPolicy,
    ModelCallKind,
)
from alphabrief_models.openai_compatible import FallbackConfig, OpenAiCompatibleAdapter
from test_model_call_admission import NOW, request, sink

MODEL = "google/gemma-4-31b-it:free"
CHANNEL = "openrouter_free"
BASE = "https://openrouter.ai/api/v1"


def settings(**kwargs: Any) -> ModelSettings:
    return ModelSettings(
        primary_channel=CHANNEL,
        primary_model=MODEL,
        daily_call_limit=45,
        daily_cost_limit_usd=Decimal(0),
        **kwargs,
    )


def catalog(pricing: Any = None, model: str = MODEL) -> HttpResponse:
    return HttpResponse(
        200,
        json.dumps(
            {
                "data": [
                    {
                        "id": model,
                        "pricing": pricing
                        if pricing is not None
                        else {"prompt": "0", "completion": "0", "request": "0"},
                    }
                ]
            }
        ).encode(),
    )


class Transport:
    def __init__(self, listing: HttpResponse | None = None, status: int = 200) -> None:
        self.listing = listing or catalog()
        self.status = status
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        assert timeout > 0
        self.calls.append((method, url, json.loads(body) if body else {}))
        if method == "GET":
            return self.listing
        return HttpResponse(
            self.status,
            json.dumps(
                {
                    "model": MODEL,
                    "choices": [
                        {
                            "message": {"content": '  {"ok":true}  '},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                }
            ).encode(),
        )


@pytest.fixture(autouse=True)
def isolated_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "alphabrief_models.openai_compatible.read_secret", lambda name: None
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    # The free branch must not even read the subscription credential file.
    def forbidden() -> None:
        raise AssertionError("ChatGPT credentials read by free primary")

    monkeypatch.setattr("alphabrief_models.channels.load_credentials", forbidden)


def build(store: ModelCallStore, transport: Transport, **kwargs: Any) -> Any:
    return build_channel_gateway(
        settings=settings(),
        environ={"OPENROUTER_API_KEY": "test-key"},
        http_send=transport,
        record_sink=sink(store),
        clock=lambda: NOW,
        daily_budget=ModelBudgetGuard(
            store, policy=settings().budget_policy(), clock=lambda: NOW
        ),
        **kwargs,
    )


def test_primary_catalog_provider_policy_and_audit(tmp_path: Path) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        transport = Transport()
        channels = build(store, transport)
        result = channels.invoke(request())
        assert channels.primary_channel == CHANNEL and channels.fallback_channel is None
        assert result.response is not None
        assert result.record.provider == CHANNEL and result.record.model == MODEL
        assert result.record.cost_estimate == 0
        assert transport.calls[0][:2] == ("GET", BASE + "/models")
        assert transport.calls[1][:2] == ("POST", BASE + "/chat/completions")
        assert transport.calls[1][2]["model"] == MODEL
        assert transport.calls[1][2]["provider"] == {
            "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0},
            "allow_fallbacks": False,
        }
        assert result.record.audit_payload is not None
        assert result.record.audit_payload["output_text"] == '  {"ok":true}  '
        assert result.record.audit_payload["provider_payload"]["model"] == MODEL
        assert store.daily_usage(NOW.replace(hour=0))[CHANNEL].calls == 1
    finally:
        store.close()


@pytest.mark.parametrize(
    "pricing",
    [
        {},
        {"prompt": "0"},
        {"completion": "0"},
        {"prompt": "0", "completion": "0.1"},
        {"prompt": "0", "completion": "0", "image": "0.01"},
        {"prompt": "0", "completion": "0", "future_dimension": None},
        {"prompt": "NaN", "completion": "0"},
        {"prompt": "Infinity", "completion": "0"},
        {"prompt": True, "completion": "0"},
        {"prompt": "garbage", "completion": "0"},
        {"prompt": "-1", "completion": "0"},
    ],
)
def test_catalog_price_rejections_before_post(tmp_path: Path, pricing: Any) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        transport = Transport(catalog(pricing))
        result = build(store, transport).invoke(request())
        assert result.response is None
        assert len(transport.calls) == 1
        assert result.record.provider == CHANNEL
        assert store.daily_usage(NOW.replace(hour=0))[CHANNEL].calls == 1
    finally:
        store.close()


@pytest.mark.parametrize(
    "listing",
    [
        HttpResponse(503, b"{}"),
        HttpResponse(302, b"{}"),
        HttpResponse(200, b"not-json"),
        HttpResponse(200, b'{"data":[]}'),
        catalog(model="openrouter/free"),
    ],
)
def test_catalog_unknown_outage_redirect_rejected(
    tmp_path: Path, listing: HttpResponse
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        transport = Transport(listing)
        assert build(store, transport).invoke(request()).response is None
        assert len(transport.calls) == 1
    finally:
        store.close()


def test_prices_rechecked_every_call(tmp_path: Path) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        transport = Transport()
        channels = build(store, transport)
        assert channels.invoke(request("first")).response is not None
        transport.listing = catalog({"prompt": "0.1", "completion": "0"})
        assert channels.invoke(request("second")).response is None
        assert [c[0] for c in transport.calls] == ["GET", "POST", "GET"]
    finally:
        store.close()


@pytest.mark.parametrize(
    "status,classification",
    [
        (401, "provider_error"),
        (429, "rate_limit"),
        (503, "provider_error"),
        (302, "provider_error"),
    ],
)
def test_provider_errors_no_post_retry_or_fallback(
    tmp_path: Path, status: int, classification: str
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        transport = Transport(status=status)
        channels = build(store, transport)
        result = channels.invoke(request())
        assert (
            result.response is None and result.record.classification == classification
        )
        assert [c[0] for c in transport.calls] == ["GET", "POST"]
        assert channels.gateway.fallback_channels == ()
        if status == 429:
            assert channels.invoke(request("again")).response is None
            assert len(transport.calls) == 2
    finally:
        store.close()


def test_missing_secret_fails_closed() -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_channel_gateway(settings=settings(), environ={})


def test_app_secret_and_env_overrides_cannot_change_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "alphabrief_models.openai_compatible.read_secret",
        lambda name: {
            "api_key": "test-key",
            "base_url": "https://paid.example",
            "model": "paid",
        },
    )
    channels = build_channel_gateway(
        settings=settings(),
        environ={
            "ALPHABRIEF_LLM_BASE_URL": "https://paid.example",
            "ALPHABRIEF_LLM_MODEL": "paid",
        },
    )
    adapter = channels.gateway._providers[0]
    assert isinstance(adapter, OpenAiCompatibleAdapter)
    assert adapter.model_name == MODEL
    assert adapter.config.base_url == BASE


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fallback_enabled": True},
        {"primary_model": "paid"},
        {"primary_model": "openrouter/free"},
        {"primary_model": "google/gemma-4-31b-it"},
        {"daily_call_limit": 46},
        {"primary_channel": "unknown"},
    ],
)
def test_invalid_primary_settings_rejected(kwargs: dict[str, Any]) -> None:
    data = {
        "primary_channel": CHANNEL,
        "primary_model": MODEL,
        "daily_call_limit": 45,
        "daily_cost_limit_usd": Decimal(0),
        **kwargs,
    }
    with pytest.raises(ValueError):
        ModelSettings(**data)


@pytest.mark.parametrize(
    "kwargs", [{"allow_fallback": True}, {"primary_model": "other:free"}]
)
def test_factory_overrides_cannot_bypass_policy(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        build_channel_gateway(
            settings=settings(), environ={"OPENROUTER_API_KEY": "test-key"}, **kwargs
        )


def test_free_requires_durable_budget_even_with_direct_gateway() -> None:
    transport = Transport()
    channels = build_channel_gateway(
        settings=settings(),
        environ={"OPENROUTER_API_KEY": "test-key"},
        http_send=transport,
    )
    assert channels.invoke(request()).response is None
    assert transport.calls == []


def test_zero_usd_budget_only_free_primary(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"model:\n  primary_channel: {CHANNEL}\n  primary_model: {MODEL}\n"
        '  daily_cost_limit_usd: "0"\n'
    )
    assert load_model_settings(path).daily_call_limit == 45
    assert load_model_settings(path).daily_cost_limit_usd == 0
    path.write_text('model:\n  daily_cost_limit_usd: "0"\n')
    with pytest.raises(ValueError):
        load_model_settings(path)
    with pytest.raises(ValueError):
        ModelSettings(daily_cost_limit_usd=Decimal(0))
    with pytest.raises(ValueError):
        ModelBudgetPolicy(daily_cost_limits={"openai_compatible": Decimal(0)})
    assert ModelSettings().primary_channel == "chatgpt_plan"


def test_restart_concurrent_daily_cap_includes_unknown_repair_shadow(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calls.duckdb"
    store = ModelCallStore(database)
    budget = ModelBudgetGuard(
        store, policy=settings().budget_policy(), clock=lambda: NOW
    )
    kinds: tuple[ModelCallKind, ...] = ("shadow", "repair")
    for i in range(44):
        assert budget.reserve(
            CHANNEL,
            f"prior-{i}",
            call_kind=kinds[i % 2],
            round_key=f"prior-round-{i}",
            symbol="EUR_USD",
        ).allowed
    store.close()
    stores = [ModelCallStore(database), ModelCallStore(database)]
    barrier = Barrier(2)
    try:

        def reserve(index: int) -> bool:
            barrier.wait(timeout=5)
            # Even an incorrectly supplied legacy policy cannot remove the cap.
            guard = ModelBudgetGuard(stores[index], clock=lambda: NOW)
            return guard.reserve(CHANNEL, f"last-{index}").allowed

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sum(pool.map(reserve, range(2))) == 1
        transport = Transport()
        assert build(stores[0], transport).invoke(request()).response is None
        assert transport.calls == []
        assert stores[0].daily_usage(NOW.replace(hour=0))[CHANNEL].calls == 45
        tomorrow = ModelBudgetGuard(
            stores[0],
            policy=settings().budget_policy(),
            clock=lambda: NOW + timedelta(days=1),
        )
        assert tomorrow.reserve(CHANNEL, "tomorrow").allowed
    finally:
        for store in stores:
            store.close()


def test_adapter_free_flag_rejects_wrong_endpoint_and_nonfree_model() -> None:
    for base, model in [
        ("https://paid.example/v1", MODEL),
        (BASE + "/", MODEL),
        (BASE, "paid"),
        (BASE, "openrouter/free"),
    ]:
        with pytest.raises(ValueError):
            OpenAiCompatibleAdapter(
                FallbackConfig(base, "test-key", model), free_only=True
            )


def test_production_factory_selects_configured_free_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alphabrief_trader import model_factory

    monkeypatch.delenv("ALPHABRIEF_AI_MODEL_PROVIDER", raising=False)
    monkeypatch.setattr(
        "alphabrief_models.channels.load_model_settings", lambda path=None: settings()
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        channels = model_factory.build_ai_trading_channels(
            daily_budget=ModelBudgetGuard(store, policy=settings().budget_policy())
        )
        assert channels.primary_channel == CHANNEL
        assert channels.gateway._providers[0].model_name == MODEL
    finally:
        store.close()


def test_catalog_numeric_underflow_is_not_free(tmp_path: Path) -> None:
    listing = HttpResponse(
        200,
        (
            '{"data":[{"id":"' + MODEL + '","pricing":'
            '{"prompt":1e-999,"completion":0}}]}'
        ).encode(),
    )
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        transport = Transport(listing)
        assert build(store, transport).invoke(request()).response is None
        assert len(transport.calls) == 1
    finally:
        store.close()


def test_free_gateway_cannot_enable_any_fallback() -> None:
    from alphabrief_models.gateway import FakeProviderAdapter, ModelGateway

    free = FakeProviderAdapter(provider_name=CHANNEL)
    with pytest.raises(ValueError, match="fallback"):
        ModelGateway([free], fallback_enabled=True)
    with pytest.raises(ValueError, match="fallback"):
        ModelGateway([free, FakeProviderAdapter()])


def test_transport_disables_redirects_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from email.message import Message
    from http.client import HTTPMessage
    from io import BytesIO
    from urllib.error import HTTPError
    from urllib.request import HTTPRedirectHandler

    from alphabrief_models import openai_compatible as compatible

    calls: list[Any] = []

    class Opener:
        def open(self, req: Any, timeout: float) -> Any:
            calls.append(req)
            raise HTTPError(
                req.full_url, 302, "redirect", Message(), BytesIO(b"{}")
            )

    def opener(*handlers: Any) -> Opener:
        redirect = next(h for h in handlers if isinstance(h, HTTPRedirectHandler))
        assert (
            redirect.redirect_request(
                Request("https://openrouter.ai/api/v1/models"),
                BytesIO(b""),
                302,
                "redirect",
                HTTPMessage(),
                "https://paid.example",
            )
            is None
        )
        return Opener()

    monkeypatch.setattr(compatible, "build_opener", opener)
    for method in ("GET", "POST"):
        response = compatible._free_http_send(method, BASE, {}, None, 1)
        assert response.status == 302
    assert len(calls) == 2


def test_failed_provider_payload_and_wrong_response_model_are_audited(
    tmp_path: Path,
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        transport = Transport(status=503)
        result = build(store, transport).invoke(request())
        assert result.record.audit_payload is not None
        assert result.record.audit_payload["provider_payload"]["model"] == MODEL

        class WrongModel(Transport):
            def __call__(
                self,
                method: str,
                url: str,
                headers: dict[str, str],
                body: bytes | None,
                timeout: float,
            ) -> HttpResponse:
                response = super().__call__(method, url, headers, body, timeout)
                if method == "GET":
                    return response
                payload = response.json()
                payload["model"] = "paid-model"
                return HttpResponse(200, json.dumps(payload).encode())

        wrong = WrongModel()
        result = build(store, wrong).invoke(request("wrong-model"))
        assert result.response is None
        assert result.record.model == MODEL and result.record.provider == CHANNEL
        assert result.record.audit_payload is not None
        assert result.record.audit_payload["provider_payload"]["model"] == "paid-model"
    finally:
        store.close()


def test_free_round_and_symbol_caps_are_unchanged(tmp_path: Path) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        budget = ModelBudgetGuard(
            store, policy=settings().budget_policy(), clock=lambda: NOW
        )
        kinds: tuple[tuple[ModelCallKind, int], ...] = (("normal", 5), ("repair", 2))
        for symbol in ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"):
            for kind, limit in kinds:
                for i in range(limit):
                    assert budget.reserve(
                        CHANNEL,
                        f"{symbol}-{kind}-{i}",
                        round_key="round",
                        symbol=symbol,
                        call_kind=kind,
                    ).allowed
                assert not budget.reserve(
                    CHANNEL,
                    f"overflow-{symbol}-{kind}",
                    round_key="round",
                    symbol=symbol,
                    call_kind=kind,
                ).allowed
        assert not budget.reserve(
            CHANNEL,
            "shadow-overflow",
            round_key="round",
            symbol="EUR_USD",
            call_kind="shadow",
        ).allowed
        assert store.round_usage("round")["total"] == 35
    finally:
        store.close()


def test_shipped_config_selects_the_pinned_free_primary() -> None:
    """The repository configuration is the reviewed free-primary selection."""
    config = Path(__file__).resolve().parents[1] / "config" / "alphabrief.yaml"
    shipped = load_model_settings(config)
    assert shipped.primary_channel == CHANNEL
    assert shipped.fallback_enabled is False
    assert shipped.primary_model is not None
    assert shipped.primary_model.endswith(":free")
    assert shipped.daily_cost_limit_usd == 0
    assert 0 < shipped.daily_call_limit <= 45
    # Reasoning models spend output tokens on reasoning before content.
    assert shipped.max_output_tokens >= 2048


def test_shipped_config_never_builds_without_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped free primary fails closed instead of routing paid."""
    config = Path(__file__).resolve().parents[1] / "config" / "alphabrief.yaml"
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "alphabrief_models.openai_compatible.read_secret", lambda name: None
    )
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_channel_gateway(settings=load_model_settings(config))


def test_primary_reporting_surfaces_do_not_read_chatgpt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from alphabrief_api.routes import settings as api_settings
    from alphabrief_cli import doctor_commands, model_commands

    def forbidden() -> None:
        raise AssertionError("inactive ChatGPT secret read")

    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        model_commands, "load_model_settings", lambda path=None: settings()
    )
    monkeypatch.setattr(
        api_settings, "load_model_settings", lambda path=None: settings()
    )
    monkeypatch.setattr(model_commands, "load_credentials", forbidden)
    monkeypatch.setattr(api_settings, "load_credentials", forbidden)
    monkeypatch.setattr("alphabrief_models.chatgpt_plan.load_credentials", forbidden)
    monkeypatch.setattr(api_settings, "_read_oanda_stored_creds", lambda: ("", ""))
    monkeypatch.setattr("alphabrief_cli.api_client.is_api_running", lambda: True)
    model_commands.status_cmd(pretty=False)
    status = json.loads(capsys.readouterr().out)
    assert status["primary"]["channel"] == CHANNEL
    assert status["primary"]["default_model"] == MODEL
    assert status["primary"]["authorized"] is True
    assert status["primary"]["pricing_verified"] is False
    overview = api_settings.get_settings_overview()
    assert overview["model_channel"]["primary_channel"] == CHANNEL
    assert overview["model_channel"]["primary_model"] == MODEL
    assert overview["model_channel"]["primary_configured"] is True
    assert doctor_commands.check_model_channel().status == "WARN"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert doctor_commands.check_model_channel().status == "FAIL"
