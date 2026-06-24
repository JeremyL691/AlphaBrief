"""RiskGate MVP for AlphaBrief paper trading."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alphabrief_core import OrderIntent, RiskDecision

from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.context import RiskContextDecision
from alphabrief_risk.kill_switch import KillSwitch


@dataclass(frozen=True)
class RiskLimitConfig:
    """Static risk limits used by the MVP RiskGate."""

    trading_enabled: bool = True
    live_trading_enabled: bool = False
    # None preserves legacy "not configured" behavior. An explicit empty set
    # is a deny-all strategy boundary, never an implicit allow-all.
    enabled_strategies: frozenset[str] | None = None
    symbol_allowlist: frozenset[str] = frozenset()
    max_order_quantity: Decimal | None = None
    max_order_value: Decimal | None = None
    # Account-level total-exposure cap. ``None`` preserves the legacy
    # per-order-only behavior (no runtime account-exposure check). When
    # set, ``RiskGate`` enforces it against an
    # :class:`AccountExposureContext` supplied at evaluation time.
    max_total_exposure: Decimal | None = None
    require_data_quality_passed: bool = True
    require_human_review: bool = False

    def __post_init__(self) -> None:
        if self.max_order_quantity is not None and self.max_order_quantity <= 0:
            raise ValueError("max_order_quantity must be positive")
        if self.max_order_value is not None and self.max_order_value <= 0:
            raise ValueError("max_order_value must be positive")
        if self.max_total_exposure is not None and self.max_total_exposure <= 0:
            raise ValueError("max_total_exposure must be positive")
        if (
            self.max_total_exposure is not None
            and self.max_order_value is not None
            and self.max_total_exposure < self.max_order_value
        ):
            raise ValueError("max_total_exposure must be at least max_order_value")


@dataclass
class RiskGate:
    """Approve or reject OrderIntent objects before paper execution."""

    limits: RiskLimitConfig
    kill_switch: KillSwitch = field(default_factory=KillSwitch)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    decision_id_factory: Callable[[], str] = field(
        default=lambda: f"risk_{uuid4().hex}"
    )

    def evaluate(
        self,
        intent: OrderIntent,
        *,
        strategy_id: str | None = None,
        estimated_price: Decimal | None = None,
        estimated_quantity: Decimal | None = None,
        data_quality_passed: bool = True,
        risk_context: RiskContextDecision | None = None,
        account_context: AccountExposureContext | None = None,
    ) -> RiskDecision:
        """Return a complete RiskDecision for an order intent.

        If ``risk_context`` is provided, it is applied in a
        **tighten-only** manner: it can never re-approve a decision
        that the base checks already rejected, it can never relax the
        human-review flag, and it can never increase ``max_quantity``
        above the configured limit.

        If ``account_context`` is provided and
        ``limits.max_total_exposure`` is configured, an account-level
        total-exposure check is applied in the same **tighten-only**
        spirit: a buy that would push gross account exposure above the
        cap is rejected, and ``max_quantity`` is clamped down to the
        largest size that lands exactly on the cap. The check is
        **fail-closed** — when ``max_total_exposure`` is configured but
        ``account_context`` is ``None``, the intent is rejected with
        the ``account_context_required`` tag rather than silently
        skipped. It can never re-approve a rejected intent, never
        relaxes the human-review flag, and never increases
        ``max_quantity``.

        Specifically, when ``risk_context`` is set the layer may:

        * merge ``risk_context.risk_tags`` into the decision tags
          (deduplicated, original order preserved);
        * flip the final ``requires_human_review`` flag on when
          ``risk_context.requires_human_review`` is ``True`` (the
          static ``RiskLimitConfig.require_human_review`` flag is
          honored as well, so the merge is effectively an OR);
        * reduce ``max_quantity`` by
          ``risk_context.suggested_max_position_multiplier`` when that
          multiplier is strictly below ``1.0`` and the configured
          ``max_order_quantity`` is set (Decimal-first, no rounding,
          never relaxed).

        The risk context **cannot** override the kill switch, lift
        the live-trading lock, add symbols to the allowlist, or
        re-approve a rejected intent.
        """

        failures: list[str] = []
        tags: list[str] = []

        if self.kill_switch.active:
            failures.append(self.kill_switch.reason)
            tags.append("kill_switch")

        if not self.limits.trading_enabled:
            failures.append("trading disabled")
            tags.append("trading_disabled")

        if self.limits.live_trading_enabled:
            failures.append("live trading is not allowed in MVP")
            tags.append("live_trading_locked")

        if self.limits.require_data_quality_passed and not data_quality_passed:
            failures.append("data quality check failed")
            tags.append("data_quality")

        if (
            self.limits.symbol_allowlist
            and intent.symbol not in self.limits.symbol_allowlist
        ):
            failures.append(f"symbol {intent.symbol} is not allowed")
            tags.append("symbol_not_allowed")

        if (
            strategy_id is not None
            and self.limits.enabled_strategies is not None
            and strategy_id not in self.limits.enabled_strategies
        ):
            failures.append(f"strategy {strategy_id} is not enabled")
            tags.append("strategy_disabled")

        if intent.quantity is not None:
            self._check_quantity_limit(intent.quantity, failures, tags)
            self._check_order_value_limit(
                quantity=intent.quantity,
                estimated_price=estimated_price,
                failures=failures,
                tags=tags,
            )
        elif intent.target_position_pct is not None:
            self._check_target_pct_limits(
                estimated_quantity=estimated_quantity,
                estimated_price=estimated_price,
                failures=failures,
                tags=tags,
            )

        # Account-level total-exposure check (tighten-only / fail-closed).
        # Returns the largest buyable quantity that lands exactly on the
        # cap, or None when no clamp applies.
        account_qty_clamp = self._check_account_exposure(
            intent=intent,
            estimated_price=estimated_price,
            account_context=account_context,
            failures=failures,
            tags=tags,
        )

        approved = not failures
        if approved:
            tags.append("approved")

        max_quantity = self.limits.max_order_quantity
        requires_human_review = self.limits.require_human_review

        if risk_context is not None:
            for tag in risk_context.risk_tags:
                if tag not in tags:
                    tags.append(tag)
            if risk_context.requires_human_review:
                requires_human_review = True
            if (
                0.0 < risk_context.suggested_max_position_multiplier < 1.0
                and max_quantity is not None
            ):
                multiplier = Decimal(
                    str(risk_context.suggested_max_position_multiplier)
                )
                reduced = max_quantity * multiplier
                if reduced < max_quantity:
                    max_quantity = reduced

        # Fold the account-exposure clamp into max_quantity. The clamp is
        # tighten-only: it can only reduce an existing max_quantity, never
        # create one where the per-order limit is unset, and never increase
        # it. It composes with the risk_context multiplier by taking the
        # smaller of the two (the stricter bound wins).
        if (
            account_qty_clamp is not None
            and max_quantity is not None
            and account_qty_clamp < max_quantity
        ):
            max_quantity = account_qty_clamp

        return RiskDecision(
            decision_id=self.decision_id_factory(),
            intent_id=intent.intent_id,
            approved=approved,
            reason="approved" if approved else "; ".join(failures),
            max_quantity=max_quantity,
            risk_tags=tags,
            requires_human_review=requires_human_review,
            source_module="alphabrief_risk",
            created_at=self.clock(),
        )

    def _check_target_pct_limits(
        self,
        *,
        estimated_quantity: Decimal | None,
        estimated_price: Decimal | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        has_quantity_limit = self.limits.max_order_quantity is not None
        has_value_limit = self.limits.max_order_value is not None
        if not has_quantity_limit and not has_value_limit:
            return
        if estimated_quantity is None:
            failures.append(
                "estimated_quantity required for target_position_pct limits"
            )
            tags.append("missing_quantity_estimate")
            return
        self._check_quantity_limit(estimated_quantity, failures, tags)
        self._check_order_value_limit(
            quantity=estimated_quantity,
            estimated_price=estimated_price,
            failures=failures,
            tags=tags,
        )

    def _check_quantity_limit(
        self,
        quantity: Decimal,
        failures: list[str],
        tags: list[str],
    ) -> None:
        if (
            self.limits.max_order_quantity is not None
            and quantity > self.limits.max_order_quantity
        ):
            failures.append("order quantity exceeds max_order_quantity")
            tags.append("max_quantity")

    def _check_order_value_limit(
        self,
        *,
        quantity: Decimal,
        estimated_price: Decimal | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        if self.limits.max_order_value is None:
            return
        if estimated_price is None:
            failures.append("estimated_price is required for max_order_value")
            tags.append("missing_price")
            return
        if quantity * estimated_price > self.limits.max_order_value:
            failures.append("order value exceeds max_order_value")
            tags.append("max_order_value")

    def _check_account_exposure(
        self,
        *,
        intent: OrderIntent,
        estimated_price: Decimal | None,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> Decimal | None:
        """Enforce ``max_total_exposure`` against live account state.

        Returns the largest buyable quantity that lands exactly on the
        cap (so the caller can clamp ``max_quantity`` down), or ``None``
        when no clamp applies (cap unset, sell side, or no headroom).

        Tighten-only / fail-closed:

        * When ``max_total_exposure`` is unset, this is a no-op (legacy
          per-order-only behavior preserved).
        * When the cap is set but ``account_context`` is ``None``, the
          intent is rejected with the ``account_context_required`` tag.
          Skipping would defeat runtime enforcement.
        * Sells never increase gross exposure, so they bypass the
          new-exposure projection (they may still fail other checks).
          ponytail:sell-exposure-ceiling: we treat sells as never
          increasing gross exposure, which ignores a short-sale flip
          from a net-short position. Acceptable for the paper long-only
          policy (``us_equity``, allowlisted ETFs); upgrade path is to
          track signed exposure if shorts are ever admitted.
        * Buys project ``current_total_exposure + qty * price`` and
          reject with ``max_total_exposure`` when over the cap; the
          returned clamp is ``headroom / price``.
        * A buy with no ``estimated_price`` while the cap is set is
          rejected with ``missing_price`` (mirrors
          ``_check_order_value_limit``).
        """
        cap = self.limits.max_total_exposure
        if cap is None:
            return None

        if account_context is None:
            failures.append(
                "runtime account exposure check required but no account "
                "context supplied"
            )
            tags.append("account_context_required")
            return None

        # Sells reduce or close exposure; they do not add gross notional.
        if intent.side == "sell":
            return None

        if intent.quantity is None:
            # target_position_pct path: no discrete quantity to clamp.
            # We cannot project a new-notional without a quantity, so we
            # do not enforce the cap here. The per-order value check and
            # the human-review gate still apply.
            return None

        if estimated_price is None:
            failures.append("estimated_price is required for max_total_exposure")
            tags.append("missing_price")
            return None

        new_notional = intent.quantity * estimated_price
        projected = account_context.current_total_exposure + new_notional
        if projected <= cap:
            return None

        failures.append("order would breach max_total_exposure")
        tags.append("max_total_exposure")

        headroom = cap - account_context.current_total_exposure
        if headroom <= 0:
            return None
        # Largest buyable qty that lands on the cap. Decimal division
        # under the default context never raises here (price > 0 is
        # guaranteed to reach this point, and headroom > 0). The clamp
        # is advisory: a caller that resubmits at this size is
        # re-evaluated, so a last-digit rounding-up edge case simply
        # re-rejects rather than breaching the cap.
        return headroom / estimated_price
