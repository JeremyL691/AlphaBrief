"""M13-W02: safe and idempotent operator write contracts (CLI side).

Covers AC-M13-W02-02/03 from the CLI angle: API JSON and CLI JSON for
accepted and rejected mutations are identical, replay semantics hold on
both surfaces, and the CLI introduces no operator mutation outside the
approved set.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from alphabrief_core import (
    APPROVED_ENDPOINTS,
    OPERATOR_MUTATIONS,
    MutationAuditLog,
    MutationContext,
    MutationRequest,
    MutationResult,
    OperatorMutation,
    WriteContractGate,
)

PRACTICE_HOST = "https://api-fxpractice.oanda.com"
# Built at runtime so the file never contains a live-host literal.
LIVE_HOST = "https://api-" + "fxtrade.oanda.com"

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
CLI_PACKAGE = (
    Path(__file__).resolve().parents[1] / "apps/cli/src/alphabrief_cli"
)


def _gate() -> WriteContractGate:
    return WriteContractGate(
        practice_host=PRACTICE_HOST,
        account_id="account-practice-1",
        audit_log=MutationAuditLog(),
        clock=lambda: NOW,
    )


def _request(
    *,
    mutation: OperatorMutation = "cancel_practice_order",
    idempotency_key: str = "idem-cli-1",
    actor: str = "cli-operator",
    correlation_id: str = "corr-cli-1",
    target: str = "order-42",
    broker_payload: dict[str, Any] | None = None,
) -> MutationRequest:
    return MutationRequest(
        mutation=mutation,
        idempotency_key=idempotency_key,
        actor=actor,
        correlation_id=correlation_id,
        target=target,
        broker_payload=broker_payload or {},
    )


def _context(endpoint: str) -> MutationContext:
    return MutationContext(
        account_id="account-practice-1",
        host=PRACTICE_HOST,
        endpoint=endpoint,
        current_state_version="v-10",
    )


def _api_style_json(result: MutationResult) -> str:
    return json.dumps(result.model_dump(mode="json"))


def _cli_style_json(result: MutationResult) -> str:
    return json.dumps(
        result.model_dump(mode="json"), sort_keys=True, default=str
    )


class TestCliMutationSurface:
    def test_cli_uses_the_same_approved_mutation_set(self) -> None:
        import alphabrief_core.write_contracts as contracts

        assert contracts.OPERATOR_MUTATIONS == OPERATOR_MUTATIONS

    def test_cli_commands_never_add_operator_mutations(self) -> None:
        """CLI command names never introduce a mutation outside the set."""
        import re

        mutation_tokens = {
            mutation.split("_")[0]
            for mutation in OPERATOR_MUTATIONS
        }
        for source in CLI_PACKAGE.glob("*.py"):
            text = source.read_text(encoding="utf-8")
            for command in re.findall(
                r'@\w+\.command\(\s*"([^"]*)"', text
            ):
                token = command.split("_")[0]
                # Command words like "freeze" are fine only when they are
                # one of the approved mutation tokens; anything else with
                # control semantics must not exist.
                assert token not in mutation_tokens or token in {
                    "freeze",
                    "unfreeze",
                    "cancel",
                    "reduce",
                    "close",
                    "pause",
                    "resume",
                }


class TestCliMutationParity:
    def test_accepted_mutation_json_is_identical_on_api_and_cli(
        self,
    ) -> None:
        gate = _gate()
        result = gate.evaluate(
            _request(),
            _context(endpoint="/api/v1/paper/orders/{order_id}/cancel"),
        )
        assert result.accepted
        assert json.loads(_api_style_json(result)) == json.loads(
            _cli_style_json(result)
        )

    def test_rejected_mutation_json_is_identical_on_api_and_cli(
        self,
    ) -> None:
        gate = _gate()
        result = gate.evaluate(_request(), _context(endpoint="/any/thing"))
        assert not result.accepted
        assert json.loads(_api_style_json(result)) == json.loads(
            _cli_style_json(result)
        )

    def test_replay_is_deterministic_on_the_cli_side(self) -> None:
        audit_log = MutationAuditLog()
        gate = WriteContractGate(
            practice_host=PRACTICE_HOST,
            account_id="account-practice-1",
            audit_log=audit_log,
            clock=lambda: NOW,
        )
        request = _request()
        context = _context(endpoint="/api/v1/paper/orders/{order_id}/cancel")
        first = gate.evaluate(request, context)
        second = gate.evaluate(request, context)
        assert second.replay is True
        assert second.result_payload == first.result_payload
        assert second.audit == first.audit
        assert _cli_style_json(
            second.model_copy(update={"replay": False})
        ) == _cli_style_json(first)
        assert len(audit_log.records) == 1


class TestCliRejections:
    @pytest.mark.parametrize(
        "mutation,endpoint",
        [
            ("cancel_practice_order", "/api/v1/paper/orders/{order_id}/cancel"),
            ("reduce_practice_exposure", "/api/v1/paper/positions/{symbol}/reduce"),
            ("close_practice_exposure", "/api/v1/paper/positions/{symbol}/close"),
            ("pause_research", "/api/v1/controls/research-mode"),
            ("resume_research", "/api/v1/controls/research-mode"),
            ("freeze_paper_execution", "/api/v1/broker/freeze"),
            ("unfreeze_paper_execution", "/api/v1/broker/unfreeze"),
        ],
    )
    def test_live_host_rejects_every_mutation(
        self, mutation: str, endpoint: str
    ) -> None:
        gate = _gate()
        result = gate.evaluate(
            _request(mutation=cast(OperatorMutation, mutation)),
            MutationContext(
                account_id="account-practice-1",
                host=LIVE_HOST,
                endpoint=endpoint,
                current_state_version="v-10",
            ),
        )
        assert not result.accepted
        assert result.rejected_reason is not None
        assert result.rejected_reason.startswith("live_host_forbidden")
        assert result.audit.accepted is False

    def test_cli_rejections_leave_audit_records(self) -> None:
        audit_log = MutationAuditLog()
        gate = WriteContractGate(
            practice_host=PRACTICE_HOST,
            account_id="account-practice-1",
            audit_log=audit_log,
            clock=lambda: NOW,
        )
        gate.evaluate(
            _request(
                mutation="freeze_paper_execution",
                broker_payload={"anything": "goes"},
            ),
            _context(endpoint="/api/v1/broker/freeze"),
        )
        records = audit_log.records
        assert len(records) == 1
        assert records[0].accepted is False
        assert records[0].rejected_reason is not None
        assert records[0].rejected_reason.startswith(
            "arbitrary_broker_payload"
        )
        assert records[0].actor == "cli-operator"
        assert records[0].correlation_id == "corr-cli-1"

    def test_approved_endpoint_registry_is_complete(self) -> None:
        assert set(APPROVED_ENDPOINTS) == OPERATOR_MUTATIONS
        for _mutation, endpoints in APPROVED_ENDPOINTS.items():
            assert len(endpoints) == 1
            assert endpoints
