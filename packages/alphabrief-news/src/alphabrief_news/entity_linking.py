"""Deterministic news entity linking (M09-W02).

Associates content with markets, asset classes, currencies, countries,
companies, and OANDA instruments through deterministic dictionary rules
(REQ-NEWS-003). Every entity link records entity type, normalized
identifier, matching rule version, confidence, and the originating
evidence ID (AC-M09-W02-03).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EntityType = Literal[
    "market",
    "asset_class",
    "currency",
    "country",
    "company",
    "instrument",
]

#: The deterministic matching-rule version for every link.
ENTITY_RULE_VERSION = "2026-08-13.1"

#: Confidence for an exact instrument-symbol match.
CONFIDENCE_EXACT_SYMBOL = "1.0"

#: Confidence for an explicit dictionary-name match.
CONFIDENCE_DICTIONARY_MATCH = "0.8"


class EntityLink(BaseModel):
    """One deterministic entity link with its evidence trail."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_type: EntityType
    normalized_identifier: str = Field(min_length=1)
    matching_rule_version: str = ENTITY_RULE_VERSION
    confidence: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)


class EntityDictionary(BaseModel):
    """One deterministic entity dictionary per type.

    Keys are normalized identifiers; values are the name aliases the
    rule matcher looks for in titles and summaries (case-insensitive).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    currencies: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    countries: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    companies: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    asset_classes: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    markets: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class EntityLinkInput(BaseModel):
    """One content item to link (title, summary, and its symbol tags)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = ""
    symbols: tuple[str, ...] = ()


def _matches_any(text: str, aliases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(alias.lower() in lowered for alias in aliases)


def link_entities(
    item: EntityLinkInput,
    dictionary: EntityDictionary,
) -> tuple[EntityLink, ...]:
    """Link one content item deterministically.

    - every headline symbol maps to an exact instrument link
      (confidence 1.0, rule ``exact_symbol``);
    - dictionary aliases found in the title or summary produce
      currency/country/company/asset-class/market links (confidence
      0.8, rule ``dictionary_alias``).
    """
    links: list[EntityLink] = []
    text = f"{item.title} {item.summary}"

    for symbol in item.symbols:
        normalized = symbol.strip().upper()
        if normalized:
            links.append(
                EntityLink(
                    entity_type="instrument",
                    normalized_identifier=normalized,
                    confidence=CONFIDENCE_EXACT_SYMBOL,
                    evidence_id=item.evidence_id,
                )
            )

    for identifier, aliases in dictionary.currencies.items():
        if _matches_any(text, aliases):
            links.append(
                EntityLink(
                    entity_type="currency",
                    normalized_identifier=identifier.upper(),
                    confidence=CONFIDENCE_DICTIONARY_MATCH,
                    evidence_id=item.evidence_id,
                )
            )
    for identifier, aliases in dictionary.countries.items():
        if _matches_any(text, aliases):
            links.append(
                EntityLink(
                    entity_type="country",
                    normalized_identifier=identifier.upper(),
                    confidence=CONFIDENCE_DICTIONARY_MATCH,
                    evidence_id=item.evidence_id,
                )
            )
    for identifier, aliases in dictionary.companies.items():
        if _matches_any(text, aliases):
            links.append(
                EntityLink(
                    entity_type="company",
                    normalized_identifier=identifier.upper(),
                    confidence=CONFIDENCE_DICTIONARY_MATCH,
                    evidence_id=item.evidence_id,
                )
            )
    for identifier, aliases in dictionary.asset_classes.items():
        if _matches_any(text, aliases):
            links.append(
                EntityLink(
                    entity_type="asset_class",
                    normalized_identifier=identifier.upper(),
                    confidence=CONFIDENCE_DICTIONARY_MATCH,
                    evidence_id=item.evidence_id,
                )
            )
    for identifier, aliases in dictionary.markets.items():
        if _matches_any(text, aliases):
            links.append(
                EntityLink(
                    entity_type="market",
                    normalized_identifier=identifier.upper(),
                    confidence=CONFIDENCE_DICTIONARY_MATCH,
                    evidence_id=item.evidence_id,
                )
            )
    return tuple(links)


__all__ = [
    "CONFIDENCE_DICTIONARY_MATCH",
    "CONFIDENCE_EXACT_SYMBOL",
    "ENTITY_RULE_VERSION",
    "EntityDictionary",
    "EntityLink",
    "EntityLinkInput",
    "EntityType",
    "link_entities",
]
