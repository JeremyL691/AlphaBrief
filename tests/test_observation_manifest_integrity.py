"""M16-W05: daily and weekly artifact hash integrity.

Covers AC-M16-W05-03: Day 30 validates every daily and weekly artifact
hash — 30 daily manifests plus 4 weekly gates, never accepting a
missing, blank, or duplicated hash.
"""

from __future__ import annotations

from alphabrief_core import (
    ManifestHashVerdict,
    validate_manifest_hashes,
)


def _full_hashes() -> dict[str, str]:
    return {
        f"day-{day:02d}": f"sha256:daily-{day:02d}"
        for day in range(1, 31)
    } | {
        f"week-{week}": f"sha256:weekly-{week}"
        for week in range(1, 5)
    }


class TestManifestIntegrity:
    def test_all_34_hashes_validate(self) -> None:
        verdict = validate_manifest_hashes(hashes=_full_hashes())
        assert isinstance(verdict, ManifestHashVerdict)
        assert verdict.valid is True
        assert verdict.count == 34

    def test_missing_hashes_fail_closed(self) -> None:
        verdict = validate_manifest_hashes(hashes={})
        assert verdict.valid is False
        assert verdict.count == 0

    def test_blank_hash_fails(self) -> None:
        hashes = _full_hashes()
        hashes["day-01"] = "   "
        verdict = validate_manifest_hashes(hashes=hashes)
        assert verdict.valid is False
        assert "day-01" in verdict.detail

    def test_duplicate_hash_fails(self) -> None:
        hashes = _full_hashes()
        hashes["week-4"] = hashes["week-3"]
        verdict = validate_manifest_hashes(hashes=hashes)
        assert verdict.valid is False
        assert "duplicate" in verdict.detail

    def test_wrong_count_fails(self) -> None:
        verdict = validate_manifest_hashes(hashes={"day-01": "sha256:x"})
        assert verdict.valid is False
        assert "expected 34" in verdict.detail

    def test_deterministic(self) -> None:
        first = validate_manifest_hashes(hashes=_full_hashes())
        second = validate_manifest_hashes(hashes=_full_hashes())
        assert first.model_dump() == second.model_dump()
