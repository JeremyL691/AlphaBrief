"""Persistent emergency activation, production exit dispatch and entry refusal."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest
from _helpers import FakeExecutionBackend
from alphabrief_api.main import create_app
from alphabrief_api.routes import risk as risk_routes
from alphabrief_cli import (
    api_client,
    cycle_commands,
    risk_commands,
    run_commands,
    scheduler_commands,
)
from alphabrief_core import paths
from alphabrief_risk import DrawdownState, DrawdownStateStore, KillSwitchStore
from alphabrief_risk.kill_switch import load_persisted_kill_switch, observe_drawdown
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.execution_backend import (
    ExecutionBackendError,
    ExternalPaperExecutionBackend,
)
from fastapi.testclient import TestClient
from test_ai_trader_execution_backend import _decision, _FakeAdapter, _intent
from test_cycle_sizing_and_close import _account_context
from test_risk_gate_close_path import _close_intent, _context, _hostile_gate
from test_runtime_position_exit import NOW, Client, install, trade
from typer.testing import CliRunner

D = Decimal


@pytest.fixture(autouse=True)
def isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    risk_routes._reset_risk_gate()
    yield
    risk_routes._reset_risk_gate()


def seed_peak() -> None:
    store = DrawdownStateStore()
    try:
        store.save(
            "test-account",
            DrawdownState(
                high_water=D("100000"),
                updated_at=NOW,
            ),
        )
    finally:
        store.close()


def activate(*, automatic: bool = False) -> dict[str, Any]:
    store = KillSwitchStore()
    try:
        return store.activate(reason="emergency test", automatic=automatic)
    finally:
        store.close()


def test_automatic_halt_cannot_be_overwritten_or_released_on_restart() -> None:
    first = activate(automatic=True)
    store = KillSwitchStore()
    try:
        assert store.activate(reason="operator retry") == first
        assert store.activate(reason="new observation", automatic=True) == first
        with pytest.raises(
            ValueError, match="automatic_kill_switch_cannot_be_released"
        ):
            store.deactivate(reason="recovered NAV")
        assert store.load() == first
    finally:
        store.close()
    assert load_persisted_kill_switch().active is True


def test_legacy_store_migration_preserves_observed_activation() -> None:
    path = paths.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    conn.execute(
        "CREATE TABLE kill_switch_state (scope TEXT PRIMARY KEY, "
        "active BOOLEAN, reason TEXT, updated_at TIMESTAMPTZ)"
    )
    conn.execute(
        "INSERT INTO kill_switch_state VALUES ('default', true, ?, ?)",
        ["legacy operator halt", NOW],
    )
    conn.close()
    readonly = KillSwitchStore(read_only=True)
    try:
        state = readonly.load()
        assert state is not None and state["automatic"] is False
        assert state["active"] is True and state["reason"] == "legacy operator halt"
    finally:
        readonly.close()
    store = KillSwitchStore()
    try:
        assert store.load() == state
        assert store.deactivate(reason="verified release")["active"] is False
    finally:
        store.close()


@pytest.mark.parametrize(
    "nav,halt",
    [("97000", False), ("95000.01", False), ("95000", True), ("90000", True)],
)
def test_exact_drawdown_boundary_and_latched_recovery(nav: str, halt: bool) -> None:
    seed_peak()
    verdict = observe_drawdown(account_id="test-account", nav=D(nav), now=NOW)
    assert (verdict.state.state == "soak_halted") is halt
    assert load_persisted_kill_switch().active is halt
    if halt:
        recovered = observe_drawdown(
            account_id="test-account", nav=D("100100"), now=NOW + timedelta(minutes=1)
        )
        assert recovered.state.state == "soak_halted"
        assert load_persisted_kill_switch().active is True


@pytest.mark.parametrize("nav", [D("NaN"), D("Infinity"), D("-1"), None, 95000.0])
def test_invalid_nav_never_fabricates_drawdown_or_halt(nav: Any) -> None:
    with pytest.raises(ValueError, match="drawdown_nav_invalid"):
        observe_drawdown(account_id="test-account", nav=nav, now=NOW)
    assert not paths.db_path().exists()


def test_future_drawdown_state_is_not_treated_as_normal() -> None:
    store = DrawdownStateStore()
    try:
        store.save(
            "test-account",
            DrawdownState(
                high_water=D("100000"),
                updated_at=NOW + timedelta(seconds=1),
            ),
        )
    finally:
        store.close()
    with pytest.raises(ValueError, match="drawdown_state_invalid"):
        observe_drawdown(account_id="test-account", nav=D("95000"), now=NOW)


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("units", ["1000", "-1000"])
def test_emergency_monitor_closes_young_long_and_short(
    monkeypatch: pytest.MonkeyPatch, automatic: bool, units: str
) -> None:
    client = Client([trade(1, age=1, units=units)], units=units)
    submitted = install(monkeypatch, client)
    if automatic:
        seed_peak()
        client.nav = "95000"
    else:
        activate()
    report = cycle_commands.close_due_positions(now=NOW, trading="on")
    assert len(submitted) == 1
    assert submitted[0]["position_units"] == D(units)
    assert submitted[0]["reason"].startswith("kill switch:")
    assert report["due"][0]["should_close"] is True
    assert load_persisted_kill_switch().active is True
    assert len(client.calls) >= 5


def test_empty_account_observation_still_detects_automatic_halt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_peak()
    client = Client([], units="0")
    client.nav = "95000"
    submitted = install(monkeypatch, client)
    report = cycle_commands.close_due_positions(now=NOW, trading="on")
    assert report["closed"] == [] and submitted == []
    assert load_persisted_kill_switch().active is True


def test_reporting_off_does_not_advance_drawdown_or_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_peak()
    client = Client([trade(1, age=1)])
    client.nav = "95000"
    submitted = install(monkeypatch, client)
    cycle_commands.close_due_positions(now=NOW, trading="off")
    assert submitted == []
    assert load_persisted_kill_switch().active is False


def test_mismatched_native_account_never_changes_state_or_submits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client([trade(1)])
    client.account_id = "different-account"
    submitted = install(monkeypatch, client)
    with pytest.raises(ValueError, match="holding_account_mismatch"):
        cycle_commands.close_due_positions(now=NOW, trading="on")
    assert submitted == [] and not paths.db_path().exists()


@pytest.mark.parametrize(
    "age,tradeable,tag", [(60, True, "QUOTE_STALE"), (1, False, "NOT_TRADEABLE")]
)
def test_active_stop_never_bypasses_quote_rules(
    age: int, tradeable: bool, tag: str
) -> None:
    gate = _hostile_gate(kill_switch=load_persisted_kill_switch())
    gate.kill_switch.activate("emergency")
    result = gate.evaluate(
        _close_intent(),
        estimated_price=D("1.1"),
        account_context=_context(quote_age_seconds=age, tradeable=tradeable),
    )
    assert result.approved is False
    assert tag in result.risk_tags


def test_production_gate_refreshes_stop_after_it_was_constructed() -> None:
    gate = cycle_commands._risk_gate(("EUR_USD",))
    assert gate.kill_switch.active is False
    activate()
    decision = gate.evaluate(
        _close_intent(reduce_only=False, side="buy"), estimated_price=D("1.1")
    )
    assert decision.approved is False and "kill_switch" in decision.risk_tags
    assert gate.kill_switch.active is True


def test_gate_refuses_entries_when_stop_provider_fails() -> None:
    def unavailable() -> Any:
        raise OSError("test unavailable")

    gate = _hostile_gate()
    gate.kill_switch_provider = unavailable
    decision = gate.evaluate(
        _close_intent(reduce_only=False),
        estimated_price=D("1.1"),
        account_context=_context(),
    )
    assert not decision.approved and "kill_switch_unavailable" in decision.risk_tags


@pytest.mark.parametrize("reduce_only", [False, True])
def test_execution_hop_rereads_stop_after_approval(reduce_only: bool) -> None:
    adapter = _FakeAdapter()
    backend = ExternalPaperExecutionBackend(
        adapter, kill_switch_provider=load_persisted_kill_switch
    )
    decision = _decision()
    activate()
    intent = _intent().model_copy(update={"reduce_only": reduce_only})
    if reduce_only:
        result = backend.submit(
            intent,
            decision,
            reference_price=D("50"),
            now=NOW,
            estimated_quantity=D("2"),
        )
        assert result.broker_order_id == "broker-ai_test"
        assert len(adapter.requests) == 1 and adapter.requests[0].reduce_only is True
    else:
        with pytest.raises(ExecutionBackendError, match="KILL_SWITCH"):
            backend.submit(
                intent,
                decision,
                reference_price=D("50"),
                now=NOW,
                estimated_quantity=D("2"),
            )
        assert adapter.requests == []


def test_execution_hop_refuses_unknown_stop_state() -> None:
    def unavailable() -> Any:
        raise OSError("test unavailable")

    adapter = _FakeAdapter()
    backend = ExternalPaperExecutionBackend(adapter, kill_switch_provider=unavailable)
    with pytest.raises(ExecutionBackendError, match="KILL_SWITCH_UNAVAILABLE"):
        backend.submit(
            _intent(),
            _decision(),
            reference_price=D("50"),
            now=NOW,
            estimated_quantity=D("2"),
        )
    assert adapter.requests == []


def test_confirmed_api_activation_persists_before_resident_exit() -> None:
    calls: list[bool] = []
    runtime = run_commands.Runtime(
        host="127.0.0.1",
        port=0,
        universe=("EUR_USD",),
        position_monitor=lambda: calls.append(load_persisted_kill_switch().active),
    )
    app = create_app()
    app.state.request_position_exit = runtime._run_position_monitor
    risk_routes.configure_runtime_risk()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/risk/kill-switch",
            json={
                "active": True,
                "confirmed": True,
                "reason": "operator emergency",
            },
        )
        assert response.status_code == 200
        assert response.json()["close_requested"] is True
        assert calls == [True]
        assert "closed" not in response.json()
        assert client.get("/api/v1/risk/dashboard").json()["kill_switch_active"] is True
        released = client.post(
            "/api/v1/risk/kill-switch",
            json={
                "active": False,
                "confirmed": True,
                "reason": "verified incident resolved",
            },
        )
        assert released.status_code == 200
        assert released.json()["close_requested"] is False and calls == [True]
        assert client.get("/api/v1/risk/kill-switch").json()["active"] is False


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"active": True, "reason": "x"}, 422),
        ({"active": True, "confirmed": False, "reason": "x"}, 400),
        ({"active": True, "confirmed": "true", "reason": "x"}, 422),
        ({"active": True, "confirmed": True, "reason": "  "}, 400),
    ],
)
def test_api_requires_explicit_confirmation_and_reason(
    payload: dict[str, Any], status: int
) -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/risk/kill-switch", json=payload)
    assert response.status_code == status and not paths.db_path().exists()


def test_standalone_api_cannot_mutate_switch() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/risk/kill-switch",
            json={
                "active": True,
                "confirmed": True,
                "reason": "operator emergency",
            },
        )
    assert response.status_code == 503 and not paths.db_path().exists()


def test_api_cannot_release_automatic_stop() -> None:
    initial = activate(automatic=True)
    app = create_app()
    app.state.request_position_exit = lambda: None
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/risk/kill-switch",
            json={
                "active": False,
                "confirmed": True,
                "reason": "NAV recovered",
            },
        )
        assert response.status_code == 409
        assert client.get("/api/v1/risk/kill-switch").json() == initial


def test_cli_offline_is_read_only_and_preserves_switch() -> None:
    initial = activate()
    runner = CliRunner()
    result = runner.invoke(risk_commands.risk_app, ["kill-switch", "--deactivate"])
    assert result.exit_code == 3
    state = runner.invoke(risk_commands.risk_app, ["kill-switch", "--compact"])
    assert state.exit_code == 0 and json.loads(state.output) == initial
    status = runner.invoke(risk_commands.risk_app, ["status"])
    assert json.loads(status.output)["kill_switch_active"] is True
    readonly = KillSwitchStore(read_only=True)
    try:
        with pytest.raises(ValueError, match="read_only"):
            readonly.deactivate(reason="forbidden write")
    finally:
        readonly.close()


def test_cli_online_only_calls_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_client, "is_api_running", lambda: True)
    requests: list[dict[str, Any]] = []

    def http(**kwargs: Any) -> dict[str, Any]:
        requests.append(kwargs)
        return {"active": True, "close_requested": True}

    monkeypatch.setattr(api_client, "api_kill_switch", http)
    result = CliRunner().invoke(
        risk_commands.risk_app,
        [
            "kill-switch",
            "--activate",
            "--reason",
            "operator emergency",
        ],
    )
    assert result.exit_code == 0
    assert requests == [{"active": True, "reason": "operator emergency"}]
    assert not paths.db_path().exists()


def test_runtime_start_registers_shared_exit_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    monkeypatch.setattr("alphabrief_api.main.create_app", lambda: app)
    runtime = run_commands.Runtime(host="127.0.0.1", port=0, universe=("EUR_USD",))

    async def scheduler() -> Any:
        return object()

    monkeypatch.setattr(runtime, "_build_scheduler", scheduler)
    asyncio.run(runtime.start())
    assert app.state.request_position_exit == runtime._run_position_monitor
    assert risk_routes._get_risk_gate().kill_switch_provider is not None


@pytest.mark.parametrize(
    "mode",
    [
        "manual",
        "automatic",
        "corrupt_drawdown_manual",
        "corrupt_drawdown_time",
    ],
)
def test_default_monitor_emergency_exit_uses_real_gate_and_attempt_audit(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    native = Client(
        [trade(1, age=48 if mode == "corrupt_drawdown_time" else 1, units="-1000")],
        units="-1000",
    )
    original_close = cycle_commands._close_through_the_cycle
    install(monkeypatch, native)
    monkeypatch.setattr(cycle_commands, "_close_through_the_cycle", original_close)
    monkeypatch.setattr(scheduler_commands, "trading_mode", lambda: "on")
    source = SimpleNamespace(
        account_exposure_context=lambda **kwargs: _account_context(
            frozen={"EUR_USD": "unexplained difference"}
        )
    )
    monkeypatch.setattr(
        cycle_commands,
        "_risk_sources",
        lambda *a, **k: source,
    )
    factory = cycle_commands._risk_gate

    def production_gate(symbols: tuple[str, ...]) -> Any:
        gate = factory(symbols)
        gate.clock = lambda: NOW
        return gate

    monkeypatch.setattr(cycle_commands, "_risk_gate", production_gate)
    backend = FakeExecutionBackend()
    monkeypatch.setattr(cycle_commands, "_execution_backend", lambda **k: backend)

    class Clock:
        @staticmethod
        def now(tz: Any = None) -> Any:
            return NOW

    monkeypatch.setattr(cycle_commands, "datetime", Clock)
    if mode == "automatic":
        seed_peak()
        native.nav = "95000"
    elif mode != "corrupt_drawdown_time":
        activate()
    if mode.startswith("corrupt"):
        seed_peak()
        conn = duckdb.connect(str(paths.db_path()))
        conn.execute("UPDATE ai_drawdown_state SET high_water='bad'")
        conn.close()
        with pytest.raises(RuntimeError, match="drawdown_observation_unavailable"):
            run_commands.position_monitor_once(now=NOW)
    else:
        assert run_commands.position_monitor_once(now=NOW) == 1
    store = AiTradingStore(paths.db_path())
    try:
        rows = store.list_cycles()
        assert len(rows) == 1
        saved = store.get_cycle(rows[0].cycle_id)
        assert saved is not None
        attempt = saved["attempts"][0]
        assert saved["votes"] == [] and saved["plans"] == []
        assert attempt["outcome"] == "executed" and attempt["filled"] is True
        if mode != "corrupt_drawdown_time":
            assert "kill_switch_reduce_only" in attempt["risk_tags"]
        intent = attempt["order_intent_json"]
        assert intent["reduce_only"] is True and intent["side"] == "buy"
        assert intent["quantity"] == "1000"
        assert (
            attempt["risk_decision_json"]["decision_id"] == attempt["risk_decision_id"]
        )
        assert backend.submission_count == 1
    finally:
        store.close()


def test_unknown_drawdown_does_not_authorize_exiting_young_holdings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_peak()
    conn = duckdb.connect(str(paths.db_path()))
    conn.execute("UPDATE ai_drawdown_state SET high_water='bad'")
    conn.close()
    submitted = install(monkeypatch, Client([trade(1, age=1)]))
    report = cycle_commands.close_due_positions(now=NOW, trading="on")
    assert submitted == [] and report["due"] == []
    assert report["drawdown_error"] == "drawdown_observation_unavailable"


def test_manually_active_stop_closes_despite_broken_drawdown_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activate()
    seed_peak()
    conn = duckdb.connect(str(paths.db_path()))
    conn.execute("UPDATE ai_drawdown_state SET high_water='bad'")
    conn.close()
    submitted = install(monkeypatch, Client([trade(1, age=1)]))
    report = cycle_commands.close_due_positions(now=NOW, trading="on")
    assert len(submitted) == 1 and report["closed"][0]["closed"] is True
    assert report["drawdown_error"] == "drawdown_observation_unavailable"


def test_manual_stop_still_observes_and_latches_five_percent_drawdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activate()
    seed_peak()
    native = Client([trade(1, age=1)])
    native.nav = "95000"
    submitted = install(monkeypatch, native)
    report = cycle_commands.close_due_positions(now=NOW, trading="on")
    assert len(submitted) == 1 and report["drawdown_error"] is None
    store = KillSwitchStore()
    try:
        state = store.load()
        assert state is not None and state["active"] and state["automatic"]
        with pytest.raises(
            ValueError, match="automatic_kill_switch_cannot_be_released"
        ):
            store.deactivate(reason="operator resolved manual incident")
    finally:
        store.close()


def test_persisted_drawdown_blocks_release_even_before_switch_activation() -> None:
    activate()
    seed_peak()
    store = DrawdownStateStore()
    try:
        store.save(
            "test-account",
            DrawdownState(
                state="soak_halted",
                high_water=D("100000"),
                updated_at=NOW,
            ),
        )
    finally:
        store.close()
    switch = KillSwitchStore()
    try:
        with pytest.raises(
            ValueError, match="automatic_kill_switch_cannot_be_released"
        ):
            switch.deactivate(reason="restart after incomplete activation")
        assert load_persisted_kill_switch().active is True
    finally:
        switch.close()


@pytest.mark.parametrize("active", [None, True, False])
def test_cli_http_payload_is_explicit_and_has_timeout(
    monkeypatch: pytest.MonkeyPatch, active: bool | None
) -> None:
    requests: list[urllib.request.Request] = []

    def respond(request: urllib.request.Request, timeout: int) -> BytesIO:
        assert timeout == 10
        requests.append(request)
        return BytesIO(b'{"active":true}')

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    assert api_client.api_kill_switch(active=active, reason="operator emergency") == {
        "active": True,
    }
    assert len(requests) == 1
    if active is None:
        assert requests[0].get_method() == "GET" and requests[0].data is None
    else:
        assert requests[0].get_method() == "POST"
        data = requests[0].data
        assert isinstance(data, bytes)
        assert json.loads(data) == {
            "active": active,
            "reason": "operator emergency",
            "confirmed": True,
        }
    assert not paths.db_path().exists()


@pytest.mark.parametrize("failure", [TimeoutError(), urllib.error.URLError("offline")])
def test_online_cli_failure_never_falls_back_to_local_mutation(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setattr(api_client, "is_api_running", lambda: True)
    called: list[int] = []

    def fail(request: Any, timeout: int) -> Any:
        called.append(timeout)
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    result = CliRunner().invoke(
        risk_commands.risk_app,
        [
            "kill-switch",
            "--activate",
            "--reason",
            "operator emergency",
        ],
    )
    assert result.exit_code == 1 and called == [10]
    assert not paths.db_path().exists()


def test_api_persistence_failure_never_dispatches_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched: list[bool] = []
    app = create_app()
    app.state.request_position_exit = lambda: dispatched.append(True)

    def unavailable(*a: Any, **k: Any) -> Any:
        raise OSError("test private storage path")

    monkeypatch.setattr(risk_routes, "KillSwitchStore", unavailable)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/risk/kill-switch",
            json={
                "active": True,
                "confirmed": True,
                "reason": "operator emergency",
            },
        )
    assert response.status_code == 503 and dispatched == []
    assert "private" not in response.text


def test_automatic_activation_persistence_failure_cannot_become_normal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_risk import kill_switch as switch_module

    seed_peak()
    original = switch_module.KillSwitchStore

    def unavailable(*a: Any, **k: Any) -> Any:
        raise OSError("unavailable")

    monkeypatch.setattr(switch_module, "KillSwitchStore", unavailable)
    with pytest.raises(OSError):
        observe_drawdown(account_id="test-account", nav=D("95000"), now=NOW)
    monkeypatch.setattr(switch_module, "KillSwitchStore", original)
    recovered = observe_drawdown(account_id="test-account", nav=D("100100"), now=NOW)
    assert recovered.state.state == "soak_halted"
    assert load_persisted_kill_switch().active is True


def test_entry_and_monitor_observations_serialize_persistent_drawdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_peak()
    first_loaded, second_started, second_loaded, release = (
        Event(),
        Event(),
        Event(),
        Event(),
    )
    original = DrawdownStateStore.load
    calls: list[str] = []

    def load(store: DrawdownStateStore, account_id: str) -> DrawdownState | None:
        state = original(store, account_id)
        calls.append(account_id)
        if len(calls) == 1:
            first_loaded.set()
            assert release.wait(3)
        else:
            second_loaded.set()
        return state

    monkeypatch.setattr(DrawdownStateStore, "load", load)

    def halt() -> Any:
        second_started.set()
        return observe_drawdown(account_id="test-account", nav=D("95000"), now=NOW)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(
            observe_drawdown, account_id="test-account", nav=D("100100"), now=NOW
        )
        try:
            assert first_loaded.wait(3)
            second = workers.submit(halt)
            assert second_started.wait(3)
            assert not second_loaded.wait(0.05)
        finally:
            release.set()
        assert first.result(timeout=3).state.state == "normal"
        assert second.result(timeout=3).state.state == "soak_halted"
    store = DrawdownStateStore()
    try:
        state = original(store, "test-account")
        assert state is not None and state.state == "soak_halted"
        assert state.high_water == D("100100")
    finally:
        store.close()


@pytest.mark.parametrize(
    "account_id,nav,error",
    [
        ("different-account", D("95000"), "drawdown_account_mismatch"),
        ("test-account", None, "drawdown_nav_invalid"),
    ],
)
def test_entry_drawdown_refuses_unknown_or_mismatched_facts(
    monkeypatch: pytest.MonkeyPatch, account_id: str, nav: Any, error: str
) -> None:
    monkeypatch.setattr(
        "alphabrief_execution.broker.oanda.config.read_oanda_credentials",
        lambda: ("test-token", "test-account"),
    )
    sources = SimpleNamespace(
        account_exposure_context=lambda: SimpleNamespace(
            account_id=account_id,
            equity=nav,
        )
    )
    with pytest.raises(ValueError, match=error):
        cycle_commands._drawdown_verdict(sources)
    assert not paths.db_path().exists()


def test_entry_drawdown_uses_same_persistent_automatic_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_peak()
    monkeypatch.setattr(
        "alphabrief_execution.broker.oanda.config.read_oanda_credentials",
        lambda: ("test-token", "test-account"),
    )
    sources = SimpleNamespace(
        account_exposure_context=lambda: SimpleNamespace(
            account_id="test-account",
            equity=D("95000"),
        )
    )
    verdict = cycle_commands._drawdown_verdict(sources)
    assert verdict.state.state == "soak_halted"
    assert load_persisted_kill_switch().active is True
