"""Currency-relevance tagging for news (PROJECT_GUIDE S4-5).

Headlines used to be tagged with every symbol in the universe, which made
the news context identical for all instruments and useless as evidence.
This module replaces that with deterministic currency relevance:

* currency codes and central-bank names are matched in the title and
  summary (short code aliases match on word boundaries, so ``cad`` does
  not match ``decade`` and ``aud`` does not match ``fraud``);
* the matched currencies are mapped to the traded instruments that
  contain them;
* an item with no currency signal is tagged ``GENERAL`` — it is recorded
  but is not claimed to be relevant to any instrument;
* a source that is currency-specific by construction (an official Fed,
  ECB or BoE feed) supplies a default currency, used only when the text
  itself carries no signal.

No network, no model, no mutable state: the same text always produces the
same tags.
"""

from __future__ import annotations

import re

#: The traded universe; an item is only ever tagged with these.
TRADED_INSTRUMENTS = ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD")

#: The tag used when no currency signal is present.
GENERAL_TAG = "GENERAL"

#: Deterministic tagging rule version (recorded on every tagged item).
CURRENCY_TAG_RULE_VERSION = "currency-tags-1"

#: Aliases per currency. Multi-word or distinctive phrases are matched as
#: substrings; short codes are matched on word boundaries.
CURRENCY_ALIASES: dict[str, tuple[str, ...]] = {
    "USD": (
        "usd",
        "u.s. dollar",
        "us dollar",
        "greenback",
        "federal reserve",
        "fed ",
        "fomc",
        "nonfarm",
        "nfp",
        "treasury",
        "wall street",
    ),
    "EUR": (
        "eur",
        "euro",
        "eurozone",
        "euro area",
        "ecb",
        "lagarde",
        "ecb press",
    ),
    "GBP": (
        "gbp",
        "pound",
        "sterling",
        "british",
        "britain",
        "u.k.",
        "bank of england",
        "boe ",
        "gilt",
    ),
    "JPY": (
        "jpy",
        "yen",
        "bank of japan",
        "boj ",
        "kuroda",
        "ueda",
        "jgb",
    ),
    "AUD": (
        "aud",
        "aussie",
        "australian dollar",
        "reserve bank of australia",
        "rba ",
    ),
    "CAD": (
        "cad",
        "loonie",
        "canadian dollar",
        "bank of canada",
        "boc ",
        "oil price",
        "crude",
    ),
}

#: Short currency codes that must match on a word boundary.
_CODE_ALIASES = frozenset({"usd", "eur", "gbp", "jpy", "aud", "cad"})

#: Generic USD words that only count when no other currency matched:
#: "dollar" appears in "Australian dollar" and "Canadian dollar" too.
_GENERIC_USD_ALIASES = ("dollar",)

_CODE_PATTERN = re.compile(r"\b[a-z]{3}\b")


def _alias_matches(text: str, alias: str) -> bool:
    """True when one alias matches the text under the currency rules."""
    if alias in _CODE_ALIASES:
        return alias in _CODE_PATTERN.findall(text)
    if alias in _GENERIC_USD_ALIASES:
        return alias in text
    return alias in text


def currencies_in_text(text: str) -> tuple[str, ...]:
    """The currencies the text is about, most specific match first."""
    lowered = text.lower()
    matched = [
        currency
        for currency, aliases in CURRENCY_ALIASES.items()
        if any(_alias_matches(lowered, alias) for alias in aliases)
    ]
    if matched:
        return tuple(matched)
    if any(alias in lowered for alias in _GENERIC_USD_ALIASES):
        return ("USD",)
    return ()


def instruments_for_currencies(currencies: tuple[str, ...]) -> list[str]:
    """The traded instruments that contain any of the currencies."""
    if not currencies:
        return [GENERAL_TAG]
    wanted = {currency.upper() for currency in currencies}
    matched = [
        instrument
        for instrument in TRADED_INSTRUMENTS
        if wanted & set(instrument.split("_"))
    ]
    return matched or [GENERAL_TAG]


def tag_headline_symbols(
    title: str,
    summary: str = "",
    *,
    default_currency: str | None = None,
) -> list[str]:
    """The instrument tags for one headline (never "every symbol").

    ``default_currency`` is the currency a currency-specific source is
    about (the Fed feed is USD); it applies only when the text itself
    carries no signal.
    """
    currencies = currencies_in_text(f"{title} {summary}")
    if not currencies and default_currency:
        currencies = (default_currency,)
    return instruments_for_currencies(currencies)


__all__ = [
    "CURRENCY_ALIASES",
    "CURRENCY_TAG_RULE_VERSION",
    "GENERAL_TAG",
    "TRADED_INSTRUMENTS",
    "currencies_in_text",
    "instruments_for_currencies",
    "tag_headline_symbols",
]
