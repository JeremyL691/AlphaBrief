"""Credential resolution for the OANDA runtime (GUIDE 4.4).

The runtime must see OANDA practice credentials from the environment or
from ``secrets/oanda.json`` — the packaged LaunchAgent has neither a
repository checkout nor a ``.env`` file, so the secrets file is what
makes an installed background work.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_core.secrets import write_secret
from alphabrief_execution.broker.runtime import oanda_is_configured


def _env(monkeypatch: pytest.MonkeyPatch, *, token: str, account: str) -> None:
    monkeypatch.setenv("ALPHABRIEF_OANDA_TOKEN", token)
    monkeypatch.setenv("ALPHABRIEF_OANDA_ACCOUNT_ID", account)


def test_env_credentials_are_sufficient(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    _env(monkeypatch, token="tok", account="acc")
    assert oanda_is_configured() is True


def test_missing_env_without_secret_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    assert oanda_is_configured() is False


def test_secrets_file_satisfies_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    write_secret("oanda", {"token": "tok", "account_id": "acc"})
    assert oanda_is_configured() is True


def test_explicit_environ_is_not_augmented_from_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    write_secret("oanda", {"token": "tok", "account_id": "acc"})
    assert oanda_is_configured({"ALPHABRIEF_OANDA_TOKEN": "only-token"}) is False
