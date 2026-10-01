"""Single-instance runtime lock (PROJECT_GUIDE 4.1 / invariant 12).

Only one backend may run per data directory at a time, and only one
backend may hold an OANDA account in ``trading_mode=on``. The lock is an
advisory ``flock`` on ``runtime.lock`` in the data directory:

* the holder writes its pid and start time into the file for diagnostics;
* a second process fails immediately with ``Could not set lock`` rather
  than running a duplicate scheduler;
* the lock is released when the process exits (or crashes) — the kernel
  drops the ``flock`` — so a stale lock file never blocks a restart;
* ``lock_status()`` lets ``alphabrief doctor`` report who holds it.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from alphabrief_core import paths as _paths


class RuntimeLockError(RuntimeError):
    """Raised when the runtime lock is already held by another process."""


class RuntimeLock:
    """Advisory single-instance lock over ``runtime.lock``."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else _paths.runtime_lock_path()
        self._handle: object | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        """Take the lock or raise :class:`RuntimeLockError` immediately."""
        if self._handle is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+", encoding="utf-8")  # noqa: SIM115 - kept open
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            holder = lock_status(self._path)
            detail = f" (held by pid {holder.get('pid')})" if holder else ""
            raise RuntimeLockError(
                f"Could not set lock on {self._path}{detail}"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": datetime.now(UTC).isoformat(),
                },
                sort_keys=True,
            )
        )
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        finally:
            handle.close()  # type: ignore[attr-defined]
            self._handle = None

    def __enter__(self) -> RuntimeLock:
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def lock_status(path: Path | None = None) -> dict[str, str] | None:
    """The holder's recorded metadata, or ``None`` when the lock is free.

    The probe never blocks: it tries a non-blocking exclusive lock and
    releases it immediately, so ``doctor`` can run while the backend is up.
    """
    lock_path = Path(path) if path is not None else _paths.runtime_lock_path()
    if not lock_path.exists():
        return None
    try:
        with open(lock_path, encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.seek(0)
                raw = handle.read().strip()
                try:
                    parsed = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    parsed = {}
                return {str(key): str(value) for key, value in parsed.items()}
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    except OSError:
        return None
    return None


__all__ = ["RuntimeLock", "RuntimeLockError", "lock_status"]
