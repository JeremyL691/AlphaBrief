from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alphabrief_core import Bar
from alphabrief_models import (
    DeterministicKronosRuntime,
    KronosForecastAdapter,
    KronosForecastRequest,
    ModelGateway,
    ModelProviderError,
    build_kronos_evidence,
    build_kronos_model_request,
    forecast_with_kronos_gateway,
)
from pydantic import ValidationError


def _bars(symbol: str = "SPY") -> list[Bar]:
    start = datetime(2026, 6, 1, 13, 30, tzinfo=UTC)
    return [
        Bar(
            symbol=symbol,
            timestamp=start + timedelta(days=index),
            open=Decimal(str(100 + index)),
            high=Decimal(str(101 + index)),
            low=Decimal(str(99 + index)),
            close=Decimal(str(100 + index)),
            volume=Decimal("1000"),
            source="unit",
            data_version="v1",
        )
        for index in range(3)
    ]


def test_kronos_request_rejects_mixed_symbol_bars() -> None:
    bars = _bars()
    bars[1] = bars[1].model_copy(update={"symbol": "QQQ"})

    with pytest.raises(ValidationError, match="all bars must match"):
        KronosForecastRequest(
            request_id="req_1",
            symbol="SPY",
            bars=bars,
            prediction_length=2,
        )


def test_kronos_adapter_runs_through_model_gateway() -> None:
    forecast_request = KronosForecastRequest(
        request_id="req_1",
        symbol="SPY",
        bars=_bars(),
        prediction_length=2,
    )
    gateway = ModelGateway(
        [
            KronosForecastAdapter(
                runtime=DeterministicKronosRuntime(
                    clock=lambda: datetime(2026, 6, 2, 12, tzinfo=UTC),
                    forecast_id_factory=lambda: "forecast_1",
                )
            )
        ],
        call_id_factory=lambda: "call_1",
    )

    result = gateway.invoke(build_kronos_model_request(forecast_request))

    assert result.response is not None
    assert result.record.call_id == "call_1"
    assert result.record.provider == "kronos"
    assert result.record.status == "succeeded"
    report = forecast_with_kronos_gateway(
        gateway.invoke,
        forecast_request,
    )
    assert report.symbol == "SPY"
    assert report.forecast_id == "forecast_1"
    assert report.advisory_only is True
    assert len(report.points) == 2


def test_kronos_unavailable_runtime_records_gateway_failure() -> None:
    forecast_request = KronosForecastRequest(
        request_id="req_1",
        symbol="SPY",
        bars=_bars(),
        prediction_length=2,
    )
    gateway = ModelGateway([KronosForecastAdapter()])

    result = gateway.invoke(build_kronos_model_request(forecast_request))

    assert result.response is None
    assert result.record.status == "failed"
    assert result.record.error_type == "ModelProviderError"
    with pytest.raises(ModelProviderError, match="Kronos forecast failed"):
        forecast_with_kronos_gateway(gateway.invoke, forecast_request)


def test_kronos_evidence_is_advisory_and_directional() -> None:
    forecast_request = KronosForecastRequest(
        request_id="req_1",
        symbol="SPY",
        bars=_bars(),
        prediction_length=2,
    )
    report = DeterministicKronosRuntime(
        clock=lambda: datetime(2026, 6, 2, 12, tzinfo=UTC),
        forecast_id_factory=lambda: "forecast_1",
    ).forecast(forecast_request)

    evidence = build_kronos_evidence(report)

    assert evidence.forecast_id == "forecast_1"
    assert evidence.symbol == "SPY"
    assert evidence.direction_bias == "bullish"
    assert evidence.advisory_only is True
    assert evidence.expected_return is not None
