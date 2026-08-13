"""M14-W05: end-to-end decision and execution trace explorer.

Covers AC-M14-W05-01/03: every displayed cycle, intent, risk decision,
order, trade, transaction, reconciliation, and portfolio event links
bidirectionally through persisted correlation identifiers; missing,
stale, conflicting, or partial trace segments are visibly classified
and never silently collapsed into a successful execution story.
"""

from __future__ import annotations

import pytest
from alphabrief_api.dashboard.trace_explorer import (
    CORRELATION_KEYS,
    TraceExplorerView,
    build_trace_explorer,
    classify_segment,
    verify_bidirectional_links,
)


def _full_chain() -> list[dict[str, object]]:
    return [
        {
            "kind": "cycle",
            "segment_id": "cycle-1",
            "correlation_ids": {
                "cycle_id": "cycle-1",
                "intent_id": "intent-1",
                "reconciliation_id": "recon-1",
                "portfolio_event_id": "portfolio-1",
            },
            "timestamp": "2026-08-14T00:00:00+00:00",
            "detail": {"outcome": "executed"},
        },
        {
            "kind": "evidence",
            "segment_id": "snap-abc123",
            "correlation_ids": {"cycle_id": "cycle-1"},
            "detail": {"data_version": "v3", "citations": "evidence-1,news-42"},
        },
        {
            "kind": "transcript",
            "segment_id": "transcript-1",
            "correlation_ids": {"cycle_id": "cycle-1"},
            "detail": {"turns": "2"},
        },
        {
            "kind": "intent",
            "segment_id": "intent-1",
            "correlation_ids": {
                "cycle_id": "cycle-1",
                "risk_decision_id": "decision-1",
            },
            "detail": {"inputs_hash": "hash-abc"},
        },
        {
            "kind": "risk_decision",
            "segment_id": "decision-1",
            "correlation_ids": {"intent_id": "intent-1", "order_id": "order-1"},
            "detail": {
                "inputs_hash": "hash-abc",
                "rules": "margin:pass,concentration:pass",
            },
        },
        {
            "kind": "order",
            "segment_id": "order-1",
            "correlation_ids": {
                "risk_decision_id": "decision-1",
                "transaction_id": "tx-100",
            },
            "detail": {"status": "FILLED"},
        },
        {
            "kind": "trade",
            "segment_id": "trade-1",
            "correlation_ids": {"order_id": "order-1"},
            "detail": {"fill_price": "1.10000"},
        },
        {
            "kind": "transaction",
            "segment_id": "tx-100",
            "correlation_ids": {"order_id": "order-1"},
            "detail": {"broker_ref": "oanda-1"},
        },
        {
            "kind": "reconciliation",
            "segment_id": "recon-1",
            "correlation_ids": {"cycle_id": "cycle-1"},
            "detail": {"orders_match": "true"},
        },
        {
            "kind": "portfolio",
            "segment_id": "portfolio-1",
            "correlation_ids": {"cycle_id": "cycle-1"},
            "detail": {"nav": "61400.00"},
        },
    ]


class TestBidirectionalLinks:
    def test_correlation_keys_cover_every_segment_kind(self) -> None:
        assert set(CORRELATION_KEYS) == {
            "cycle_id",
            "intent_id",
            "risk_decision_id",
            "order_id",
            "transaction_id",
            "reconciliation_id",
            "portfolio_event_id",
        }

    def test_full_chain_links_bidirectionally(self) -> None:
        view = build_trace_explorer(
            cycle_id="cycle-1", segments=_full_chain()
        )
        issues = verify_bidirectional_links(view)
        assert issues == ()

    def test_broken_forward_link_is_reported(self) -> None:
        chain = _full_chain()
        chain[5]["correlation_ids"] = {"risk_decision_id": "decision-ghost"}
        view = build_trace_explorer(cycle_id="cycle-1", segments=chain)
        issues = verify_bidirectional_links(view)
        assert any("decision-ghost" in issue for issue in issues)

    def test_missing_back_link_is_reported(self) -> None:
        chain = _full_chain()
        # The order segment does not link back to its decision.
        chain[5]["correlation_ids"] = {}
        view = build_trace_explorer(cycle_id="cycle-1", segments=chain)
        issues = verify_bidirectional_links(view)
        assert any("does not link back" in issue for issue in issues)


class TestSegmentClassification:
    @pytest.mark.parametrize(
        "flags,expected",
        [
            ({"present": True}, "complete"),
            ({"present": False}, "missing"),
            ({"present": True, "stale": True}, "stale"),
            ({"present": True, "conflicting": True}, "conflicting"),
            ({"present": True, "partial": True}, "partial"),
        ],
    )
    def test_classification_matrix(self, flags: dict[str, bool], expected: str) -> None:
        assert classify_segment(**flags) == expected

    def test_missing_segment_yields_missing_disposition(self) -> None:
        chain = _full_chain()
        chain.append(
            {
                "kind": "reconciliation",
                "segment_id": "recon-2",
                "present": False,
            }
        )
        view = build_trace_explorer(cycle_id="cycle-1", segments=chain)
        assert view.disposition == "missing"

    def test_conflicting_segment_never_collapses(self) -> None:
        chain = _full_chain()
        chain[8]["conflicting"] = True  # reconciliation mismatch
        view = build_trace_explorer(cycle_id="cycle-1", segments=chain)
        assert view.disposition == "conflicting"
        segments = {s.segment_id: s for s in view.segments}
        assert segments["recon-1"].status == "conflicting"

    def test_stale_and_partial_are_visible(self) -> None:
        chain = _full_chain()
        chain[1]["stale"] = True
        chain[4]["partial"] = True
        view = build_trace_explorer(cycle_id="cycle-1", segments=chain)
        assert view.disposition == "stale"
        segments = {s.segment_id: s for s in view.segments}
        assert segments["snap-abc123"].status == "stale"
        assert segments["decision-1"].status == "partial"

    def test_complete_chain_disposition(self) -> None:
        view = build_trace_explorer(
            cycle_id="cycle-1", segments=_full_chain()
        )
        assert view.disposition == "complete"

    def test_deterministic(self) -> None:
        first = build_trace_explorer(
            cycle_id="cycle-1", segments=_full_chain()
        )
        second = build_trace_explorer(
            cycle_id="cycle-1", segments=_full_chain()
        )
        assert first.model_dump() == second.model_dump()
        assert isinstance(first, TraceExplorerView)
