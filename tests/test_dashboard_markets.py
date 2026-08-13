"""M14-W03: Markets workspace.

Covers AC-M14-W03-01: Markets browses, searches, filters, and groups
the complete account-discovered catalog while displaying tradeability,
category, price, spread, freshness, quality, and unsupported reasons.
"""

from __future__ import annotations

from alphabrief_api.dashboard.workspaces import (
    build_markets_view,
    filter_markets,
    group_markets,
    search_markets,
)


def _catalog() -> list[dict[str, object]]:
    return [
        {
            "name": "EUR_USD",
            "display_name": "EUR/USD",
            "category": "CURRENCY",
            "active": True,
            "margin_rate": "0.05",
        },
        {
            "name": "XAU_USD",
            "display_name": "Gold",
            "category": "METAL",
            "active": True,
            "margin_rate": "0.10",
        },
        {
            "name": "US100",
            "display_name": "US 100 Index",
            "category": "INDEX_CFD",
            "active": False,
            "margin_rate": "0.20",
        },
        {
            "name": "BTC_USD",
            "display_name": "Bitcoin",
            "category": "CRYPTO_CFD",
            "active": True,
            "margin_rate": "0.30",
        },
    ]


class TestMarketsView:
    def test_builds_complete_catalog_with_truth_fields(self) -> None:
        view = build_markets_view(
            _catalog(),
            prices={"EUR_USD": "1.10000", "XAU_USD": "2400.000"},
            spreads={"EUR_USD": "1.2"},
            freshness={"EUR_USD": "fresh"},
            quality={"EUR_USD": "ok"},
            unsupported={"US100": "catalog inactive"},
        )
        assert view.total == 4
        by_symbol = {row.symbol: row for row in view.instruments}
        assert by_symbol["EUR_USD"].tradeable is True
        assert by_symbol["EUR_USD"].price == "1.10000"
        assert by_symbol["EUR_USD"].spread_bps == "1.2"
        assert by_symbol["EUR_USD"].freshness == "fresh"
        assert by_symbol["EUR_USD"].quality == "ok"
        assert by_symbol["US100"].tradeable is False
        assert by_symbol["US100"].unsupported_reason == "catalog inactive"
        # Unknown symbols carry no invented price.
        assert by_symbol["BTC_USD"].price is None

    def test_unsupported_reasons_are_explicit(self) -> None:
        view = build_markets_view(_catalog(), unsupported={"US100": "inactive"})
        rows = {row.symbol: row for row in view.instruments}
        assert rows["US100"].tradeable is False
        assert rows["US100"].unsupported_reason == "inactive"
        assert rows["EUR_USD"].unsupported_reason is None

    def test_groups_by_category(self) -> None:
        view = build_markets_view(_catalog())
        assert view.groups == {
            "CRYPTO_CFD": 1,
            "CURRENCY": 1,
            "INDEX_CFD": 1,
            "METAL": 1,
        }
        grouped = group_markets(view)
        assert set(grouped) == {"CURRENCY", "METAL", "INDEX_CFD", "CRYPTO_CFD"}
        assert [row.symbol for row in grouped["CURRENCY"]] == ["EUR_USD"]

    def test_search_is_case_insensitive(self) -> None:
        view = build_markets_view(_catalog())
        assert [row.symbol for row in search_markets(view, "eur")] == ["EUR_USD"]
        assert [row.symbol for row in search_markets(view, "GOLD")] == ["XAU_USD"]
        assert search_markets(view, "  ") == view.instruments

    def test_filter_by_category_and_tradeability(self) -> None:
        view = build_markets_view(
            _catalog(), unsupported={"US100": "inactive"}
        )
        currencies = filter_markets(view, category="CURRENCY")
        assert [row.symbol for row in currencies] == ["EUR_USD"]
        tradeable = filter_markets(view, tradeable=True)
        assert {row.symbol for row in tradeable} == {
            "EUR_USD",
            "XAU_USD",
            "BTC_USD",
        }
        nontradeable = filter_markets(view, tradeable=False)
        assert [row.symbol for row in nontradeable] == ["US100"]

    def test_deterministic_ordering(self) -> None:
        first = build_markets_view(_catalog())
        second = build_markets_view(_catalog())
        assert first.model_dump() == second.model_dump()
        assert [row.symbol for row in first.instruments] == [
            "BTC_USD",
            "EUR_USD",
            "US100",
            "XAU_USD",
        ]
