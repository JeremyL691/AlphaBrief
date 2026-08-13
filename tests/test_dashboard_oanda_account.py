"""M14-W04: OANDA Account workspace.

Covers AC-M14-W04-01: OANDA Account displays cash, NAV, margin, P&L,
financing, positions, pending orders, fills, category attribution,
exposure, and time series from broker-authoritative projections.
"""

from __future__ import annotations

from alphabrief_api.dashboard.workspaces import build_account_view


def _projection() -> dict[str, object]:
    return {
        "cash": "50000.00",
        "nav": "61400.00",
        "margin_used": "1030.00",
        "realized_pnl": "1200.00",
        "unrealized_pnl": "10200.00",
        "financing": None,
        "exposure": {"gross_exposure": "15800.00", "net_exposure": "15800.00"},
        "observed_at": "2026-08-14T00:00:00+00:00",
        "freshness": "fresh",
        "positions": [
            {
                "symbol": "EUR_USD",
                "quantity": "10000",
                "average_price": "1.10000",
                "unrealized_pnl": "100.00",
            }
        ],
        "pending_orders": [
            {"client_order_id": "order-2", "broker_order_id": "oanda-2",
             "status": "SUBMITTED"}
        ],
        "fills": [
            {"event_id": "audit-1", "order_id": "order-1",
             "created_at": "2026-08-14T00:00:00+00:00"}
        ],
        "category_attribution": [
            {"category": "CURRENCY", "gross_exposure": "11000.00",
             "net_exposure": "11000.00"}
        ],
    }


def _series() -> list[dict[str, object]]:
    return [
        {
            "snapshot_id": "esnap-1",
            "captured_at": "2026-08-14T00:00:00+00:00",
            "equity": "61400.00",
            "realized_pnl_day": "200.00",
        }
    ]


class TestAccountView:
    def test_displays_broker_authoritative_fields(self) -> None:
        view = build_account_view(
            projection=_projection(), time_series=_series()
        )
        account = view.account
        assert account.cash == "50000.00"
        assert account.nav == "61400.00"
        assert account.margin_used == "1030.00"
        assert account.realized_pnl == "1200.00"
        assert account.unrealized_pnl == "10200.00"
        assert account.gross_exposure == "15800.00"
        assert account.net_exposure == "15800.00"
        assert account.observed_at == "2026-08-14T00:00:00+00:00"
        assert account.freshness == "fresh"

    def test_financing_is_explicit_null_when_unknown(self) -> None:
        view = build_account_view(projection=_projection())
        assert view.account.financing is None

    def test_positions_pending_orders_fills_attribution(self) -> None:
        view = build_account_view(
            projection=_projection(), time_series=_series()
        )
        account = view.account
        assert account.positions[0].symbol == "EUR_USD"
        assert account.positions[0].unrealized_pnl == "100.00"
        assert account.pending_orders[0]["status"] == "SUBMITTED"
        assert account.fills[0]["event_id"] == "audit-1"
        assert account.category_attribution[0]["category"] == "CURRENCY"

    def test_time_series_is_carried(self) -> None:
        view = build_account_view(
            projection=_projection(), time_series=_series()
        )
        assert view.time_series[0]["equity"] == "61400.00"
        assert view.time_series[0]["snapshot_id"] == "esnap-1"

    def test_empty_projection_yields_explicit_nulls(self) -> None:
        view = build_account_view(projection=None)
        assert view.account.cash is None
        assert view.account.nav is None
        assert view.account.positions == ()
        assert view.time_series == ()

    def test_deterministic(self) -> None:
        first = build_account_view(
            projection=_projection(), time_series=_series()
        )
        second = build_account_view(
            projection=_projection(), time_series=_series()
        )
        assert first.model_dump() == second.model_dump()
