"""Deterministic kill switch for AlphaBrief order flow."""

from dataclasses import dataclass


@dataclass
class KillSwitch:
    """Blocks all orders when activated."""

    active: bool = False
    reason: str = "kill switch inactive"

    def activate(self, reason: str) -> None:
        if reason.strip() == "":
            raise ValueError("kill switch reason must not be blank")
        self.active = True
        self.reason = reason

    def deactivate(self) -> None:
        self.active = False
        self.reason = "kill switch inactive"
