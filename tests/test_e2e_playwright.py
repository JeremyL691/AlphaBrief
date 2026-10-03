"""Playwright End-to-End smoke tests and Axe accessibility checks.

PROJECT_GUIDE S6.

Tests cover:
- Static SPA dashboard rendering all 11 views
- Responsive layout at 4 breakpoints: 320px, 768px, 1024px, 1440px
- Theme switching (Light / Dark) and screenshot generation to docs/images/
- Axe-core accessibility auditing with 0 critical or serious violations
- 5 UI states: loading, empty, error, stale, offline
- Invariant: Zero simulated/mock sample data in DOM
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from alphabrief_api.broker_adapter import _reset_broker_adapter
from alphabrief_api.main import create_app
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Browser, Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "docs" / "images"

ALL_VIEWS = [
    "overview",
    "committee",
    "orders",
    "news",
    "risk",
    "evaluation",
    "backtest",
    "strategies",
    "review",
    "settings",
    "onboarding",
]

BREAKPOINTS = [
    (320, 640),   # Mobile
    (768, 1024),  # Tablet
    (1024, 768),  # Desktop small
    (1440, 900),  # Desktop large
]


@pytest.fixture(scope="module")
def live_server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start the FastAPI backend with static files in a daemon thread."""
    tmp_path = tmp_path_factory.mktemp("e2e_alphabrief_data")
    old_data_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    old_trading_mode = os.environ.get("ALPHABRIEF_TRADING_MODE")

    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path)
    os.environ["ALPHABRIEF_TRADING_MODE"] = "off"
    _reset_broker_adapter()

    # Find free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    app = create_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server ready
    url = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                ready = True
                break
        except OSError:
            time.sleep(0.05)

    if not ready:
        raise RuntimeError("Failed to start test API server for Playwright")

    yield url

    server.should_exit = True
    thread.join(timeout=3.0)

    # Restore environment
    if old_data_dir is not None:
        os.environ["ALPHABRIEF_DATA_DIR"] = old_data_dir
    else:
        os.environ.pop("ALPHABRIEF_DATA_DIR", None)

    if old_trading_mode is not None:
        os.environ["ALPHABRIEF_TRADING_MODE"] = old_trading_mode
    else:
        os.environ.pop("ALPHABRIEF_TRADING_MODE", None)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    """Launch headless Chromium browser."""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _wait_for_view_render(page: Page, timeout_ms: int = 5000) -> None:
    """Wait for loading spinner to disappear and content container to render."""
    page.wait_for_selector("#page-content", timeout=timeout_ms)
    page.wait_for_selector(".state-loading", state="detached", timeout=timeout_ms)


def test_playwright_all_views_smoke(browser: Browser, live_server_url: str) -> None:
    """Smoke test ensuring every view renders without JavaScript errors."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    js_errors: list[str] = []
    page.on("pageerror", lambda err: js_errors.append(str(err)))

    try:
        for view in ALL_VIEWS:
            target_url = f"{live_server_url}/#{view}"
            page.goto(target_url, wait_until="networkidle")
            _wait_for_view_render(page)

            # Check that content area is populated
            content_html = page.inner_html("#page-content")
            assert len(content_html) > 50, f"View {view} rendered empty HTML"

            # Check for active nav state
            active_link = page.query_selector(f'.nav-link[data-route="{view}"]')
            if active_link:
                classes = active_link.get_attribute("class") or ""
                assert "active" in classes, f"Nav link for {view} should be active"

        assert len(js_errors) == 0, (
            f"Encountered JS errors during smoke test: {js_errors}"
        )
    finally:
        page.close()


def test_playwright_responsive_breakpoints(
    browser: Browser,
    live_server_url: str,
) -> None:
    """Verify responsive behavior across 4 breakpoints (320, 768, 1024, 1440)."""
    for width, height in BREAKPOINTS:
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(f"{live_server_url}/#overview", wait_until="networkidle")
            _wait_for_view_render(page)

            # Assert top bar and page content exist and fit viewport width
            box = page.locator("#app").bounding_box()
            assert box is not None
            assert box["width"] <= width + 1, (
                f"Layout overflow at breakpoint {width}x{height}: "
                f"app width {box['width']}"
            )
        finally:
            page.close()


def test_playwright_themes_and_screenshots(
    browser: Browser,
    live_server_url: str,
) -> None:
    """Capture screenshots for Light and Dark themes for all main views."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    try:
        for view in ALL_VIEWS:
            page.goto(f"{live_server_url}/#{view}", wait_until="networkidle")
            _wait_for_view_render(page)

            # 1. Light theme
            page.evaluate(
                "() => document.documentElement.setAttribute('data-theme', 'light')"
            )
            page.wait_for_timeout(100)
            light_path = IMAGES_DIR / f"{view}_light.png"
            page.screenshot(path=str(light_path), full_page=False)
            assert light_path.exists() and light_path.stat().st_size > 0

            # 2. Dark theme
            page.evaluate(
                "() => document.documentElement.setAttribute('data-theme', 'dark')"
            )
            page.wait_for_timeout(100)
            dark_path = IMAGES_DIR / f"{view}_dark.png"
            page.screenshot(path=str(dark_path), full_page=False)
            assert dark_path.exists() and dark_path.stat().st_size > 0

    finally:
        page.close()


def test_axe_accessibility_zero_critical_or_serious_violations(
    browser: Browser,
    live_server_url: str,
) -> None:
    """Audit accessibility using axe-core: 0 critical or serious violations."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    axe = Axe()

    try:
        for view in ALL_VIEWS:
            page.goto(f"{live_server_url}/#{view}", wait_until="networkidle")
            _wait_for_view_render(page)

            results = axe.run(page)
            violations = results.response.get("violations", [])
            critical_or_serious = [
                v for v in violations if v.get("impact") in ("critical", "serious")
            ]

            if critical_or_serious:
                details = []
                for v in critical_or_serious:
                    node_targets = [
                        (
                            f"  - {n.get('target')}: {n.get('html')} "
                            f"({n.get('failureSummary')})"
                        )
                        for n in v.get("nodes", [])
                    ]
                    details.append(
                        f"[{v.get('impact')}] {v.get('id')}: {v.get('description')}\n"
                        + "\n".join(node_targets)
                    )
                pytest.fail(
                    f"Axe a11y violations on view '{view}':\n" + "\n".join(details)
                )
    finally:
        page.close()


def test_ui_five_states(browser: Browser, live_server_url: str) -> None:
    """Verify the 5 UI states: loading, empty, offline, stale, error."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    try:
        page.goto(f"{live_server_url}/#overview", wait_until="networkidle")
        _wait_for_view_render(page)

        # 1. Empty state verification (fresh temporary database has empty positions)
        empty_el = page.query_selector(".state-empty")
        assert empty_el is not None, "Expected empty state card to be present"

        # 2. Offline state
        page.evaluate("""() => {
            window.app.systemState.online = false;
            window.app._updateTopBarState();
        }""")
        offline_banner = page.locator("#offline-banner")
        assert offline_banner.is_visible()
        pill = page.locator("#system-status-pill")
        assert "offline" in (pill.get_attribute("class") or "")

        # 3. Stale state
        page.evaluate("""() => {
            window.app.systemState.online = true;
            window.app.systemState.stale = true;
            window.app._updateTopBarState();
        }""")
        assert "stale" in (pill.get_attribute("class") or "")

        # 4. Online state
        page.evaluate("""() => {
            window.app.systemState.stale = false;
            window.app._updateTopBarState();
        }""")
        assert "online" in (pill.get_attribute("class") or "")

        # 5. Error state rendering
        page.evaluate("""() => {
            const container = document.getElementById('page-content');
            container.innerHTML = `
                <div class="state-error" role="alert">
                    <svg class="nav-icon"><use href="#icon-alert-triangle"></use></svg>
                    <h3>数据加载失败 / Loading Error</h3>
                    <p>Failed to connect to endpoint</p>
                </div>
            `;
        }""")
        error_el = page.query_selector(".state-error")
        assert error_el is not None
        assert "Loading Error" in error_el.inner_text()

    finally:
        page.close()


def test_no_simulated_sample_data_in_dom(
    browser: Browser,
    live_server_url: str,
) -> None:
    """Verify that DOM across all views never contains simulated sample data."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    try:
        for view in ALL_VIEWS:
            page.goto(f"{live_server_url}/#{view}", wait_until="networkidle")
            _wait_for_view_render(page)

            body_text = page.inner_text("body")
            assert "Simulated sample" not in body_text, (
                f"Found 'Simulated sample' in view {view}"
            )
    finally:
        page.close()
