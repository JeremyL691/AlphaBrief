"""Risk routes — config and dashboard."""

from __future__ import annotations

from decimal import Decimal

from alphabrief_risk import KillSwitch, RiskGate, RiskLimitConfig
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Module-level risk gate
# ---------------------------------------------------------------------------

_default_limits = RiskLimitConfig(
    trading_enabled=True,
    live_trading_enabled=False,
    enabled_strategies=frozenset(["ma_trend"]),
    symbol_allowlist=frozenset(["BTC-USD", "ETH-USD"]),
    max_order_quantity=Decimal("100"),
    max_order_value=Decimal("100000"),
    require_data_quality_passed=True,
    require_human_review=False,
)
_default_kill_switch = KillSwitch()
_default_risk_gate = RiskGate(limits=_default_limits, kill_switch=_default_kill_switch)


def _get_risk_gate() -> RiskGate:
    return _default_risk_gate


def _reset_risk_gate() -> None:
    """Reset risk gate state for test isolation."""
    global _default_kill_switch, _default_risk_gate
    _default_kill_switch = KillSwitch()
    _default_risk_gate = RiskGate(
        limits=_default_limits, kill_switch=_default_kill_switch
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class RiskConfigResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    trading_enabled: bool
    live_trading_enabled: bool
    enabled_strategies: list[str]
    symbol_allowlist: list[str]
    max_order_quantity: str | None
    max_order_value: str | None
    require_data_quality_passed: bool
    require_human_review: bool


class RiskDashboardResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    kill_switch_active: bool
    kill_switch_reason: str | None
    config: RiskConfigResponse


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/config", response_model=RiskConfigResponse)
def get_risk_config() -> RiskConfigResponse:
    """Return the current RiskGate configuration."""
    gate = _get_risk_gate()
    limits = gate.limits
    return RiskConfigResponse(
        trading_enabled=limits.trading_enabled,
        live_trading_enabled=limits.live_trading_enabled,
        enabled_strategies=sorted(limits.enabled_strategies),
        symbol_allowlist=sorted(limits.symbol_allowlist),
        max_order_quantity=(
            str(limits.max_order_quantity)
            if limits.max_order_quantity is not None
            else None
        ),
        max_order_value=(
            str(limits.max_order_value)
            if limits.max_order_value is not None
            else None
        ),
        require_data_quality_passed=limits.require_data_quality_passed,
        require_human_review=limits.require_human_review,
    )


@router.get("/dashboard", response_model=RiskDashboardResponse)
def get_risk_dashboard() -> RiskDashboardResponse:
    """Return the risk overview dashboard."""
    gate = _get_risk_gate()
    config = get_risk_config()
    return RiskDashboardResponse(
        kill_switch_active=gate.kill_switch.active,
        kill_switch_reason=gate.kill_switch.reason,
        config=config,
    )


__all__ = [
    "RiskConfigResponse",
    "RiskDashboardResponse",
    "router",
]
