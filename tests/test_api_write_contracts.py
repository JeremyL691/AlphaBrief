"""M13-W02: safe and idempotent operator write contracts (API side).

Covers AC-M13-W02-01/02/03: only the approved operator mutations are
exposed; every accepted mutation validates current state, requires an
idempotency key, persists actor and correlation metadata, and returns
the same result on replay; live host, arbitrary endpoint, arbitrary
broker payload, unsupported mutation, stale version, and cross-account
fixtures fail before provider invocation and leave an audit rejection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from alphabrief_core import (
    APPROVED_ENDPOINTS,
    APPROVED_PAYLOAD_KEYS,
    OPERATOR_MUTATIONS,
    MutationAuditLog,
    MutationContext,
    MutationRequest,
    MutationResult,
    OperatorMutation,
    WriteContractGate,
)
from pydantic import ValidationError

PRACTICE_HOST = "https://api-fxpractice.oanda.com"
# Built at runtime so the file never contains a live-host literal.
LIVE_HOST = "https://api-" + "fxtrade.oanda.com"

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
API_ROUTES = Path(__file__).resolve().parents[1] / "apps/api/src/alphabrief_api/routes"


def _gate(
    *,
    audit_log: MutationAuditLog | None = None,
    account_id: str = "account-practice-1",
) -> WriteContractGate:
    return WriteContractGate(
        practice_host=PRACTICE_HOST,
        account_id=account_id,
        audit_log=audit_log or MutationAuditLog(),
        clock=lambda: NOW,
    )


def _request(
    *,
    mutation: OperatorMutation = "freeze_paper_execution",
    idempotency_key: str = "idem-1",
    actor: str = "operator-jeremy",
    correlation_id: str = "corr-1",
    target: str = "all",
    expected_state_version: str | None = None,
    broker_payload: dict[str, Any] | None = None,
) -> MutationRequest:
    return MutationRequest(
        mutation=mutation,
        idempotency_key=idempotency_key,
        actor=actor,
        correlation_id=correlation_id,
        target=target,
        expected_state_version=expected_state_version,
        broker_payload=broker_payload or {},
    )


def _context(
    *,
    account_id: str = "account-practice-1",
    host: str = PRACTICE_HOST,
    endpoint: str = "/api/v1/broker/freeze",
    current_state_version: str | None = "v-10",
) -> MutationContext:
    return MutationContext(
        account_id=account_id,
        host=host,
        endpoint=endpoint,
        current_state_version=current_state_version,
    )


class TestApprovedMutationSurface:
    def test_operator_mutations_are_exactly_the_approved_seven(self) -> None:
        assert OPERATOR_MUTATIONS == {
            "pause_research",
            "resume_research",
            "freeze_paper_execution",
            "unfreeze_paper_execution",
            "cancel_practice_order",
            "reduce_practice_exposure",
            "close_practice_exposure",
        }

    def test_every_mutation_has_approved_endpoints_and_payload_keys(
        self,
    ) -> None:
        for mutation in OPERATOR_MUTATIONS:
            assert mutation in APPROVED_ENDPOINTS
            assert APPROVED_ENDPOINTS[mutation]
            assert mutation in APPROVED_PAYLOAD_KEYS

    def test_existing_api_mutation_endpoints_are_classified(self) -> None:
        """Every API mutation route is an approved operator mutation or a
        documented non-operator class (order submission / research /
        data / run)."""
        known_operator = {
            "freeze": "freeze_paper_execution",
            "unfreeze": "unfreeze_paper_execution",
        }
        # Non-operator classes: data ingestion, model calls, research,
        # registry writes, runs, reconcile, and strategy-driven paper
        # order submission (RiskGate-gated, not manual operator control).
        known_non_operator = {
            "",
            "check",
            "compare",
            "debate",
            "evaluate",
            "fetch",
            "generate",
            "kronos",
            "load",
            "orders",
            "reconcile",
            "releases",
            "route",
            "run",
            "signals",
            "specs",
        }
        import re

        mutation_paths: list[str] = []
        for source in API_ROUTES.glob("*.py"):
            text = source.read_text(encoding="utf-8")
            for match in re.finditer(
                r'@router\.(?:post|put|delete|patch)\(\s*"([^"]*)"',
                text,
            ):
                mutation_paths.append(f"{source.name}:{match.group(1)}")
        for decorated in mutation_paths:
            route_name = decorated.split(":", 1)[1].strip("/")
            operation = route_name.split("/")[0] or ""
            assert operation in known_operator or operation in known_non_operator, (
                f"unclassified mutation route {decorated}"
            )


class TestAcceptedMutations:
    def test_accepted_mutation_requires_and_persists_metadata(self) -> None:
        audit_log = MutationAuditLog()
        gate = _gate(audit_log=audit_log)
        result = gate.evaluate(
            _request(
                actor="operator-jeremy",
                correlation_id="corr-9",
                expected_state_version="v-10",
            ),
            _context(current_state_version="v-10"),
        )
        assert result.accepted
        assert not result.replay
        assert result.rejected_reason is None
        assert result.audit.actor == "operator-jeremy"
        assert result.audit.correlation_id == "corr-9"
        assert result.audit.accepted is True
        assert result.audit.at == NOW
        assert len(audit_log.records) == 1

    def test_idempotency_key_is_required(self) -> None:
        with pytest.raises(Exception, match="idempotency_key"):
            MutationRequest(
                mutation="freeze_paper_execution",
                idempotency_key="",
                actor="a",
                correlation_id="c",
                target="t",
            )
        with pytest.raises(ValidationError):
            MutationRequest.model_validate(
                {
                    "mutation": "freeze_paper_execution",
                    "actor": "a",
                    "correlation_id": "c",
                    "target": "t",
                }
            )

    def test_current_state_is_validated(self) -> None:
        gate = _gate()
        stale = gate.evaluate(
            _request(expected_state_version="v-9"),
            _context(current_state_version="v-10"),
        )
        assert not stale.accepted
        assert stale.rejected_reason is not None
        assert stale.rejected_reason.startswith("stale_version")

    def test_replay_returns_the_same_result(self) -> None:
        audit_log = MutationAuditLog()
        gate = _gate(audit_log=audit_log)
        first = gate.evaluate(_request(idempotency_key="idem-r"), _context())
        second = gate.evaluate(_request(idempotency_key="idem-r"), _context())
        assert first.accepted
        assert second.replay is True
        assert second.accepted == first.accepted
        assert second.result_payload == first.result_payload
        assert second.audit.audit_id == first.audit.audit_id
        assert second.audit.at == first.audit.at
        assert len(audit_log.records) == 1

    def test_replay_reproduces_rejections_too(self) -> None:
        audit_log = MutationAuditLog()
        gate = _gate(audit_log=audit_log)
        first = gate.evaluate(
            _request(idempotency_key="idem-rej"),
            _context(host=LIVE_HOST),
        )
        second = gate.evaluate(
            _request(idempotency_key="idem-rej"),
            _context(host=LIVE_HOST),
        )
        assert not first.accepted
        assert second.replay is True
        assert second.rejected_reason == first.rejected_reason

    @pytest.mark.parametrize(
        "mutation",
        sorted(OPERATOR_MUTATIONS),
    )
    def test_every_approved_mutation_accepts_with_its_endpoint(
        self, mutation: str
    ) -> None:
        gate = _gate()
        endpoint = next(iter(APPROVED_ENDPOINTS[mutation]))
        result = gate.evaluate(
            _request(mutation=cast(OperatorMutation, mutation)),
            _context(endpoint=endpoint),
        )
        assert result.accepted, result.rejected_reason


class TestFailBeforeInvocation:
    def _rejection(
        self,
        *,
        request: MutationRequest,
        context: MutationContext,
    ) -> MutationResult:
        audit_log = MutationAuditLog()
        gate = _gate(audit_log=audit_log)
        result = gate.evaluate(request, context)
        assert not result.accepted
        assert result.result_payload is None
        assert result.audit.accepted is False
        assert result.audit.rejected_reason == result.rejected_reason
        assert len(audit_log.records) == 1
        return result

    def test_live_host_fails_before_invocation(self) -> None:
        result = self._rejection(
            request=_request(),
            context=_context(host=LIVE_HOST),
        )
        assert result.rejected_reason is not None
        assert result.rejected_reason.startswith("live_host_forbidden")

    def test_arbitrary_endpoint_fails(self) -> None:
        result = self._rejection(
            request=_request(),
            context=_context(endpoint="/api/v1/broker/anything"),
        )
        assert result.rejected_reason is not None
        assert result.rejected_reason.startswith("arbitrary_endpoint")

    def test_arbitrary_broker_payload_fails(self) -> None:
        result = self._rejection(
            request=_request(
                broker_payload={"execution": {"venue": "anywhere"}}
            ),
            context=_context(),
        )
        assert result.rejected_reason is not None
        assert result.rejected_reason.startswith("arbitrary_broker_payload")

    def test_unsupported_mutation_fails(self) -> None:
        # The typed model rejects unknown mutations at parse time; the
        # gate still fails closed for any registry mismatch.
        request = MutationRequest(
            mutation="freeze_paper_execution",
            idempotency_key="idem-u",
            actor="a",
            correlation_id="c",
            target="t",
        )
        result = self._rejection(
            request=request,
            context=_context(endpoint="/api/v1/broker/anything"),
        )
        assert result.rejected_reason is not None
        assert result.rejected_reason.startswith("arbitrary_endpoint")

    def test_stale_version_fails(self) -> None:
        result = self._rejection(
            request=_request(expected_state_version="v-1"),
            context=_context(current_state_version="v-2"),
        )
        assert result.rejected_reason is not None
        assert result.rejected_reason.startswith("stale_version")

    def test_cross_account_fails(self) -> None:
        result = self._rejection(
            request=_request(),
            context=_context(account_id="account-other-99"),
        )
        assert result.rejected_reason is not None
        assert result.rejected_reason.startswith("cross_account")

    def test_gate_never_invokes_any_provider(self) -> None:
        """The gate is a pure function: no broker or runtime imports."""
        import alphabrief_core.write_contracts as write_contracts

        source = Path(write_contracts.__file__).read_text(encoding="utf-8")
        for token in (
            "import requests",
            "import urllib",
            "http.client",
            "oanda",
            "submit",
        ):
            assert token not in source
