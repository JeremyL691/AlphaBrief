"""Practice test: order payload shape against the real instrument catalog.

No order is submitted here: safety invariant 5 requires every order to
pass the decision → RiskGate → persisted RiskDecision chain, which is
exercised by the S3 vertical slice. This test only proves that the
account's real precision rules produce a valid v20 payload.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import load_env_file
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import (
    load_oanda_paper_config,
    read_oanda_credentials,
)
from alphabrief_execution.broker.oanda.instruments import fetch_instruments
from alphabrief_execution.broker.oanda.orders import (
    DependentOrder,
    OandaOrderRequest,
    serialize_order,
)
from alphabrief_execution.broker.runtime import oanda_is_configured

pytestmark = pytest.mark.practice

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_payload_serializes_with_the_accounts_real_precision() -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        load_env_file(env_path)
    if not oanda_is_configured():
        pytest.fail(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )
    token, account_id = read_oanda_credentials()
    client = OandaHttpClient(
        config=load_oanda_paper_config(REPO_ROOT / "config/oanda_paper.yaml"),
        token=token,
        account_id=account_id,
    )
    catalog = fetch_instruments(client, account_id=account_id)
    eur_usd = next(i for i in catalog.instruments if i.name == "EUR_USD")

    payload = serialize_order(
        OandaOrderRequest(
            type="MARKET",
            instrument="EUR_USD",
            units=Decimal("-1000"),
            time_in_force="FOK",
            stop_loss=DependentOrder(kind="stop_loss", price=Decimal("1.00000")),
            take_profit=DependentOrder(kind="take_profit", price=Decimal("2.00000")),
        ),
        eur_usd,
    )

    assert payload["units"] == "-1000"
    assert "side" not in payload
    assert payload["timeInForce"] == "FOK"
    assert payload["stopLossOnFill"]["price"] == "1.00000"
    assert payload["takeProfitOnFill"]["price"] == "2.00000"
    # Precision comes from the account's own metadata.
    assert eur_usd.trade_units_precision == 0
    assert payload["instrument"] == eur_usd.name
