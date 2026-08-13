"""M07-W01: broker order ledger integration.

Covers:
- reservation, approved-decision binding, submit attempt, broker result,
  and related IDs commit atomically with compare-and-set transitions and
  immutable history (AC-M07-W01-02);
- the ledger composes with the unknown-outcome resolver so a timeout
  after submit never duplicates the order.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.faults import (
    ClassifiedRequestExecutor,
    UnknownOutcomeFailure,
)
from alphabrief_execution.broker.oanda.order_ledger import (
    LedgerTransitionError,
    OrderLedger,
)
from alphabrief_execution.broker.oanda.order_ops import OrderOpsClient
from alphabrief_execution.broker.oanda.unknown_outcome import (
    UnknownOutcomeResolver,
)

ACCOUNT_ID = "101-004-1234567-001"
BASE = f"http://oanda.test/v3/accounts/{ACCOUNT_ID}"
CYCLE = "cycle-2026-08-13"
INTENT = "intent-42"
OWNER = "daily-runner"
PAYLOAD = "sha256:payload-1"
DECISION = "risk-1"


class _FakeBroker:
    """Deterministic in-memory broker with absorb-after-submit."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.next_id = 100
        self.absorb_submit = False

    def _tx(self) -> str:
        value = str(self.next_id)
        self.next_id += 1
        return value

    def handle(self, request: Request) -> bytes:
        method = request.method
        url = request.full_url
        raw = request.data
        body = json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else {}
        path, _, _ = url.partition("?")

        if method == "POST" and path == f"{BASE}/orders":
            order = body["order"]
            order_id = self._tx()
            record = {
                "id": order_id,
                "instrument": order.get("instrument", ""),
                "units": order.get("units", "0"),
                "state": "PENDING",
                "createTime": "2026-08-04T12:00:00.000000000Z",
                "clientExtensions": order.get("clientExtensions", {}),
            }
            self.orders[order_id] = record
            if self.absorb_submit:
                raise TimeoutError("timed out")
            return json.dumps(
                {
                    "orderCreateTransaction": {"id": order_id},
                    "orderFillTransaction": None,
                }
            ).encode("utf-8")
        if method == "GET" and path == f"{BASE}/orders":
            return json.dumps(
                {"orders": list(self.orders.values())}
            ).encode("utf-8")
        raise AssertionError(f"unexpected request: {method} {path}")


def _client(broker: _FakeBroker) -> OandaHttpClient:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        return broker.handle(request)

    return OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send,
        token="t",
        account_id=ACCOUNT_ID,
    )


def _submit_payload() -> dict[str, Any]:
    return {
        "order": {
            "type": "MARKET",
            "instrument": "EUR_USD",
            "units": "1",
            "clientExtensions": {"id": f"{CYCLE}:{INTENT}"},
        }
    }


# ---------------------------------------------------------------------------
# AC-M07-W01-02: atomic compare-and-set transitions with immutable history
# ---------------------------------------------------------------------------


def test_full_flow_commits_atomically(tmp_path: Path) -> None:
    broker = _FakeBroker()
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    try:
        reserved = ledger.reserve(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            owner=OWNER,
        )
        submit_id = reserved.submit_id
        ledger.bind_decision(
            submit_id, decision_id=DECISION, payload_hash=PAYLOAD, owner=OWNER
        )
        ledger.record_submit_attempt(
            submit_id, payload_hash=PAYLOAD, owner=OWNER
        )
        ops = OrderOpsClient(_client(broker))
        created = ops.create_order(
            _order_request_from_payload(),
            _instrument(),
            client_order_id=f"{CYCLE}:{INTENT}",
        )
        ledger.record_broker_result(
            submit_id,
            broker_order_id=created.broker_order_id,
            state=created.state,
            transaction_id="100",
            owner=OWNER,
        )
        ledger.record_related_id(
            submit_id, kind="transaction", related_id="100", owner=OWNER
        )
        ledger.record_related_id(
            submit_id, kind="trade", related_id="101", owner=OWNER
        )

        assert ledger.status(submit_id) == "COMPLETED"
        reservation = ledger.reservation(submit_id)
        assert reservation is not None
        assert reservation["broker_order_id"] == created.broker_order_id
        assert reservation["state"] == "PENDING"
        assert reservation["transaction_id"] == "100"
        kinds = [e["kind"] for e in ledger.events(submit_id)]
        assert kinds == [
            "RESERVED",
            "BIND",
            "SUBMIT_ATTEMPT",
            "BROKER_RESULT",
            "RELATED_ID",
            "RELATED_ID",
        ]
    finally:
        ledger.close()


def test_broker_result_replay_is_idempotent(tmp_path: Path) -> None:
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    try:
        reserved = ledger.reserve(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            owner=OWNER,
        )
        submit_id = reserved.submit_id
        ledger.bind_decision(
            submit_id, decision_id=DECISION, payload_hash=PAYLOAD, owner=OWNER
        )
        ledger.record_submit_attempt(
            submit_id, payload_hash=PAYLOAD, owner=OWNER
        )
        ledger.record_broker_result(
            submit_id,
            broker_order_id="200",
            state="PENDING",
            transaction_id="100",
            owner=OWNER,
        )
        # A replay of the identical broker result is accepted idempotently.
        ledger.record_broker_result(
            submit_id,
            broker_order_id="200",
            state="PENDING",
            transaction_id="100",
            owner=OWNER,
        )
        kinds = [e["kind"] for e in ledger.events(submit_id)]
        assert kinds.count("BROKER_RESULT") == 1
    finally:
        ledger.close()


def test_events_are_immutable_and_ordered(tmp_path: Path) -> None:
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    try:
        reserved = ledger.reserve(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            owner=OWNER,
        )
        submit_id = reserved.submit_id
        ledger.bind_decision(
            submit_id, decision_id=DECISION, payload_hash=PAYLOAD, owner=OWNER
        )
        first_read = ledger.events(submit_id)
        second_read = ledger.events(submit_id)
        assert first_read == second_read
        ids = [e["event_id"] for e in first_read]
        assert ids == sorted(ids)
        assert len(ids) == len(set(ids))
    finally:
        ledger.close()


def test_related_ids_require_completed_submit(tmp_path: Path) -> None:
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    try:
        reserved = ledger.reserve(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            owner=OWNER,
        )
        with pytest.raises(LedgerTransitionError) as excinfo:
            ledger.record_related_id(
                reserved.submit_id, kind="trade", related_id="1", owner=OWNER
            )
        assert excinfo.value.kind == "state_conflict"
    finally:
        ledger.close()


# ---------------------------------------------------------------------------
# Timeout composition: ledger + unknown-outcome resolver
# ---------------------------------------------------------------------------


def test_timeout_after_submit_resolves_without_duplicate(tmp_path: Path) -> None:
    broker = _FakeBroker()
    broker.absorb_submit = True
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    try:
        reserved = ledger.reserve(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            owner=OWNER,
        )
        submit_id = reserved.submit_id
        ledger.bind_decision(
            submit_id, decision_id=DECISION, payload_hash=PAYLOAD, owner=OWNER
        )
        ledger.record_submit_attempt(
            submit_id, payload_hash=PAYLOAD, owner=OWNER
        )

        http = _client(broker)
        executor = ClassifiedRequestExecutor(http, max_attempts=1)
        with pytest.raises(UnknownOutcomeFailure):
            executor.execute(
                "POST",
                http.account_path("/orders"),
                json_body=_submit_payload(),
                request_id=f"{CYCLE}:{INTENT}",
            )
        # The ledger state is in-flight; the resolver finds the absorbed
        # order by the persisted client identity.
        resolver = UnknownOutcomeResolver(OrderOpsClient(http))
        verdict = resolver.resolve(f"{CYCLE}:{INTENT}")
        assert verdict.resolution == "RESOLVED_ACCEPTED"
        ledger.record_broker_result(
            submit_id,
            broker_order_id=verdict.broker_order_id or "",
            state=verdict.state or "PENDING",
            transaction_id="100",
            owner=OWNER,
        )
        assert ledger.status(submit_id) == "COMPLETED"
        # Exactly one broker order exists: the retry never duplicated.
        assert len(broker.orders) == 1
    finally:
        ledger.close()


def _order_request_from_payload() -> Any:
    from decimal import Decimal

    from alphabrief_execution.broker.oanda.orders import OandaOrderRequest

    return OandaOrderRequest(
        type="MARKET",
        instrument="EUR_USD",
        units=Decimal("1"),
        time_in_force="FOK",
    )


def _instrument() -> Any:
    from decimal import Decimal

    from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata

    return InstrumentMetadata(
        name="EUR_USD",
        display_name="EUR/USD",
        raw_type="CURRENCY",
        display_precision=5,
        trade_units_precision=0,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("0"),
        maximum_position_size=Decimal("0"),
        margin_rate=Decimal("0.05"),
        pip_location=-4,
        raw_payload={"guaranteedStopLossOrderMode": "ENABLED"},
    )
