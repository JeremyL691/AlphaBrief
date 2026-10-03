"""RiskGate MVP for AlphaBrief paper trading."""

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from alphabrief_core import OrderIntent, PaperExecutionPolicy, RiskDecision

from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.context import RiskContextDecision
from alphabrief_risk.entry_rules import (
    EntryRulePolicy,
    RuleRejection,
    evaluate_entry_rules,
    evaluate_quote_rules,
    rejection_codes,
)
from alphabrief_risk.kill_switch import KillSwitch
from alphabrief_risk.loss_state import daily_loss_breached


def _is_close_intent(intent: OrderIntent) -> bool:
    """An order that can only reduce exposure (PROJECT_GUIDE 5.7)."""
    return bool(intent.reduce_only or intent.target_position_pct == 0)


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
    require_home_currency_exposure: bool = False
    max_order_value_pct: Decimal | None = None
    max_total_exposure_pct: Decimal | None = None
    max_order_value: Decimal | None = None
    # Account-level total-exposure cap. ``None`` preserves the legacy
    # per-order-only behavior (no runtime account-exposure check). When
    # set, ``RiskGate`` enforces it against an
    # :class:`AccountExposureContext` supplied at evaluation time.
    max_total_exposure: Decimal | None = None
    require_data_quality_passed: bool = True
    require_human_review: bool = False
    # --- Account-level rules (R21.2, all tighten-only / fail-closed) ---
    # Per-symbol gross exposure cap. When set, a buy that would push a
    # single symbol's gross notional above the cap is rejected and
    # ``max_quantity`` is clamped to the headroom. Requires
    # ``account_context`` (fail-closed).
    max_symbol_exposure: Decimal | None = None
    # Max fraction of total exposure concentrated in one symbol, 0..1.
    # ``None`` preserves legacy behavior. A no-op while the portfolio is
    # single-symbol (concentration is always 1.0); binds once the
    # allowlist grows. Requires ``account_context``.
    max_concentration_pct: Decimal | None = None
    # Max gross exposure / equity. Requires ``account_context.equity``
    # (fail-closed ``missing_equity``). Long-only paper policy defaults
    # to 1.0 (no margin).
    max_leverage: Decimal | None = None
    # Max |estimated_price - mark| / mark, 0..1. Requires a reference
    # mark in ``account_context.reference_mark_prices`` for the order
    # symbol (fail-closed ``missing_mark_price``).
    max_price_deviation_pct: Decimal | None = None
    # Max age of an order's signal: ``(clock - intent.created_at)`` in
    # seconds. Rejects stale signals.
    max_signal_age_seconds: int | None = None
    # When True, reject orders outside the policy trading session. Reads
    # ``session_policy`` (fail-closed ``market_closed`` if no policy is
    # wired). ponytail: no holiday calendar — upgrade path is a
    # market-calendar provider.
    require_market_open: bool = False
    # Entry rules from PROJECT_GUIDE 5.7 that the base checks do not cover
    # (quote freshness/tradeability, daily caps, max positions, losing
    # streak, weekend, protective orders). ``None`` leaves them disabled so
    # existing callers keep their behavior; the production policy sets one.
    entry_rules: EntryRulePolicy | None = None
    # The session policy used by the market-state check. Optional; when
    # ``require_market_open`` is True and this is None the gate fails
    # closed.
    session_policy: PaperExecutionPolicy | None = None
    # Duplicate-order detection: reject when ``>= max_count`` identical
    # (symbol, side, quantity) intents arrive within the window.
    # ponytail:duplicate_order_state: in-memory deque, not persistent —
    # a restart loses dedup memory. Acceptable for paper; upgrade path
    # is a persistent recent-intent store.
    duplicate_order_window_seconds: int | None = None
    duplicate_order_max_count: int = 1
    # --- Stateful account rules (R21.3, tighten-only / fail-closed) ---
    # Rule 10: today's realized + current unrealized loss must stay below
    # this fraction of current NAV. Requires fresh broker evidence and a
    # durable UTC-day block; both long and short entries are checked.
    max_daily_loss_pct: Decimal | None = None
    max_margin_utilization_pct: Decimal | None = None
    margin_warning_pct: Decimal | None = None
    # Reject new buys when the drawdown from the equity high-water mark
    # exceeds this fraction of the HWM, 0..1. Requires
    # ``account_context.equity_high_water_mark`` (fail-closed
    # ``missing_equity_hwm``). The HWM must be supplied by the caller from
    # a persistent snapshot store so a restart cannot widen the floor.
    max_drawdown_floor_pct: Decimal | None = None

    def __post_init__(self) -> None:
        for value in (self.max_order_value_pct, self.max_total_exposure_pct):
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite() or value <= 0
            ):
                raise ValueError("exposure fractions must be finite positive Decimals")
        if (
            self.max_order_value_pct is not None
            and self.max_total_exposure_pct is not None
            and self.max_order_value_pct > self.max_total_exposure_pct
        ):
            raise ValueError("total exposure fraction must cover order fraction")
        for value in (self.max_margin_utilization_pct, self.margin_warning_pct):
            if value is not None and (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or not Decimal(0) < value <= Decimal(1)
            ):
                raise ValueError("margin limits must be finite Decimal fractions")
        if self.margin_warning_pct is not None and (
            self.max_margin_utilization_pct is None
            or self.margin_warning_pct >= self.max_margin_utilization_pct
        ):
            raise ValueError("margin warning must be below the configured ceiling")
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
        if self.max_symbol_exposure is not None and self.max_symbol_exposure <= 0:
            raise ValueError("max_symbol_exposure must be positive")
        if self.max_concentration_pct is not None and not (
            Decimal("0") < self.max_concentration_pct <= Decimal("1")
        ):
            raise ValueError("max_concentration_pct must be in (0, 1]")
        if self.max_leverage is not None and self.max_leverage <= 0:
            raise ValueError("max_leverage must be positive")
        if self.max_price_deviation_pct is not None and not (
            Decimal("0") <= self.max_price_deviation_pct <= Decimal("1")
        ):
            raise ValueError("max_price_deviation_pct must be in [0, 1]")
        if self.max_signal_age_seconds is not None and self.max_signal_age_seconds <= 0:
            raise ValueError("max_signal_age_seconds must be positive")
        if self.duplicate_order_window_seconds is not None:
            if self.duplicate_order_window_seconds <= 0:
                raise ValueError("duplicate_order_window_seconds must be positive")
            if self.duplicate_order_max_count < 1:
                raise ValueError("duplicate_order_max_count must be >= 1")
        if self.max_daily_loss_pct is not None and (
            not isinstance(self.max_daily_loss_pct, Decimal)
            or not self.max_daily_loss_pct.is_finite()
            or not Decimal(0) < self.max_daily_loss_pct <= Decimal(1)
        ):
            raise ValueError("max_daily_loss_pct must be a finite Decimal in (0, 1]")
        if self.max_drawdown_floor_pct is not None and not (
            Decimal("0") <= self.max_drawdown_floor_pct <= Decimal("1")
        ):
            raise ValueError("max_drawdown_floor_pct must be in [0, 1]")


@dataclass
class RiskGate:
    """Approve or reject OrderIntent objects before paper execution."""

    limits: RiskLimitConfig
    kill_switch: KillSwitch = field(default_factory=KillSwitch)
    kill_switch_provider: Callable[[], KillSwitch] | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    decision_id_factory: Callable[[], str] = field(
        default=lambda: f"risk_{uuid4().hex}"
    )
    # In-memory dedup window for the duplicate-order check. Lives on the
    # mutable gate instance; not persistent across restarts.
    # ponytail:duplicate_order_state: see RiskLimitConfig docstring.
    _recent_intents: deque[tuple[str, str, Decimal, datetime]] = field(
        default_factory=deque
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
        spirit: an entry that would push gross account exposure above the
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

        if self.kill_switch_provider is not None:
            try:
                self.kill_switch = self.kill_switch_provider()
            except Exception:  # noqa: BLE001 - unreadable authority fails closed
                failures.append("kill switch state unavailable")
                tags.append("kill_switch_unavailable")
        if self.kill_switch.active and not intent.reduce_only:
            failures.append(self.kill_switch.reason)
            tags.append("kill_switch")
        elif self.kill_switch.active:
            tags.append("kill_switch_reduce_only")

        if self.limits.live_trading_enabled:
            failures.append("live trading is not allowed in MVP")
            tags.append("live_trading_locked")

        if _is_close_intent(intent):
            # Explicit REDUCE_ONLY exits remain available under the emergency
            # stop, but still require a fresh, tradeable quote (rule 3).
            # Trading off, a freeze, the daily caps or the weekend window
            # never prevent a position from being closed, and no exposure or
            # order-value limit can block a reduction.
            self._check_close_quote_rules(
                intent=intent,
                account_context=account_context,
                failures=failures,
                tags=tags,
            )
            return self._finalize(intent, failures, tags, risk_context, ())

        if not self.limits.trading_enabled:
            failures.append("trading disabled")
            tags.append("trading_disabled")

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

        order_cap, total_cap, cap_evidence = self._exposure_caps(
            account_context,
            failures,
            tags,
        )
        home_price, exposure_evidence = self._home_exposure_price(
            intent,
            estimated_price,
            account_context,
            failures,
            tags,
        )
        if exposure_evidence:
            exposure_evidence["exposure"]["order_cap"] = str(order_cap)
            exposure_evidence["exposure"]["total_cap"] = str(total_cap)
            exposure_evidence["exposure"]["pending_gross"] = str(
                None
                if account_context is None
                else sum(
                    account_context.pending_exposure_by_symbol.values(), Decimal(0)
                )
            )
        if intent.quantity is not None:
            self._check_quantity_limit(intent.quantity, failures, tags)
            self._check_order_value_limit(
                quantity=intent.quantity,
                estimated_price=home_price,
                failures=failures,
                tags=tags,
                cap=order_cap,
            )
        elif intent.target_position_pct is not None:
            self._check_target_pct_limits(
                estimated_quantity=estimated_quantity,
                estimated_price=home_price,
                failures=failures,
                tags=tags,
                cap=order_cap,
            )

        # Account-level total-exposure check (tighten-only / fail-closed).
        # Returns the largest entry quantity that lands exactly on the
        # cap, or None when no clamp applies.
        account_qty_clamp = self._check_account_exposure(
            intent=intent,
            estimated_price=home_price,
            account_context=account_context,
            failures=failures,
            tags=tags,
            cap=total_cap,
        )

        # R21.2 account-level rules (all tighten-only / fail-closed). The
        # per-symbol exposure check returns a clamp like the total-exposure
        # check; the rest append failures/tags only.
        symbol_qty_clamp = self._check_symbol_exposure(
            intent=intent,
            estimated_price=home_price,
            account_context=account_context,
            failures=failures,
            tags=tags,
        )
        self._check_concentration(
            intent=intent,
            estimated_price=home_price,
            account_context=account_context,
            failures=failures,
            tags=tags,
        )
        self._check_leverage(
            intent=intent,
            estimated_price=home_price,
            account_context=account_context,
            failures=failures,
            tags=tags,
        )
        self._check_price_deviation(
            intent=intent,
            estimated_price=estimated_price,
            account_context=account_context,
            failures=failures,
            tags=tags,
        )
        self._check_market_open(
            intent=intent,
            failures=failures,
            tags=tags,
        )
        self._check_signal_age(
            intent=intent,
            failures=failures,
            tags=tags,
        )
        self._check_duplicate_order(
            intent=intent,
            failures=failures,
            tags=tags,
        )
        margin_evidence = self._check_margin(
            account_context=account_context,
            failures=failures,
            tags=tags,
        )
        daily_loss_evidence = self._check_daily_loss(
            intent=intent,
            estimated_price=estimated_price,
            account_context=account_context,
            failures=failures,
            tags=tags,
        )
        self._check_drawdown(
            intent=intent,
            estimated_price=estimated_price,
            account_context=account_context,
            failures=failures,
            tags=tags,
        )
        self._check_entry_rules(
            intent=intent,
            account_context=account_context,
            failures=failures,
            tags=tags,
        )

        streak_evidence: dict[str, dict[str, str]] = {}
        if self.limits.entry_rules and self.limits.entry_rules.require_loss_streak:
            context = account_context
            streak_evidence["loss_streak"] = {
                **(
                    {}
                    if context is None
                    else context.loss_streak_evidence.get(intent.symbol, {})
                ),
                "last_transaction_id": str(
                    None if context is None else context.loss_streak_last_transaction_id
                ),
                "complete": str(
                    context is not None and context.loss_streak_complete
                ).lower(),
                "observed_at": str(
                    None if context is None else context.loss_streak_captured_at
                ),
                "error": "missing_context"
                if context is None
                else context.loss_streak_error or "",
            }
        return self._finalize(
            intent,
            failures,
            tags,
            risk_context,
            (account_qty_clamp, symbol_qty_clamp),
            {
                **margin_evidence,
                **exposure_evidence,
                **cap_evidence,
                **daily_loss_evidence,
                **streak_evidence,
            },
        )

    def _finalize(
        self,
        intent: OrderIntent,
        failures: list[str],
        tags: list[str],
        risk_context: RiskContextDecision | None,
        clamps: tuple[Decimal | None, ...],
        rule_evidence: dict[str, dict[str, str]] | None = None,
    ) -> RiskDecision:
        """Build the RiskDecision from the collected failures and tags."""
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

        # Fold the tighten-only clamps into max_quantity. Each clamp can
        # only reduce an existing max_quantity, never create one where the
        # per-order limit is unset, and never increase it. The stricter
        # (smaller) bound wins across all clamps and the risk_context
        # multiplier.
        for clamp in clamps:
            if clamp is not None and max_quantity is not None and clamp < max_quantity:
                max_quantity = clamp

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
            rule_evidence=rule_evidence or {},
        )

    def _check_margin(
        self,
        *,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> dict[str, dict[str, str]]:
        from alphabrief_risk.margin_loss_rules import evaluate_margin_utilization

        ceiling = self.limits.max_margin_utilization_pct
        if ceiling is None:
            return {}
        context = account_context
        result = evaluate_margin_utilization(
            nav=None if context is None else context.equity,
            margin_used=None if context is None else context.margin_used,
            ceiling=ceiling,
        )
        age = (
            None
            if context is None
            else (self.clock() - context.captured_at).total_seconds()
        )
        fresh = age is not None and 0 <= age <= 60
        passed = result.passed and fresh
        evidence = {
            "nav": "missing" if context is None else str(context.equity),
            "margin_used": "missing" if context is None else str(context.margin_used),
            "captured_at": (
                "missing" if context is None else context.captured_at.isoformat()
            ),
            "utilization": result.value,
            "ceiling": str(ceiling),
            "fresh": str(fresh),
            "passed": str(passed),
        }
        if not passed:
            failures.append(f"MARGIN: {result.detail}; fresh={fresh}")
            tags.append("MARGIN")
        warning = self.limits.margin_warning_pct
        if warning is not None and result.value != "unknown" and fresh:
            warned = Decimal(result.value) > warning
            evidence.update(warning_threshold=str(warning), warning=str(warned))
            if warned:
                tags.append("MARGIN_WARNING")
        return {"margin": evidence}

    def _check_target_pct_limits(
        self,
        *,
        estimated_quantity: Decimal | None,
        estimated_price: Decimal | None,
        failures: list[str],
        tags: list[str],
        cap: Decimal | None = None,
    ) -> None:
        has_quantity_limit = self.limits.max_order_quantity is not None
        has_value_limit = cap is not None or self.limits.max_order_value is not None
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
            cap=cap,
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

    def _exposure_caps(
        self,
        context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> tuple[Decimal | None, Decimal | None, dict[str, dict[str, str]]]:
        order, total = self.limits.max_order_value, self.limits.max_total_exposure
        fractions = (
            self.limits.max_order_value_pct,
            self.limits.max_total_exposure_pct,
        )
        if all(value is None for value in fractions):
            return order, total, {}
        nav = None if context is None else context.equity
        fresh = (
            context is not None
            and 0 <= (self.clock() - context.captured_at).total_seconds() <= 60
        )
        valid = nav is not None and nav.is_finite() and nav > 0 and fresh
        if not valid:
            failures.append("fresh positive NAV required for exposure fractions")
            tags.append("EXPOSURE")
        else:
            assert nav is not None
            if fractions[0] is not None:
                ratio_cap = nav * fractions[0]
                order = ratio_cap if order is None else min(order, ratio_cap)
            if fractions[1] is not None:
                ratio_cap = nav * fractions[1]
                total = ratio_cap if total is None else min(total, ratio_cap)
        return (
            order,
            total,
            {
                "exposure_caps": {
                    "nav": str(nav),
                    "fresh": str(fresh),
                    "passed": str(valid),
                    "order_pct": str(fractions[0]),
                    "total_pct": str(fractions[1]),
                    "order_cap": str(order),
                    "total_cap": str(total),
                }
            },
        )

    def _home_exposure_price(
        self,
        intent: OrderIntent,
        price: Decimal | None,
        context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> tuple[Decimal | None, dict[str, dict[str, str]]]:
        """Resolve value conversion separately from raw quote-price comparisons."""
        if not self.limits.require_home_currency_exposure:
            return price, {}
        factor = (
            None
            if context is None
            else context.quote_position_to_home.get(intent.symbol)
        )
        fresh = (
            context is not None
            and 0 <= (self.clock() - context.captured_at).total_seconds() <= 60
        )
        complete = (
            context is not None
            and context.exposure_complete
            and not context.exposure_errors
        )
        valid_price = isinstance(price, Decimal) and price.is_finite() and price > 0
        if not fresh or not complete or factor is None or not valid_price:
            failures.append("complete fresh home-currency exposure evidence required")
            tags.append("EXPOSURE")
            home_price = None
        else:
            assert price is not None
            home_price = price * factor
        evidence = {
            "price": str(price),
            "position_value_factor": str(factor),
            "home_price": str(home_price),
            "fresh": str(fresh),
            "complete": str(complete),
            "current_gross": str(
                None if context is None else context.current_total_exposure
            ),
            "order_notional": str(
                None
                if home_price is None or intent.quantity is None
                else intent.quantity * home_price
            ),
            "order_cap": str(self.limits.max_order_value),
            "total_cap": str(self.limits.max_total_exposure),
            "captured_at": str(None if context is None else context.captured_at),
            "coverage_errors": str({} if context is None else context.exposure_errors),
            "projected_gross": str(
                None
                if context is None or home_price is None or intent.quantity is None
                else context.current_total_exposure + intent.quantity * home_price
            ),
        }
        return home_price, {"exposure": evidence}

    def _check_order_value_limit(
        self,
        *,
        quantity: Decimal,
        estimated_price: Decimal | None,
        failures: list[str],
        tags: list[str],
        cap: Decimal | None = None,
    ) -> None:
        cap = self.limits.max_order_value if cap is None else cap
        if cap is None:
            return
        if estimated_price is None:
            failures.append("estimated_price is required for max_order_value")
            tags.append("missing_price")
            return
        if quantity * estimated_price > cap:
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
        cap: Decimal | None = None,
    ) -> Decimal | None:
        """Both entry directions add gross home notional; reduce-only exits earlier."""
        cap = self.limits.max_total_exposure if cap is None else cap
        if cap is None:
            return None

        if account_context is None:
            failures.append(
                "runtime account exposure check required but no account "
                "context supplied"
            )
            tags.append("account_context_required")
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

    def _check_symbol_exposure(
        self,
        *,
        intent: OrderIntent,
        estimated_price: Decimal | None,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> Decimal | None:
        """Enforce ``max_symbol_exposure`` for the order's symbol.

        Tighten-only / fail-closed, mirroring ``_check_account_exposure``.
        Returns the largest entry qty that lands the symbol's projected
        notional exactly on the cap, or None when no clamp applies.
        """
        cap = self.limits.max_symbol_exposure
        if cap is None:
            return None
        if account_context is None:
            failures.append(
                "per-symbol exposure check required but no account context supplied"
            )
            tags.append("account_context_required")
            return None
        if intent.quantity is None:
            return None
        if estimated_price is None:
            failures.append("estimated_price is required for max_symbol_exposure")
            tags.append("missing_price")
            return None

        current = account_context.exposure_by_symbol.get(intent.symbol, Decimal("0"))
        new_notional = intent.quantity * estimated_price
        projected = current + new_notional
        if projected <= cap:
            return None

        failures.append(f"order would breach max_symbol_exposure for {intent.symbol}")
        tags.append("max_symbol_exposure")
        headroom = cap - current
        if headroom <= 0:
            return None
        return headroom / estimated_price

    def _check_concentration(
        self,
        *,
        intent: OrderIntent,
        estimated_price: Decimal | None,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        """Enforce ``max_concentration_pct`` (max fraction in one symbol)."""
        pct = self.limits.max_concentration_pct
        if pct is None:
            return
        if account_context is None:
            failures.append(
                "concentration check required but no account context supplied"
            )
            tags.append("account_context_required")
            return
        if intent.quantity is None:
            return

        # Project the post-order per-symbol and total notional.
        price = estimated_price
        if price is None:
            # Without a price we cannot project notional; fail closed.
            failures.append("estimated_price is required for max_concentration_pct")
            tags.append("missing_price")
            return
        current_symbol = account_context.exposure_by_symbol.get(
            intent.symbol, Decimal("0")
        )
        projected_symbol = current_symbol + intent.quantity * price
        projected_total = (
            account_context.current_total_exposure + intent.quantity * price
        )
        if projected_total <= 0:
            return
        concentration = projected_symbol / projected_total
        if concentration > pct:
            failures.append(
                f"order would concentrate {intent.symbol} above max_concentration_pct"
            )
            tags.append("max_concentration")

    def _check_leverage(
        self,
        *,
        intent: OrderIntent,
        estimated_price: Decimal | None,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        """Enforce ``max_leverage`` (projected gross exposure / equity)."""
        lev = self.limits.max_leverage
        if lev is None:
            return
        if account_context is None:
            failures.append("leverage check required but no account context supplied")
            tags.append("account_context_required")
            return
        if account_context.equity is None:
            failures.append("max_leverage configured but account equity missing")
            tags.append("missing_equity")
            return
        if account_context.equity <= 0:
            failures.append("account equity must be positive for leverage check")
            tags.append("missing_equity")
            return
        if intent.quantity is None:
            return
        if estimated_price is None:
            failures.append("estimated_price is required for max_leverage")
            tags.append("missing_price")
            return

        new_notional = intent.quantity * estimated_price
        projected_gross = account_context.current_total_exposure + new_notional
        if projected_gross / account_context.equity > lev:
            failures.append("order would breach max_leverage")
            tags.append("max_leverage")

    def _check_price_deviation(
        self,
        *,
        intent: OrderIntent,
        estimated_price: Decimal | None,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        """Reject when ``estimated_price`` deviates from the mark beyond pct."""
        pct = self.limits.max_price_deviation_pct
        if pct is None:
            return
        if estimated_price is None:
            failures.append("estimated_price is required for max_price_deviation_pct")
            tags.append("missing_price")
            return
        if account_context is None:
            failures.append(
                "price-deviation check required but no account context supplied"
            )
            tags.append("account_context_required")
            return
        mark = account_context.reference_mark_prices.get(intent.symbol)
        if mark is None or mark <= 0:
            failures.append(
                f"no reference mark price for {intent.symbol}; cannot verify "
                "price deviation"
            )
            tags.append("missing_mark_price")
            return
        deviation = abs(estimated_price - mark) / mark
        if deviation > pct:
            failures.append("estimated price deviates from mark beyond limit")
            tags.append("price_deviation")

    def _check_market_open(
        self,
        *,
        intent: OrderIntent,
        failures: list[str],
        tags: list[str],
    ) -> None:
        """Reject orders outside the policy trading session."""
        if not self.limits.require_market_open:
            return
        policy = self.limits.session_policy
        if policy is None:
            # Fail closed: cannot verify the session without a policy.
            failures.append("market-open check required but no session policy wired")
            tags.append("market_closed")
            return

        now = self.clock()
        local = now.astimezone(ZoneInfo(policy.timezone))
        day = local.strftime("%a").lower()  # mon..sun
        if day not in {d for d in policy.trading_days}:
            failures.append("market is closed (non-trading day)")
            tags.append("market_closed")
            return
        # session_start/end are "HH:MM" strings; compare as minutes-of-day.
        start_h, start_m = (int(x) for x in policy.session_start.split(":"))
        end_h, end_m = (int(x) for x in policy.session_end.split(":"))
        now_minutes = local.hour * 60 + local.minute
        if now_minutes < start_h * 60 + start_m or now_minutes >= end_h * 60 + end_m:
            failures.append("market is closed (outside trading session)")
            tags.append("market_closed")

    def _check_signal_age(
        self,
        *,
        intent: OrderIntent,
        failures: list[str],
        tags: list[str],
    ) -> None:
        """Reject orders whose signal is older than ``max_signal_age_seconds``."""
        max_age = self.limits.max_signal_age_seconds
        if max_age is None:
            return
        age = (self.clock() - intent.created_at).total_seconds()
        if age > max_age:
            failures.append("signal is stale (exceeds max_signal_age_seconds)")
            tags.append("stale_signal")

    def _check_duplicate_order(
        self,
        *,
        intent: OrderIntent,
        failures: list[str],
        tags: list[str],
    ) -> None:
        """Reject near-identical intents submitted within the dedup window.

        ponytail:duplicate_order_state: in-memory deque on the gate; a
        process restart loses dedup memory (a restart-then-resubmit is
        not caught). Acceptable for paper; upgrade path is a persistent
        recent-intent store.
        """
        window = self.limits.duplicate_order_window_seconds
        if window is None or intent.quantity is None:
            return
        now = self.clock()
        max_count = self.limits.duplicate_order_max_count
        key = (intent.symbol, intent.side, intent.quantity)

        # Drop entries older than the window.
        cutoff = now.timestamp() - window
        while self._recent_intents and self._recent_intents[0][3].timestamp() < cutoff:
            self._recent_intents.popleft()

        # Count identical intents still in the window.
        identical = sum(1 for k in self._recent_intents if (k[0], k[1], k[2]) == key)
        # Record this intent regardless of outcome so a later resubmit
        # sees it (tighten-only: recording never approves anything).
        self._recent_intents.append((intent.symbol, intent.side, intent.quantity, now))
        if identical + 1 > max_count:
            failures.append("duplicate order within dedup window")
            tags.append("duplicate_order")

    def _check_daily_loss(
        self,
        *,
        intent: OrderIntent,
        estimated_price: Decimal | None,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> dict[str, dict[str, str]]:
        """Both entry directions require fresh broker P&L and the durable latch."""
        pct = self.limits.max_daily_loss_pct
        if pct is None:
            return {}
        context = account_context
        now = self.clock().astimezone(UTC)
        evidence = {"ceiling_pct": str(pct), "valid": "false"}
        valid = False
        breached = False
        if context is not None:
            stamp = context.daily_loss_captured_at
            evidence.update(
                {
                    "realized_pnl": str(context.day_realized_pnl),
                    "unrealized_pnl": str(context.day_unrealized_pnl),
                    "nav": str(context.equity),
                    "blocked_for_day": str(context.daily_loss_blocked),
                    "observed_at": str(stamp),
                    "error": context.daily_loss_error or "",
                }
            )
            valid = (
                stamp is not None
                and stamp.tzinfo is not None
                and stamp.astimezone(UTC).date() == now.date()
                and 0 <= (now - stamp).total_seconds() <= 60
                and context.daily_loss_blocked is not None
                and context.daily_loss_error is None
                and context.day_realized_pnl is not None
                and context.day_unrealized_pnl is not None
                and context.equity is not None
            )
            if valid:
                assert context.day_realized_pnl is not None
                assert context.day_unrealized_pnl is not None
                assert context.equity is not None
                try:
                    breached = daily_loss_breached(
                        context.day_realized_pnl,
                        context.day_unrealized_pnl,
                        context.equity,
                        pct,
                    ) or bool(context.daily_loss_blocked)
                except ValueError:
                    valid = False
        evidence["valid"] = str(valid).lower()
        evidence["breached"] = str(breached).lower()
        if not valid or breached:
            failures.append(
                "daily loss evidence incomplete"
                if not valid
                else "daily loss blocks entries for this UTC day"
            )
            tags.extend(("DAILY_LOSS", "max_daily_loss"))
        return {"daily_loss": evidence}

    def _check_entry_rules(
        self,
        *,
        intent: OrderIntent,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        """Apply the entry rules from PROJECT_GUIDE 5.7.

        Only reached for orders that increase exposure; closes take the
        reduced rule-1/rule-3 path instead.
        """
        policy = self.limits.entry_rules
        if policy is None:
            return
        rejections = evaluate_entry_rules(
            intent,
            policy=policy,
            now=self.clock(),
            account_context=account_context,
        )
        self._record_rule_rejections(rejections, failures, tags)

    def _check_close_quote_rules(
        self,
        *,
        intent: OrderIntent,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        """Rule 3 only, for a reduce-only close (PROJECT_GUIDE 5.7)."""
        policy = self.limits.entry_rules
        if policy is None:
            return
        rejections = evaluate_quote_rules(
            intent,
            policy=policy,
            now=self.clock(),
            account_context=account_context,
        )
        self._record_rule_rejections(rejections, failures, tags)

    @staticmethod
    def _record_rule_rejections(
        rejections: Sequence[RuleRejection],
        failures: list[str],
        tags: list[str],
    ) -> None:
        for rejection in rejections:
            failures.append(f"{rejection.code}: {rejection.detail}")
        for code in rejection_codes(rejections):
            if code not in tags:
                tags.append(code)

    def _check_drawdown(
        self,
        *,
        intent: OrderIntent,
        estimated_price: Decimal | None,
        account_context: AccountExposureContext | None,
        failures: list[str],
        tags: list[str],
    ) -> None:
        """Reject new buys when the drawdown from the HWM exceeds the cap.

        Tighten-only / fail-closed. The HWM must be supplied by the caller
        from a persistent snapshot store so a restart cannot reset the
        peak and silently widen the floor (the whole point of R21.3).

        ponytail:drawdown_on_unrealized: drawdown is measured against the
        current ``equity`` (cash + unrealized mark-to-market), not against
        realized-only P&L. Ceiling: an intraday mark that has not yet been
        snapshotted understates the peak. Upgrade path: snapshot equity
        on every mark change, not only after fills.
        """
        pct = self.limits.max_drawdown_floor_pct
        if pct is None:
            return
        if account_context is None:
            failures.append("drawdown check required but no account context supplied")
            tags.append("account_context_required")
            return
        if intent.side == "sell":
            return
        if account_context.equity_high_water_mark is None:
            failures.append(
                "max_drawdown_floor_pct configured but equity_high_water_mark missing"
            )
            tags.append("missing_equity_hwm")
            return
        if account_context.equity is None:
            failures.append(
                "max_drawdown_floor_pct configured but current equity missing"
            )
            tags.append("missing_equity")
            return
        if account_context.equity_high_water_mark <= 0:
            failures.append("equity high-water mark must be positive for drawdown")
            tags.append("missing_equity_hwm")
            return
        drawdown_pct = (
            account_context.equity_high_water_mark - account_context.equity
        ) / account_context.equity_high_water_mark
        if drawdown_pct > pct:
            failures.append("order would breach max_drawdown_floor_pct")
            tags.append("max_drawdown_floor")
