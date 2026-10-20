"""CLI and API must report the scheduler's runtime truth identically.

``alphabrief scheduler status`` and ``GET /api/v1/scheduler/status``
describe the same durable state. The CLI rendered ``next_due_at`` (and
the other instants) through ``_iso``, while the API returned whatever the
store handed back. Depending on the DuckDB JSON round-trip that could be
a ``datetime`` or an already-formatted string, so the two surfaces
disagreed and an operator comparing them saw a contract break.

The API is the single rendered authority: both surfaces must produce the
same JSON-friendly ISO string for the same stored instant.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alphabrief_api.main import create_app
from alphabrief_cli.scheduler_commands import scheduler_app
from alphabrief_trader.runtime_truth import RuntimeTruthStore
from fastapi.testclient import TestClient
from typer.testing import CliRunner

runner = CliRunner()
_T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


@pytest.fixture()
def truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[RuntimeTruthStore]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    # Both surfaces must resolve the same file: the store the fixture
    # writes and the one the API and CLI read.
    from alphabrief_core import paths as _paths

    store = RuntimeTruthStore(db_path=_paths.db_path())
    store.update(
        leader_id="scheduler-main",
        active_config={"tasks": ["ai-cycle"], "ttl_seconds": 60},
        running_phase="discuss",
        phase_started_at=_T0,
        last_outcome="no_trade",
        failure_classification="none",
        next_due_at=_T0 + timedelta(minutes=15),
    )
    store.heartbeat(leader_id="scheduler-main", running_phase="discuss")
    yield store
    store.close()


def _api() -> dict[str, object]:
    payload: dict[str, object] = (
        TestClient(create_app()).get("/api/v1/scheduler/status").json()
    )
    return payload


def _cli() -> dict[str, object]:
    import json

    result = runner.invoke(scheduler_app, ["status", "--compact"])
    assert result.exit_code == 0, result.output
    payload: dict[str, object] = json.loads(result.stdout)
    return payload


@pytest.mark.parametrize(
    "field",
    ["leader_id", "running_phase", "last_outcome", "next_due_at", "heartbeat_at"],
)
def test_both_surfaces_agree_on_every_field(
    truth: RuntimeTruthStore, field: str
) -> None:
    del truth  # seeded by the fixture

    assert _cli()[field] == _api()[field]


def test_instants_are_rendered_as_iso_strings(
    truth: RuntimeTruthStore,
) -> None:
    """A JSON client must receive text, never a Python object's repr."""
    del truth
    api = _api()

    for field in ("next_due_at", "heartbeat_at", "phase_started_at"):
        value = api[field]
        assert value is None or isinstance(value, str), (
            f"{field} came back as {type(value).__name__}; the CLI renders "
            "an ISO string, so the API must too"
        )


def test_the_cli_instant_matches_the_stored_instant(
    truth: RuntimeTruthStore,
) -> None:
    del truth

    cli = _cli()
    expected = (_T0 + timedelta(minutes=15)).isoformat()
    assert str(cli["next_due_at"]).replace(" ", "T").startswith(
        expected[:16]
    )
