"""M09-W02: deterministic news entity linking.

- every entity link records entity type, normalized identifier,
  matching rule version, confidence, and originating evidence ID
  (AC-M09-W02-03);
- symbols link to instruments exactly; dictionary aliases link
  currencies, countries, companies, asset classes, and markets.
"""

from __future__ import annotations

from alphabrief_news.entity_linking import (
    CONFIDENCE_DICTIONARY_MATCH,
    CONFIDENCE_EXACT_SYMBOL,
    ENTITY_RULE_VERSION,
    EntityDictionary,
    EntityLinkInput,
    link_entities,
)


def _dictionary() -> EntityDictionary:
    return EntityDictionary(
        currencies={
            "EUR": ("euro", "eur"),
            "GBP": ("pound", "sterling"),
        },
        countries={
            "DE": ("germany", "berlin"),
            "US": ("united states", "washington"),
        },
        companies={
            "ECB": ("ecb", "european central bank"),
        },
        asset_classes={
            "FX": ("currency", "fx"),
        },
        markets={
            "EUROPE": ("europe", "eurozone"),
        },
    )


def _input(**overrides: object) -> EntityLinkInput:
    payload: dict[str, object] = {
        "evidence_id": "h-1",
        "title": "ECB holds rates steady in FX markets",
        "summary": "The European Central Bank left rates unchanged in Berlin.",
        "symbols": ("EUR_USD",),
    }
    payload.update(overrides)
    return EntityLinkInput.model_validate(payload)


def test_symbols_link_to_instruments_exactly() -> None:
    links = link_entities(_input(), _dictionary())
    instrument_links = [
        link for link in links if link.entity_type == "instrument"
    ]
    assert len(instrument_links) == 1
    link = instrument_links[0]
    assert link.normalized_identifier == "EUR_USD"
    assert link.confidence == CONFIDENCE_EXACT_SYMBOL
    assert link.matching_rule_version == ENTITY_RULE_VERSION
    assert link.evidence_id == "h-1"


def test_dictionary_aliases_link_all_types() -> None:
    links = link_entities(_input(), _dictionary())
    by_type = {link.entity_type: link for link in links}
    assert by_type["currency"].normalized_identifier == "EUR"
    assert by_type["currency"].confidence == CONFIDENCE_DICTIONARY_MATCH
    assert by_type["country"].normalized_identifier == "DE"
    assert by_type["company"].normalized_identifier == "ECB"
    assert by_type["asset_class"].normalized_identifier == "FX"
    assert by_type["market"].normalized_identifier == "EUROPE"
    for link in links:
        assert link.matching_rule_version == ENTITY_RULE_VERSION
        assert link.evidence_id == "h-1"


def test_case_insensitive_alias_matching() -> None:
    links = link_entities(
        _input(
            title="STERLING weakens after LONDON session",
            summary="The pound fell.",
            symbols=(),
        ),
        _dictionary(),
    )
    by_type = {link.entity_type: link for link in links}
    assert by_type["currency"].normalized_identifier == "GBP"


def test_empty_symbols_and_no_alias_matches_produce_no_links() -> None:
    links = link_entities(
        _input(
            title="Unrelated headline",
            summary="Nothing to link here.",
            symbols=(),
        ),
        _dictionary(),
    )
    assert links == ()


def test_deterministic_for_identical_input() -> None:
    first = link_entities(_input(), _dictionary())
    second = link_entities(_input(), _dictionary())
    assert first == second
