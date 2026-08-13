"""M16-W01: Day 0 commissioning.

Covers AC-M16-W01-01/03: the Day 0 manifest fixes commit and tree
hashes, schema and config versions, dependency hashes, provider
profiles, account hash, catalog version, timezone, start timestamps,
and one unique observation ID — created only after all gates succeed;
missing checks record BLOCKED_EXTERNAL without manufacturing a pass.
"""

from __future__ import annotations

from datetime import date

from alphabrief_core import (
    ObservationManifest,
    build_day_zero_attempt,
)

MANIFEST_FIELDS = {
    "observation_id": "obs-abc123",
    "commit_hash": "c0ffee",
    "tree_hash": "tree123",
    "schema_version": "read-v1",
    "config_version": "2026-08-13.1",
    "dependency_hash": "dep123",
    "provider_profile": "oanda-practice",
    "account_hash": "acc123",
    "catalog_version": "cat-v1",
    "timezone": "UTC",
    "start_timestamp": "2026-08-14T00:00:00+00:00",
}


def _all_gates() -> dict[str, bool]:
    return {
        "engineering_readiness": True,
        "observation_preflight": True,
        "practice_e2e": True,
        "clean_reconciliation": True,
        "isolated_restore": True,
    }


class TestManifestFields:
    def test_manifest_fixes_all_day_zero_fields(self) -> None:
        attempt = build_day_zero_attempt(
            today=date(2026, 8, 14),
            rehearsal_dates=(date(2026, 8, 12),),
            gates=_all_gates(),
            manifest_fields=MANIFEST_FIELDS,
        )
        assert attempt.ready
        manifest = attempt.manifest
        assert manifest is not None
        assert isinstance(manifest, ObservationManifest)
        assert manifest.observation_id == "obs-abc123"
        assert manifest.commit_hash == "c0ffee"
        assert manifest.tree_hash == "tree123"
        assert manifest.schema_version == "read-v1"
        assert manifest.config_version == "2026-08-13.1"
        assert manifest.dependency_hash == "dep123"
        assert manifest.provider_profile == "oanda-practice"
        assert manifest.account_hash == "acc123"
        assert manifest.catalog_version == "cat-v1"
        assert manifest.timezone == "UTC"
        assert manifest.start_timestamp == "2026-08-14T00:00:00+00:00"
        assert manifest.day_zero_date == "2026-08-14"

    def test_observation_id_is_unique_per_manifest(self) -> None:
        first = build_day_zero_attempt(
            today=date(2026, 8, 14),
            rehearsal_dates=(date(2026, 8, 12),),
            gates=_all_gates(),
            manifest_fields={**MANIFEST_FIELDS, "observation_id": "obs-1"},
        )
        second = build_day_zero_attempt(
            today=date(2026, 8, 14),
            rehearsal_dates=(date(2026, 8, 12),),
            gates=_all_gates(),
            manifest_fields={**MANIFEST_FIELDS, "observation_id": "obs-2"},
        )
        assert first.manifest is not None
        assert second.manifest is not None
        assert first.manifest.observation_id != second.manifest.observation_id


class TestBlockerRecording:
    def test_failed_gate_blocks_without_manifest(self) -> None:
        gates = _all_gates()
        gates["practice_e2e"] = False
        attempt = build_day_zero_attempt(
            today=date(2026, 8, 14),
            rehearsal_dates=(date(2026, 8, 12),),
            gates=gates,
            manifest_fields=MANIFEST_FIELDS,
        )
        assert not attempt.ready
        assert attempt.manifest is None
        assert any("practice_e2e" in b for b in attempt.blockers)

    def test_multiple_failures_record_all_blockers(self) -> None:
        gates = {
            "engineering_readiness": False,
            "observation_preflight": False,
            "practice_e2e": False,
            "clean_reconciliation": False,
            "isolated_restore": False,
        }
        attempt = build_day_zero_attempt(
            today=date(2026, 8, 14),
            rehearsal_dates=(date(2026, 8, 12),),
            gates=gates,
            manifest_fields=MANIFEST_FIELDS,
        )
        assert not attempt.ready
        assert len(attempt.blockers) == 5

    def test_blockers_never_manufacture_a_pass(self) -> None:
        attempt = build_day_zero_attempt(
            today=date(2026, 8, 14),
            rehearsal_dates=(date(2026, 8, 14),),  # today is rehearsal
            gates=_all_gates(),
            manifest_fields=MANIFEST_FIELDS,
        )
        assert not attempt.ready
        assert attempt.manifest is None
        assert any("clock cannot start" in b for b in attempt.blockers)

    def test_deterministic(self) -> None:
        first = build_day_zero_attempt(
            today=date(2026, 8, 14),
            rehearsal_dates=(date(2026, 8, 12),),
            gates=_all_gates(),
            manifest_fields=MANIFEST_FIELDS,
        )
        second = build_day_zero_attempt(
            today=date(2026, 8, 14),
            rehearsal_dates=(date(2026, 8, 12),),
            gates=_all_gates(),
            manifest_fields=MANIFEST_FIELDS,
        )
        assert first.model_dump() == second.model_dump()
