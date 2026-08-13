"""Controlled minimal-risk OANDA practice scenarios (M06-W07).

Runs one fixed minimum-risk scenario through the formal product path:
OrderIntent -> RiskGate -> persisted RiskDecision -> idempotent OANDA
submit -> automatic cleanup -> final reconciliation evidence. Missing
credentials produce ``ENVIRONMENT_BLOCKED``; unresolved cleanup or an
external outage produce ``FAIL``. A fill is never fabricated, no waiver
is possible, and no human review is requested.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import duckdb
from alphabrief_core.domain import OrderIntent
from alphabrief_risk.gate import RiskGate, RiskLimitConfig
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.oanda.account_ops import AccountOpsClient
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from alphabrief_execution.broker.oanda.order_ops import OrderOpsClient
from alphabrief_execution.broker.oanda.orders import OandaOrderRequest
from alphabrief_execution.broker.oanda.trade_ops import TradeOpsClient

PracticeVerdict = Literal["COMPLETED", "ENVIRONMENT_BLOCKED", "FAIL"]

#: The fixed scenario symbol and quantity: minimal risk by construction.
SCENARIO_SYMBOL = "EUR_USD"
SCENARIO_MINIMUM_RISK_UNITS = Decimal("1")


class ScenarioVerdict(BaseModel):
    """One deterministic practice-scenario verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: PracticeVerdict
    scenario_id: str = Field(min_length=1)
    detail: str
    decision_id: str | None = None
    approved: bool | None = None
    broker_order_id: str | None = None
    reused_identity: bool | None = None
    cleanup_result: str | None = None
    evidence: dict[str, Any] = {}
    recorded_at: datetime


class PracticeScenarioRunner:
    """Runs the controlled scenario; always cleans up; never fakes."""

    def __init__(
        self,
        *,
        client: OandaHttpClient | None = None,
        store_path: Path | str | None = None,
        scenario_id: str | None = None,
        symbol: str = SCENARIO_SYMBOL,
        minimum_risk_units: Decimal = SCENARIO_MINIMUM_RISK_UNITS,
    ) -> None:
        self._client = client
        self._store_path = store_path
        self._scenario_id = scenario_id or "practice-scenario"
        self._symbol = symbol
        self._minimum_risk_units = minimum_risk_units
        self._instrument = _scenario_instrument(symbol)
        self._orders: OrderOpsClient | None = None
        self._trades: TradeOpsClient | None = None
        self._accounts: AccountOpsClient | None = None

    def run(self) -> ScenarioVerdict:
        """Execute the scenario and return one deterministic verdict."""
        if self._client is None:
            return self._finish(
                verdict="ENVIRONMENT_BLOCKED",
                detail="no OANDA practice client; credentials are required",
            )
        # The ops clients are cached across runs so the idempotent
        # client identity survives retries of the whole scenario.
        if self._orders is None:
            self._orders = OrderOpsClient(self._client)
            self._trades = TradeOpsClient(self._client)
            self._accounts = AccountOpsClient(self._client)

        # The intent is capped to the fixed minimum risk by construction,
        # so the gate always evaluates a minimal-risk scenario.
        intent_units = min(self._minimum_risk_units, SCENARIO_MINIMUM_RISK_UNITS)
        intent = OrderIntent(
            intent_id=f"{self._scenario_id}-intent",
            source="manual",
            symbol=self._symbol,
            side="buy",
            order_type="market",
            quantity=intent_units,
            rationale="fixed minimum-risk controlled practice scenario",
            created_at=datetime.now(UTC),
        )
        gate = RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True,
                live_trading_enabled=False,
                symbol_allowlist=frozenset({self._symbol}),
                # The gate cap is the fixed minimum risk by construction;
                # the intent can never exceed it.
                max_order_quantity=SCENARIO_MINIMUM_RISK_UNITS,
                require_data_quality_passed=True,
                require_human_review=False,
            )
        )
        decision = gate.evaluate(intent, strategy_id=f"practice-{self._scenario_id}")
        if decision.requires_human_review:
            return self._finish(
                verdict="FAIL",
                detail=(
                    "risk gate requires human review; "
                    "scenarios never request review"
                ),
                decision_id=decision.decision_id,
                approved=decision.approved,
            )
        if not decision.approved:
            return self._finish(
                verdict="FAIL",
                detail=f"risk gate rejected the scenario intent: {decision.reason}",
                decision_id=decision.decision_id,
                approved=False,
            )

        # Formal submit with an idempotent client identity. The units
        # follow the approved persisted decision, never the raw intent.
        client_order_id = f"{self._scenario_id}-{intent.intent_id}"
        approved_units = decision.max_quantity or self._minimum_risk_units
        request = OandaOrderRequest(
            type="MARKET",
            instrument=self._symbol,
            units=approved_units,
            time_in_force="FOK",
        )
        created = self._orders.create_order(
            request,
            self._instrument,
            client_order_id=client_order_id,
        )
        broker_order_id = created.broker_order_id
        cleanup = self._cleanup(client_order_id, created.state)
        if cleanup.startswith("UNRESOLVED"):
            return self._finish(
                verdict="FAIL",
                detail=f"automatic cleanup unresolved: {cleanup}",
                decision_id=decision.decision_id,
                approved=True,
                broker_order_id=broker_order_id,
                reused_identity=created.reused,
                cleanup_result=cleanup,
            )
        evidence = self._reconciliation_evidence()
        return self._finish(
            verdict="COMPLETED",
            detail="scenario completed with automatic cleanup and reconciliation",
            decision_id=decision.decision_id,
            approved=True,
            broker_order_id=broker_order_id,
            reused_identity=created.reused,
            cleanup_result=cleanup,
            evidence=evidence,
        )

    # ------------------------------------------------------------------
    # Cleanup and evidence
    # ------------------------------------------------------------------

    def _cleanup(self, client_order_id: str, state: str) -> str:
        """Automatically cancel pending orders or close filled trades."""
        assert self._orders is not None and self._trades is not None
        try:
            if state == "PENDING":
                order_listing = self._orders.list_orders(status="PENDING")
                pending = [
                    order
                    for order in order_listing.orders
                    if order.client_order_id == client_order_id
                ]
                if not pending:
                    return "UNRESOLVED: pending order not found for cleanup"
                self._orders.cancel_order(pending[0].broker_order_id)
                return "cancelled"
            trade_listing = self._trades.list_trades(state="OPEN")
            opened = [
                trade
                for trade in trade_listing.trades
                if trade.client_order_id == client_order_id
            ]
            if opened:
                self._trades.close_trade(opened[0].broker_trade_id)
                return "closed"
            # No open trade: an idempotent replay of a completed scenario
            # finds the trade already closed. A missing trade record at
            # all is a genuine anomaly and fails closed.
            all_trades = self._trades.list_trades()
            matched = [
                trade
                for trade in all_trades.trades
                if trade.client_order_id == client_order_id
            ]
            if matched:
                return "already_closed"
            return "UNRESOLVED: filled trade not found for cleanup"
        except Exception as exc:  # noqa: BLE001 — cleanup must fail closed
            return f"UNRESOLVED: cleanup raised {exc!r}"

    def _reconciliation_evidence(self) -> dict[str, Any]:
        """Final broker-side evidence: nothing of ours stays open."""
        assert self._orders is not None and self._trades is not None
        assert self._accounts is not None
        open_orders = len(self._orders.list_orders(status="PENDING").orders)
        open_trades = len(self._trades.list_trades(state="OPEN").trades)
        positions = self._accounts.account_summary()
        return {
            "open_orders": open_orders,
            "open_trades": open_trades,
            "open_position_count": positions.open_position_count,
            "balance": str(positions.balance),
        }

    def _finish(
        self,
        *,
        verdict: PracticeVerdict,
        detail: str,
        decision_id: str | None = None,
        approved: bool | None = None,
        broker_order_id: str | None = None,
        reused_identity: bool | None = None,
        cleanup_result: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> ScenarioVerdict:
        result = ScenarioVerdict(
            verdict=verdict,
            scenario_id=self._scenario_id,
            detail=detail,
            decision_id=decision_id,
            approved=approved,
            broker_order_id=broker_order_id,
            reused_identity=reused_identity,
            cleanup_result=cleanup_result,
            evidence=evidence or {},
            recorded_at=datetime.now(UTC),
        )
        self._persist(result)
        return result

    def _persist(self, verdict: ScenarioVerdict) -> None:
        if self._store_path is None:
            return
        path = Path(self._store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(path))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS practice_scenarios (
                    scenario_id   TEXT PRIMARY KEY,
                    verdict       TEXT NOT NULL,
                    detail        TEXT NOT NULL,
                    decision_id   TEXT,
                    approved      BOOLEAN,
                    broker_order_id TEXT,
                    reused_identity BOOLEAN,
                    cleanup_result TEXT,
                    evidence      TEXT,
                    recorded_at   TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO practice_scenarios (
                    scenario_id, verdict, detail, decision_id, approved,
                    broker_order_id, reused_identity, cleanup_result,
                    evidence, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (scenario_id) DO UPDATE SET
                    verdict = EXCLUDED.verdict,
                    detail = EXCLUDED.detail,
                    decision_id = EXCLUDED.decision_id,
                    approved = EXCLUDED.approved,
                    broker_order_id = EXCLUDED.broker_order_id,
                    reused_identity = EXCLUDED.reused_identity,
                    cleanup_result = EXCLUDED.cleanup_result,
                    evidence = EXCLUDED.evidence,
                    recorded_at = EXCLUDED.recorded_at
                """,
                [
                    verdict.scenario_id,
                    verdict.verdict,
                    verdict.detail,
                    verdict.decision_id,
                    verdict.approved,
                    verdict.broker_order_id,
                    verdict.reused_identity,
                    verdict.cleanup_result,
                    _json_dumps(verdict.evidence),
                    verdict.recorded_at,
                ],
            )
        finally:
            conn.close()


def _scenario_instrument(symbol: str) -> InstrumentMetadata:
    return InstrumentMetadata(
        name=symbol,
        display_name=symbol.replace("_", "/"),
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


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, sort_keys=True)


def default_store_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "practice_scenarios.db"


__all__ = [
    "PracticeScenarioRunner",
    "PracticeVerdict",
    "SCENARIO_MINIMUM_RISK_UNITS",
    "SCENARIO_SYMBOL",
    "ScenarioVerdict",
    "default_store_path",
]
