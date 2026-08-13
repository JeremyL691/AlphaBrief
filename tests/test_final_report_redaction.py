"""M17-W01: final report redaction scan.

Covers AC-M17-W01-03: the report contains no secret, full account ID,
authorization value, unlicensed news body, waiver, TBD, unsupported
completion claim, or implication that live trading is enabled.
"""

from __future__ import annotations

from alphabrief_core import (
    FORBIDDEN_REPORT_MARKERS,
    LIVE_CLAIM_MARKERS,
    ReportContentVerdict,
    scan_report_content,
)

CLEAN_TEXT = (
    "AlphaBrief final acceptance report\n"
    "Status: NOT_PASSED\n"
    "OANDA practice-only; no live trading path exists."
)


class TestReportRedaction:
    def test_clean_content_passes(self) -> None:
        verdict = scan_report_content(text=CLEAN_TEXT)
        assert isinstance(verdict, ReportContentVerdict)
        assert verdict.clean is True
        assert verdict.findings == ()

    def test_bearer_token_is_caught(self) -> None:
        verdict = scan_report_content(
            text=CLEAN_TEXT + "\nBearer abc123def456\n"
        )
        assert verdict.clean is False
        assert any("bearer" in finding for finding in verdict.findings)

    def test_token_value_is_caught(self) -> None:
        verdict = scan_report_content(
            text=CLEAN_TEXT + '\ntoken = "super-secret"\n'
        )
        assert verdict.clean is False

    def test_authorization_value_is_caught(self) -> None:
        verdict = scan_report_content(
            text=CLEAN_TEXT + "\nauthorization: XYZ\n"
        )
        assert verdict.clean is False

    def test_full_account_id_is_caught(self) -> None:
        verdict = scan_report_content(
            text=CLEAN_TEXT + "\naccount_id: 001-002-3456789-001\n"
        )
        assert verdict.clean is False

    def test_bare_full_account_number_is_caught(self) -> None:
        verdict = scan_report_content(
            text=CLEAN_TEXT + "\naccount-12345678\n"
        )
        assert verdict.clean is False

    def test_waiver_and_tbd_markers_are_declared(self) -> None:
        assert FORBIDDEN_REPORT_MARKERS == ("waiver", "tbd")

    def test_waiver_is_caught(self) -> None:
        verdict = scan_report_content(
            text=CLEAN_TEXT + "\nA waiver was granted for M04.\n"
        )
        assert verdict.clean is False
        assert any("waiver" in finding for finding in verdict.findings)

    def test_tbd_is_caught(self) -> None:
        verdict = scan_report_content(
            text=CLEAN_TEXT + "\nRemaining work: TBD.\n"
        )
        assert verdict.clean is False
        assert any("tbd" in finding for finding in verdict.findings)

    def test_live_claim_markers_are_declared(self) -> None:
        assert LIVE_CLAIM_MARKERS == (
            "live trading is enabled",
            "live mode is active",
            "go live",
        )

    def test_live_trading_claim_is_caught(self) -> None:
        verdict = scan_report_content(
            text=CLEAN_TEXT + "\nLive trading is enabled for this account.\n"
        )
        assert verdict.clean is False
        assert any("live-claim" in finding for finding in verdict.findings)

    def test_practice_only_statement_is_not_caught(self) -> None:
        # The mandatory practice-only statement mentions the word live
        # only in a negative form and must stay clean.
        verdict = scan_report_content(text=CLEAN_TEXT)
        assert verdict.clean is True

    def test_deterministic(self) -> None:
        first = scan_report_content(text=CLEAN_TEXT)
        second = scan_report_content(text=CLEAN_TEXT)
        assert first.model_dump() == second.model_dump()
