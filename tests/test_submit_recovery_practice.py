"""Practice tests for post-submission crash recovery and resolution (GUIDE S5).

Run with:
    pytest -m practice tests/test_submit_recovery_practice.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent, load_env_file
from alphabrief_execution.broker.oanda.order_ops import OrderOpsClient
from alphabrief_execution.broker.oanda.unknown_outcome import (
    UnknownOutcomeResolver,
)
from alphabrief_execution.broker.runtime import (
    build_oanda_paper_client,
    oanda_is_configured,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_risk.entry_rules import EntryRulePolicy

pytestmark = pytest.mark.practice

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_oanda() -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        load_env_file(env_path)
    if not oanda_is_configured():
        pytest.fail(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )


def test_practice_unknown_outcome_resolver_resolves_historical_order() -> None:
    """Verify UnknownOutcomeResolver queries real OANDA for historical orders."""
    _ensure_oanda()
    client = build_oanda_paper_client()
    resolver = UnknownOutcomeResolver(OrderOpsClient(client))

    # Historical S3 vertical slice client order id
    res = resolver.resolve("ai_e482fc8865b9")
    assert res.resolution == "RESOLVED_ACCEPTED"
    assert res.broker_order_id == "4"


def test_practice_unknown_outcome_resolver_not_found() -> None:
    """Verify UnknownOutcomeResolver returns RESOLVED_NOT_SUBMITTED."""
    _ensure_oanda()
    client = build_oanda_paper_client()
    resolver = UnknownOutcomeResolver(OrderOpsClient(client))

    res = resolver.resolve("nonexistent_client_id_99999999")
    assert res.resolution == "RESOLVED_NOT_SUBMITTED"


def test_practice_market_hours_enforced() -> None:
    """Verify RiskGate blocks order submission outside market hours safely."""
    _ensure_oanda()

    gate = RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset({"EUR_USD"}),
            entry_rules=EntryRulePolicy(block_weekend_and_late_friday=True),
        )
    )

    now = datetime.now(UTC)
    intent = OrderIntent(
        intent_id="test_weekend_gate",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1000"),
        rationale="test weekend gate",
        source="manual",
        created_at=now,
    )

    # If currently weekend (Saturday/Sunday) or Friday after 13:00 UTC:
    is_weekend = now.weekday() in (5, 6) or (now.weekday() == 4 and now.hour >= 13)
    if is_weekend:
        decision = gate.evaluate(intent)
        assert decision.approved is False
        assert (
            any(
                "WEEKEND" in tag or "weekend" in tag.lower()
                for tag in decision.risk_tags
            )
            or "weekend" in decision.reason.lower()
        )
