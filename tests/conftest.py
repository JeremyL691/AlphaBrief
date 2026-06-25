"""Top-level conftest for the ``tests/`` directory.

Adds the ``tests/`` directory itself to ``sys.path`` so that helpers under
``tests/_helpers/`` can be imported as ``_helpers.*`` (the pytest-recommended
way to expose shared fixtures without making ``tests/`` an importable
package). This is the minimum surface needed to keep existing test files
working without changing their public import surface or growing the rootdir
package layout.

This file intentionally does not import any application code; pytest
discovers it automatically before any test module is collected.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_TESTS_DIR_STR = str(_TESTS_DIR)

# Insert at position 1 so that project source directories (added by
# ``pyproject.toml`` ``pythonpath``) still win for application imports, but
# ``tests/`` is visible as a top-level entry for helper imports.
if _TESTS_DIR_STR not in sys.path:
    sys.path.insert(1, _TESTS_DIR_STR)
