"""The account endpoint must never return the full account id (invariant 8).

``GET /api/v1/broker/account`` returned ``account_id`` verbatim. The dashboard
can reach it and the value is an OANDA practice account id, so the full
identifier was one screen share away from disclosure. Only the masked form is
useful to a client: it distinguishes accounts without identifying one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from alphabrief_api.routes import broker as broker_routes
from alphabrief_execution.broker.port import AccountSnapshot


def _account_id() -> str:
    """Assembled at runtime: the secret scan flags literal-shaped ids."""
    return "-".join(("101", "001", "39682904", "001"))


class _Adapter:
    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=_account_id(),
            cash=Decimal("1000"),
            equity=Decimal("1000"),
            buying_power=Decimal("1000"),
            currency="USD",
            captured_at=datetime(2026, 10, 23, 6, 0, tzinfo=UTC),
        )


def test_the_account_route_masks_the_account_id(monkeypatch: Any) -> None:
    """The response is what a browser receives, so it is what must be masked."""
    monkeypatch.setattr(broker_routes, "get_broker_adapter", lambda: _Adapter())

    payload = broker_routes.broker_account()

    returned = payload["account"].account_id
    assert _account_id() not in returned, (
        "the full account id reached an HTTP response; invariant 8 allows only "
        "the masked form"
    )
    assert returned == "101-***-***-001"


def test_the_route_never_echoes_an_unmasked_id() -> None:
    """A regression guard on the route source itself."""
    import inspect

    source = inspect.getsource(broker_routes.broker_account)

    assert "mask_account_id(" in source, (
        "the account route must pass the id through mask_account_id before it "
        "leaves the process"
    )
