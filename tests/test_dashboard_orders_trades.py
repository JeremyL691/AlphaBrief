"""M14-W04: Orders & Trades workspace.

Covers AC-M14-W04-03: Orders & Trades represents pending, filled,
partially filled, rejected, cancelled, replaced, expired, closed, and
reconciliation-difference states without losing OANDA transaction
identity.
"""

from __future__ import annotations

from alphabrief_api.dashboard.workspaces import (
    ORDER_STATES,
    build_orders_trades_view,
)


def _orders() -> list[dict[str, object]]:
    return [
        {
            "client_order_id": "order-1",
            "broker_order_id": "oanda-1",
            "status": "FILLED",
            "transaction_id": "tx-100",
            "symbol": "EUR_USD",
            "side": "buy",
            "quantity": "10000",
            "fill_price": "1.10000",
        },
        {
            "client_order_id": "order-2",
            "broker_order_id": "oanda-2",
            "status": "PENDING",
            "transaction_id": "tx-101",
            "symbol": "XAU_USD",
        },
        {
            "client_order_id": "order-3",
            "broker_order_id": "oanda-3",
            "status": "REJECTED",
            "transaction_id": "tx-102",
        },
    ]


class TestOrderStates:
    def test_all_documented_states_are_representable(self) -> None:
        assert ORDER_STATES == (
            "pending",
            "filled",
            "partially_filled",
            "rejected",
            "cancelled",
            "replaced",
            "expired",
            "closed",
            "reconciliation_difference",
        )

    def test_state_counts_cover_every_documented_state(self) -> None:
        view = build_orders_trades_view(orders=_orders())
        assert set(view.state_counts) == set(ORDER_STATES)
        assert view.state_counts["filled"] == 1
        assert view.state_counts["pending"] == 1
        assert view.state_counts["rejected"] == 1
        assert view.state_counts["partially_filled"] == 0

    def test_oanda_transaction_identity_is_preserved(self) -> None:
        view = build_orders_trades_view(orders=_orders())
        by_id = {row.client_order_id: row for row in view.orders}
        assert by_id["order-1"].transaction_id == "tx-100"
        assert by_id["order-1"].broker_order_id == "oanda-1"
        assert by_id["order-1"].fill_price == "1.10000"

    def test_partially_filled_and_replaced_are_representable(self) -> None:
        orders = _orders() + [
            {
                "client_order_id": "order-4",
                "broker_order_id": "oanda-4",
                "status": "PARTIALLY_FILLED",
                "transaction_id": "tx-103",
            },
            {
                "client_order_id": "order-5",
                "broker_order_id": "oanda-5",
                "status": "REPLACED",
                "transaction_id": "tx-104",
            },
        ]
        view = build_orders_trades_view(orders=orders)
        assert view.state_counts["partially_filled"] == 1
        assert view.state_counts["replaced"] == 1

    def test_reconciliation_differences_are_marked_not_merged(self) -> None:
        view = build_orders_trades_view(
            orders=_orders(), reconciliation_diffs=["order-2"]
        )
        by_id = {row.client_order_id: row for row in view.orders}
        assert by_id["order-2"].reconciliation_diff is True
        assert by_id["order-1"].reconciliation_diff is False

    def test_deterministic(self) -> None:
        first = build_orders_trades_view(orders=_orders())
        second = build_orders_trades_view(orders=_orders())
        assert first.model_dump() == second.model_dump()
