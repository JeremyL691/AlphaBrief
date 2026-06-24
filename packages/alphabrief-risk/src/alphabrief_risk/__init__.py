"""Risk controls for AlphaBrief paper trading."""

from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.context import (
    MACRO_HIGH_RISK_INDICATOR_COUNT,
    MACRO_HIGH_RISK_POSITION_MULTIPLIER,
    NEGATIVE_SENTIMENT_FLOOR,
    RISK_TAG_HUMAN_REVIEW,
    RISK_TAG_MACRO_HIGH_RISK,
    RISK_TAG_NEGATIVE_NEWS,
    RISK_TAG_POSITION_REDUCTION,
    NewsMacroRiskContext,
    RiskContextDecision,
    evaluate_news_macro_risk,
)
from alphabrief_risk.gate import RiskGate, RiskLimitConfig
from alphabrief_risk.kill_switch import KillSwitch

__all__ = [
    "AccountExposureContext",
    "KillSwitch",
    "MACRO_HIGH_RISK_INDICATOR_COUNT",
    "MACRO_HIGH_RISK_POSITION_MULTIPLIER",
    "NEGATIVE_SENTIMENT_FLOOR",
    "NewsMacroRiskContext",
    "RISK_TAG_HUMAN_REVIEW",
    "RISK_TAG_MACRO_HIGH_RISK",
    "RISK_TAG_NEGATIVE_NEWS",
    "RISK_TAG_POSITION_REDUCTION",
    "RiskContextDecision",
    "RiskGate",
    "RiskLimitConfig",
    "evaluate_news_macro_risk",
]
