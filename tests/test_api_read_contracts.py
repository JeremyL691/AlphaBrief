"""M13-W01: unified versioned API read contracts.

Covers AC-M13-W01-01/03: every required read surface has one versioned
response schema with UTC timestamps, stable IDs, provenance, freshness,
pagination, and explicit empty or partial state; unknown filters,
malformed cursors, invalid identifiers, and unavailable sources return
typed errors without fake or silently truncated data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast, get_args

import pytest
from alphabrief_core import (
    READ_DOMAINS,
    READ_SCHEMA_VERSION,
    FreshnessVerdict,
    PageCursor,
    Provenance,
    ReadDomain,
    ReadState,
    VersionedReadEnvelope,
    build_read_envelope,
    invalid_identifier_error,
    malformed_cursor_error,
    unavailable_source_error,
    unknown_filter_error,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)


def _envelope(
    *,
    domain: ReadDomain = "instruments",
    items: tuple[dict[str, Any], ...] = (
        {"id": "EUR_USD", "name": "EUR/USD"},
        {"id": "XAU_USD", "name": "Gold"},
    ),
    state: ReadState | None = None,
) -> VersionedReadEnvelope:
    return build_read_envelope(
        domain=domain,
        resource="catalog",
        items=items,
        provenance=Provenance(
            source="oanda-practice",
            data_version="catalog-v1",
            retrieved_at=NOW,
        ),
        freshness=FreshnessVerdict(
            status="fresh", age_seconds=10, max_age_seconds=300
        ),
        pagination=PageCursor(
            cursor="page-1", next_cursor="page-2", has_more=True, limit=50, count=2
        ),
        state=state,
        generated_at=NOW,
    )


class TestEveryReadSurface:
    @pytest.mark.parametrize("domain", sorted(READ_DOMAINS))
    def test_each_domain_has_one_versioned_schema(self, domain: str) -> None:
        envelope = _envelope(domain=cast(ReadDomain, domain))
        assert envelope.schema_version == READ_SCHEMA_VERSION
        assert envelope.domain == domain
        assert isinstance(envelope, VersionedReadEnvelope)

    def test_all_required_domains_are_covered(self) -> None:
        assert READ_DOMAINS == {
            "instruments",
            "prices",
            "candles",
            "news",
            "sentiment",
            "committee",
            "risk",
            "orders",
            "trades",
            "positions",
            "cycles",
            "scheduler",
            "alerts",
            "observation",
        }

    def test_domain_literal_matches_the_registry(self) -> None:
        assert set(get_args(ReadDomain)) == READ_DOMAINS


class TestEnvelopeProperties:
    def test_timestamps_are_utc(self) -> None:
        envelope = _envelope()
        assert envelope.generated_at.utcoffset() == timedelta(0)
        assert envelope.provenance.retrieved_at.utcoffset() == timedelta(0)

    def test_non_utc_or_naive_timestamps_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            build_read_envelope(
                domain="instruments",
                resource="catalog",
                items=(),
                provenance=Provenance(
                    source="s",
                    data_version="v",
                    retrieved_at=datetime(2026, 8, 14, 0, 0),
                ),
                freshness=FreshnessVerdict(status="unknown"),
                pagination=PageCursor(limit=50, count=0),
                generated_at=datetime(2026, 8, 14, 0, 0),
            )
        with pytest.raises(ValidationError, match="UTC"):
            VersionedReadEnvelope.model_validate(
                {
                    **_envelope().model_dump(),
                    "generated_at": datetime(
                        2026, 8, 14, 0, 0,
                        tzinfo=timezone(timedelta(hours=8)),
                    ),
                }
            )

    def test_items_carry_stable_ids_and_deterministic_ordering(self) -> None:
        envelope = _envelope(
            items=(
                {"id": "XAU_USD", "name": "Gold"},
                {"id": "EUR_USD", "name": "EUR/USD"},
            )
        )
        assert [item["id"] for item in envelope.items] == ["EUR_USD", "XAU_USD"]

    def test_items_without_stable_id_are_rejected(self) -> None:
        with pytest.raises(Exception, match="stable 'id'"):
            _envelope(items=({"name": "no-id"},))

    def test_empty_and_partial_states_are_explicit(self) -> None:
        empty = _envelope(items=(), state="empty")
        assert empty.state == "empty"
        assert empty.items == ()
        partial = _envelope(state="partial")
        assert partial.state == "partial"
        with pytest.raises(Exception, match="state"):
            _envelope(items=(), state="complete")

    def test_provenance_and_freshness_are_present(self) -> None:
        envelope = _envelope()
        assert envelope.provenance.source == "oanda-practice"
        assert envelope.provenance.data_version == "catalog-v1"
        assert envelope.freshness.status == "fresh"
        assert envelope.freshness.age_seconds == 10

    def test_freshness_verdict_must_be_consistent(self) -> None:
        with pytest.raises(Exception, match="age"):
            FreshnessVerdict(status="fresh")
        with pytest.raises(Exception, match="age"):
            FreshnessVerdict(status="unknown", age_seconds=10)

    def test_pagination_contract_is_consistent(self) -> None:
        with pytest.raises(Exception, match="next_cursor"):
            PageCursor(limit=50, count=1, has_more=True)
        with pytest.raises(Exception, match="next_cursor"):
            PageCursor(limit=50, count=1, next_cursor="x", has_more=False)


class TestTypedReadErrors:
    def test_unknown_filter_error_is_typed_and_explicit(self) -> None:
        error = unknown_filter_error("candles", "period=banana")
        assert error.error_code == "unknown_filter"
        assert "banana" in error.message
        assert error.resource == "candles"
        assert error.schema_version == READ_SCHEMA_VERSION

    def test_malformed_cursor_error_is_typed_and_explicit(self) -> None:
        error = malformed_cursor_error("candles", "not-a-cursor!!")
        assert error.error_code == "malformed_cursor"
        assert "not-a-cursor" in error.message

    def test_invalid_identifier_error_is_typed_and_explicit(self) -> None:
        error = invalid_identifier_error("positions", "SPY@")
        assert error.error_code == "invalid_identifier"
        assert "SPY@" in error.message

    def test_unavailable_source_error_is_typed_and_explicit(self) -> None:
        error = unavailable_source_error("news", "bloomberg")
        assert error.error_code == "unavailable_source"
        assert "bloomberg" in error.message

    def test_typed_errors_never_carry_items(self) -> None:
        for error in (
            unknown_filter_error("candles", "x"),
            malformed_cursor_error("candles", "x"),
            invalid_identifier_error("positions", "x"),
            unavailable_source_error("news", "x"),
        ):
            payload = error.model_dump(mode="json")
            assert "items" not in payload
            assert "pagination" not in payload
