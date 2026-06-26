"""Kronos forecasting integration boundary for AlphaBrief.

The external Kronos project is treated as an optional local forecasting
runtime. AlphaBrief owns the schemas, gateway adapter, audit records, and risk
boundaries. Forecasts are advisory research evidence only; this module never
creates signals, order intents, orders, broker calls, or risk decisions.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from typing import Any, Literal, Protocol
from uuid import uuid4

from alphabrief_core import Bar
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphabrief_models.gateway import (
    ModelCapability,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
)

KronosDirectionBias = Literal["bullish", "bearish", "neutral"]

_KRONOS_CAPABILITIES: frozenset[ModelCapability] = frozenset(
    ("structured_output", "time_series_forecasting")
)


def _reject_float_decimal(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("decimal fields must not be provided as float values")
    return value


def _validate_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime fields must be timezone-aware")
    return value


class KronosSchema(BaseModel):
    """Strict schema base for Kronos integration objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class KronosForecastPoint(KronosSchema):
    """One predicted OHLCV bar from a Kronos runtime."""

    step: int = Field(ge=1)
    timestamp: datetime | None = None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is None:
            return None
        return _validate_timezone_aware(value)

    @field_validator("open", "high", "low", "close", "volume", mode="before")
    @classmethod
    def decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float_decimal(value)

    @model_validator(mode="after")
    def validate_ohlcv(self) -> KronosForecastPoint:
        prices = [self.open, self.high, self.low, self.close]
        if any(price < 0 for price in prices):
            raise ValueError("forecast prices must be non-negative")
        if self.volume < 0:
            raise ValueError("forecast volume must be non-negative")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("forecast high must be at least open, low, and close")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("forecast low must be at most open, high, and close")
        return self


class KronosForecastRequest(KronosSchema):
    """Input carried through ModelGateway to the Kronos adapter."""

    request_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    bars: list[Bar] = Field(min_length=2)
    prediction_length: int = Field(ge=1, le=512)
    model_name: str = Field(default="NeoQuasar/Kronos-mini", min_length=1)
    tokenizer_name: str = Field(default="NeoQuasar/Kronos-Tokenizer-base", min_length=1)
    temperature: Decimal = Field(default=Decimal("1.0"), gt=0)
    top_p: Decimal = Field(default=Decimal("0.9"), gt=0, le=1)
    sample_count: int = Field(default=1, ge=1, le=32)

    @field_validator("temperature", "top_p", mode="before")
    @classmethod
    def decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float_decimal(value)

    @model_validator(mode="after")
    def validate_bars(self) -> KronosForecastRequest:
        symbols = {bar.symbol for bar in self.bars}
        if symbols != {self.symbol}:
            raise ValueError("all bars must match request symbol")
        timestamps = [bar.timestamp for bar in self.bars]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
            raise ValueError("bars must have strictly increasing timestamps")
        return self


class KronosForecastReport(KronosSchema):
    """Structured advisory forecast emitted by a Kronos runtime."""

    forecast_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    provider: str = Field(default="kronos", min_length=1)
    model: str = Field(min_length=1)
    tokenizer: str = Field(min_length=1)
    input_bar_count: int = Field(ge=2)
    prediction_length: int = Field(ge=1)
    source_data_version: str = Field(min_length=1)
    generated_at: datetime
    points: list[KronosForecastPoint] = Field(min_length=1)
    advisory_only: bool = True
    notes: list[str] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("notes")
    @classmethod
    def notes_must_not_contain_blanks(cls, value: list[str]) -> list[str]:
        if any(note.strip() == "" for note in value):
            raise ValueError("notes must not contain blank strings")
        return value

    @model_validator(mode="after")
    def validate_report(self) -> KronosForecastReport:
        if len(self.points) != self.prediction_length:
            raise ValueError("points length must match prediction_length")
        expected_steps = list(range(1, self.prediction_length + 1))
        if [point.step for point in self.points] != expected_steps:
            raise ValueError("forecast point steps must be sequential")
        if self.advisory_only is not True:
            raise ValueError("Kronos forecasts must remain advisory_only")
        return self


class KronosForecastEvidence(KronosSchema):
    """Compact evidence object that research or strategy code may attach."""

    forecast_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    model: str = Field(min_length=1)
    horizon_steps: int = Field(ge=1)
    direction_bias: KronosDirectionBias
    confidence: float = Field(ge=0, le=1)
    expected_return: Decimal | None = None
    generated_at: datetime
    advisory_only: bool = True

    @field_validator("expected_return", mode="before")
    @classmethod
    def decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float_decimal(value)

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @model_validator(mode="after")
    def validate_evidence(self) -> KronosForecastEvidence:
        if self.advisory_only is not True:
            raise ValueError("Kronos evidence must remain advisory_only")
        return self


class KronosRuntime(Protocol):
    """Runtime seam for a local Kronos predictor implementation."""

    def forecast(self, request: KronosForecastRequest) -> KronosForecastReport:
        """Return an AlphaBrief-owned forecast report."""


class UnavailableKronosRuntime:
    """Runtime used when the external Kronos predictor is not configured."""

    def forecast(self, request: KronosForecastRequest) -> KronosForecastReport:
        raise ModelProviderError(
            "Kronos runtime is not configured. Install and initialize the external "
            "Kronos predictor, then inject a KronosRuntime implementation."
        )


class DeterministicKronosRuntime:
    """Deterministic local runtime for tests, demos, and CI.

    It is explicitly not a replacement for the external Kronos model. It
    preserves the AlphaBrief integration path when heavyweight optional model
    dependencies are absent.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        forecast_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._forecast_id_factory = forecast_id_factory or (
            lambda: f"kronos_forecast_{uuid4().hex}"
        )

    def forecast(self, request: KronosForecastRequest) -> KronosForecastReport:
        last = request.bars[-1]
        prev = request.bars[-2]
        delta = last.close - prev.close
        points: list[KronosForecastPoint] = []
        current_close = last.close
        for step in range(1, request.prediction_length + 1):
            next_close = max(Decimal("0"), current_close + delta)
            high = max(current_close, next_close)
            low = min(current_close, next_close)
            points.append(
                KronosForecastPoint(
                    step=step,
                    timestamp=None,
                    open=current_close,
                    high=high,
                    low=low,
                    close=next_close,
                    volume=last.volume,
                )
            )
            current_close = next_close

        return KronosForecastReport(
            forecast_id=self._forecast_id_factory(),
            request_id=request.request_id,
            symbol=request.symbol,
            model=request.model_name,
            tokenizer=request.tokenizer_name,
            input_bar_count=len(request.bars),
            prediction_length=request.prediction_length,
            source_data_version=last.data_version,
            generated_at=self._clock(),
            points=points,
            notes=[
                "deterministic AlphaBrief runtime; configure external Kronos "
                "for model-backed forecasts"
            ],
        )


class PredictorKronosRuntime:
    """Adapter for an already-initialized external Kronos predictor object.

    The object must expose a ``predict`` method compatible with the Kronos
    project's predictor API. This wrapper intentionally avoids importing torch,
    pandas, or Hugging Face at module import time.
    """

    def __init__(
        self,
        predictor: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        forecast_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if predictor is None or not hasattr(predictor, "predict"):
            raise ValueError("predictor must expose a predict method")
        self._predictor = predictor
        self._clock = clock or (lambda: datetime.now(UTC))
        self._forecast_id_factory = forecast_id_factory or (
            lambda: f"kronos_forecast_{uuid4().hex}"
        )

    def forecast(self, request: KronosForecastRequest) -> KronosForecastReport:
        try:
            pd: Any = import_module("pandas")
        except Exception as exc:  # pragma: no cover - optional dependency branch
            raise ModelProviderError(
                "pandas is required when using PredictorKronosRuntime"
            ) from exc

        frame = pd.DataFrame(
            [
                {
                    "timestamp": bar.timestamp,
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": str(bar.volume),
                }
                for bar in request.bars
            ]
        )
        try:
            raw = self._predictor.predict(
                frame,
                pred_len=request.prediction_length,
                T=float(request.temperature),
                top_p=float(request.top_p),
                sample_count=request.sample_count,
            )
        except Exception as exc:  # pragma: no cover - depends on external runtime
            error_type = type(exc).__name__
            raise ModelProviderError(f"Kronos predictor failed: {error_type}") from exc

        points = _points_from_predictor_output(raw, request.prediction_length)
        return KronosForecastReport(
            forecast_id=self._forecast_id_factory(),
            request_id=request.request_id,
            symbol=request.symbol,
            model=request.model_name,
            tokenizer=request.tokenizer_name,
            input_bar_count=len(request.bars),
            prediction_length=request.prediction_length,
            source_data_version=request.bars[-1].data_version,
            generated_at=self._clock(),
            points=points,
            notes=["external Kronos predictor runtime"],
        )


class KronosForecastAdapter:
    """ModelGateway provider adapter for Kronos market forecasts."""

    provider_name = "kronos"

    def __init__(
        self,
        *,
        runtime: KronosRuntime | None = None,
        model_name: str = "NeoQuasar/Kronos-mini",
        tokenizer_name: str = "NeoQuasar/Kronos-Tokenizer-base",
    ) -> None:
        self.model_name = model_name
        self.tokenizer_name = tokenizer_name
        self.capabilities = _KRONOS_CAPABILITIES
        self._runtime = runtime or UnavailableKronosRuntime()

    def call(self, request: ModelRequest) -> ModelResponse:
        if request.task_type != "market_forecast":
            raise ModelProviderError("Kronos adapter only supports market_forecast")
        if not _KRONOS_CAPABILITIES.issuperset(request.required_capabilities):
            raise ModelProviderError("Kronos request asks for unsupported capabilities")

        forecast_request = KronosForecastRequest.model_validate_json(request.input_text)
        forecast_request = forecast_request.model_copy(
            update={
                "model_name": self.model_name,
                "tokenizer_name": self.tokenizer_name,
            }
        )
        report = self._runtime.forecast(forecast_request)
        structured = report.model_dump(mode="json")
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text=json.dumps(structured, sort_keys=True),
            structured_output=structured,
            status="succeeded",
            finish_reason="forecast_complete",
        )


def build_kronos_model_request(
    forecast_request: KronosForecastRequest,
) -> ModelRequest:
    """Serialize a typed Kronos forecast request for ModelGateway."""

    return ModelRequest(
        request_id=forecast_request.request_id,
        task_type="market_forecast",
        prompt_version="kronos-forecast:v1",
        input_text=forecast_request.model_dump_json(),
        required_capabilities=["structured_output", "time_series_forecasting"],
        metadata={
            "symbol": forecast_request.symbol,
            "model_family": "kronos",
        },
    )


def forecast_with_kronos_gateway(
    gateway_call: Callable[[ModelRequest], Any],
    forecast_request: KronosForecastRequest,
) -> KronosForecastReport:
    """Invoke a gateway-like callable and validate the forecast report."""

    result = gateway_call(build_kronos_model_request(forecast_request))
    response = getattr(result, "response", None)
    if response is None:
        record = getattr(result, "record", None)
        error_type = getattr(record, "error_type", None) or "unknown"
        raise ModelProviderError(f"Kronos forecast failed: {error_type}")
    payload = response.structured_output
    if payload is None:
        payload = json.loads(response.output_text)
    return KronosForecastReport.model_validate(payload)


def build_kronos_evidence(report: KronosForecastReport) -> KronosForecastEvidence:
    """Summarize a forecast report as advisory evidence."""

    first = report.points[0]
    last = report.points[-1]
    expected_return: Decimal | None = None
    if first.open != 0:
        expected_return = (last.close - first.open) / first.open

    direction: KronosDirectionBias = "neutral"
    if expected_return is not None:
        if expected_return > Decimal("0"):
            direction = "bullish"
        elif expected_return < Decimal("0"):
            direction = "bearish"

    confidence = 0.5
    if expected_return is not None:
        magnitude = min(abs(float(expected_return)), 0.5)
        confidence = 0.5 + magnitude

    return KronosForecastEvidence(
        forecast_id=report.forecast_id,
        symbol=report.symbol,
        model=report.model,
        horizon_steps=report.prediction_length,
        direction_bias=direction,
        confidence=confidence,
        expected_return=expected_return,
        generated_at=report.generated_at,
    )


def _points_from_predictor_output(
    raw: Any,
    prediction_length: int,
) -> list[KronosForecastPoint]:
    if hasattr(raw, "to_dict"):
        rows = raw.to_dict(orient="records")
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        rows = list(raw)
    else:
        raise ModelProviderError("Kronos predictor returned unsupported output")

    if len(rows) < prediction_length:
        raise ModelProviderError("Kronos predictor returned too few rows")

    points: list[KronosForecastPoint] = []
    for step, row in enumerate(rows[:prediction_length], start=1):
        if not isinstance(row, dict):
            raise ModelProviderError("Kronos predictor rows must be mapping objects")
        points.append(
            KronosForecastPoint(
                step=step,
                timestamp=row.get("timestamp"),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row.get("volume", Decimal("0")),
            )
        )
    return points


__all__ = [
    "DeterministicKronosRuntime",
    "KronosDirectionBias",
    "KronosForecastAdapter",
    "KronosForecastEvidence",
    "KronosForecastPoint",
    "KronosForecastReport",
    "KronosForecastRequest",
    "KronosRuntime",
    "PredictorKronosRuntime",
    "UnavailableKronosRuntime",
    "build_kronos_evidence",
    "build_kronos_model_request",
    "forecast_with_kronos_gateway",
]
