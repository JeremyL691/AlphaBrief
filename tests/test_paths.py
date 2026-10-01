"""Contract tests for the single path module (``alphabrief_core.paths``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alphabrief_core import paths


def test_default_data_dir_is_under_application_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(paths.ENV_HOME, raising=False)
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)

    resolved = paths.data_dir()

    assert resolved.is_absolute()
    assert resolved.name == "AlphaBrief"
    assert resolved.parent.name == "Application Support"


def test_home_env_overrides_the_default(tmp_path: Path) -> None:
    resolved = paths.data_dir({paths.ENV_HOME: str(tmp_path / "home")})

    assert resolved == tmp_path / "home"


def test_data_dir_alias_is_accepted(tmp_path: Path) -> None:
    resolved = paths.data_dir({paths.ENV_DATA_DIR: str(tmp_path / "dev")})

    assert resolved == tmp_path / "dev"


def test_home_env_wins_over_the_alias(tmp_path: Path) -> None:
    resolved = paths.data_dir(
        {
            paths.ENV_HOME: str(tmp_path / "home"),
            paths.ENV_DATA_DIR: str(tmp_path / "alias"),
        }
    )

    assert resolved == tmp_path / "home"


@pytest.mark.parametrize("name", [paths.ENV_HOME, paths.ENV_DATA_DIR])
def test_relative_override_is_rejected(name: str) -> None:
    with pytest.raises(paths.PathConfigError, match="must be an absolute path"):
        paths.data_dir({name: "data/local"})


def test_db_path_is_the_single_database_file(tmp_path: Path) -> None:
    resolved = paths.db_path({paths.ENV_HOME: str(tmp_path)})

    assert resolved == tmp_path / paths.DATABASE_NAME
    assert resolved.parent.is_dir()


def test_layout_directories_are_created_under_the_data_dir(
    tmp_path: Path,
) -> None:
    environ = {paths.ENV_HOME: str(tmp_path)}

    assert paths.secrets_dir(environ) == tmp_path / "secrets"
    assert paths.logs_dir(environ) == tmp_path / "logs"
    assert paths.reports_dir(environ) == tmp_path / "reports"
    assert paths.daily_reports_dir(environ) == tmp_path / "reports" / "daily"
    assert paths.backups_dir(environ) == tmp_path / "backups"
    assert paths.cache_dir(environ) == tmp_path / "cache"
    assert paths.runtime_lock_path(environ) == tmp_path / paths.RUNTIME_LOCK_NAME

    for directory in (
        paths.secrets_dir(environ),
        paths.logs_dir(environ),
        paths.daily_reports_dir(environ),
        paths.backups_dir(environ),
        paths.cache_dir(environ),
    ):
        assert directory.is_dir()


def test_stores_share_one_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every store resolves its default database through this module."""
    from alphabrief_execution.broker.recon_store import BrokerReconStore
    from alphabrief_news.macro_release import MacroReleaseStore
    from alphabrief_risk.decision_store import RiskDecisionStore
    from alphabrief_trader.db_store import AiTradingStore

    monkeypatch.setenv(paths.ENV_HOME, str(tmp_path))
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    expected = paths.db_path()
    stores: list[Any] = [
        AiTradingStore(),
        MacroReleaseStore(),
        RiskDecisionStore(),
        BrokerReconStore(),
    ]
    try:
        for store in stores:
            assert store._db_path == expected  # noqa: SLF001
    finally:
        for store in stores:
            store.close()
