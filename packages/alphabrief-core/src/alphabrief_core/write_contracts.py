"""Safe and idempotent operator write contracts (M13-W02).

Operator mutations are limited to the REQ-UI-010 set — pause/resume
research, freeze/unfreeze paper execution, cancel practice order, and
reduce/close practice exposure. Every accepted mutation validates
current state, requires an idempotency key, persists actor and
correlation metadata, and returns the same result on replay. Live
hosts, arbitrary endpoints, arbitrary broker payloads, unsupported
mutations, stale versions, and cross-account requests fail *before*
any provider invocation and leave an audit rejection. There is no
generic broker or arbitrary runtime request surface (REQ-UI-002,
REQ-UI-010, REQ-PLAT-009).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

OperatorMutation = Literal[
    "pause_research",
    "resume_research",
    "freeze_paper_execution",
    "unfreeze_paper_execution",
    "cancel_practice_order",
    "reduce_practice_exposure",
    "close_practice_exposure",
]

#: The complete, closed set of operator mutations (REQ-UI-010).
OPERATOR_MUTATIONS: frozenset[str] = frozenset(
    {
        "pause_research",
        "resume_research",
        "freeze_paper_execution",
        "unfreeze_paper_execution",
        "cancel_practice_order",
        "reduce_practice_exposure",
        "close_practice_exposure",
    }
)

#: The only endpoints each mutation may target.
APPROVED_ENDPOINTS: dict[str, frozenset[str]] = {
    "pause_research": frozenset({"/api/v1/controls/research-mode"}),
    "resume_research": frozenset({"/api/v1/controls/research-mode"}),
    "freeze_paper_execution": frozenset({"/api/v1/broker/freeze"}),
    "unfreeze_paper_execution": frozenset({"/api/v1/broker/unfreeze"}),
    "cancel_practice_order": frozenset(
        {"/api/v1/paper/orders/{order_id}/cancel"}
    ),
    "reduce_practice_exposure": frozenset(
        {"/api/v1/paper/positions/{symbol}/reduce"}
    ),
    "close_practice_exposure": frozenset(
        {"/api/v1/paper/positions/{symbol}/close"}
    ),
}

#: The only broker-payload keys each mutation may carry. Anything else
#: is an arbitrary broker payload and is rejected before invocation.
APPROVED_PAYLOAD_KEYS: dict[str, frozenset[str]] = {
    "pause_research": frozenset({"mode"}),
    "resume_research": frozenset({"mode"}),
    "freeze_paper_execution": frozenset({"reason"}),
    "unfreeze_paper_execution": frozenset({"freeze_id"}),
    "cancel_practice_order": frozenset({"order_id"}),
    "reduce_practice_exposure": frozenset({"symbol", "units"}),
    "close_practice_exposure": frozenset({"symbol"}),
}


class MutationRequest(BaseModel):
    """One operator mutation request with full audit metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mutation: OperatorMutation
    idempotency_key: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    expected_state_version: str | None = None
    broker_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("idempotency_key", "actor", "correlation_id", "target")
    @classmethod
    def strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("mutation strings must not be blank")
        return value


class MutationContext(BaseModel):
    """The environment a mutation would run against (fail-closed)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    host: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    current_state_version: str | None = None


class MutationAudit(BaseModel):
    """One immutable audit record for an accepted or rejected mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: str = Field(min_length=1)
    mutation: OperatorMutation
    idempotency_key: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    accepted: bool
    rejected_reason: str | None = None
    result_payload: dict[str, Any] | None = None
    at: datetime

    @field_validator("at")
    @classmethod
    def at_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit timestamps must be timezone-aware")
        return value


class MutationResult(BaseModel):
    """One deterministic mutation outcome (accepted, rejected, or replay)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mutation: OperatorMutation
    idempotency_key: str = Field(min_length=1)
    accepted: bool
    replay: bool = False
    result_payload: dict[str, Any] | None = None
    rejected_reason: str | None = None
    audit: MutationAudit


class MutationAuditLog:
    """Append-only audit log with deterministic replay lookup."""

    def __init__(self) -> None:
        self._by_key: dict[str, MutationAudit] = {}

    def lookup(self, idempotency_key: str) -> MutationAudit | None:
        return self._by_key.get(idempotency_key)

    def append(self, audit: MutationAudit) -> None:
        self._by_key[audit.idempotency_key] = audit

    @property
    def records(self) -> tuple[MutationAudit, ...]:
        return tuple(sorted(self._by_key.values(), key=lambda a: a.at))


class WriteContractGate:
    """Deterministic fail-before-invocation gate for operator mutations.

    Rejections happen before any provider invocation: the gate is a
    pure function over the request, the context, and the audit log, and
    never touches a broker or runtime provider.
    """

    def __init__(
        self,
        *,
        practice_host: str,
        account_id: str,
        audit_log: MutationAuditLog,
        clock: Any | None = None,
    ) -> None:
        if not practice_host.startswith("https://"):
            raise ValueError("practice_host must be an https URL")
        self._practice_host = practice_host
        self._account_id = account_id
        self._audit_log = audit_log
        self._clock = clock or (lambda: datetime.now(UTC))

    def evaluate(
        self,
        request: MutationRequest,
        context: MutationContext,
    ) -> MutationResult:
        """Validate, audit, and (on replay) reproduce one mutation."""
        prior = self._audit_log.lookup(request.idempotency_key)
        if prior is not None:
            return MutationResult(
                mutation=request.mutation,
                idempotency_key=request.idempotency_key,
                accepted=prior.accepted,
                replay=True,
                result_payload=prior.result_payload,
                rejected_reason=prior.rejected_reason,
                audit=prior,
            )

        rejection = self._rejection_reason(request, context)
        if rejection is not None:
            return self._record(
                request, accepted=False, rejected_reason=rejection
            )

        return self._record(
            request,
            accepted=True,
            result_payload={
                "accepted": True,
                "mutation": request.mutation,
                "target": request.target,
            },
        )

    def _rejection_reason(
        self, request: MutationRequest, context: MutationContext
    ) -> str | None:
        if request.mutation not in OPERATOR_MUTATIONS:
            return f"unsupported_mutation: {request.mutation!r}"
        if context.host != self._practice_host:
            return (
                "live_host_forbidden: host must be the practice host, "
                f"got {context.host!r}"
            )
        if context.account_id != self._account_id:
            return (
                "cross_account: "
                f"account {context.account_id!r} is not the gate account"
            )
        if context.endpoint not in APPROVED_ENDPOINTS[request.mutation]:
            return (
                "arbitrary_endpoint: "
                f"{context.endpoint!r} is not approved for "
                f"{request.mutation}"
            )
        payload_keys = set(request.broker_payload)
        approved = APPROVED_PAYLOAD_KEYS[request.mutation]
        if not payload_keys.issubset(approved):
            unexpected = sorted(payload_keys - approved)
            return (
                "arbitrary_broker_payload: unexpected keys "
                f"{unexpected!r} for {request.mutation}"
            )
        if (
            request.expected_state_version is not None
            and context.current_state_version is not None
            and request.expected_state_version != context.current_state_version
        ):
            return (
                "stale_version: expected "
                f"{request.expected_state_version!r} but current is "
                f"{context.current_state_version!r}"
            )
        return None

    def _record(
        self,
        request: MutationRequest,
        *,
        accepted: bool,
        rejected_reason: str | None = None,
        result_payload: dict[str, Any] | None = None,
    ) -> MutationResult:
        audit = MutationAudit(
            audit_id=(
                f"audit-{request.mutation}-{request.idempotency_key}"
            ),
            mutation=request.mutation,
            idempotency_key=request.idempotency_key,
            actor=request.actor,
            correlation_id=request.correlation_id,
            target=request.target,
            accepted=accepted,
            rejected_reason=rejected_reason,
            result_payload=result_payload,
            at=self._clock(),
        )
        self._audit_log.append(audit)
        return MutationResult(
            mutation=request.mutation,
            idempotency_key=request.idempotency_key,
            accepted=accepted,
            result_payload=result_payload,
            rejected_reason=rejected_reason,
            audit=audit,
        )


__all__ = [
    "APPROVED_ENDPOINTS",
    "APPROVED_PAYLOAD_KEYS",
    "OPERATOR_MUTATIONS",
    "MutationAudit",
    "MutationAuditLog",
    "MutationContext",
    "MutationRequest",
    "MutationResult",
    "OperatorMutation",
    "WriteContractGate",
]
