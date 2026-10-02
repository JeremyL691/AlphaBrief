"""GUIDE manager JSON reaches deterministic actions and protective orders."""

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from _helpers import FakeExecutionBackend
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import CommitteeInput, MarketSnapshot, TradingCommittee
from alphabrief_trader.daily_cycle import DailyTradingCycle
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.schemas import DailyCycleRecord
from test_broker_input_quality import NOW, facts

D = Decimal
ZERO = D(0)


class RawManager(FakeProviderAdapter):
    """Raw JSON only, no legacy conversion or fixture helper."""

    def __init__(
        self,
        action: str = "open_long",
        *,
        changes: dict[str, Any] | None = None,
        missing: str | None = None,
        bad_json: bool = False,
        supporters: int = 4,
        risk_veto: bool = False,
    ) -> None:
        super().__init__(capabilities=["structured_output"])
        self.action = action
        self.changes = changes or {}
        self.missing = missing
        self.bad_json = bad_json
        self.supporters = supporters
        self.risk_veto = risk_veto
        self.requests: list[ModelRequest] = []

    def call(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        role = request.metadata["committee_role"]
        available = json.loads(request.metadata["available_evidence_ids"])
        evidence = [available[0]]
        if role == "manager":
            output: dict[str, Any] = {
                "action": self.action,
                "confidence": 0.8,
                "stop_atr_multiple": 2.5,
                "take_profit_r_multiple": 1.2,
                "rationale": "Actual evidence supports the bounded decision.",
                "evidence_ids": evidence,
            }
            if request.call_kind != "repair":
                output.update(self.changes)
                if self.missing:
                    output.pop(self.missing)
        else:
            ordinal = ["technical", "macro_news", "intermarket", "risk"].index(role)
            supporting = "short" if self.action == "open_short" else "long"
            output = {
                "stance": supporting
                if ordinal < self.supporters
                else ("long" if supporting == "short" else "short"),
                "confidence": 0.8,
                "horizon_hours": 24,
                "key_points": ["Actual evidence supports this opinion."],
                "evidence_ids": evidence,
                "veto": role == "risk" and self.risk_veto,
            }
        text = json.dumps(output)
        if role == "manager" and self.bad_json and request.call_kind != "repair":
            text = "not JSON"
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text=text,
            finish_reason="stop",
        )


def snapshot(units: Decimal = ZERO) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EUR_USD",
        reference_price=D("1.1"),
        atr=D("0.001"),
        captured_at=NOW,
        broker_evidence=facts().model_copy(update={"position_units": units}),
    )


def committee(
    provider: RawManager, *, repairs: int = 0
) -> tuple[TradingCommittee, ModelGateway]:
    gateway = ModelGateway([provider])
    return TradingCommittee(
        gateway=gateway,
        max_turns=5,
        challenge_rounds=0,
        repair_attempts=repairs,
        clock=lambda: NOW,
    ), gateway


@pytest.mark.parametrize(
    "action", ["open_long", "open_short", "close", "hold", "no_trade"]
)
def test_all_actions_have_native_audit_and_persisted_identity(
    tmp_path: Path, action: str
) -> None:
    provider = RawManager(action)
    engine, gateway = committee(provider)
    result = engine.run(CommitteeInput(snapshot=snapshot()))
    assert result.ok and result.plan is not None
    manager = result.votes[-1]
    assert manager.manager_action == action and result.plan.action == action
    assert manager.target_position_pct == 0  # The manager cannot propose a size.
    assert result.plan.manager_call_id == manager.model_call_id
    assert result.plan.stop_atr_multiple == D("2.5")
    assert result.plan.take_profit_r_multiple == D("1.2")
    assert "Actual evidence supports" in result.plan.rationale
    event = gateway.validation_records[-1]
    assert event.verdict == "accepted" and event.call_id == manager.model_call_id
    assert event.parsed_output is not None and event.parsed_output["action"] == action
    assert set(event.parsed_output) == {
        "action",
        "confidence",
        "stop_atr_multiple",
        "take_profit_r_multiple",
        "rationale",
        "evidence_ids",
    }
    database = tmp_path / "decisions.duckdb"
    store = AiTradingStore(db_path=database)
    store.save_cycle(
        DailyCycleRecord(
            cycle_id="native-manager",
            trading_day="2026-10-02",
            symbols=["EUR_USD"],
            plans=[result.plan],
            votes=result.votes,
            outcome="skipped_no_intent",
            enabled=True,
            summary="Native manager audit",
            created_at=NOW,
        )
    )
    store.close()
    reader = AiTradingStore(db_path=database)
    try:
        saved = reader.get_cycle("native-manager")
        assert saved is not None and saved["plans"][0]["action"] == action
        assert saved["plans"][0]["manager_call_id"] == manager.model_call_id
        assert saved["votes"][-1]["manager_action"] == action
        assert saved["votes"][-1]["stop_atr_multiple"] == "2.5"
    finally:
        reader.close()


@pytest.mark.parametrize(
    "missing", ["action", "confidence", "rationale", "evidence_ids"]
)
def test_required_fields_missing_produce_no_plan(missing: str) -> None:
    engine, gateway = committee(RawManager(missing=missing))
    result = engine.run(CommitteeInput(snapshot=snapshot()))
    assert result.plan is None and len(result.votes) == 4
    assert gateway.validation_records[-1].verdict == "schema_rejected"


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "buy"},
        {"action": "liquidate"},
        {"action": None},
        {"confidence": "0.8"},
        {"confidence": True},
        {"confidence": -1},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"rationale": "  "},
        {"rationale": 42},
        {"stop_atr_multiple": "2"},
        {"stop_atr_multiple": True},
        {"stop_atr_multiple": float("nan")},
        {"take_profit_r_multiple": None},
        {"take_profit_r_multiple": float("inf")},
        {"target_position_pct": 0.5},
        {"suggested_action": "buy"},
        {"needs_human_review": False},
        {"veto": False},
        {"evidence_ids": ["invented:missing"]},
    ],
)
def test_invalid_or_legacy_outputs_cannot_authorize_a_plan(
    changes: dict[str, Any],
) -> None:
    engine, gateway = committee(RawManager(changes=changes))
    result = engine.run(CommitteeInput(snapshot=snapshot()))
    assert result.plan is None and len(result.votes) == 4
    assert gateway.validation_records[-1].verdict in {
        "schema_rejected",
        "grounding_rejected",
    }


@pytest.mark.parametrize("kind", ["json", "schema", "evidence"])
def test_successful_repair_preserves_actual_manager_call(kind: str) -> None:
    changes: dict[str, dict[str, Any]] = {
        "schema": {"action": "buy"},
        "evidence": {"evidence_ids": ["bad"]},
    }
    provider = RawManager(bad_json=kind == "json", changes=changes.get(kind))
    engine, gateway = committee(provider, repairs=2)
    result = engine.run(CommitteeInput(snapshot=snapshot()))
    assert result.ok and result.plan is not None
    assert len(provider.requests) == 6 and len(result.repair_attempts) == 1
    assert result.repair_attempts[0].ok
    assert result.plan.manager_call_id == gateway.call_records[-1].call_id
    assert gateway.validation_records[-1].verdict == "accepted"
    assert gateway.validation_records[-2].verdict != "accepted"
    assert '"action"' in provider.requests[-1].input_text


@pytest.mark.parametrize(
    "field,expected", [("stop_atr_multiple", "1.5"), ("take_profit_r_multiple", "2.0")]
)
def test_omitted_advice_uses_specified_default(field: str, expected: str) -> None:
    engine, gateway = committee(RawManager(missing=field))
    result = engine.run(CommitteeInput(snapshot=snapshot()))
    assert result.plan is not None and getattr(result.plan, field) == D(expected)
    schema = gateway.validation_records[-1].target_schema["properties"][field]
    assert schema["type"] == "number" and "anyOf" not in schema
    assert schema["default"] == float(expected)


@pytest.mark.parametrize(
    "supporters,confidence,veto,expected",
    [
        (2, 0.55, False, "open_long"),
        (1, 0.8, False, "no_trade"),
        (2, 0.549, False, "no_trade"),
        (4, 0.8, True, "no_trade"),
    ],
)
def test_direction_is_exact_and_confidence_and_risk_veto_are_absolute(
    supporters: int,
    confidence: float,
    veto: bool,
    expected: str,
) -> None:
    engine, _ = committee(
        RawManager(
            supporters=supporters, changes={"confidence": confidence}, risk_veto=veto
        )
    )
    result = engine.run(CommitteeInput(snapshot=snapshot()))
    assert result.plan is not None and result.plan.action == expected
    assert (result.plan.target_position_pct > 0) == (expected == "open_long")


@pytest.mark.parametrize(
    "requested,units,effective,count,side",
    [
        ("open_long", "10", "hold", 0, None),
        ("open_short", "-10", "hold", 0, None),
        ("open_long", "-10", "close", 1, "buy"),
        ("open_short", "10", "close", 1, "sell"),
        ("close", "10", "close", 1, "sell"),
        ("close", "-10", "close", 1, "buy"),
        ("close", "0", "hold", 0, None),
        ("hold", "10", "hold", 0, None),
        ("no_trade", "0", "no_trade", 0, None),
        ("open_long", "0", "open_long", 1, "buy"),
        ("open_short", "0", "open_short", 1, "sell"),
    ],
)
def test_current_position_controls_orders_without_same_round_reversal(
    tmp_path: Path,
    requested: str,
    units: str,
    effective: str,
    count: int,
    side: str | None,
) -> None:
    engine, _ = committee(RawManager(requested))
    store = AiTradingStore(db_path=tmp_path / "cycle.duckdb")
    backend = FakeExecutionBackend()
    backend.positions["EUR_USD"] = D(units)
    try:
        cycle = DailyTradingCycle(
            committee=engine,
            risk_gate=RiskGate(
                RiskLimitConfig(symbol_allowlist=frozenset({"EUR_USD"})),
                clock=lambda: NOW,
            ),
            execution_backend=backend,
            store=store,
            snapshot_loader=lambda _: snapshot(D(units)),
            quantity_override=D(2),
            trading_mode="on",
            enabled=True,
            clock=lambda: NOW,
        )
        result = cycle.run(["EUR_USD"])
        assert result.plans[0].action == effective
        assert result.votes[-1].manager_action == requested
        assert backend.submission_count == count
        if count:
            intent = backend.submissions[0].intent
            assert intent.side == side and intent.reduce_only == (effective == "close")
            assert intent.quantity == (abs(D(units)) if effective == "close" else D(2))
            assert result.attempts[0].risk_decision_id is not None
            if effective == "close":
                assert backend.positions["EUR_USD"] == 0
            else:
                expected_stop = D("1.0975") if side == "buy" else D("1.1025")
                expected_target = D("1.1030") if side == "buy" else D("1.0970")
                assert (
                    intent.stop_loss == expected_stop
                    and intent.take_profit == expected_target
                )
        else:
            assert result.attempts == []
    finally:
        store.close()


@pytest.mark.parametrize("age", [61, -1, None])
def test_changed_position_observation_is_rejected_after_model(
    tmp_path: Path, age: int | None
) -> None:
    engine, _ = committee(RawManager())
    store = AiTradingStore(db_path=tmp_path / "cycle.duckdb")
    backend = FakeExecutionBackend()
    refreshes = 0

    def refresh(value: MarketSnapshot) -> MarketSnapshot:
        nonlocal refreshes
        refreshes += 1
        if refreshes == 1:
            return value
        assert value.broker_evidence is not None
        if age is None:
            return value.model_copy(update={"broker_evidence": None})
        return value.model_copy(
            update={
                "broker_evidence": value.broker_evidence.model_copy(
                    update={"positions_captured_at": NOW - timedelta(seconds=age)}
                )
            }
        )

    try:
        cycle = DailyTradingCycle(
            committee=engine,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=backend,
            store=store,
            snapshot_loader=lambda _: snapshot(),
            snapshot_refresher=refresh,
            quantity_override=D(2),
            trading_mode="on",
            enabled=True,
            clock=lambda: NOW,
        )
        result = cycle.run(["EUR_USD"])
        assert result.plans[0].action == "no_trade" and result.attempts == []
        assert backend.submission_count == 0 and refreshes == 2
    finally:
        store.close()


@pytest.mark.parametrize(
    "stop,reward,sl,tp",
    [
        (-10, 100, "1.09900", "1.10300"),
        (100, -10, "1.09700", "1.10300"),
    ],
)
def test_proposed_multiples_are_clamped_in_executable_protection(
    tmp_path: Path,
    stop: int,
    reward: int,
    sl: str,
    tp: str,
) -> None:
    engine, _ = committee(
        RawManager(
            changes={
                "stop_atr_multiple": stop,
                "take_profit_r_multiple": reward,
            }
        )
    )
    store = AiTradingStore(db_path=tmp_path / "protection.duckdb")
    backend = FakeExecutionBackend()
    try:
        cycle = DailyTradingCycle(
            committee=engine,
            risk_gate=RiskGate(RiskLimitConfig(), clock=lambda: NOW),
            execution_backend=backend,
            store=store,
            snapshot_loader=lambda _: snapshot(),
            quantity_override=D(2),
            trading_mode="on",
            enabled=True,
            clock=lambda: NOW,
        )
        record = cycle.run(["EUR_USD"])
        assert len(record.attempts) == 1 and backend.submission_count == 1
        intent = backend.submissions[0].intent
        assert intent.stop_loss == D(sl) and intent.take_profit == D(tp)
        assert record.votes[-1].stop_atr_multiple == D(stop)
    finally:
        store.close()


def test_close_with_trading_off_is_risk_checked_without_submission(
    tmp_path: Path,
) -> None:
    engine, _ = committee(RawManager("close"))
    store = AiTradingStore(db_path=tmp_path / "off.duckdb")
    backend = FakeExecutionBackend()
    try:
        cycle = DailyTradingCycle(
            committee=engine,
            risk_gate=RiskGate(RiskLimitConfig(), clock=lambda: NOW),
            execution_backend=backend,
            store=store,
            snapshot_loader=lambda _: snapshot(D(10)),
            trading_mode="off",
            enabled=True,
            clock=lambda: NOW,
        )
        record = cycle.run(["EUR_USD"])
        assert backend.submission_count == 0 and len(record.attempts) == 1
        assert record.attempts[0].outcome == "blocked_trading_off"
        assert record.attempts[0].order_intent_json["reduce_only"] is True
        assert record.attempts[0].risk_decision_id is not None
    finally:
        store.close()


@pytest.mark.parametrize(
    "supporters,confidence,veto", [(1, 0.8, False), (4, 0.2, False), (4, 0.8, True)]
)
def test_native_decision_invariants_cannot_be_disabled_by_legacy_settings(
    supporters: int,
    confidence: float,
    veto: bool,
) -> None:
    from alphabrief_trader.rules import DisciplineConfig

    provider = RawManager(
        supporters=supporters, changes={"confidence": confidence}, risk_veto=veto
    )
    engine = TradingCommittee(
        gateway=ModelGateway([provider]),
        max_turns=5,
        challenge_rounds=0,
        discipline=DisciplineConfig(
            no_trade_below_confidence=0.1,
            min_analysts_supporting_direction=0,
            honour_risk_role_veto=False,
        ),
    )
    result = engine.run(CommitteeInput(snapshot=snapshot()))
    assert result.plan is not None and result.plan.action == "no_trade"
    assert result.plan.target_position_pct == 0


def test_historical_records_do_not_invent_actions_or_model_advice() -> None:
    from alphabrief_trader.schemas import CommitteeVote, TradePlan

    engine, _ = committee(RawManager())
    result = engine.run(CommitteeInput(snapshot=snapshot()))
    assert result.plan is not None
    old_vote = result.votes[-1].model_dump()
    for key in ("manager_action", "stop_atr_multiple", "take_profit_r_multiple"):
        old_vote.pop(key)
    vote = CommitteeVote.model_validate(old_vote)
    assert vote.manager_action is None and vote.stop_atr_multiple is None
    assert vote.take_profit_r_multiple is None
    old_plan = result.plan.model_dump()
    for key in (
        "action",
        "manager_call_id",
        "stop_atr_multiple",
        "take_profit_r_multiple",
    ):
        old_plan.pop(key)
    plan = TradePlan.model_validate(old_plan)
    assert plan.action is None and plan.manager_call_id is None
    assert plan.stop_atr_multiple is None and plan.take_profit_r_multiple is None
