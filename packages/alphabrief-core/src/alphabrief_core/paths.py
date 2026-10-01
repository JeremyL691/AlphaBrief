"""The single source of truth for AlphaBrief filesystem paths.

Every store, backend and entry point resolves its paths here so the
whole product agrees on one data directory and one database file.

Layout (``docs/PROJECT_GUIDE.md`` appendix B)::

    <data_dir>/
      alphabrief.duckdb   唯一数据库
      runtime.lock        单实例锁
      secrets/            0600 凭证
      logs/               结构化 JSON 日志
      reports/daily/      日报
      backups/            备份
      cache/              可删除缓存

``ALPHABRIEF_HOME`` overrides the data directory and must be an absolute
path; a relative path is a hard error rather than a path that silently
depends on the current working directory. ``ALPHABRIEF_DATA_DIR`` is
accepted as a development/test alias with the same absolute-path rule.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path

ENV_HOME = "ALPHABRIEF_HOME"
ENV_DATA_DIR = "ALPHABRIEF_DATA_DIR"

#: Database file name inside the data directory.
DATABASE_NAME = "alphabrief.duckdb"

#: Single-instance lock file name inside the data directory.
RUNTIME_LOCK_NAME = "runtime.lock"

_DEFAULT_HOME = Path.home() / "Library" / "Application Support" / "AlphaBrief"


class PathConfigError(ValueError):
    """Raised when a configured path is unusable (for example relative)."""


def _resolve_override(environ: Mapping[str, str] | None) -> Path | None:
    source: Mapping[str, str] = os.environ if environ is None else environ
    for name in (ENV_HOME, ENV_DATA_DIR):
        raw = (source.get(name) or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise PathConfigError(
                f"{name} must be an absolute path, got {raw!r}"
            )
        return candidate
    return None


def data_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the data directory, creating it when missing.

    ``ALPHABRIEF_HOME`` wins over ``ALPHABRIEF_DATA_DIR``; both must be
    absolute. Without either, the macOS application-support directory is
    used.
    """
    base = _resolve_override(environ) or _DEFAULT_HOME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the path to the single DuckDB database file."""
    base = data_dir(environ)
    base.mkdir(parents=True, exist_ok=True)
    return base / DATABASE_NAME


def runtime_lock_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the single-instance lock file path."""
    return data_dir(environ) / RUNTIME_LOCK_NAME


def account_runtime_lock_path(account_id: str) -> Path:
    """A per-user account lock independent of all data-directory overrides.

    Account identifiers never appear in filenames or holder metadata.
    """
    normalized = account_id.strip()
    if not normalized:
        raise PathConfigError("an OANDA account is required for trading ownership")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return _DEFAULT_HOME / "account-locks" / f"{digest}.lock"


def secrets_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the directory holding credential files (mode 0600)."""
    path = data_dir(environ) / "secrets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the directory holding structured JSON logs."""
    path = data_dir(environ) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the directory holding generated reports."""
    path = data_dir(environ) / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def daily_reports_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the directory holding daily reports."""
    path = reports_dir(environ) / "daily"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the directory holding database backups."""
    path = data_dir(environ) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the directory holding disposable cache data."""
    path = data_dir(environ) / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


__all__ = [
    "DATABASE_NAME",
    "ENV_DATA_DIR",
    "ENV_HOME",
    "RUNTIME_LOCK_NAME",
    "PathConfigError",
    "account_runtime_lock_path",
    "backups_dir",
    "cache_dir",
    "daily_reports_dir",
    "data_dir",
    "db_path",
    "logs_dir",
    "reports_dir",
    "runtime_lock_path",
    "secrets_dir",
]
