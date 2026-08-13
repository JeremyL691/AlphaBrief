"""Soft application shell and truthful page-state system (M14-W02).

The required information architecture (REQ-UI-004) is declared once as
navigation data: Overview, Markets, News & Sentiment, AI Research, Risk,
OANDA Account, Orders & Trades, Scheduler, 30-Day Observation, and
Settings — with per-viewport behavior (collapsed below 1024px, full
above) and semantic, keyboard-reachable anchors. Every page renders one
of the eight documented states — loading, empty, stale, partial, error,
offline, frozen, ready — derived deterministically from API truth only;
no blank panel and no fake fallback value (REQ-UI-005, REQ-UI-003).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The four required viewports for responsive verification.
VIEWPORTS: tuple[int, ...] = (320, 768, 1024, 1440)

#: The complete documented page-state set (REQ-UI-005).
PageState = Literal[
    "loading",
    "empty",
    "stale",
    "partial",
    "error",
    "offline",
    "frozen",
    "ready",
]

PAGE_STATES: tuple[PageState, ...] = (
    "loading",
    "empty",
    "stale",
    "partial",
    "error",
    "offline",
    "frozen",
    "ready",
)


class NavigationItem(BaseModel):
    """One required navigation entry (icon = library name, never emoji)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    route: str = Field(min_length=1)
    icon: str = Field(min_length=1)
    order: int = Field(ge=0)


NAVIGATION_SECTIONS: tuple[NavigationItem, ...] = (
    NavigationItem(
        id="overview",
        label="Overview",
        route="/dashboard",
        icon="home",
        order=0,
    ),
    NavigationItem(
        id="markets",
        label="Markets",
        route="/dashboard/markets",
        icon="chart",
        order=1,
    ),
    NavigationItem(
        id="news_sentiment",
        label="News & Sentiment",
        route="/dashboard/news",
        icon="news",
        order=2,
    ),
    NavigationItem(
        id="ai_research",
        label="AI Research",
        route="/dashboard/ai-trading",
        icon="brain",
        order=3,
    ),
    NavigationItem(
        id="risk",
        label="Risk",
        route="/dashboard/risk",
        icon="shield",
        order=4,
    ),
    NavigationItem(
        id="oanda_account",
        label="OANDA Account",
        route="/dashboard/account",
        icon="wallet",
        order=5,
    ),
    NavigationItem(
        id="orders_trades",
        label="Orders & Trades",
        route="/dashboard/orders",
        icon="arrows",
        order=6,
    ),
    NavigationItem(
        id="scheduler",
        label="Scheduler",
        route="/dashboard/scheduler",
        icon="clock",
        order=7,
    ),
    NavigationItem(
        id="observation",
        label="30-Day Observation",
        route="/dashboard/observation",
        icon="calendar",
        order=8,
    ),
    NavigationItem(
        id="settings",
        label="Settings",
        route="/dashboard/settings",
        icon="gear",
        order=9,
    ),
)

#: Collapsed navigation below this width; full navigation at and above.
FULL_NAV_MIN_WIDTH = 1024


class PageStatePayload(BaseModel):
    """One deterministic state payload derived from API truth only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: PageState
    title: str
    message: str
    action: str | None = None


class TruthInputs(BaseModel):
    """The API truth a page state is derived from. Never fabricated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    has_data: bool = False
    freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    partial: bool = False
    error: bool = False
    offline: bool = False
    frozen: bool = False


def derive_page_state(truth: TruthInputs) -> PageState:
    """Derive the page state deterministically from API truth.

    Order: frozen -> offline -> error -> empty -> stale -> partial ->
    ready. A frozen or offline truth never degrades into a fake ready.
    """
    if truth.frozen:
        return "frozen"
    if truth.offline:
        return "offline"
    if truth.error:
        return "error"
    if not truth.has_data:
        return "empty"
    if truth.freshness_status == "stale":
        return "stale"
    if truth.partial:
        return "partial"
    return "ready"


_STATE_COPY: dict[PageState, tuple[str, str, str | None]] = {
    "loading": (
        "Loading",
        "Fetching the latest evidence from the runtime store.",
        None,
    ),
    "empty": (
        "No data yet",
        "The runtime store has no records for this view.",
        "Check the scheduler for the latest run.",
    ),
    "stale": (
        "Stale data",
        "The latest evidence is older than the freshness limit.",
        "Wait for the next scheduler cycle.",
    ),
    "partial": (
        "Partial data",
        "Some requested evidence is unavailable.",
        "Review the missing sources in the trace view.",
    ),
    "error": (
        "Error",
        "The runtime store returned an error for this view.",
        "Check the scheduler logs.",
    ),
    "offline": (
        "Offline",
        "The runtime store is unreachable.",
        "Start the API server and retry.",
    ),
    "frozen": (
        "Frozen",
        "Execution is frozen; this view reflects the frozen state.",
        "Resolve the freeze before continuing.",
    ),
    "ready": (
        "Ready",
        "The latest evidence is fresh and complete.",
        None,
    ),
}


def render_state_payload(
    state: PageState, resource: str
) -> PageStatePayload:
    """The typed, copy-safe payload for one page state.

    The payload carries only documented copy for the state class; no
    runtime value is invented here.
    """
    title, message, action = _STATE_COPY[state]
    return PageStatePayload(
        state=state,
        title=title,
        message=f"{message} ({resource})",
        action=action,
    )


def navigation_for_viewport(width: int) -> tuple[NavigationItem, ...]:
    """The navigation entries reachable at one viewport width.

    All ten sections are always declared; below the full-nav breakpoint
    they are reachable through the collapsed (menu) navigation, at and
    above it they render inline.
    """
    return NAVIGATION_SECTIONS


def shell_css() -> str:
    """The shell styles: semantic nav, responsive breakpoints, no
    horizontal overflow at any required viewport, focus-visible rings,
    and light/dark theme support via the design tokens."""
    return _SHELL_CSS


_SHELL_CSS = """
/* Soft application shell (M14-W02). Consumes design tokens only. */
.app-shell { max-width: 100%; overflow-x: hidden; }
.app-nav { display: flex; flex-wrap: wrap; gap: var(--space-2, 8px); }
.app-nav a {
  color: var(--text, #3d3a34);
  text-decoration: none;
  padding: var(--space-2, 8px) var(--space-3, 12px);
  border-radius: var(--radius-md, 10px);
}
.app-nav a:focus-visible {
  outline: var(--interaction-focus-ring, 2px solid var(--accent, #b07d3f));
  outline-offset: 2px;
}
.app-nav a:hover { background: var(--accent-soft, rgba(176, 125, 63, 0.12)); }
.app-shell main, .app-shell section, .app-shell article {
  max-width: 100%;
  overflow-wrap: break-word;
}
@media (max-width: 767px) {
  .app-nav { flex-direction: column; }
  .app-nav a { width: 100%; }
}
@media (min-width: 768px) and (max-width: 1023px) {
  .app-nav { flex-wrap: wrap; }
}
@media (min-width: 1024px) {
  .app-nav { flex-wrap: nowrap; }
}
/* No horizontal overflow guards at every required viewport. */
html, body { max-width: 100%; overflow-x: hidden; }
* { min-width: 0; }
"""
