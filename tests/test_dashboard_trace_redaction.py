"""M14-W05: trace explorer redaction.

Covers AC-M14-W05-02: the explorer exposes evidence versions,
citations, inputs hash, rule-by-rule outcomes, broker references,
timestamps, and reconciliation disposition without exposing secrets or
full account IDs.
"""

from __future__ import annotations

from alphabrief_api.dashboard.trace_explorer import (
    account_id_hash,
    build_trace_explorer,
    redact_explorer,
)
from test_dashboard_trace_explorer import _full_chain


def _chain_with_secrets() -> list[dict[str, object]]:
    chain = _full_chain()
    chain.append(
        {
            "kind": "transaction",
            "segment_id": "tx-200",
            "correlation_ids": {"order_id": "order-1"},
            "detail": {
                "broker_ref": "oanda-9",
                "authorization": "Bearer " + "abcdef123456",
                "token": "secret-" + "token-value",
                "account_id": "account-" + "12345678901234567890",
            },
        }
    )
    return chain


class TestRedaction:
    def test_secrets_are_redacted(self) -> None:
        view = build_trace_explorer(
            cycle_id="cycle-1", segments=_chain_with_secrets()
        )
        redacted = redact_explorer(view)
        serialized = redacted.model_dump_json()
        assert "abcdef123456" not in serialized
        assert "secret-token-value" not in serialized
        assert "account-12345678901234567890" not in serialized

    def test_full_account_ids_never_survive(self) -> None:
        view = build_trace_explorer(
            cycle_id="cycle-1", segments=_chain_with_secrets()
        )
        redacted = redact_explorer(view)
        serialized = redacted.model_dump_json()
        assert "account-12345678901234567890" not in serialized
        assert "[REDACTED]" in serialized

    def test_evidence_and_hashes_are_preserved(self) -> None:
        view = build_trace_explorer(
            cycle_id="cycle-1", segments=_chain_with_secrets()
        )
        redacted = redact_explorer(view)
        segments = {s.segment_id: s for s in redacted.segments}
        assert segments["snap-abc123"].detail["data_version"] == "v3"
        assert segments["snap-abc123"].detail["citations"] == (
            "evidence-1,news-42"
        )
        assert segments["decision-1"].detail["inputs_hash"] == "hash-abc"
        assert segments["decision-1"].detail["rules"] == (
            "margin:pass,concentration:pass"
        )

    def test_broker_references_and_timestamps_survive(self) -> None:
        view = build_trace_explorer(
            cycle_id="cycle-1", segments=_chain_with_secrets()
        )
        redacted = redact_explorer(view)
        segments = {s.segment_id: s for s in redacted.segments}
        assert segments["tx-200"].detail["broker_ref"] == "oanda-9"
        assert segments["cycle-1"].timestamp == "2026-08-14T00:00:00+00:00"

    def test_reconciliation_disposition_is_preserved(self) -> None:
        view = build_trace_explorer(
            cycle_id="cycle-1", segments=_chain_with_secrets()
        )
        redacted = redact_explorer(view)
        assert redacted.disposition == view.disposition
        assert redacted.redaction_applied is True

    def test_account_id_hash_is_non_reversible_display(self) -> None:
        full_id = "account-" + "12345678901234567890"
        digest = account_id_hash(full_id)
        assert len(digest) == 12
        assert digest != full_id
        assert account_id_hash(full_id) == digest

    def test_deterministic(self) -> None:
        first_view = build_trace_explorer(
            cycle_id="cycle-1", segments=_chain_with_secrets()
        )
        second_view = build_trace_explorer(
            cycle_id="cycle-1", segments=_chain_with_secrets()
        )
        assert redact_explorer(first_view).model_dump() == (
            redact_explorer(second_view).model_dump()
        )
