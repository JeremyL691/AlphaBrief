"""The dashboard's API client must only call routes that exist.

`static/api.js` shipped with a set of paths the backend never served:
``/api/v1/ai-trading/*`` (the real prefix is ``/api/v1/ai``),
``/api/v1/risk/status`` (the real endpoints are ``kill-switch``,
``context`` and ``dashboard``), plus ``/api/v1/soak/status`` and
``/api/v1/models`` which had no route at all. Every one of them returned
404 against a running backend, so an operator saw an empty panel and had
no way to tell a broken route from "no data yet".

The fix has two halves and this module checks both:

* every path the client uses resolves against the real route table;
* the two missing read endpoints now exist and answer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alphabrief_api.main import create_app
from fastapi.testclient import TestClient

STATIC_DIR = (
    Path(__file__).resolve().parents[1] / "apps/api/src/alphabrief_api/static"
)
API_JS = STATIC_DIR / "api.js"


def _app_routes() -> list[str]:
    """Every served path, read from the generated schema.

    The API routers are mounted on a sub-application, so ``app.routes``
    only shows the mounts; the OpenAPI document is the authoritative list
    of what the server actually answers.
    """
    spec = create_app().openapi()
    return sorted(spec["paths"])


def _client_paths() -> list[str]:
    """Every ``/api/...`` literal the browser client requests."""
    text = API_JS.read_text(encoding="utf-8")
    found = re.findall(r"[\"'`](/api/v1/[A-Za-z0-9/_\-${}.]+)", text)
    # Drop query strings and template substitutions, keep the shape.
    cleaned = []
    for path in found:
        head = path.split("?", 1)[0]
        head = re.sub(r"\$\{[^}]+\}", "{param}", head).rstrip("/")
        cleaned.append(head)
    return sorted(set(cleaned))


def _matches(client_path: str, server_path: str) -> bool:
    """True when a concrete client path fits a templated server route."""
    pattern = re.sub(r"\{[^}]+\}", "[^/]+", server_path)
    return re.fullmatch(pattern.rstrip("/"), client_path) is not None


def test_every_client_path_has_a_route() -> None:
    """A 404 in the dashboard is a contract break, not an empty state."""
    routes = _app_routes()
    missing = [
        path
        for path in _client_paths()
        if not any(_matches(path, route) for route in routes)
    ]

    assert missing == [], f"api.js requests unserved paths: {missing}"


def test_client_uses_the_real_ai_prefix() -> None:
    """The routes are mounted at /api/v1/ai, not /api/v1/ai-trading."""
    text = API_JS.read_text(encoding="utf-8")

    assert "/api/v1/ai-trading" not in text
    assert "/api/v1/ai/" in text


def test_client_uses_a_real_risk_endpoint() -> None:
    """There is no /api/v1/risk/status; the dashboard route carries the state."""
    text = API_JS.read_text(encoding="utf-8")

    assert "/api/v1/risk/status" not in text
    assert "/api/v1/risk/dashboard" in text


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the API at a temporary data directory.

    The endpoints read the real stores; without this the test would try to
    open the live database that the resident backend holds.
    """
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.mark.parametrize("path", ["/api/v1/soak/status", "/api/v1/models"])
def test_previously_missing_endpoints_answer(path: str, client: TestClient) -> None:
    res = client.get(path)

    assert res.status_code == 200, f"{path} -> {res.status_code}"


def test_soak_status_answers_even_when_it_owns_the_write_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process that holds the writer must still be able to read.

    DuckDB refuses a second connection with a different configuration, so
    the evaluator snapshots the file instead of reopening it. This is the
    shape the resident backend serves the dashboard with.
    """
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    import duckdb
    from alphabrief_api.db.schema import apply_schema
    from alphabrief_core import paths as _paths

    writer = duckdb.connect(str(_paths.db_path()))
    try:
        apply_schema(writer)
        res = TestClient(create_app()).get("/api/v1/soak/status")

        assert res.status_code == 200, res.text
    finally:
        writer.close()


def test_soak_status_endpoint_reports_real_facts(client: TestClient) -> None:
    """The panel must receive the same numbers the CLI computes."""
    payload = client.get("/api/v1/soak/status").json()

    assert set(
        {
            "soak_started",
            "run_index",
            "state",
            "qualified_days",
            "target_days",
            "days",
        }
    ) <= set(payload)
    assert payload["target_days"] == 14


def test_models_endpoint_carries_no_credentials(client: TestClient) -> None:
    """Channel state is public to the local UI; the key is not."""
    payload = client.get("/api/v1/models").json()
    raw = str(payload)

    assert "primary_channel" in payload
    for marker in ("api_key", "token", "sk-", "Bearer"):
        assert marker not in raw


def test_models_endpoint_reports_the_configured_channel(
    client: TestClient,
) -> None:
    from alphabrief_models.channels import load_model_settings

    payload = client.get("/api/v1/models").json()
    settings = load_model_settings()

    assert payload["primary_channel"] == settings.primary_channel
    assert payload["daily_call_limit"] == settings.daily_call_limit


def test_risk_dashboard_exposes_the_percentage_caps(
    client: TestClient,
) -> None:
    """The risk page needs the reviewed percentages, not hardcoded ones."""
    config = client.get("/api/v1/risk/dashboard").json()["config"]

    assert "max_order_value_pct" in config
    assert "max_total_exposure_pct" in config
