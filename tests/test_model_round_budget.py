"""Outbound normal/repair/round caps survive retries, fallback and restart."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_models import FakeProviderAdapter
from alphabrief_models.gateway import ModelGateway, ModelRequest, ModelResponse
from alphabrief_models.model_budget import ModelBudgetGuard, ModelCallKind
from alphabrief_models.repair import repair_structured_output
from alphabrief_trader import CommitteeInput, MarketSnapshot, model_factory
from alphabrief_trader.committee import TradingCommittee
from pydantic import BaseModel
from test_model_call_admission import NOW, Provider, guard, request, sink


def scoped(
    symbol: str = "EUR_USD", kind: ModelCallKind = "normal", round_key: str = "round-1"
) -> ModelRequest:
    return request().model_copy(
        update={
            "cycle_key": round_key,
            "metadata": {"symbol": symbol},
            "call_kind": kind,
        }
    )


@pytest.mark.parametrize("kind,limit", [("normal", 5), ("repair", 2)])
def test_symbol_caps_count_outbound_attempts(
    tmp_path: Path, kind: ModelCallKind, limit: int
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = Provider()
        gateway = ModelGateway(
            [provider], daily_budget=guard(store), record_sink=sink(store)
        )
        results = [gateway.invoke(scoped(kind=kind)) for _ in range(limit + 1)]
        assert provider.sent == limit
        assert results[-1].response is None
        assert results[-1].record.classification == "budget_exhausted"
        assert store.round_usage("round-1")[kind] == limit
        assert store.round_usage("round-1")["total"] == limit
    finally:
        store.close()


def test_five_symbols_share_35_calls_and_next_round_has_separate_capacity(
    tmp_path: Path,
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = Provider()
        gateway = ModelGateway(
            [provider], daily_budget=guard(store), record_sink=sink(store)
        )
        for symbol in ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"):
            for _ in range(5):
                assert gateway.invoke(scoped(symbol)).response is not None
            for _ in range(2):
                assert gateway.invoke(scoped(symbol, "repair")).response is not None
            assert store.round_usage("round-1", symbol=symbol) == {
                "total": 7,
                "normal": 5,
                "repair": 2,
            }
        assert gateway.invoke(scoped("NZD_USD")).response is None
        assert provider.sent == 35
        assert store.round_usage("round-1") == {"total": 35, "normal": 25, "repair": 10}
        assert gateway.invoke(scoped(round_key="round-2")).response is not None
        assert provider.sent == 36
    finally:
        store.close()


def test_unknown_admissions_survive_restart_and_utc_day_rollover(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calls.duckdb"
    store = ModelCallStore(database)
    for i in range(5):
        assert (
            guard(store)
            .reserve("chatgpt_plan", str(i), round_key="round-1", symbol="EUR_USD")
            .allowed
        )
    store.close()
    store = ModelCallStore(database)
    try:
        tomorrow = ModelBudgetGuard(store, clock=lambda: NOW + timedelta(days=1))
        provider = Provider()
        result = ModelGateway([provider], daily_budget=tomorrow).invoke(scoped())
        assert result.response is None and provider.sent == 0
        assert store.round_usage("round-1")["normal"] == 5
        assert tomorrow.reserve(
            "chatgpt_plan", "new-round", round_key="round-2", symbol="EUR_USD"
        ).allowed
    finally:
        store.close()


@pytest.mark.parametrize("kind,prior", [("normal", 4), ("repair", 1)])
def test_two_channels_cannot_both_take_last_symbol_slot(
    tmp_path: Path, kind: ModelCallKind, prior: int
) -> None:
    database = tmp_path / "calls.duckdb"
    stores = [ModelCallStore(database), ModelCallStore(database)]
    barrier = Barrier(2)
    try:
        for i in range(prior):
            assert (
                guard(stores[0])
                .reserve(
                    "chatgpt_plan",
                    f"seed-{i}",
                    round_key="round-1",
                    symbol="EUR_USD",
                    call_kind=kind,
                )
                .allowed
            )

        def reserve(index: int) -> bool:
            barrier.wait(timeout=5)
            return (
                guard(stores[index])
                .reserve(
                    "chatgpt_plan" if index == 0 else "openai_compatible",
                    str(index),
                    estimated_cost=Decimal("0.01"),
                    round_key="round-1",
                    symbol="EUR_USD",
                    call_kind=kind,
                )
                .allowed
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sum(pool.map(reserve, range(2))) == 1
        assert stores[0].round_usage("round-1")[kind] == prior + 1
    finally:
        for store in stores:
            store.close()


def test_two_channels_cannot_both_take_last_round_slot(tmp_path: Path) -> None:
    database = tmp_path / "calls.duckdb"
    stores = [ModelCallStore(database), ModelCallStore(database)]
    barrier = Barrier(2)
    try:
        for s in range(5):
            for i in range(5):
                assert (
                    guard(stores[0])
                    .reserve(
                        "chatgpt_plan",
                        f"normal-{s}-{i}",
                        round_key="round-1",
                        symbol=str(s),
                    )
                    .allowed
                )
            for i in range(2 if s < 4 else 1):
                assert (
                    guard(stores[0])
                    .reserve(
                        "chatgpt_plan",
                        f"repair-{s}-{i}",
                        round_key="round-1",
                        symbol=str(s),
                        call_kind="repair",
                    )
                    .allowed
                )
        assert stores[0].round_usage("round-1")["total"] == 34

        def reserve(index: int) -> bool:
            barrier.wait(timeout=5)
            return (
                guard(stores[index])
                .reserve(
                    "chatgpt_plan" if index == 0 else "openai_compatible",
                    f"last-{index}",
                    estimated_cost=Decimal("0.01"),
                    round_key="round-1",
                    symbol="LAST",
                )
                .allowed
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sum(pool.map(reserve, range(2))) == 1
        assert stores[0].round_usage("round-1")["total"] == 35
    finally:
        for store in stores:
            store.close()


def test_fallback_attempts_share_symbol_capacity(tmp_path: Path) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        primary = Provider(quota=True)
        fallback = Provider(
            "openai_compatible", cost=Decimal("0.01"), charged=Decimal("0.01")
        )
        gateway = ModelGateway(
            [primary, fallback],
            daily_budget=guard(store),
            record_sink=sink(store),
            fallback_enabled=True,
        )
        results = [gateway.invoke(scoped()) for _ in range(5)]
        assert primary.sent == 1 and fallback.sent == 4
        assert results[-1].response is None
        assert store.round_usage("round-1") == {"total": 5, "normal": 5, "repair": 0}
    finally:
        store.close()


def test_repair_request_keeps_scope_and_cannot_take_a_normal_slot(
    tmp_path: Path,
) -> None:
    class Output(BaseModel):
        accepted: bool

    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = Provider()
        result = repair_structured_output(
            gateway=ModelGateway(
                [provider], daily_budget=guard(store), record_sink=sink(store)
            ),
            request=scoped(),
            target=Output,
            raw_output="bad",
            failure_reason="invalid_json",
            max_attempts=10,
        )
        assert not result.ok and result.exhausted
        assert provider.sent == 2
        assert store.round_usage("round-1") == {"total": 2, "normal": 0, "repair": 2}
        assert (result.attempts[-1].error_code or "").startswith("model_budget:")
    finally:
        store.close()


def test_production_factory_shares_two_repairs_across_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[ModelRequest] = []

    class MalformedAnalysts(Provider):
        def call(self, request: ModelRequest) -> ModelResponse:
            seen.append(request)
            response = super().call(request)
            if (
                request.call_kind == "normal"
                and len([r for r in seen if r.call_kind == "normal"]) <= 3
            ):
                return response
            return response.model_copy(
                update={
                    "structured_output": {
                        "analysis": "Observed test evidence",
                        "view": "bullish",
                        "confidence": 0.8,
                        "evidence": [],
                        "risks": [],
                        "suggested_action": "buy",
                        "target_position_pct": "0.1",
                    }
                }
            )

    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = MalformedAnalysts()

        def channels(**kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                gateway=ModelGateway(
                    [provider],
                    daily_budget=kwargs["daily_budget"],
                    record_sink=kwargs["record_sink"],
                )
            )

        monkeypatch.setattr(model_factory, "build_ai_trading_channels", channels)
        committee = model_factory.build_ai_trading_committee(
            daily_budget=guard(store), record_sink=sink(store)
        )
        result = committee.run(
            CommitteeInput(
                snapshot=MarketSnapshot(
                    symbol="EUR_USD", reference_price=Decimal("1.1"), captured_at=NOW
                ),
                cycle_key="round-1",
            )
        )
        assert len(seen) == 7
        assert [r.call_kind for r in seen].count("normal") == 5
        assert [r.call_kind for r in seen].count("repair") == 2
        assert {r.cycle_key for r in seen} == {"round-1"}
        assert len(result.repair_attempts) == 2
        assert not result.ok and result.plan is None
        assert "model_budget_exhausted" == result.error_message
        assert store.round_usage("round-1") == {"total": 7, "normal": 5, "repair": 2}
    finally:
        store.close()


def test_legacy_reservation_schema_migrates_without_releasing_unknown_calls(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calls.duckdb"
    conn = duckdb.connect(str(database))
    conn.execute(
        """CREATE TABLE model_call_reservations (call_id TEXT PRIMARY KEY,
        provider TEXT, created_at TIMESTAMPTZ, reserved_cost DECIMAL(38,18))"""
    )
    conn.execute(
        "INSERT INTO model_call_reservations VALUES "
        "('legacy', 'chatgpt_plan', ?, NULL)",
        [NOW],
    )
    conn.close()
    store = ModelCallStore(database)
    try:
        assert not guard(store, limit=1).reserve("chatgpt_plan", "new").allowed
        assert store.round_usage("round-1")["total"] == 0
    finally:
        store.close()


def test_legacy_round_record_with_missing_scope_fails_closed(tmp_path: Path) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = Provider()
        ModelGateway([provider], record_sink=sink(store), clock=lambda: NOW).invoke(
            scoped()
        )
        result = ModelGateway(
            [provider], daily_budget=guard(store), record_sink=sink(store)
        ).invoke(scoped())
        assert provider.sent == 1 and result.response is None
        assert store.round_usage("round-1")["total"] == 0
    finally:
        store.close()


@pytest.mark.parametrize(
    "round_key,symbol,kind",
    [
        (None, None, "repair"),
        ("round-1", None, "normal"),
        ("round-1", "eur_usd", "normal"),
        (" round-1 ", "EUR_USD", "normal"),
    ],
)
def test_missing_or_ambiguous_scope_never_reserves_capacity(
    tmp_path: Path,
    round_key: str | None,
    symbol: str | None,
    kind: ModelCallKind,
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        verdict = guard(store).reserve(
            "chatgpt_plan",
            "invalid",
            round_key=round_key,
            symbol=symbol,
            call_kind=kind,
        )
        assert not verdict.allowed
        assert store.daily_usage(NOW.replace(hour=0)) == {}
    finally:
        store.close()


def test_optional_discussion_cannot_hide_an_outbound_budget_refusal(
    tmp_path: Path,
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = FakeProviderAdapter(
            provider_name="chatgpt_plan",
            capabilities=["structured_output"],
            structured_output={
                "analysis": "Observed test inputs",
                "view": "bullish",
                "confidence": 0.8,
                "evidence": [],
                "risks": [],
                "suggested_action": "buy",
                "target_position_pct": "0.1",
            },
        )
        gateway = ModelGateway(
            [provider], daily_budget=guard(store), record_sink=sink(store)
        )
        result = TradingCommittee(gateway, max_turns=10, challenge_rounds=1).run(
            CommitteeInput(
                snapshot=MarketSnapshot(
                    symbol="EUR_USD", reference_price=Decimal("1.1"), captured_at=NOW
                ),
                cycle_key="round-1",
            )
        )
        assert store.round_usage("round-1") == {"normal": 5, "repair": 0, "total": 5}
        assert len([r for r in gateway.call_records if r.status == "succeeded"]) == 5
        assert not result.ok and result.plan is None
        assert result.error_message == "model_budget_exhausted"
        assert any(": model_budget:" in error for error in result.role_errors)
    finally:
        store.close()
