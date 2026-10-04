"""Single runtime version source for AlphaBrief.

The value here must match ``project.version`` in ``pyproject.toml`` and
``version`` in ``electron/package.json``; ``scripts/build_release.sh``
refuses to build when they diverge.
"""

from __future__ import annotations

__version__ = "1.0.0-rc.1"

__all__ = ["__version__"]
