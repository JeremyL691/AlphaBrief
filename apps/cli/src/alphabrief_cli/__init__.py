"""AlphaBrief CLI surface.

Loading the project ``.env`` from the working directory or an
ancestor happens here so every subcommand inherits the same operator
configuration. Tests can opt out by setting
``ALPHABRIEF_NO_AUTO_LOAD_ENV=1`` or by running under pytest (which
sets ``PYTEST_CURRENT_TEST``).
"""

from __future__ import annotations

from alphabrief_core import load_env_file as _load_env_file

_load_env_file()

__all__ = []
