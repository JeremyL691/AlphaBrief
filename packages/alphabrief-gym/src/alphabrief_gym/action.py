"""Action space abstractions for the AlphaBrief trading environment."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

from alphabrief_gym.schemas import (
    ContinuousActionSpace,
    DiscreteActionSpace,
    SingleAssetAction,
)


def validate_continuous_targets(
    space: ContinuousActionSpace,
    targets: Mapping[str, Decimal],
) -> dict[str, Decimal]:
    """Validate a target-weight action against a continuous action space.

    Returns the targets coerced to plain ``Decimal`` values keyed by
    asset. Raises :class:`ValueError` for unknown assets, missing
    assets, or weights that violate leverage / short constraints.
    """
    if set(targets.keys()) != set(space.assets):
        missing = set(space.assets) - set(targets.keys())
        extra = set(targets.keys()) - set(space.assets)
        msg: list[str] = []
        if missing:
            msg.append(f"missing targets: {sorted(missing)}")
        if extra:
            msg.append(f"unexpected targets: {sorted(extra)}")
        raise ValueError("; ".join(msg))

    bounds = abs(space.max_leverage)
    cleaned: dict[str, Decimal] = {}
    for asset, raw in targets.items():
        try:
            value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
        except Exception as exc:
            raise ValueError(
                f"target weight for {asset!r} is not numeric: {raw!r}"
            ) from exc
        if value.copy_abs() > bounds:
            raise ValueError(
                f"target weight for {asset!r} ({value}) exceeds "
                f"max_leverage {space.max_leverage}"
            )
        if not space.allow_short and value < 0:
            raise ValueError(
                f"short not allowed; target for {asset!r} is negative"
            )
        cleaned[asset] = value
    return cleaned


def validate_discrete_action(
    space: DiscreteActionSpace, action: Any
) -> SingleAssetAction:
    """Validate a discrete action against the configured space."""
    if action not in space.actions:
        raise ValueError(
            f"action {action!r} not in {list(space.actions)}"
        )
    return cast(SingleAssetAction, action)


__all__ = [
    "validate_continuous_targets",
    "validate_discrete_action",
]
