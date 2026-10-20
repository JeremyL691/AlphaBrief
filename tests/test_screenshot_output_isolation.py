"""Repository hygiene for the Playwright screenshot test.

`tests/test_e2e_playwright.py` renders the real SPA and captures PNGs. A
full test run must not rewrite tracked files: the screenshots under
``docs/images/`` are release material committed on purpose, and a test
that writes them on every run makes ``git status`` dirty for anyone who
just ran the suite.

The capture directory therefore defaults to a temporary path and only
writes the repository copy when the operator explicitly asks for it.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_MODULE = "test_e2e_playwright"


def _load_e2e(monkeypatch: pytest.MonkeyPatch, value: str | None) -> Any:
    """Import the E2E module with the capture switch at *value*."""
    if value is None:
        monkeypatch.delenv("ALPHABRIEF_UPDATE_SCREENSHOTS", raising=False)
    else:
        monkeypatch.setenv("ALPHABRIEF_UPDATE_SCREENSHOTS", value)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent))
    return importlib.reload(importlib.import_module(E2E_MODULE))


def test_capture_dir_defaults_outside_the_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain test run must never target the tracked docs/images dir."""
    module = _load_e2e(monkeypatch, None)
    capture_dir = module.resolve_capture_dir()

    assert not capture_dir.is_relative_to(REPO_ROOT), (
        f"default screenshot directory {capture_dir} is inside the "
        "repository; running the suite would dirty tracked files"
    )
    assert capture_dir.name == "images"


def test_capture_dir_uses_the_repository_only_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented switch is the only way to rewrite release material."""
    module = _load_e2e(monkeypatch, "1")
    capture_dir = module.resolve_capture_dir()

    assert capture_dir == REPO_ROOT / "docs" / "images"


def test_capture_switch_treats_other_values_as_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo in the switch must not rewrite tracked screenshots."""
    module = _load_e2e(monkeypatch, "yes")
    capture_dir = module.resolve_capture_dir()

    assert not capture_dir.is_relative_to(REPO_ROOT)
