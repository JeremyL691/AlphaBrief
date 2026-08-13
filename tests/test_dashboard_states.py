"""M14-W02: truthful page-state system.

Covers AC-M14-W02-02: each route renders deterministic loading, empty,
stale, partial, error, offline, frozen, and ready states from API truth
instead of blank panels or fake fallback values.
"""

from __future__ import annotations

import pytest
from alphabrief_api.dashboard.shell import (
    PAGE_STATES,
    PageState,
    TruthInputs,
    derive_page_state,
    render_state_payload,
)


class TestStateDerivation:
    def test_all_eight_states_are_declared(self) -> None:
        assert PAGE_STATES == (
            "loading",
            "empty",
            "stale",
            "partial",
            "error",
            "offline",
            "frozen",
            "ready",
        )

    def test_ready_from_fresh_complete_truth(self) -> None:
        truth = TruthInputs(
            has_data=True,
            freshness_status="fresh",
            partial=False,
        )
        assert derive_page_state(truth) == "ready"

    def test_empty_from_missing_data(self) -> None:
        truth = TruthInputs(has_data=False, freshness_status="fresh")
        assert derive_page_state(truth) == "empty"

    def test_stale_from_stale_truth(self) -> None:
        truth = TruthInputs(has_data=True, freshness_status="stale")
        assert derive_page_state(truth) == "stale"

    def test_partial_from_partial_truth(self) -> None:
        truth = TruthInputs(
            has_data=True, freshness_status="fresh", partial=True
        )
        assert derive_page_state(truth) == "partial"

    def test_error_from_error_truth(self) -> None:
        truth = TruthInputs(has_data=True, error=True)
        assert derive_page_state(truth) == "error"

    def test_offline_from_offline_truth(self) -> None:
        truth = TruthInputs(has_data=True, offline=True)
        assert derive_page_state(truth) == "offline"

    def test_frozen_wins_over_everything(self) -> None:
        truth = TruthInputs(
            has_data=True,
            freshness_status="fresh",
            error=True,
            offline=True,
            frozen=True,
        )
        assert derive_page_state(truth) == "frozen"

    def test_offline_never_degrades_to_ready(self) -> None:
        truth = TruthInputs(
            has_data=True, freshness_status="fresh", offline=True
        )
        assert derive_page_state(truth) == "offline"

    def test_derivation_is_deterministic(self) -> None:
        first = TruthInputs(has_data=True, freshness_status="stale", partial=True)
        second = TruthInputs(has_data=True, freshness_status="stale", partial=True)
        assert derive_page_state(first) == derive_page_state(second)


class TestStatePayloads:
    @pytest.mark.parametrize("state", PAGE_STATES)
    def test_every_state_has_a_typed_payload(self, state: PageState) -> None:
        payload = render_state_payload(state, "overview")
        assert payload.state == state
        assert payload.title
        assert payload.message
        assert "overview" in payload.message

    def test_payloads_never_invent_runtime_values(self) -> None:
        """State payloads carry documented copy only: no fabricated
        numbers, prices, or positions."""
        for state in PAGE_STATES:
            payload = render_state_payload(state, "risk")
            for field in ("title", "message", "action"):
                value = getattr(payload, field)
                if value is None:
                    continue
                assert "100" not in value
                assert "0.0" not in value
                assert "1.00" not in value

    def test_ready_payload_has_no_action(self) -> None:
        assert render_state_payload("ready", "overview").action is None

    def test_frozen_payload_mentions_frozen(self) -> None:
        payload = render_state_payload("frozen", "scheduler")
        assert "frozen" in payload.title.lower() or "frozen" in (
            payload.message.lower()
        )
