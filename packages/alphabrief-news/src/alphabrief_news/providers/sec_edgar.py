"""SEC EDGAR news provider for AlphaBrief.

This provider reads SEC EDGAR's company filing RSS feed for a single
ticker (CIK) and converts the most recent filings into
:class:`NewsHeadline` objects tagged with ``category="earnings"``.

SEC has a fair-access policy that requires a descriptive User-Agent
header. The provider accepts a configurable ``user_agent`` and
defaults to a generic placeholder. It is the caller's responsibility
to set a real contact (e.g. ``"AlphaBrief admin@example.com"``) before
running at scale.

The provider does **not** call any third-party SDK and uses only the
standard library.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import cast

from alphabrief_data.providers import (
    RetryPolicy,
    call_with_retry,
    is_retryable_exception,
)

from alphabrief_news.providers.base import (
    HttpGet,
    NewsProviderError,
    NewsProviderErrorCode,
)
from alphabrief_news.types import NewsFetchQuery, NewsHeadline

_BASE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_DEFAULT_TIMEOUT = 30.0
_EARNINGS_FORMS = frozenset(
    {"10-K", "10-Q", "8-K", "20-F", "40-F", "6-K", "S-1", "S-1/A", "F-1"}
)
_TYPE_QUERY = "10-K,10-Q,8-K,20-F,40-F,6-K,S-1"
_FORM_TITLE_RE = re.compile(r"^([A-Z0-9/\-]+)\b")

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _validate_symbol(symbol: str) -> str:
    candidate = symbol.strip().upper()
    if not _TICKER_RE.match(candidate):
        raise NewsProviderError(
            NewsProviderErrorCode.INVALID_SYMBOL,
            f"invalid ticker symbol: {symbol!r}",
        )
    return candidate


def _default_http_get(request: urllib.request.Request, timeout_seconds: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return cast(bytes, response.read())


def _parse_rfc3339(value: str) -> datetime:
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class SecEdgarNewsProvider:
    """News provider that reads SEC EDGAR's company filing RSS feed."""

    def __init__(
        self,
        user_agent: str = "AlphaBrief/0.0 (research; contact@example.com)",
        *,
        http_get: HttpGet | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._http_get = http_get or _default_http_get

    def fetch_headlines(self, query: NewsFetchQuery) -> list[NewsHeadline]:
        """Fetch recent filings for the requested ticker symbol."""
        if not query.symbols:
            raise NewsProviderError(
                NewsProviderErrorCode.INVALID_SYMBOL,
                "at least one symbol is required",
            )
        ticker = _validate_symbol(query.symbols[0])

        url = (
            f"{_BASE_URL}?action=getcompany&CIK={urllib.parse.quote(ticker)}"
            f"&type={urllib.parse.quote(_TYPE_QUERY)}"
            f"&dateb=&owner=include&count=40&output=atom"
        )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/atom+xml, application/xml, text/xml",
            },
        )

        try:
            body = self._http_with_retry(request)
        except NewsProviderError:
            raise

        if not body:
            raise NewsProviderError(
                NewsProviderErrorCode.EMPTY_RESPONSE,
                "SEC EDGAR returned an empty response",
            )

        entries = self._parse_atom(body)
        if not entries:
            return []

        results: list[NewsHeadline] = []
        for entry in entries:
            published_at = cast(datetime, entry["updated"])
            if not (query.start <= published_at < query.end):
                continue
            form_match = _FORM_TITLE_RE.match(cast(str, entry["title"]))
            if form_match and form_match.group(1) not in _EARNINGS_FORMS:
                continue
            results.append(
                NewsHeadline(
                    headline_id=f"sec:{ticker}:{cast(str, entry['id'])}",
                    published_at=published_at,
                    symbols=[ticker],
                    category="earnings",
                    source="sec-edgar",
                    title=cast(str, entry["title"]),
                    summary=cast(str, entry["summary"]),
                    url=cast("str | None", entry["link"]),
                    sentiment=None,
                    data_version="sec-v1",
                )
            )
        return results[: query.limit]

    def _http_with_retry(self, request: urllib.request.Request) -> bytes:
        policy = RetryPolicy()

        def _do() -> bytes:
            return self._http_get(request, _DEFAULT_TIMEOUT)

        try:
            return cast(
                bytes,
                call_with_retry(
                    _do,
                    retry_policy=policy,
                    is_retryable=is_retryable_exception,
                ),
            )
        except NewsProviderError:
            raise
        except Exception as exc:
            from urllib.error import HTTPError, URLError

            if isinstance(exc, HTTPError):
                if exc.code in (418, 429) or exc.code >= 500:
                    raise NewsProviderError(
                        NewsProviderErrorCode.RATE_LIMITED,
                        f"SEC rate limited or server error: {exc.code}",
                    ) from exc
                raise NewsProviderError(
                    NewsProviderErrorCode.HTTP_ERROR,
                    f"SEC HTTP error: {exc.code}",
                ) from exc
            if isinstance(exc, URLError):
                raise NewsProviderError(
                    NewsProviderErrorCode.NETWORK_ERROR,
                    f"SEC network error: {exc}",
                ) from exc
            raise NewsProviderError(
                NewsProviderErrorCode.NETWORK_ERROR,
                f"SEC unexpected error: {exc}",
            ) from exc

    def _parse_atom(self, xml_bytes: bytes) -> list[dict[str, str | datetime | None]]:
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise NewsProviderError(
                NewsProviderErrorCode.PARSE_ERROR,
                f"invalid SEC EDGAR XML: {exc}",
            ) from exc

        ns = "http://www.w3.org/2005/Atom"
        entries = root.findall(f"{{{ns}}}entry")
        parsed: list[dict[str, str | datetime | None]] = []
        for entry in entries:
            title_el = entry.find(f"{{{ns}}}title")
            title = (title_el.text or "").strip() if title_el is not None else ""
            if not title:
                continue
            link_el = entry.find(f"{{{ns}}}link")
            link: str | None = link_el.get("href") if link_el is not None else None
            updated_el = entry.find(f"{{{ns}}}updated")
            updated_text = (
                (updated_el.text or "").strip() if updated_el is not None else ""
            )
            if not updated_text:
                continue
            try:
                updated_dt: datetime = _parse_rfc3339(updated_text)
            except ValueError:
                continue
            summary_el = entry.find(f"{{{ns}}}summary")
            summary: str = (
                (summary_el.text or "").strip() if summary_el is not None else ""
            )
            id_el = entry.find(f"{{{ns}}}id")
            entry_id: str = (
                (id_el.text or "").strip() if id_el is not None else title
            )
            parsed.append(
                {
                    "title": title,
                    "link": link,
                    "updated": updated_dt,
                    "summary": summary,
                    "id": entry_id,
                }
            )
        return parsed


def _encode_symbols(symbols: list[str]) -> str:
    """Return a JSON-encoded string for storage in a VARCHAR column."""
    return json.dumps(symbols, separators=(",", ":"))


__all__ = [
    "SecEdgarNewsProvider",
    "_EARNINGS_FORMS",
    "_validate_symbol",
]
