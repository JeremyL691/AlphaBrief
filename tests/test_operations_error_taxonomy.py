"""M15-W02: deterministic error taxonomy.

Covers AC-M15-W02-01: auth, validation, broker reject, rate-limit,
transient, protocol, data-quality, and safety failures map
deterministically to retryability, severity, execution freeze,
no-trade, and escalation behavior.
"""

from __future__ import annotations

import pytest
from alphabrief_core import (
    ERROR_CLASSES,
    ErrorClassification,
    classify_error,
)


class TestErrorClasses:
    def test_all_eight_classes_are_declared(self) -> None:
        assert ERROR_CLASSES == (
            "auth",
            "validation",
            "broker_reject",
            "rate_limit",
            "transient",
            "protocol",
            "data_quality",
            "safety",
        )

    @pytest.mark.parametrize(
        "code,retryable,severity,freeze,no_trade,escalate",
        [
            ("auth", False, "blocker", True, True, True),
            ("validation", False, "warning", False, True, False),
            ("broker_reject", False, "critical", True, True, True),
            ("rate_limit", True, "warning", False, True, False),
            ("transient", True, "warning", False, False, False),
            ("protocol", True, "warning", False, True, False),
            ("data_quality", False, "critical", False, True, True),
            ("safety", False, "blocker", True, True, True),
        ],
    )
    def test_classification_matrix(
        self,
        code: str,
        retryable: bool,
        severity: str,
        freeze: bool,
        no_trade: bool,
        escalate: bool,
    ) -> None:
        classification = classify_error(code)
        assert isinstance(classification, ErrorClassification)
        assert classification.retryable is retryable, code
        assert classification.severity == severity, code
        assert classification.freeze_execution is freeze, code
        assert classification.no_trade is no_trade, code
        assert classification.escalate is escalate, code

    def test_unknown_class_fails_closed_as_safety(self) -> None:
        classification = classify_error("mystery_failure")
        assert classification.error_class == "safety"
        assert classification.retryable is False
        assert classification.freeze_execution is True
        assert classification.no_trade is True
        assert classification.escalate is True
        assert classification.severity == "blocker"

    def test_classification_is_deterministic(self) -> None:
        for code in ERROR_CLASSES:
            first = classify_error(code)
            second = classify_error(code)
            assert first.model_dump() == second.model_dump()

    def test_safety_class_never_retries(self) -> None:
        assert classify_error("safety").retryable is False
