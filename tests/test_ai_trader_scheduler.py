"""Tests for the AI Trading Committee scheduler integration."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import alphabrief_cli.scheduler_commands as scheduler_commands
import pytest
from alphabrief_api.db import AiTradingStore, MarketDataStore, NewsStore
from alphabrief_cli.scheduler_commands import _ai_cycle_factory
from alphabrief_core import Bar
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
from alphabrief_news.types import NewsFetchQuery, NewsHeadline
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

    async def list_fills(
        self, since: datetime | None = None
    ) -> list[Fill]:
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


class _SubmittingAdapter(_NullAdapter):
    def __init__(self) -> None:
        self.requests: list[SubmitRequest] = []
        self.client_order_ids: list[str] = []

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        self.requests.append(request)
        self.client_order_ids.append(client_order_id)
        return SubmitResult(
            broker_order_id=f"broker-{client_order_id}",
            client_order_id=client_order_id,
            status=BrokerOrderStatus.NEW,
            accepted_at=datetime.now(UTC),
        )

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="paper",
            cash=Decimal("1000"),
            equity=Decimal("1000"),
            buying_power=Decimal("1000"),
            currency="USD",
            captured_at=datetime.now(UTC),
        )


@pytest.fixture(autouse=True)
def _scheduler_ai_test_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHABRIEF_AI_PRE_CYCLE_INGEST_ENABLED", "false")
    monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "fake")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Keep AI-cycle observation exports out of the real ~/.alphabrief dir.
    monkeypatch.setenv(
        "ALPHABRIEF_OBSERVATION_DIR", str(tmp_path / "observation")
    )
    # The project's local ``.env`` is auto-loaded at CLI / API import
    # time (before pytest sets ``PYTEST_CURRENT_TEST``), so OANDA and
    # Alpaca credentials from the developer's machine would otherwise
    # leak into these tests. Strip both broker-credential sets so each
    # test can opt in cleanly.
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_KEY", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_SECRET", raising=False)


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

    def test_ai_cycle_factory_ingests_market_and_news_before_cycle(
        self, isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        monkeypatch.setenv("ALPHABRIEF_AI_PRE_CYCLE_INGEST_ENABLED", "true")
        monkeypatch.setenv("ALPHABRIEF_AI_MARKET_DATA_SOURCE", "yahoo")
        monkeypatch.setenv("ALPHABRIEF_AI_NEWS_SOURCE", "rss")
        monkeypatch.setenv("ALPHABRIEF_AI_NEWS_FEEDS", "marketwatch-rss")
        # Pin a small universe so the test stays focused on the ingestion
        # pipeline (the default universe now spans FX + equities + crypto).
        monkeypatch.setenv(
            "ALPHABRIEF_AI_SCHEDULER_UNIVERSE", "EUR_USD,GBP_USD,USD_JPY"
        )

        class _MarketProvider:
            provider_name = "test-market"

            def fetch_ohlcv(
                self,
                *,
                symbol: str,
                start: datetime,
                end: datetime,
                interval: str,
            ) -> list[Bar]:
                del start, interval
                return [
                    Bar(
                        symbol=symbol,
                        timestamp=end - timedelta(days=2),
                        open=Decimal("99"),
                        high=Decimal("101"),
                        low=Decimal("98"),
                        close=Decimal("100"),
                        volume=Decimal("1000"),
                        source="test-market",
                        data_version="test",
                    ),
                    Bar(
                        symbol=symbol,
                        timestamp=end - timedelta(days=1),
                        open=Decimal("100"),
                        high=Decimal("102"),
                        low=Decimal("99"),
                        close=Decimal("101"),
                        volume=Decimal("1100"),
                        source="test-market",
                        data_version="test",
                    ),
                ]

        class _NewsProvider:
            def fetch_headlines(
                self, query: NewsFetchQuery
            ) -> list[NewsHeadline]:
                return [
                    NewsHeadline(
                        headline_id=f"{query.symbols[0]}-1",
                        published_at=query.end - timedelta(hours=1),
                        symbols=["GENERAL"],
                        category="macro",
                        source="Test Wire",
                        title="Markets gain as policy uncertainty eases",
                        summary="",
                        url="https://example.test/story",
                        sentiment="positive",
                        data_version=query.data_version,
                    )
                ]

        monkeypatch.setattr(
            scheduler_commands,
            "_build_market_data_provider",
            lambda source: _MarketProvider(),
        )
        monkeypatch.setattr(
            scheduler_commands,
            "_build_news_provider",
            lambda source: _NewsProvider(),
        )

        handler = _ai_cycle_factory(db_path=isolated_data_dir)

        async def _run_handler() -> None:
            await handler()

        asyncio.run(_run_handler())

        market_store = MarketDataStore(db_path=isolated_data_dir / "alphabrief.db")
        news_store = NewsStore(db_path=isolated_data_dir / "alphabrief.db")
        ai_store = AiTradingStore(db_path=isolated_data_dir / "alphabrief.db")
        try:
            assert market_store.get_bar_count("EUR_USD") == 2
            headlines = news_store.list_headlines(symbol="EUR_USD", limit=10)
            assert len(headlines) == 1
            assert headlines[0].symbols == ["EUR_USD", "GBP_USD", "USD_JPY"]

            latest = ai_store.get_latest_cycle()
            assert latest is not None
            assert set(latest["symbols"]) == {
                "EUR_USD",
                "GBP_USD",
                "USD_JPY",
            }
            assert len(latest["votes"]) == 12
        finally:
            ai_store.close()
            news_store.close()
            market_store.close()

    def test_ai_cycle_factory_skips_symbols_without_local_bars(
        self, isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        handler = _ai_cycle_factory(db_path=isolated_data_dir)

        async def _run_handler() -> None:
            await handler()

        asyncio.run(_run_handler())

        store = AiTradingStore(db_path=isolated_data_dir / "alphabrief.db")
        try:
            latest = store.get_latest_cycle()
            assert latest is not None
            assert latest["outcome"] == "skipped_no_consensus"
            assert latest["votes"] == []
            assert latest["plans"] == []
            assert latest["attempts"] == []
        finally:
            store.close()

    def test_ai_cycle_factory_exports_latest_cycle_json(
        self,
        isolated_data_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        obs_dir = tmp_path / "observation"
        handler = _ai_cycle_factory(db_path=isolated_data_dir)

        async def _run_handler() -> None:
            await handler()

        asyncio.run(_run_handler())

        store = AiTradingStore(db_path=isolated_data_dir / "alphabrief.db")
        try:
            latest = store.get_latest_cycle()
            assert latest is not None
        finally:
            store.close()

        exports = list(obs_dir.glob("ai_cycle_*.json"))
        assert len(exports) == 1
        data = json.loads(exports[0].read_text(encoding="utf-8"))
        assert data["trading_day"] == latest["trading_day"]
        assert data["outcome"] == "skipped_no_consensus"

    def test_ai_cycle_factory_writes_error_json_on_failure(
        self,
        isolated_data_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        obs_dir = tmp_path / "observation"

        def _boom() -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(
            scheduler_commands, "_ai_scheduler_universe", _boom
        )
        handler = _ai_cycle_factory(db_path=isolated_data_dir)

        async def _run_handler() -> None:
            await handler()

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(_run_handler())

        errors = list(obs_dir.glob("ai_cycle_error_*.json"))
        assert len(errors) == 1
        data = json.loads(errors[0].read_text(encoding="utf-8"))
        assert data["error"] == "boom"
        assert "at" in data

    def test_ai_cycle_factory_submits_to_external_paper_when_enabled(
        self, isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Round 0063: default paper broker is OANDA, so set OANDA credentials
        # to match the default policy. Insert a EUR_USD bar instead of SPY
        # because SPY is no longer in the default allowlist.
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        monkeypatch.setenv("ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED", "true")
        monkeypatch.setenv("ALPHABRIEF_OANDA_TOKEN", "test-token")
        monkeypatch.setenv("ALPHABRIEF_OANDA_ACCOUNT_ID", "test-account")
        adapter = _SubmittingAdapter()
        monkeypatch.setattr(scheduler_commands, "_build_adapter", lambda: adapter)

        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-1",
            capabilities=["structured_output"],
            structured_output={
                "analysis": "Bullish continuation.",
                "view": "bullish",
                "confidence": 0.8,
                "evidence": ["trend"],
                "risks": [],
                "suggested_action": "buy",
                "target_position_pct": "0.10",
                "veto": False,
                "needs_human_review": False,
            },
        )
        monkeypatch.setattr(
            scheduler_commands,
            "_build_ai_committee",
            lambda: TradingCommittee(
                gateway=ModelGateway(providers=[provider]),
                discipline=DisciplineConfig(),
            ),
        )

        market_store = MarketDataStore(db_path=isolated_data_dir / "alphabrief.db")
        try:
            market_store.insert_bars(
                [
                    Bar(
                        symbol="EUR_USD",
                        timestamp=datetime.now(UTC),
                        open=Decimal("1.14"),
                        high=Decimal("1.14"),
                        low=Decimal("1.14"),
                        close=Decimal("1.14"),
                        volume=Decimal("1000"),
                        source="test",
                        data_version="test",
                    )
                ],
                source="test",
                data_version="test",
            )
        finally:
            market_store.close()

        handler = _ai_cycle_factory(db_path=isolated_data_dir)

        async def _run_handler() -> None:
            await handler()

        asyncio.run(_run_handler())

        assert len(adapter.requests) == 1
        assert adapter.requests[0].symbol == "EUR_USD"
        # The committee's unchanged $100 paper budget is converted into FX
        # units at the stored EUR_USD price before external submission.
        assert adapter.requests[0].quantity == Decimal("100") / Decimal("1.14")

        store = AiTradingStore(db_path=isolated_data_dir / "alphabrief.db")
        try:
            latest = store.get_latest_cycle()
            assert latest is not None
            attempt = latest["attempts"][0]
            assert attempt["execution_backend"] == "external_paper"
            assert attempt["broker_order_id"] == attempt["order_id"]
            assert attempt["client_order_id"] == attempt["intent_id"]
        finally:
            store.close()

    def test_external_ai_cycle_refuses_missing_oanda_credentials(
        self, isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M01-W01: the policy can only claim OANDA practice, so the
        expressible fail-closed case is an OANDA policy with no OANDA
        credentials configured. The external paper path must raise instead
        of running (missing credentials fail closed, no local fill).
        """
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        monkeypatch.setenv("ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED", "true")
        monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
        monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
        # An OANDA-only policy with no credentials must be refused.
        policy_path = isolated_data_dir / "policy.yaml"
        policy_path.write_text(
            (
                "mode: paper\n"
                "provider: oanda_paper\n"
                "market: fx\n"
                "symbols: [EUR_USD]\n"
                "order_types: [market, limit]\n"
                "timezone: America/New_York\n"
                "trading_days: [mon, tue, wed, thu, fri]\n"
                "session_start: \"09:30\"\n"
                "session_end: \"16:00\"\n"
                "max_order_notional: \"100\"\n"
                "max_total_exposure: \"300\"\n"
                "require_human_review: true\n"
                "automated_execution: false\n"
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("ALPHABRIEF_EXECUTION_POLICY_FILE", str(policy_path))

        handler = _ai_cycle_factory(db_path=isolated_data_dir)

        async def _run_handler() -> None:
            await handler()

        with pytest.raises(RuntimeError, match="requires OANDA"):
            asyncio.run(_run_handler())

    def test_ai_scheduler_universe_can_be_overridden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "ALPHABRIEF_AI_SCHEDULER_UNIVERSE",
            " eur_usd, gbp_usd ",
        )

        assert scheduler_commands._ai_scheduler_universe() == (
            "EUR_USD",
            "GBP_USD",
        )


class TestResearchContentFactory:
    def test_generates_macro_and_evaluation(
        self, isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The content factory builds its ModelGateway through the
        # production provider factory, which fails closed without a real
        # provider. Explicit fake selection is test composition; macro
        # indicators and model evaluations are deterministic and
        # provider-independent, while briefs/debates need a real provider
        # whose output matches the brief/debate schemas (the conservative
        # fake returns committee-vote shaped output), so they are
        # exercised in the deployed environment instead.
        from alphabrief_api.db import MacroStore
        from alphabrief_api.db.model_eval import ModelEvalStore
        from alphabrief_cli.scheduler_commands import _research_content_factory

        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "fake")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        handler = _research_content_factory(db_path=isolated_data_dir)

        async def _run() -> None:
            await handler()

        asyncio.run(_run())

        database = isolated_data_dir / "alphabrief.db"
        macro_store = MacroStore(db_path=database)
        eval_store = ModelEvalStore(db_path=database)
        try:
            indicators = macro_store.list_indicators(limit=50)
            assert any(i.indicator_id == "GDP" for i in indicators)
            evaluations = eval_store.list_evaluations(limit=10)
            assert len(evaluations) >= 1
        finally:
            macro_store.close()
            eval_store.close()
