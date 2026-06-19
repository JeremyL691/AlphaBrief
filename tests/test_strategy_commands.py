"""Tests for the strategy CLI subcommands (Phase 15 R15.3)."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml
from alphabrief_cli.strategy_commands import strategy_app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path: Path) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    yield


def _spec(
    strategy_id: str = "ema_trend_v1",
    name: str = "EMA Trend v1",
    version: str = "1.0.0",
) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "name": name,
        "version": version,
        "universe": {"symbols": ["BTC-USD"]},
        "timeframe": "1d",
        "entry": {"condition": "close > ema_50"},
        "exit": {"condition": "close < ema_50"},
        "risk": {"max_position_pct": "0.2"},
        "costs": {"fee_bps": "5", "slippage_bps": "10"},
        "evaluation": {
            "train_period": {"start": "2024-01-01", "end": "2024-12-31"},
            "test_period": {"start": "2025-01-01", "end": "2025-12-31"},
        },
    }


# ---------------------------------------------------------------------------
# save --from-yaml
# ---------------------------------------------------------------------------


def test_save_from_yaml_persists(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(_spec()), encoding="utf-8")

    result = runner.invoke(
        strategy_app,
        ["save", "--from-yaml", str(spec_path)],
    )
    assert result.exit_code == 0, result.output
    assert "strategy_id: ema_trend_v1" in result.output
    assert "enabled: False" in result.output

    list_result = runner.invoke(strategy_app, ["list", "--compact"])
    assert list_result.exit_code == 0, list_result.output
    body = json.loads(list_result.stdout.strip())
    assert len(body["strategies"]) == 1
    assert body["strategies"][0]["strategy_id"] == "ema_trend_v1"


def test_save_from_yaml_with_enable_flag(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(_spec()), encoding="utf-8")

    result = runner.invoke(
        strategy_app,
        ["save", "--from-yaml", str(spec_path), "--enable"],
    )
    assert result.exit_code == 0, result.output
    assert "enabled: True" in result.output

    body = json.loads(runner.invoke(strategy_app, ["list", "--compact"]).stdout.strip())
    assert body["strategies"][0]["enabled"] is True


def test_save_from_yaml_rejects_invalid_payload(tmp_path: Path) -> None:
    bad = _spec()
    del bad["universe"]
    spec_path = tmp_path / "bad.yaml"
    spec_path.write_text(yaml.safe_dump(bad), encoding="utf-8")

    result = runner.invoke(
        strategy_app, ["save", "--from-yaml", str(spec_path)]
    )
    assert result.exit_code != 0
    assert "StrategySpec" in result.stderr


def test_save_from_yaml_rejects_malformed_yaml(tmp_path: Path) -> None:
    spec_path = tmp_path / "bad.yaml"
    spec_path.write_text(": not yaml\n  : :", encoding="utf-8")
    result = runner.invoke(
        strategy_app, ["save", "--from-yaml", str(spec_path)]
    )
    assert result.exit_code != 0
    assert "invalid payload" in result.stderr


# ---------------------------------------------------------------------------
# save --from-json
# ---------------------------------------------------------------------------


def test_save_from_json(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_spec(strategy_id="json_v1")), encoding="utf-8")

    result = runner.invoke(
        strategy_app, ["save", "--from-json", str(spec_path)]
    )
    assert result.exit_code == 0, result.output
    assert "strategy_id: json_v1" in result.output


def test_save_requires_input() -> None:
    result = runner.invoke(strategy_app, ["save"])
    assert result.exit_code != 0
    assert "--from-yaml" in result.stderr or "or --from-json" in result.stderr


def test_save_rejects_both_sources(tmp_path: Path) -> None:
    yp = tmp_path / "x.yaml"
    yp.write_text(yaml.safe_dump(_spec()), encoding="utf-8")
    jp = tmp_path / "x.json"
    jp.write_text(json.dumps(_spec()), encoding="utf-8")

    result = runner.invoke(
        strategy_app,
        ["save", "--from-yaml", str(yp), "--from-json", str(jp)],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.stderr


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_empty() -> None:
    result = runner.invoke(strategy_app, ["list", "--compact"])
    assert result.exit_code == 0
    body = json.loads(result.stdout.strip())
    assert body == {"strategies": []}


def test_list_returns_summaries(tmp_path: Path) -> None:
    for sid in ["a", "b"]:
        spec_path = tmp_path / f"{sid}.json"
        spec_path.write_text(json.dumps(_spec(strategy_id=sid, name=sid.upper())))
        result = runner.invoke(
            strategy_app, ["save", "--from-json", str(spec_path), "--enable"]
            if sid == "a"
            else ["save", "--from-json", str(spec_path)],
        )
        assert result.exit_code == 0, result.output

    body = json.loads(runner.invoke(strategy_app, ["list", "--compact"]).stdout.strip())
    assert len(body["strategies"]) == 2
    ids = {row["strategy_id"] for row in body["strategies"]}
    assert ids == {"a", "b"}
    for row in body["strategies"]:
        assert "spec" not in row


def test_list_enabled_filter(tmp_path: Path) -> None:
    for sid, flag in [("a", "--enable"), ("b", "--disable")]:
        spec_path = tmp_path / f"{sid}.json"
        spec_path.write_text(json.dumps(_spec(strategy_id=sid, name=sid.upper())))
        result = runner.invoke(
            strategy_app, ["save", "--from-json", str(spec_path), flag]
        )
        assert result.exit_code == 0, result.output

    body = json.loads(
        runner.invoke(strategy_app, ["list", "--enabled", "--compact"]).stdout.strip()
    )
    assert len(body["strategies"]) == 1
    assert body["strategies"][0]["strategy_id"] == "a"

    body = json.loads(
        runner.invoke(strategy_app, ["list", "--disabled", "--compact"]).stdout.strip()
    )
    assert len(body["strategies"]) == 1
    assert body["strategies"][0]["strategy_id"] == "b"


def test_list_ordered_by_id(tmp_path: Path) -> None:
    for sid in ["c", "a", "b"]:
        spec_path = tmp_path / f"{sid}.json"
        spec_path.write_text(json.dumps(_spec(strategy_id=sid, name=sid.upper())))
        result = runner.invoke(
            strategy_app, ["save", "--from-json", str(spec_path)]
        )
        assert result.exit_code == 0, result.output

    body = json.loads(runner.invoke(strategy_app, ["list", "--compact"]).stdout.strip())
    ids = [row["strategy_id"] for row in body["strategies"]]
    assert ids == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_returns_full_record(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    result = runner.invoke(
        strategy_app, ["save", "--from-json", str(spec_path), "--enable"]
    )
    assert result.exit_code == 0, result.output

    show = runner.invoke(strategy_app, ["show", "ema_trend_v1", "--compact"])
    assert show.exit_code == 0, show.output
    body = json.loads(show.stdout.strip())
    assert body["strategy_id"] == "ema_trend_v1"
    assert body["enabled"] is True
    assert body["spec"]["entry"]["condition"] == "close > ema_50"


def test_show_404_message_for_missing() -> None:
    result = runner.invoke(strategy_app, ["show", "nope"])
    assert result.exit_code != 0
    assert "not found" in result.stderr


# ---------------------------------------------------------------------------
# enable / disable
# ---------------------------------------------------------------------------


def test_enable_flips_flag(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    runner.invoke(strategy_app, ["save", "--from-json", str(spec_path)])

    result = runner.invoke(strategy_app, ["enable", "ema_trend_v1"])
    assert result.exit_code == 0, result.output
    assert "enabled: True" in result.output

    body = json.loads(
        runner.invoke(
            strategy_app, ["show", "ema_trend_v1", "--compact"]
        ).stdout.strip()
    )
    assert body["enabled"] is True


def test_disable_flips_flag(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    runner.invoke(
        strategy_app, ["save", "--from-json", str(spec_path), "--enable"]
    )

    result = runner.invoke(strategy_app, ["disable", "ema_trend_v1"])
    assert result.exit_code == 0, result.output
    assert "enabled: False" in result.output

    body = json.loads(
        runner.invoke(
            strategy_app, ["show", "ema_trend_v1", "--compact"]
        ).stdout.strip()
    )
    assert body["enabled"] is False


def test_enable_missing_exits_nonzero() -> None:
    result = runner.invoke(strategy_app, ["enable", "ghost"])
    assert result.exit_code != 0
    assert "not found" in result.stderr


def test_disable_missing_exits_nonzero() -> None:
    result = runner.invoke(strategy_app, ["disable", "ghost"])
    assert result.exit_code != 0
    assert "not found" in result.stderr


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_removes_record(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    runner.invoke(strategy_app, ["save", "--from-json", str(spec_path)])

    result = runner.invoke(strategy_app, ["delete", "ema_trend_v1"])
    assert result.exit_code == 0, result.output
    assert "deleted: True" in result.output

    show = runner.invoke(strategy_app, ["show", "ema_trend_v1"])
    assert show.exit_code != 0
    assert "not found" in show.stderr


def test_delete_missing_exits_nonzero() -> None:
    result = runner.invoke(strategy_app, ["delete", "ghost"])
    assert result.exit_code != 0
    assert "not found" in result.stderr


# ---------------------------------------------------------------------------
# record-signal / list-signals / show-signal / count-signals
# ---------------------------------------------------------------------------


def _signal(
    signal_id: str = "sig_1",
    strategy_id: str = "ema_trend_v1",
    symbol: str = "BTC-USD",
    ts: str = "2024-06-01T00:00:00+00:00",
    direction: str = "long",
    confidence: float = 0.8,
    horizon: str = "1d",
) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timestamp": ts,
        "direction": direction,
        "confidence": confidence,
        "horizon": horizon,
        "rationale": f"rationale for {signal_id}",
    }


def test_record_signal_from_yaml_persists(tmp_path: Path) -> None:
    sig_path = tmp_path / "sig.yaml"
    sig_path.write_text(yaml.safe_dump(_signal()), encoding="utf-8")

    result = runner.invoke(
        strategy_app,
        ["record-signal", "--from-yaml", str(sig_path)],
    )
    assert result.exit_code == 0, result.output
    assert "signal_id: sig_1" in result.output
    assert "source: other" in result.output

    show = runner.invoke(strategy_app, ["show-signal", "sig_1", "--compact"])
    body = json.loads(show.stdout.strip())
    assert body["strategy_id"] == "ema_trend_v1"


def test_record_signal_from_json_with_source(tmp_path: Path) -> None:
    sig_path = tmp_path / "sig.json"
    sig_path.write_text(json.dumps(_signal(signal_id="s1")), encoding="utf-8")

    result = runner.invoke(
        strategy_app,
        [
            "record-signal",
            "--from-json",
            str(sig_path),
            "--source",
            "backtest",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "source: backtest" in result.output


def test_record_signal_requires_input() -> None:
    result = runner.invoke(strategy_app, ["record-signal"])
    assert result.exit_code != 0
    assert "--from-yaml" in result.stderr or "or --from-json" in result.stderr


def test_record_signal_rejects_invalid_source(tmp_path: Path) -> None:
    sig_path = tmp_path / "sig.json"
    sig_path.write_text(json.dumps(_signal()), encoding="utf-8")
    result = runner.invoke(
        strategy_app,
        [
            "record-signal",
            "--from-json",
            str(sig_path),
            "--source",
            "bogus",
        ],
    )
    assert result.exit_code != 0
    assert "source" in result.stderr


def test_record_signal_rejects_invalid_payload(tmp_path: Path) -> None:
    bad = _signal()
    del bad["confidence"]
    sig_path = tmp_path / "bad.json"
    sig_path.write_text(json.dumps(bad), encoding="utf-8")

    result = runner.invoke(
        strategy_app, ["record-signal", "--from-json", str(sig_path)]
    )
    assert result.exit_code != 0
    assert "confidence" in result.stderr


def test_list_signals_empty() -> None:
    result = runner.invoke(strategy_app, ["list-signals", "--compact"])
    assert result.exit_code == 0
    assert json.loads(result.stdout.strip()) == {"signals": []}


def test_list_signals_filters(tmp_path: Path) -> None:
    for sid, src in [("a", "backtest"), ("b", "manual"), ("c", "other")]:
        p = tmp_path / f"{sid}.json"
        strategy = "s1" if sid != "c" else "s2"
        p.write_text(
            json.dumps(_signal(signal_id=sid, strategy_id=strategy)),
            encoding="utf-8",
        )
        result = runner.invoke(
            strategy_app,
            [
                "record-signal",
                "--from-json",
                str(p),
                "--source",
                src,
            ],
        )
        assert result.exit_code == 0, result.output

    body = json.loads(
        runner.invoke(strategy_app, ["list-signals", "--compact"]).stdout.strip()
    )
    assert len(body["signals"]) == 3

    body = json.loads(
        runner.invoke(
            strategy_app,
            ["list-signals", "--strategy-id", "s1", "--compact"],
        ).stdout.strip()
    )
    assert len(body["signals"]) == 2

    body = json.loads(
        runner.invoke(
            strategy_app,
            ["list-signals", "--source", "manual", "--compact"],
        ).stdout.strip()
    )
    assert len(body["signals"]) == 1
    assert body["signals"][0]["signal_id"] == "b"


def test_show_signal_missing(tmp_path: Path) -> None:
    result = runner.invoke(strategy_app, ["show-signal", "ghost"])
    assert result.exit_code != 0
    assert "not found" in result.stderr


def test_count_signals(tmp_path: Path) -> None:
    for i in range(3):
        p = tmp_path / f"s{i}.json"
        p.write_text(
            json.dumps(_signal(signal_id=f"s{i}", strategy_id="s1")),
            encoding="utf-8",
        )
        runner.invoke(strategy_app, ["record-signal", "--from-json", str(p)])

    p = tmp_path / "x.json"
    p.write_text(json.dumps(_signal(signal_id="x", strategy_id="s2")), encoding="utf-8")
    runner.invoke(strategy_app, ["record-signal", "--from-json", str(p)])

    result = runner.invoke(strategy_app, ["count-signals", "s1"])
    assert result.exit_code == 0
    assert "count: 3" in result.output

    result_zero = runner.invoke(strategy_app, ["count-signals", "empty"])
    assert "count: 0" in result_zero.output
