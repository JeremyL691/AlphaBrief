"""FastAPI application surface for AlphaBrief."""

from __future__ import annotations

# Load .env from the project root before any package reads os.environ.
# Explicit shell exports always win — we never override an existing value.
from alphabrief_core import load_env_file as _load_env_file  # noqa: E402

_load_env_file()  # noqa: E402

from alphabrief_api.main import app  # noqa: E402

__all__ = ["app"]
