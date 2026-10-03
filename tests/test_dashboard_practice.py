"""Practice test: verify dashboard overview NAV matches OANDA practice account summary.

PROJECT_GUIDE S6.

Run with ``pytest -m practice -k test_dashboard_practice``.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from alphabrief_api.broker_adapter import _reset_broker_adapter
from alphabrief_api.main import create_app
from alphabrief_core import load_env_file
from alphabrief_execution.broker.oanda.account_ops import AccountOpsClient
from alphabrief_execution.broker.runtime import (
    build_oanda_paper_client,
    oanda_is_configured,
)
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.practice

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_nav_matches_oanda_practice_account_summary(
    tmp_path: Path,
) -> None:
    """Verify overview page displays NAV matching live OANDA account summary."""
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        load_env_file(env_path)
    if not oanda_is_configured():
        pytest.fail(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )

    # 1. Fetch real OANDA account summary
    client = build_oanda_paper_client()
    account_ops = AccountOpsClient(client)
    oanda_summary = account_ops.account_summary()
    expected_nav = oanda_summary.nav

    # 2. Run API server with real broker adapter
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path)
    os.environ["ALPHABRIEF_TRADING_MODE"] = "off"
    _reset_broker_adapter()

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

    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)

    try:
        # 3. Load dashboard in Playwright and verify rendered NAV
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{url}/#overview", wait_until="networkidle")
            page.wait_for_selector("#page-content", timeout=5000)
            page.wait_for_selector(
                ".state-loading", state="detached", timeout=5000
            )

            from decimal import Decimal

            nav_el = page.wait_for_selector("#overview-nav-val", timeout=5000)
            assert nav_el is not None
            displayed_nav_text = nav_el.inner_text().strip()

            displayed_num_str = (
                displayed_nav_text.replace("USD", "").replace(",", "").strip()
            )
            displayed_decimal = Decimal(displayed_num_str)
            assert displayed_decimal == expected_nav, (
                f"Dashboard displayed NAV '{displayed_nav_text}' does not match "
                f"OANDA account summary NAV '{expected_nav} USD'"
            )
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=3.0)
