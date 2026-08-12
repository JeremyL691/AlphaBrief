"""Versioned deterministic OANDA instrument taxonomy (M04-W04).

Classifies every instrument into Currency, Metal, or an OANDA CFD
subclass while preserving the raw broker type and an explicit unknown
category. The raw instrument snapshot is never mutated: the taxonomy is
a derived, versioned projection over the immutable metadata.

Classification rules are display-name based (the broker's own
presentation), never symbol-based; an unrecognized type or display
pattern stays visible as OTHER_CFD with its raw value, so unknown
instruments never disappear from catalog counts or search.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.oanda.instruments import (
    InstrumentCatalogSnapshot,
    InstrumentMetadata,
)

#: Bump when any classification rule changes (AC-M04-W04-03).
TAXONOMY_VERSION = "oanda-taxonomy-1"

InstrumentCategory = Literal[
    "CURRENCY",
    "METAL",
    "INDEX_CFD",
    "COMMODITY_CFD",
    "BOND_CFD",
    "EQUITY_CFD",
    "CRYPTO_CFD",
    "OTHER_CFD",
]


class ClassifiedInstrument(BaseModel):
    """One instrument with its derived taxonomy output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    raw_type: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    category: InstrumentCategory
    taxonomy_version: str = Field(min_length=1)
    basis: str = Field(min_length=1)


#: Display-name markers for CFD subclasses (checked in order).
_CFD_RULES: tuple[tuple[InstrumentCategory, tuple[str, ...]], ...] = (
    (
        "INDEX_CFD",
        ("index", "indice", "spx", "nasdaq", "dow", "wall st", "nikkei", "dax"),
    ),
    (
        "CRYPTO_CFD",
        (
            "bitcoin", "ethereum", "xbt", "btc", "eth", "ada", "xrp",
            "ltc", "dogecoin", "solana",
        ),
    ),
    ("COMMODITY_CFD", ("oil", "gas", "gasoline", "wti", "brent", "natural gas")),
    ("BOND_CFD", ("bond", "treasury", "t-note", "bund", "gilt", "jgb")),
    ("EQUITY_CFD", ("share", "stock", "equity", "inc", "corp", "ltd", "plc", "co.")),
)

#: Raw broker types mapped directly to categories.
_RAW_TYPE_MAP: dict[str, InstrumentCategory] = {
    "CURRENCY": "CURRENCY",
    "METAL": "METAL",
}


def classify_instrument(metadata: InstrumentMetadata) -> ClassifiedInstrument:
    """Classify one instrument deterministically.

    The raw broker type is always preserved; an unrecognized type or
    display pattern yields OTHER_CFD with its raw value, so nothing is
    dropped from the catalog.
    """
    raw_type = metadata.raw_type.upper().strip()
    display = metadata.display_name.lower()

    if raw_type in _RAW_TYPE_MAP:
        return ClassifiedInstrument(
            name=metadata.name,
            raw_type=metadata.raw_type,
            display_name=metadata.display_name,
            category=_RAW_TYPE_MAP[raw_type],
            taxonomy_version=TAXONOMY_VERSION,
            basis=f"raw_type={metadata.raw_type}",
        )

    if raw_type == "CFD":
        for category, markers in _CFD_RULES:
            for marker in markers:
                if marker in display:
                    return ClassifiedInstrument(
                        name=metadata.name,
                        raw_type=metadata.raw_type,
                        display_name=metadata.display_name,
                        category=category,
                        taxonomy_version=TAXONOMY_VERSION,
                        basis=f"display={marker}",
                    )
        return ClassifiedInstrument(
            name=metadata.name,
            raw_type=metadata.raw_type,
            display_name=metadata.display_name,
            category="OTHER_CFD",
            taxonomy_version=TAXONOMY_VERSION,
            basis="unrecognized CFD display pattern",
        )

    return ClassifiedInstrument(
        name=metadata.name,
        raw_type=metadata.raw_type,
        display_name=metadata.display_name,
        category="OTHER_CFD",
        taxonomy_version=TAXONOMY_VERSION,
        basis=f"unrecognized raw type {metadata.raw_type!r}",
    )


def classify_snapshot(
    snapshot: InstrumentCatalogSnapshot,
) -> tuple[ClassifiedInstrument, ...]:
    """Classify every instrument of one immutable snapshot."""
    return tuple(classify_instrument(instrument) for instrument in snapshot.instruments)


__all__ = [
    "ClassifiedInstrument",
    "InstrumentCategory",
    "TAXONOMY_VERSION",
    "classify_instrument",
    "classify_snapshot",
]
