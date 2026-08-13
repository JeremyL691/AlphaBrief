"""M13-W01: unified CLI read contracts and API/CLI parity.

Covers AC-M13-W01-02/03: API JSON and CLI JSON for the same fixture
normalize to the same domain payload and ordering; typed errors are
shared verbatim across both surfaces.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from alphabrief_core import (
    FreshnessVerdict,
    PageCursor,
    Provenance,
    VersionedReadEnvelope,
    build_read_envelope,
    invalid_identifier_error,
    malformed_cursor_error,
    normalize_read_payload,
    unavailable_source_error,
    unknown_filter_error,
)

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)


def _fixture_envelope() -> VersionedReadEnvelope:
    """One fixture shared by the API and CLI parity checks."""
    return build_read_envelope(
        domain="candles",
        resource="EUR_USD",
        items=(
            {
                "id": "candle-2",
                "timestamp": "2026-08-13T22:00:00+00:00",
                "close": "1.10000",
            },
            {
                "id": "candle-1",
                "timestamp": "2026-08-13T21:00:00+00:00",
                "close": "1.09900",
            },
        ),
        provenance=Provenance(
            source="oanda-practice",
            data_version="candles-v3",
            retrieved_at=NOW,
        ),
        freshness=FreshnessVerdict(
            status="fresh", age_seconds=5, max_age_seconds=300
        ),
        pagination=PageCursor(
            cursor="c1", next_cursor="c2", has_more=True, limit=100, count=2
        ),
        generated_at=NOW,
    )


def _api_style_json(envelope: VersionedReadEnvelope) -> str:
    """What a FastAPI route returning the envelope would emit."""
    return json.dumps(envelope.model_dump(mode="json"))


def _cli_style_json(envelope: VersionedReadEnvelope) -> str:
    """What the CLI dump helper emits (sorted keys, str fallback)."""
    return json.dumps(
        envelope.model_dump(mode="json"),
        sort_keys=True,
        default=str,
    )


class TestApiCliParity:
    def test_api_and_cli_json_normalize_to_the_same_domain_payload(
        self,
    ) -> None:
        envelope = _fixture_envelope()
        api_payload = json.loads(_api_style_json(envelope))
        cli_payload = json.loads(_cli_style_json(envelope))
        canonical = normalize_read_payload(envelope)
        assert api_payload == canonical
        assert cli_payload == canonical

    def test_api_and_cli_share_one_item_ordering(self) -> None:
        envelope = _fixture_envelope()
        api_items = json.loads(_api_style_json(envelope))["items"]
        cli_items = json.loads(_cli_style_json(envelope))["items"]
        assert [item["id"] for item in api_items] == ["candle-1", "candle-2"]
        assert api_items == cli_items

    def test_normalized_payload_is_byte_stable(self) -> None:
        first = normalize_read_payload(_fixture_envelope())
        second = normalize_read_payload(_fixture_envelope())
        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(
            second, sort_keys=True
        )

    def test_envelope_fields_survive_both_serializations(self) -> None:
        envelope = _fixture_envelope()
        for serialized in (_api_style_json(envelope), _cli_style_json(envelope)):
            payload = json.loads(serialized)
            assert payload["schema_version"] == "read-v1"
            assert payload["domain"] == "candles"
            assert datetime.fromisoformat(payload["generated_at"]) == NOW
            assert payload["provenance"]["data_version"] == "candles-v3"
            assert payload["freshness"]["status"] == "fresh"
            assert payload["pagination"]["has_more"] is True
            assert payload["state"] == "complete"

    def test_empty_and_partial_states_are_identical_across_surfaces(
        self,
    ) -> None:
        empty = build_read_envelope(
            domain="news",
            resource="feed",
            items=(),
            provenance=Provenance(
                source="rss", data_version="v1", retrieved_at=NOW
            ),
            freshness=FreshnessVerdict(status="unknown"),
            pagination=PageCursor(limit=50, count=0),
            generated_at=NOW,
        )
        assert normalize_read_payload(empty) == json.loads(
            _cli_style_json(empty)
        )
        assert normalize_read_payload(empty)["state"] == "empty"
        assert normalize_read_payload(empty)["items"] == []


class TestSharedTypedErrors:
    @pytest.mark.parametrize(
        "builder,expected_code",
        [
            (unknown_filter_error, "unknown_filter"),
            (malformed_cursor_error, "malformed_cursor"),
            (invalid_identifier_error, "invalid_identifier"),
            (unavailable_source_error, "unavailable_source"),
        ],
    )
    def test_typed_errors_are_identical_on_api_and_cli(
        self, builder: Any, expected_code: str
    ) -> None:
        error = builder("candles", "bad-value")
        api_json = json.dumps(error.model_dump(mode="json"))
        cli_json = json.dumps(
            error.model_dump(mode="json"), sort_keys=True, default=str
        )
        assert json.loads(api_json)["error_code"] == expected_code
        assert json.loads(cli_json) == json.loads(api_json)

    def test_error_payloads_never_contain_items_or_data(self) -> None:
        error = unknown_filter_error("candles", "x")
        payload = json.loads(
            json.dumps(error.model_dump(mode="json"), sort_keys=True)
        )
        assert set(payload) == {"schema_version", "error_code", "message", "resource"}
        assert "items" not in payload
