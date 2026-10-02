"""Complete native closed history and durable per-instrument rule 12."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alphabrief_core import OrderIntent
from alphabrief_execution.broker.oanda.risk_sources import OandaRiskContextSources
from alphabrief_execution.broker.oanda.trade_ops import (
    TradeOperationError,
    TradeOpsClient,
)
from alphabrief_risk import AccountExposureContext, RiskGate, RiskLimitConfig
from alphabrief_risk.entry_rules import EntryRulePolicy
from alphabrief_risk.loss_state import ClosedTradeResult, LossStateStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
D = Decimal


def closed(
    identity: int,
    pnl: str = "-1",
    *,
    symbol: str = "EUR_USD",
    stamp: datetime | None = None,
) -> ClosedTradeResult:
    return ClosedTradeResult(
        trade_id=str(identity),
        symbol=symbol,
        closed_at=stamp or NOW - timedelta(hours=10 - identity),
        closing_transaction_id=str(100 + identity),
        pnl=D(pnl),
    )


def observe(
    store: LossStateStore,
    account: str,
    *,
    trades: tuple[ClosedTradeResult, ...],
    observed_at: datetime,
) -> dict[str, Any]:
    return store.observe_closed_trades(
        account,
        trades=trades,
        observed_at=observed_at,
        last_transaction_id=str(
            max([1, *(int(t.closing_transaction_id) for t in trades)])
        ),
    )


def test_third_loss_freezes_only_its_symbol_and_survives_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.duckdb"
    trades = (closed(1), closed(2), closed(3), closed(4, symbol="USD_JPY"))
    store = LossStateStore(database)
    states = observe(store, "test", trades=trades, observed_at=NOW)
    deadline = trades[2].closed_at + timedelta(hours=24)
    assert states["EUR_USD"].consecutive_losses == 3
    assert states["EUR_USD"].frozen_until == deadline
    assert states["USD_JPY"].consecutive_losses == 1
    assert states["USD_JPY"].frozen_until is None
    store.close()
    restarted = LossStateStore(database)
    try:
        assert restarted.symbol_state("test", "EUR_USD") == states["EUR_USD"]
        replay = observe(
            restarted,
            "test",
            trades=tuple(reversed(trades)),
            observed_at=NOW + timedelta(hours=2),
        )
        assert replay == states
        assert replay["EUR_USD"].frozen_until == deadline
        assert restarted.symbol_state("other", "EUR_USD") is None
    finally:
        restarted.close()


@pytest.mark.parametrize("pnl", ["0", "2"])
def test_nonlosing_closure_resets_streak_without_clearing_active_freeze(
    tmp_path: Path, pnl: str
) -> None:
    store = LossStateStore(tmp_path / "state.duckdb")
    try:
        before = (closed(1), closed(2), closed(3))
        initial = observe(store, "test", trades=before, observed_at=NOW)
        after = observe(
            store, "test", trades=(*before, closed(4, pnl)), observed_at=NOW
        )
        assert after["EUR_USD"].consecutive_losses == 0
        assert after["EUR_USD"].frozen_until == initial["EUR_USD"].frozen_until
        assert store.symbol_state("test", "EUR_USD") == after["EUR_USD"]
    finally:
        store.close()


def test_additional_real_loss_extends_from_its_close_not_observation(
    tmp_path: Path,
) -> None:
    store = LossStateStore(tmp_path / "state.duckdb")
    try:
        trades = tuple(closed(i) for i in range(1, 5))
        states = observe(store, "test", trades=trades, observed_at=NOW)
        deadline = trades[-1].closed_at + timedelta(hours=24)
        assert states["EUR_USD"].frozen_until == deadline
        expired = observe(
            store, "test", trades=trades, observed_at=deadline + timedelta(seconds=1)
        )
        assert expired["EUR_USD"].frozen_until == deadline
    finally:
        store.close()


@pytest.mark.parametrize(
    "failure", ["missing", "pnl", "time", "symbol", "duplicate", "future", "order"]
)
def test_bad_history_rolls_back_and_preserves_prior_freeze(
    tmp_path: Path, failure: str
) -> None:
    store = LossStateStore(tmp_path / "state.duckdb")
    trades = tuple(closed(i) for i in range(1, 4))
    before = observe(store, "test", trades=trades, observed_at=NOW)
    changed = list(trades)
    if failure == "missing":
        changed.pop()
    elif failure == "pnl":
        changed[0] = changed[0].model_copy(update={"pnl": D(1)})
    elif failure == "time":
        changed[0] = changed[0].model_copy(update={"closed_at": NOW})
    elif failure == "symbol":
        changed[0] = changed[0].model_copy(update={"symbol": "USD_JPY"})
    elif failure == "duplicate":
        changed.append(changed[0])
    elif failure == "future":
        changed.append(closed(4, stamp=NOW + timedelta(seconds=1)))
    else:
        changed.append(closed(4, stamp=NOW - timedelta(hours=20)))
    try:
        with pytest.raises(ValueError):
            observe(store, "test", trades=tuple(changed), observed_at=NOW)
        assert store.symbol_state("test", "EUR_USD") == before["EUR_USD"]
        assert observe(store, "test", trades=trades, observed_at=NOW) == before
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["backward", "omitted", "beyond"])
def test_watermark_rejects_history_regression_atomically(
    tmp_path: Path, failure: str
) -> None:
    store = LossStateStore(tmp_path / "state.duckdb")
    trades = tuple(closed(i) for i in range(1, 4))
    before = store.observe_closed_trades(
        "test", trades=trades, observed_at=NOW, last_transaction_id="200"
    )
    changed = trades
    watermark = "200"
    if failure == "backward":
        watermark = "199"
    elif failure == "omitted":
        changed = (*trades, closed(4, "2"))
    else:
        changed = (
            *trades,
            closed(4).model_copy(update={"closing_transaction_id": "201"}),
        )
    try:
        with pytest.raises(ValueError):
            store.observe_closed_trades(
                "test",
                trades=changed,
                observed_at=NOW,
                last_transaction_id=watermark,
            )
        assert store.symbol_state("test", "EUR_USD") == before["EUR_USD"]
        assert (
            store.observe_closed_trades(
                "test", trades=trades, observed_at=NOW, last_transaction_id="200"
            )
            == before
        )
        following = closed(4, "2").model_copy(update={"closing_transaction_id": "201"})
        after = store.observe_closed_trades(
            "test",
            trades=(*trades, following),
            observed_at=NOW,
            last_transaction_id="201",
        )
        assert after["EUR_USD"].consecutive_losses == 0
        assert after["EUR_USD"].frozen_until == before["EUR_USD"].frozen_until
    finally:
        store.close()


class Client:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []
        self.watermark = "99999"
        self.fail_page = False

    def account_path(self, suffix: str) -> str:
        return "/v3/accounts/test" + suffix

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        assert method == "GET"
        params = kwargs.get("params", {})
        if path.endswith("/summary"):
            return SimpleNamespace(
                json_body={
                    "account": dict(
                        id="test",
                        currency="USD",
                        balance="1000",
                        NAV="1000",
                        unrealizedPL="0",
                        marginUsed="0",
                        marginAvailable="1000",
                        lastTransactionID="99999",
                    )
                }
            )
        assert path.endswith("/trades")
        self.calls.append(params)
        if self.fail_page and "beforeID" in params:
            raise RuntimeError("private network error")
        rows = sorted(self.rows, key=lambda r: int(r["id"]), reverse=True)
        rows = [
            r
            for r in rows
            if (params["state"] == "ALL" or r["state"] == params["state"])
            and int(r["id"]) < int(params.get("beforeID", 10**12))
        ]
        return SimpleNamespace(
            json_body=dict(
                trades=rows[: params["count"]], lastTransactionID=self.watermark
            )
        )


def row(identity: int, *, state: str = "CLOSED", pnl: str = "-1") -> dict[str, Any]:
    return dict(
        id=str(identity),
        instrument="EUR_USD",
        state=state,
        currentUnits="0" if state == "CLOSED" else "50",
        initialUnits="100",
        realizedPL=pnl,
        financing="0",
        openTime=(NOW - timedelta(days=30)).isoformat(),
        closeTime=(NOW - timedelta(minutes=502 - identity)).isoformat(),
        closingTransactionIDs=[str(10000 + identity)],
    )


def test_complete_history_uses_native_before_id_beyond_first_500() -> None:
    client: Any = Client([row(i) for i in range(1, 502)])
    trades = TradeOpsClient(client).closed_trade_history(expected_watermark="99999")
    assert len(trades) == 501
    assert [trade.broker_trade_id for trade in trades] == list(map(str, range(1, 502)))
    assert client.calls == [
        dict(state="CLOSED", count=500),
        dict(state="CLOSED", count=500, beforeID="2"),
        dict(state="CLOSED", count=500, beforeID="1"),
    ]


def test_close_order_is_not_open_trade_id_order() -> None:
    old = row(1)
    new = row(2)
    old.update(closeTime=NOW.isoformat(), closingTransactionIDs=["20000"])
    client: Any = Client([old, new])
    trades = TradeOpsClient(client).closed_trade_history(expected_watermark="99999")
    assert [trade.broker_trade_id for trade in trades] == ["2", "1"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("realizedPL", None),
        ("realizedPL", -1.0),
        ("realizedPL", "NaN"),
        ("financing", None),
        ("financing", True),
        ("currentUnits", "1"),
        ("initialUnits", "0"),
        ("closingTransactionIDs", []),
        ("closingTransactionIDs", ["1"]),
        ("closingTransactionIDs", ["10001", "10001"]),
        ("closeTime", None),
        ("closeTime", "2026-10-02T12:00:00"),
    ],
)
def test_invalid_native_closed_facts_fail(field: str, value: Any) -> None:
    bad = row(1)
    if value is None:
        bad.pop(field)
    else:
        bad[field] = value
    client: Any = Client([bad])
    with pytest.raises((TradeOperationError, ValueError)):
        TradeOpsClient(client).closed_trade_history(expected_watermark="99999")


def test_failed_later_page_never_returns_partial_history() -> None:
    client: Any = Client([row(1), row(2)])
    client.fail_page = True
    with pytest.raises(RuntimeError):
        TradeOpsClient(client).closed_trade_history(
            expected_watermark="99999", page_size=1
        )


def test_changed_account_watermark_fails() -> None:
    client: Any = Client([])
    client.watermark = "100000"
    with pytest.raises(TradeOperationError):
        TradeOpsClient(client).closed_trade_history(expected_watermark="99999")


def test_native_source_ignores_partial_closure_and_uses_cumulative_pnl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finished = row(1, pnl="2")
    finished.update(financing="-3", closingTransactionIDs=["200", "10001"])
    client: Any = Client([finished, row(2, state="OPEN", pnl="-50")])
    source = OandaRiskContextSources(client, symbols=())
    monkeypatch.setattr(source, "fetch_positions", lambda: [])
    monkeypatch.setattr(source, "fetch_pending_orders", lambda: [])
    monkeypatch.setattr(source, "_prices_by_symbol", lambda: {})
    monkeypatch.setattr(source, "fetch_reconciliation_state", lambda: "clean")
    context = source.account_exposure_context(now=NOW, include_loss_streak=True)
    assert context.closed_trade_results is not None
    assert len(context.closed_trade_results) == 1
    result = context.closed_trade_results[0]
    assert result.trade_id == "1" and result.pnl == D(-1)
    assert result.closing_transaction_id == "10001"
    assert not context.loss_streak_complete  # Durable provider still must admit it.
    assert context.loss_streak_error is None


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("failure", ["frozen", "unknown", "stale", "future", "error"])
def test_required_streak_gate_rejects_both_directions(side: str, failure: str) -> None:
    context = AccountExposureContext(
        account_id="test",
        cash=D(1000),
        equity=D(1000),
        captured_at=NOW,
        current_total_exposure=D(0),
        loss_streak_complete=True,
        loss_streak_captured_at=NOW,
    )
    variants: dict[str, dict[str, Any]] = {
        "frozen": {"frozen_symbols": {"EUR_USD": "until tomorrow"}},
        "unknown": {"loss_streak_complete": False},
        "stale": {"loss_streak_captured_at": NOW - timedelta(seconds=61)},
        "future": {"loss_streak_captured_at": NOW + timedelta(seconds=1)},
        "error": {"loss_streak_error": "protocol"},
    }
    context = context.model_copy(update=variants[failure])
    gate = RiskGate(
        limits=RiskLimitConfig(entry_rules=EntryRulePolicy(require_loss_streak=True)),
        clock=lambda: NOW,
    )
    intent = OrderIntent.model_validate(
        dict(
            intent_id="test",
            symbol="EUR_USD",
            source="manual",
            side=side,
            order_type="market",
            quantity=D(1),
            rationale="test",
            created_at=NOW,
        )
    )
    decision = gate.evaluate(intent, estimated_price=D(1), account_context=context)
    assert not decision.approved and "LOSS_STREAK" in decision.risk_tags
    assert "loss_streak" in decision.rule_evidence
