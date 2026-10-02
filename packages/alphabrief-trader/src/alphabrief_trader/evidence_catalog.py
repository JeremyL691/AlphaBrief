"""Content-addressed, scrubbed facts frozen at the committee boundary."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from alphabrief_news import NewsHeadline
from alphabrief_news.untrusted import sanitize_external_text

if TYPE_CHECKING:
    from alphabrief_trader.schemas import MarketSnapshot


def scrub_secrets(text: str) -> str:
    """One redaction policy for evidence bodies and rendered prompts."""
    patterns = (
        (r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", "[REDACTED-TOKEN]"),
        (
            r"(?:api[_-]?key|secret|token)\s*[:=]\s*[A-Za-z0-9._~+/=-]{12,}",
            "[REDACTED-SECRET]",
        ),
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED-SECRET]"),
        (r"\b\d{3}-\d{3}-\d{7,}-\d{3}\b", "[REDACTED-ACCOUNT-ID]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def prepare_headline(headline: NewsHeadline) -> NewsHeadline | None:
    """Exclude injected entries, including directives hidden in metadata."""
    raw = headline.model_dump_json()
    check = sanitize_external_text(raw, source="committee-headline")
    if check.neutralized_instructions:
        return None
    updates: dict[str, Any] = {}
    for field in ("headline_id", "source", "title", "summary", "url", "data_version"):
        value = getattr(headline, field)
        if value:
            updates[field] = scrub_secrets(
                sanitize_external_text(
                    value, source="committee-headline"
                ).sanitized_text
            )
    return headline.model_copy(update=updates)


def headline_hash(headline: NewsHeadline) -> str:
    """Retain a hash, never the rejected text or secrets, for exclusion audit."""
    return sha256(headline.model_dump_json().encode("utf-8")).hexdigest()


def build_evidence_catalog(snapshot: MarketSnapshot) -> dict[str, str]:
    """Hash exactly the JSON bodies shown to the model; never invent inputs."""
    catalog: dict[str, str] = {}

    def add(kind: str, values: dict[str, Any]) -> None:
        body = scrub_secrets(
            json.dumps(
                {"symbol": snapshot.symbol, **values},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        catalog[f"{kind}:{sha256(body.encode('utf-8')).hexdigest()}"] = body

    add(
        "market",
        {
            "reference_price": str(snapshot.reference_price),
            "captured_at": snapshot.captured_at.isoformat(),
            "data_version": snapshot.data_version,
            "recent_volume": (
                None if snapshot.recent_volume is None else str(snapshot.recent_volume)
            ),
            "recent_return_pct": (
                None
                if snapshot.recent_return_pct is None
                else str(snapshot.recent_return_pct)
            ),
        },
    )
    if snapshot.market_evidence is not None:
        add(
            "candle",
            {
                "windows": snapshot.market_evidence.model_dump(mode="json"),
                "atr_14_h1": None if snapshot.atr is None else str(snapshot.atr),
                "return_20d_pct": (
                    None
                    if snapshot.momentum_20d_pct is None
                    else str(snapshot.momentum_20d_pct)
                ),
                "volatility_20d_pct": (
                    None
                    if snapshot.volatility_20d_pct is None
                    else str(snapshot.volatility_20d_pct)
                ),
            },
        )
    if snapshot.broker_evidence is not None:
        add("broker", snapshot.broker_evidence.model_dump(mode="json"))
    if snapshot.signal_evidence is not None:
        for symbol, facts in sorted(snapshot.signal_evidence.signals.items()):
            add("signal", {"instrument": symbol, **facts.model_dump(mode="json")})
    for headline in snapshot.news_items:
        safe = prepare_headline(headline)
        if safe is not None:
            add("news", safe.model_dump(mode="json"))
    if snapshot.macro_context and snapshot.macro_context.strip():
        macro = sanitize_external_text(snapshot.macro_context, source="committee-macro")
        if not macro.neutralized_instructions:
            add("macro", {"context": macro.sanitized_text})
    return dict(sorted(catalog.items()))
