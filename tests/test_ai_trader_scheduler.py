"""Tests for the AI Trading Committee scheduler integration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db import AiTradingStore
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderStatus,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.reconciliation import ReconciliationRunner
from alphabrief_execution.operations.scheduler import (
    AlertSink,
    HeartbeatStore,
    OperationsScheduler,
    SchedulerConfig,
    build_default_tasks,
)
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyTradingCycle,
    DisciplineConfig,
    MarketSnapshot,
    TradingCommittee,
    is_ai_trading_enabled,
)


class _NullAdapter(BrokerAdapter):
    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True,
            detail="null",
            checked_at=datetime.now(UTC),
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        raise NotImplementedError

    async def cancel(self, broker_order_id: str) -> CancelResult:
        raise NotImplementedError

    async def get_order(self, broker_order_id: str) -> OrderState:
        raise NotImplementedError

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        return []

    async def list_fills(self, since=None) -> list[Fill]:  # type: ignore[no-untyped-def]
        return []

    async def get_positions(self) -> list[Position]:
        return []

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="null",
            cash=Decimal("0"),
            equity=Decimal("0"),
            buying_power=Decimal("0"),
            currency="USD",
            captured_at=datetime.now(UTC),
        )


@pytest.fixture
def isolated_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    return tmp_path


class TestBuildDefaultTasksAiHook:
    def test_no_ai_task_without_handler(self) -> None:
        async def _reconcile(scope: str) -> None:
            return None

        tasks = build_default_tasks(on_reconcile=_reconcile)
        assert [t.name for t in tasks] == ["reconcile"]

    def test_ai_task_present_when_handler_supplied(self) -> None:
        async def _reconcile(scope: str) -> None:
            return None

        async def _ai_cycle() -> None:
            return None

        tasks = build_default_tasks(
            on_reconcile=_reconcile, on_ai_cycle=_ai_cycle
        )
        names = [t.name for t in tasks]
        assert "ai_daily_cycle" in names
        ai_task = next(t for t in tasks if t.name == "ai_daily_cycle")
        assert ai_task.enabled is False
        assert ai_task.interval_seconds == 86_400.0


class TestSchedulerRunsAiTask:
    def test_ai_task_runs_when_enabled(
        self, isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        assert is_ai_trading_enabled() is True

        db_path = isolated_data_dir / "alphabrief.db"

        payload = {
            "analysis": "Bullish continuation.",
            "view": "bullish",
            "confidence": 0.7,
            "evidence": ["e"],
            "risks": [],
            "suggested_action": "buy",
            "target_position_pct": 0.10,
            "veto": False,
            "needs_human_review": False,
        }
        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-1",
            capabilities=["structured_output"],
            structured_output=payload,
        )
        committee = TradingCommittee(
            gateway=ModelGateway(providers=[provider]),
            discipline=DisciplineConfig(),
        )
        broker = PaperBroker(
            portfolio=PortfolioState(cash=Decimal("100000")),
            router=OrderRouter(),
            fill_simulator=FillSimulator(),
        )
        risk_gate = RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True,
                symbol_allowlist=frozenset({"SPY"}),
            )
        )

        store = AiTradingStore(db_path=db_path)
        try:
            cycle = DailyTradingCycle(
                committee=committee,
                risk_gate=risk_gate,
                broker=broker,
                store=store,
                snapshot_loader=lambda s: MarketSnapshot(
                    symbol=s,
                    reference_price=Decimal("100"),
                    data_version="test-v1",
                    captured_at=datetime.now(UTC),
                )
                if s == "SPY"
                else None,
                enabled=True,
            )

            ran: list[int] = []

            async def _ai_cycle() -> None:
                ran.append(1)
                cycle.run(["SPY"])

            async def _on_reconcile(scope: str) -> None:
                return None

            tasks = build_default_tasks(
                on_reconcile=_on_reconcile, on_ai_cycle=_ai_cycle
            )
            from dataclasses import replace as _replace

            tasks = [
                _replace(t, enabled=True, interval_seconds=0.1)
                if t.name == "ai_daily_cycle"
                else t
                for t in tasks
            ]
            tasks = [
                _replace(t, enabled=False) if t.name == "reconcile" else t
                for t in tasks
            ]

            heartbeats = HeartbeatStore(db_path=db_path)
            recon_store = BrokerReconStore(db_path=db_path)
            try:
                runner = ReconciliationRunner(
                    adapter=_NullAdapter(), store=recon_store
                )
                scheduler = OperationsScheduler(
                    tasks=tasks,
                    heartbeat_store=heartbeats,
                    alert_sink=AlertSink(heartbeat_store=heartbeats),
                    recon_runner=runner,
                    recon_store=recon_store,
                    config=SchedulerConfig(
                        reconcile_on_start=False,
                        max_consecutive_failures=3,
                    ),
                )

                async def _stop_after_run() -> None:
                    while not ran:
                        await asyncio.sleep(0.05)
                    scheduler.request_stop()

                async def _run_scheduler_until_ai_cycle() -> None:
                    stop_task = asyncio.create_task(_stop_after_run())
                    await asyncio.gather(scheduler.run(), stop_task)

                asyncio.run(_run_scheduler_until_ai_cycle())

                assert ran, "ai_daily_cycle handler did not run"
                latest = store.get_latest_cycle()
                assert latest is not None
            finally:
                heartbeats.close()
                recon_store.close()
        finally:
            store.close()