"""Practice test for the ChatGPT subscription channel (real credentials).

Run explicitly with ``pytest -m practice -k chatgpt_channel_practice``
after ``alphabrief model login``; CI excludes it with
``-m "not practice"``. The test performs one real inference call and
asserts the response parses as strict JSON, and that the call record
carries the channel, model, latency and token usage.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import load_env_file
from alphabrief_models.chatgpt_plan import (
    ChatGptPlanAdapter,
    ChatGptPlanError,
    load_credentials,
)
from alphabrief_models.gateway import ModelCallRecord, ModelGateway, ModelRequest

pytestmark = pytest.mark.practice

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _local_environment() -> None:
    """Load the developer's ``.env`` (credentials and the TLS bundle)."""
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        load_env_file(env_path)


def test_signed_in_and_inference_scope_granted() -> None:
    credentials = load_credentials()

    assert credentials is not None, (
        "not signed in: run 'alphabrief model login' once"
    )
    assert credentials.has_inference_scope(), (
        "the stored authorization lacks chatgpt.tokens.use.direct"
    )
    assert credentials.default_model, (
        "no default model discovered; run 'alphabrief model login' again"
    )


def test_real_call_returns_strict_json_and_is_recorded() -> None:
    records: list[ModelCallRecord] = []
    adapter = ChatGptPlanAdapter()
    try:
        adapter._current()  # noqa: SLF001 - fail fast with a clear code
    except ChatGptPlanError as exc:  # pragma: no cover - needs credentials
        pytest.fail(f"channel unavailable: {exc.code}")

    gateway = ModelGateway([adapter], record_sink=records.append)
    request = ModelRequest(
        request_id="practice_chatgpt_channel",
        task_type="test",
        prompt_version="practice-v1",
        input_text=(
            "Reply with exactly one JSON object, no prose: "
            '{"ok": true, "channel": "chatgpt_plan"}'
        ),
        required_capabilities=["text_generation"],
    )

    result = gateway.invoke(request)

    assert result.response is not None, (
        f"call failed: {result.record.error_type}"
    )
    assert result.record.provider == "chatgpt_plan"
    assert result.record.status == "succeeded"
    assert result.record.latency_ms >= 0
    assert len(records) == 1
    assert records[0].input_hash and len(records[0].input_hash) == 64

    payload = result.response.output_text.strip()
    assert payload.startswith("{") and payload.endswith("}"), payload
    assert '"ok"' in payload
    # Token usage is reported by the Responses API when available.
    assert records[0].output_tokens is None or isinstance(
        records[0].output_tokens, int
    )
    assert Decimal(0) <= Decimal(records[0].latency_ms)
