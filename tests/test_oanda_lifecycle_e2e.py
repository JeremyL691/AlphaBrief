"""M06-W07 runtime E2E: controlled practice scenarios.

Proves the formal product path end to end — OrderIntent, RiskGate,
persisted RiskDecision, idempotent submit, automatic cleanup, and final
reconciliation evidence — and proves that missing credentials produce
``ENVIRONMENT_BLOCKED`` with no fake fill, no waiver, and no question.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.request import Request

from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.practice_scenarios import (
    PracticeScenarioRunner,
)

ACCOUNT_ID = "101-004-1234567-001"
BASE = f"http://oanda.test/v3/accounts/{ACCOUNT_ID}"


class _FakePracticeBroker:
    """Deterministic in-memory broker for the scenario lifecycle."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.trades: dict[str, dict[str, Any]] = {}
        self.next_id = 1000
        self.fail_close = False
        self.captured: list[dict[str, Any]] = []

    def _tx(self) -> str:
        value = str(self.next_id)
        self.next_id += 1
        return value

    def handle(self, request: Request) -> bytes:
        method = request.method
        url = request.full_url
        raw = request.data
        body = json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else {}
        self.captured.append({"method": method, "url": url, "body": body})
        path, _, _ = url.partition("?")

        if method == "POST" and path == f"{BASE}/orders":
            order = body["order"]
            order_id = self._tx()
            trade_id = self._tx()
            extensions = order.get("clientExtensions", {})
            self.orders[order_id] = {
                "id": order_id,
                "instrument": order.get("instrument", ""),
                "units": order.get("units", "0"),
                "state": "FILLED",
                "createTime": "2026-08-04T12:00:00.000000000Z",
                "clientExtensions": extensions,
            }
            self.trades[trade_id] = {
                "id": trade_id,
                "instrument": order.get("instrument", ""),
                "price": "1.10500",
                "openTime": "2026-08-04T12:00:00.000000000Z",
                "state": "OPEN",
                "initialUnits": order.get("units", "0"),
                "currentUnits": order.get("units", "0"),
                "realizedPL": "0",
                "unrealizedPL": "0",
                "financing": "0",
                "clientExtensions": extensions,
            }
            return json.dumps(
                {
                    "orderCreateTransaction": {"id": order_id},
                    "orderFillTransaction": {"id": trade_id},
                }
            ).encode("utf-8")
        if method == "GET" and path == f"{BASE}/orders":
            return json.dumps({"orders": list(self.orders.values())}).encode("utf-8")
        if method == "GET" and path == f"{BASE}/trades":
            return json.dumps({"trades": list(self.trades.values())}).encode("utf-8")
        if method == "GET" and path.startswith(f"{BASE}/trades/"):
            trade_id = path.split("/trades/", 1)[1]
            trade = self.trades.get(trade_id)
            if trade is None:
                raise AssertionError(f"unknown trade {trade_id}")
            return json.dumps({"trade": trade}).encode("utf-8")
        if method == "PUT" and path.endswith("/close"):
            if self.fail_close:
                raise TimeoutError("timed out")
            trade_id = path.split("/trades/", 1)[1].split("/", 1)[0]
            trade = self.trades[trade_id]
            units = trade["currentUnits"]
            trade["state"] = "CLOSED"
            trade["currentUnits"] = "0"
            return json.dumps(
                {
                    "orderCreateTransaction": {"id": self._tx()},
                    "orderFillTransaction": {
                        "id": self._tx(),
                        "units": units,
                    },
                    "tradeCloseTransaction": {"id": self._tx()},
                    "realizedPL": "0.01",
                    "financing": "0",
                }
            ).encode("utf-8")
        if method == "GET" and path == f"{BASE}/summary":
            return json.dumps(
                {
                    "account": {
                        "id": ACCOUNT_ID,
                        "currency": "USD",
                        "balance": "100000.00",
                        "NAV": "100001.00",
                        "unrealizedPL": "1.00",
                        "marginUsed": "1.00",
                        "marginAvailable": "99999.00",
                        "openOrderCount": 0,
                        "openTradeCount": 0,
                        "openPositionCount": 0,
                        "lastTransactionID": "3000",
                    }
                }
            ).encode("utf-8")
        raise AssertionError(f"unexpected request: {method} {path}")


def _client(broker: _FakePracticeBroker) -> OandaHttpClient:
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


def test_controlled_scenario_completes_with_cleanup_and_reconciliation(
    tmp_path: Path,
) -> None:
    broker = _FakePracticeBroker()
    runner = PracticeScenarioRunner(
        client=_client(broker),
        store_path=tmp_path / "scenarios.db",
        scenario_id="scenario-1",
    )
    verdict = runner.run()
    assert verdict.verdict == "COMPLETED"
    assert verdict.approved is True
    assert verdict.decision_id is not None
    assert verdict.broker_order_id is not None
    assert verdict.cleanup_result == "closed"
    # Final reconciliation evidence: nothing of ours stays open.
    assert verdict.evidence["open_orders"] == 0
    assert verdict.evidence["open_trades"] == 0
    assert verdict.evidence["open_position_count"] == 0
    assert verdict.evidence["balance"] == "100000.00"
    # The scenario never fabricated anything and never asked a question.
    assert len(broker.trades) == 1
    assert broker.trades[next(iter(broker.trades))]["state"] == "CLOSED"


def test_idempotent_client_identity_never_duplicates() -> None:
    broker = _FakePracticeBroker()
    runner = PracticeScenarioRunner(
        client=_client(broker),
        store_path=None,
        scenario_id="scenario-2",
    )
    first = runner.run()
    second = runner.run()
    assert first.verdict == "COMPLETED"
    assert second.verdict == "COMPLETED"
    assert second.reused_identity is True
    # Exactly one broker order and one trade across both runs.
    assert len(broker.orders) == 1
    assert len(broker.trades) == 1
    assert second.broker_order_id == first.broker_order_id


def test_missing_credentials_block_environment(tmp_path: Path) -> None:
    runner = PracticeScenarioRunner(
        client=None,
        store_path=tmp_path / "scenarios.db",
        scenario_id="scenario-3",
    )
    verdict = runner.run()
    assert verdict.verdict == "ENVIRONMENT_BLOCKED"
    assert verdict.approved is None
    assert verdict.broker_order_id is None
    assert verdict.cleanup_result is None
    # No fake fill, no fallback execution, no question asked.
    assert "credential" in verdict.detail


def test_submission_follows_the_approved_decision(tmp_path: Path) -> None:
    broker = _FakePracticeBroker()
    # The intent asks for 2 units, but the scenario is fixed minimum risk
    # by construction: the intent is capped to 1 and the approved
    # decision bounds the submit — the broker never sees more than 1.
    runner = PracticeScenarioRunner(
        client=_client(broker),
        store_path=tmp_path / "scenarios.db",
        scenario_id="scenario-4",
        minimum_risk_units=Decimal("2"),
    )
    verdict = runner.run()
    assert verdict.verdict == "COMPLETED"
    assert verdict.approved is True
    assert verdict.decision_id is not None
    order = broker.orders[next(iter(broker.orders))]
    assert order["units"] == "1"
    # The trade was opened at the approved size and then closed by the
    # automatic cleanup.
    trade = broker.trades[next(iter(broker.trades))]
    assert trade["initialUnits"] == "1"
    assert trade["state"] == "CLOSED"


def test_unresolved_cleanup_fails_closed() -> None:
    broker = _FakePracticeBroker()
    broker.fail_close = True
    runner = PracticeScenarioRunner(
        client=_client(broker),
        store_path=None,
        scenario_id="scenario-5",
    )
    verdict = runner.run()
    assert verdict.verdict == "FAIL"
    assert verdict.approved is True
    assert verdict.cleanup_result is not None
    assert verdict.cleanup_result.startswith("UNRESOLVED")
    # The failed close never produced a local synthetic fill.
    trade = broker.trades[next(iter(broker.trades))]
    assert trade["state"] == "OPEN"


def test_verdicts_are_persisted_with_the_decision(tmp_path: Path) -> None:
    broker = _FakePracticeBroker()
    store = tmp_path / "scenarios.db"
    runner = PracticeScenarioRunner(
        client=_client(broker),
        store_path=store,
        scenario_id="scenario-6",
    )
    verdict = runner.run()
    assert verdict.verdict == "COMPLETED"

    import duckdb

    conn = duckdb.connect(str(store))
    try:
        row = conn.execute(
            "SELECT scenario_id, verdict, decision_id, approved FROM practice_scenarios"
        ).fetchone()
        assert row is not None
        assert row[0] == "scenario-6"
        assert row[1] == "COMPLETED"
        assert row[2] == verdict.decision_id
        assert row[3] is True
    finally:
        conn.close()
