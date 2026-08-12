import asyncio
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent, load_paper_execution_policy, load_settings
from alphabrief_execution.broker.runtime import NullBrokerAdapter
from alphabrief_risk import AccountExposureContext
from pydantic import ValidationError

POLICY_NOW = datetime(2026, 6, 22, 14, 0, tzinfo=UTC)
# A Monday 10:00 America/New_York moment — inside the policy trading
# session, so the R21.2 ``require_market_open`` check does not reject.
# Kept in sync with ``POLICY_NOW`` so signal-staleness also passes.


def _empty_account_context(
    symbol: str = "SPY",
    mark: Decimal = Decimal("100"),
) -> "AccountExposureContext":
    """An AccountExposureContext with zero exposure.

    The Phase 19 default gate enforces the $300 total-exposure cap at
    runtime, so a buy without an account_context fails closed
    (``account_context_required``). R21.2 adds leverage (needs ``equity``)
    and price-deviation (needs ``reference_mark_prices``) checks, both
    fail-closed. R21.3 adds daily-loss (needs ``day_start_equity``) and
    drawdown (needs ``equity_high_water_mark``), also fail-closed. These
    tests exercise the symbol / order-value / human-review boundaries,
    not those checks, so the helper supplies a zero-exposure context
    with equity, mark, and HWM/day-start set to the current equity so
    only the boundaries under test surface. ``symbol`` / ``mark`` let
    each caller match the mark to its order price.
    """
    return AccountExposureContext(
        current_total_exposure=Decimal("0"),
        exposure_by_symbol={},
        cash=Decimal("100000"),
        account_id="paper_local",
        captured_at=POLICY_NOW,
        equity=Decimal("100000"),
        reference_mark_prices={symbol: mark},
        equity_high_water_mark=Decimal("100000"),
        day_start_equity=Decimal("100000"),
    )


def _configured_policy_text() -> str:
    return Path("config/paper_execution_policy.yaml").read_text(encoding="utf-8")


def test_checked_in_execution_policy_is_paper_only_and_locked() -> None:
    """M01-W01: default policy is OANDA-practice paper auto-execution.

    FX / metals / index CFDs and the transitional names all sit behind the
    single OANDA practice provider; the RiskGate allowlist is the policy
    symbols. Paper mode and the live-trading lock are unchanged; automated
    execution is allowed inside paper mode only.
    """
    policy = load_paper_execution_policy("config/paper_execution_policy.yaml")

    assert policy.mode == "paper"
    assert policy.provider == "oanda_paper"
    assert policy.market == "multi_asset"
    assert policy.symbols == (
        # FX Majors
        "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD", "NZD_USD",
        # FX Crosses
        "EUR_GBP", "EUR_JPY", "GBP_JPY", "AUD_JPY", "CHF_JPY",
        # Metals
        "XAU_USD", "XAG_USD",
        # Index CFDs (US + EU + JP)
        "US30_USD", "SPX500_USD", "NAS100_USD", "DE30_EUR", "JP225_USD",
        # US Equities (Alpaca)
        "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "AMD", "SPY", "QQQ",
        # Crypto (Alpaca)
        "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD",
    )
    assert policy.order_types == ("market", "limit")
    assert policy.max_order_notional == Decimal("2000")
    assert policy.max_total_exposure == Decimal("20000")
    assert policy.require_human_review is False
    assert policy.automated_execution is True


@pytest.mark.parametrize(
    ("replacement", "error"),
    [
        ("mode: live", "Input should be 'paper'"),
        ("order_types: [market, stop]", "market' or 'limit"),
        ("max_order_notional: 100.0", "must not be floats"),
        ('session_end: "09:30"', "session_start must be earlier"),
    ],
)
def test_execution_policy_rejects_invalid_operating_boundaries(
    tmp_path: Path,
    replacement: str,
    error: str,
) -> None:
    """Round 0063: baseline-aware boundary tests.

    Replacements target fields by key prefix on the actual baseline so the
    tests stay stable when default values (provider, market, symbols,
    notional caps, session window) change across rounds.
    """
    policy_path = tmp_path / "policy.yaml"
    baseline = _configured_policy_text()

    def _replace_first(prefix: str, new_text: str) -> str:
        for line in baseline.splitlines():
            if line.startswith(prefix):
                return baseline.replace(line, new_text, 1)
        raise AssertionError(f"baseline has no line starting with {prefix!r}")

    if replacement.startswith("mode:"):
        text = _replace_first("mode:", replacement)
    elif replacement.startswith("order_types:"):
        text = _replace_first("order_types:", replacement)
    elif replacement.startswith("max_order_notional:"):
        text = _replace_first("max_order_notional:", replacement)
    else:
        # session_end: pin start to 10:00 so the validator's start > end
        # check fires. We mutate the running text each step because each
        # ``_replace_first`` call rebuilds from the original baseline.
        text = baseline
        for prefix, value in (
            ("session_start:", 'session_start: "10:00"'),
            ("session_end:", replacement),
        ):
            for line in text.splitlines():
                if line.startswith(prefix):
                    text = text.replace(line, value, 1)
                    break
            else:
                raise AssertionError(
                    f"running text has no line starting with {prefix!r}"
                )
    policy_path.write_text(text, encoding="utf-8")

    with pytest.raises((ValidationError, ValueError), match=error):
        load_paper_execution_policy(policy_path)


def test_execution_policy_rejects_unknown_fields(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(_configured_policy_text() + "live_endpoint: nope\n")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_paper_execution_policy(policy_path)


def test_execution_policy_accepts_reviewed_oanda_paper_boundary(
    tmp_path: Path,
) -> None:
    """Round 0063: default paper policy is now OANDA + multi_asset.

    This test still proves the policy can be expressed as a paper OANDA
    configuration, but it now mutates symbols on the already-OANDA baseline
    rather than translating an Alpaca baseline.
    """
    baseline = _configured_policy_text()
    text = baseline
    # Force the OANDA + fx + EUR-only shape regardless of what the baseline
    # currently says — this test documents that the reviewed boundary can be
    # expressed from any starting policy. Round 0063 changed the default to
    # multi_asset, so we explicitly collapse to fx here.
    text = re.sub(
        r"^provider:.*$", "provider: oanda_paper", text, count=1, flags=re.MULTILINE
    )
    text = re.sub(r"^market:.*$", "market: fx", text, count=1, flags=re.MULTILINE)
    # The baseline uses a block-style ``symbols:`` list (one per line);
    # replace the whole block so we can narrow to a pure-FX pair. The list
    # contains commented sub-sections (e.g. "  # FX Majors") which are also
    # matched by `  - .+\n` because they start with "  -". The non-greedy
    # `+` followed by a comment-and-list pattern needs DOTALL + matching the
    # leading "  - " (any content) plus subsequent "  - " lines, but skipping
    # comment lines.
    text = re.sub(
        r"(?ms)^symbols:\n((?:  - [^\n]+\n|  #[^\n]*\n)+)",
        "symbols:\n  - EUR_USD\n  - GBP_USD\n",
        text,
        count=1,
    )
    policy_path = tmp_path / "oanda_policy.yaml"
    policy_path.write_text(text, encoding="utf-8")

    policy = load_paper_execution_policy(policy_path)

    assert policy.provider == "oanda_paper"
    assert policy.market == "fx"
    assert policy.symbols == ("EUR_USD", "GBP_USD")


def test_settings_accepts_execution_policy_file_override() -> None:
    settings = load_settings({"ALPHABRIEF_EXECUTION_POLICY_FILE": "custom/policy.yaml"})

    assert settings.execution_policy_file == Path("custom/policy.yaml")


def test_default_api_risk_gate_enforces_policy_subset() -> None:
    from alphabrief_api.routes.risk import _get_risk_gate, _reset_risk_gate

    _reset_risk_gate()
    gate = _get_risk_gate()
    gate.clock = lambda: POLICY_NOW  # session-in, fresh signal
    # M01-W01: default universe is the OANDA-practice multi-asset boundary
    # (FX + metals + index CFDs + transitional names). Use a representative
    # instrument from each class; order value stays well under
    # max_order_notional=2000 USD.
    allowed = OrderIntent(
        intent_id="policy-eurusd",
        source="manual",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("100"),
        rationale="policy boundary test",
        created_at=POLICY_NOW,
    )
    allowed_crypto = allowed.model_copy(
        update={"symbol": "BTC-USD", "quantity": Decimal("0.01")}
    )
    allowed_equity = allowed.model_copy(
        update={"symbol": "AAPL", "quantity": Decimal("5")}
    )
    blocked_symbol = allowed.model_copy(update={"symbol": "NFLX"})
    blocked_value = allowed.model_copy(update={"quantity": Decimal("99999")})

    ctx_eur = _empty_account_context(symbol="EUR_USD", mark=Decimal("1.14"))
    ctx_btc = _empty_account_context(symbol="BTC-USD", mark=Decimal("60000"))
    ctx_aapl = _empty_account_context(symbol="AAPL", mark=Decimal("230"))
    allowed_decision = gate.evaluate(
        allowed, estimated_price=Decimal("1.14"), account_context=ctx_eur
    )
    crypto_decision = gate.evaluate(
        allowed_crypto, estimated_price=Decimal("60000"), account_context=ctx_btc
    )
    equity_decision = gate.evaluate(
        allowed_equity, estimated_price=Decimal("230"), account_context=ctx_aapl
    )
    blocked_symbol_decision = gate.evaluate(
        blocked_symbol, estimated_price=Decimal("100"), account_context=ctx_eur
    )
    blocked_value_decision = gate.evaluate(
        blocked_value, estimated_price=Decimal("1.14"), account_context=ctx_eur
    )
    assert allowed_decision.approved is True
    assert allowed_decision.requires_human_review is False
    assert crypto_decision.approved is True
    assert equity_decision.approved is True
    assert blocked_symbol_decision.approved is False
    assert blocked_value_decision.approved is False


@pytest.mark.parametrize(
    ("symbol", "quantity"),
    [
        # M01-W01: sample from the OANDA-practice multi-asset boundary.
        # Quantities keep the USD notional under max_order_notional=2000 at
        # each asset class's representative mark.
        ("EUR_USD", Decimal("1000")),
        ("GBP_JPY", Decimal("5")),
        ("AUD_JPY", Decimal("10")),
        ("XAU_USD", Decimal("0.4")),
        ("XAG_USD", Decimal("30")),
        ("AAPL", Decimal("8")),
        ("BTC-USD", Decimal("0.02")),
        ("ETH-USD", Decimal("0.5")),
    ],
)
def test_risk_gate_accepts_extended_etf_symbols(symbol: str, quantity: Decimal) -> None:
    from alphabrief_api.routes.risk import _get_risk_gate, _reset_risk_gate

    _reset_risk_gate()
    gate = _get_risk_gate()
    gate.clock = lambda: POLICY_NOW  # session-in, fresh signal
    intent = OrderIntent(
        intent_id=f"policy-{symbol.lower()}",
        source="manual",
        symbol=symbol,
        side="buy",
        order_type="market",
        quantity=quantity,
        rationale="policy boundary test",
        created_at=POLICY_NOW,
    )

    # Match mark to a representative price per asset class; the quantity
    # keeps the order notional under max_order_notional=2000 USD. We only
    # verify symbol membership in the allowlist here — order-value ceilings
    # are covered by test_default_api_risk_gate_enforces_policy_subset.
    mark = {
        "EUR_USD": Decimal("1.14"),
        "GBP_JPY": Decimal("217.0"),
        "AUD_JPY": Decimal("112.4"),
        "XAU_USD": Decimal("4100"),
        "XAG_USD": Decimal("59.7"),
        "AAPL": Decimal("230"),
        "BTC-USD": Decimal("60000"),
        "ETH-USD": Decimal("3500"),
    }[symbol]

    decision = gate.evaluate(
        intent,
        estimated_price=mark,
        account_context=_empty_account_context(symbol=symbol, mark=mark),
    )

    assert decision.approved is True


@pytest.mark.parametrize("symbol", ["NFLX", "RIVN", "LTC-USD", "PEPE-USD"])
def test_risk_gate_rejects_unapproved_symbols(symbol: str) -> None:
    from alphabrief_api.routes.risk import _get_risk_gate, _reset_risk_gate

    _reset_risk_gate()
    gate = _get_risk_gate()
    intent = OrderIntent(
        intent_id=f"policy-{symbol.lower()}",
        source="manual",
        symbol=symbol,
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        rationale="policy boundary test",
        created_at=datetime(2026, 6, 20, tzinfo=UTC),
    )

    decision = gate.evaluate(intent, estimated_price=Decimal("100"))

    assert decision.approved is False
    assert "symbol_not_allowed" in decision.risk_tags


def test_relative_policy_path_resolves_against_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative path still resolves even when the caller is in a different cwd."""

    policy = load_paper_execution_policy("config/paper_execution_policy.yaml")
    monkeypatch.chdir(tmp_path)

    again = load_paper_execution_policy("config/paper_execution_policy.yaml")

    assert policy.provider == again.provider
    assert policy.symbols == again.symbols
    assert policy.market == again.market


# ---------------------------------------------------------------------------
# M01-W01: OANDA-only policy boundary and negative gates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["routed", "alpaca_paper"])
def test_execution_policy_rejects_non_oanda_providers(
    tmp_path: Path, provider: str
) -> None:
    """AC-M01-W01-01: provider accepts only ``oanda_paper``."""
    policy_path = tmp_path / "policy.yaml"
    text = _replace_line(
        _configured_policy_text(), "provider:", f"provider: {provider}"
    )
    policy_path.write_text(text, encoding="utf-8")

    with pytest.raises(ValidationError, match="Input should be 'oanda_paper'"):
        load_paper_execution_policy(policy_path)


def test_execution_policy_rejects_non_oanda_market(tmp_path: Path) -> None:
    """AC-M01-W01-01: market must be an OANDA-account market boundary."""
    policy_path = tmp_path / "policy.yaml"
    text = _replace_line(
        _configured_policy_text(), "market:", "market: us_equity"
    )
    policy_path.write_text(text, encoding="utf-8")

    with pytest.raises(ValidationError, match="Input should be"):
        load_paper_execution_policy(policy_path)


def test_production_boundary_gate_accepts_checked_in_configuration() -> None:
    """AC-M01-W01-02: the checked-in production configuration passes."""
    from alphabrief_execution.broker.safety import production_boundary_violations

    root = Path(__file__).resolve().parents[1]
    assert production_boundary_violations(root) == []


@pytest.mark.parametrize(
    ("file_name", "prefix", "replacement", "fragment"),
    [
        ("paper_execution_policy.yaml", "provider:", "provider: routed", "provider"),
        (
            "paper_execution_policy.yaml",
            "provider:",
            "provider: alpaca_paper",
            "provider",
        ),
        ("paper_execution_policy.yaml", "mode:", "mode: live", "mode"),
        (
            "paper_execution_policy.yaml",
            "market:",
            "market: us_equity",
            "market",
        ),
        (
            "paper_execution_policy.yaml",
            "provider:",
            "provider: oanda_paper\nfallback: true",
            "fallback",
        ),
        (
            "oanda_paper.yaml",
            "base_url:",
            "base_url: https://api-fxtrade.oanda.com",
            "base_url",
        ),
    ],
)
def test_production_boundary_gate_rejects_forbidden_selections(
    tmp_path: Path,
    file_name: str,
    prefix: str,
    replacement: str,
    fragment: str,
) -> None:
    """AC-M01-W01-02: no live host, other broker, routing, or fallback."""
    from alphabrief_execution.broker.safety import production_boundary_violations

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    baseline = Path(f"config/{file_name}").read_text(encoding="utf-8")
    (config_dir / file_name).write_text(
        _replace_line(baseline, prefix, replacement), encoding="utf-8"
    )
    for other in ("paper_execution_policy.yaml", "oanda_paper.yaml"):
        if other != file_name:
            (config_dir / other).write_text(
                Path(f"config/{other}").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

    violations = production_boundary_violations(tmp_path)

    assert violations, "forbidden selection must produce a violation"
    assert any(fragment in violation for violation in violations)


def test_missing_oanda_credentials_fail_closed_without_order_or_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M01-W01-03: missing credentials fail closed with no order or fill."""
    from alphabrief_execution.broker.errors import BrokerAuthError
    from alphabrief_execution.broker.oanda.client import OandaHttpClient
    from alphabrief_execution.broker.oanda.config import OandaPaperConfig
    from alphabrief_execution.broker.port import (
        BrokerOrderSide,
        BrokerOrderType,
        SubmitRequest,
    )

    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_BASE_URL", raising=False)

    # A client cannot even be constructed without credentials, so no HTTP
    # request and no order/fill can be generated.
    with pytest.raises(BrokerAuthError, match="missing OANDA credentials"):
        OandaHttpClient(
            config=OandaPaperConfig(
                base_url="http://oanda.test",
                timeout_seconds=1.0,
                max_retries=0,
                retry_backoff_seconds=0.001,
                allow_insecure_base_url=True,
            )
        )

    # The production API factory resolves to an adapter whose submit path
    # raises instead of synthesizing a local fill.
    from alphabrief_api import broker_adapter

    broker_adapter._reset_broker_adapter()
    adapter = broker_adapter.get_broker_adapter()
    assert isinstance(adapter, NullBrokerAdapter)
    with pytest.raises(NotImplementedError):
        asyncio.run(
            adapter.submit(
                SubmitRequest(
                    symbol="EUR_USD",
                    side=BrokerOrderSide.BUY,
                    order_type=BrokerOrderType.MARKET,
                    quantity=Decimal("1000"),
                ),
                client_order_id="missing-credentials",
            )
        )
    broker_adapter._reset_broker_adapter()


def _replace_line(text: str, prefix: str, new_text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = new_text
            return "\n".join(lines)
    raise AssertionError(f"baseline has no line starting with {prefix!r}")
