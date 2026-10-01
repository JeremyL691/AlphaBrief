"""Tests for the real policy/input hashing behind persisted decisions (S4-3).

PROJECT_GUIDE 5.7: every decision persists its rule results, an input
hash derived from the real snapshot content, and a policy hash derived
from the reviewed configuration file contents. A constant version string
or a timestamp is not a hash of anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core.policy_version import (
    POLICY_CONFIG_FILES,
    PolicyVersionError,
    default_policy_files,
    policy_version_hash,
    policy_version_label,
    project_root,
)
from alphabrief_risk.broker_context import (
    AccountStateDatum,
    BrokerRiskContext,
)
from alphabrief_trader.execution_backend import snapshot_content_hash

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _context(
    *,
    nav: Decimal = Decimal("100000"),
    captured_at: datetime = NOW,
) -> BrokerRiskContext:
    return BrokerRiskContext(
        account=AccountStateDatum(
            account_id="acct-1",
            state="open",
            tradeable=True,
            home_currency="USD",
        ),
        captured_at=captured_at,
        source_ids=("account:acct-1",),
        balance=nav,
        nav=nav,
        margin_used=Decimal("0"),
        margin_available=nav,
        catalog_version="catalog-1",
        reconciliation_state="clean",
        health_state="healthy",
    )


class TestPolicyVersionHash:
    def test_hash_covers_the_reviewed_config_files(self) -> None:
        files = default_policy_files()
        assert tuple(path.name for path in files) == tuple(
            Path(name).name for name in POLICY_CONFIG_FILES
        )
        digest = policy_version_hash()

        assert len(digest) == 64
        assert digest == policy_version_hash()
        assert policy_version_label().startswith("policy:")

    def test_changing_a_file_changes_the_hash(self, tmp_path: Path) -> None:
        first = tmp_path / "policy.yaml"
        second = tmp_path / "alphabrief.yaml"
        first.write_text("mode: paper\n")
        second.write_text("model: {}\n")
        before = policy_version_hash((first, second), root=tmp_path)

        second.write_text("model: {primary: x}\n")

        assert policy_version_hash((first, second), root=tmp_path) != before

    def test_missing_file_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(PolicyVersionError, match="missing"):
            policy_version_hash((tmp_path / "absent.yaml",), root=tmp_path)

    def test_empty_file_fails_closed(self, tmp_path: Path) -> None:
        empty = tmp_path / "policy.yaml"
        empty.write_text("   \n")

        with pytest.raises(PolicyVersionError, match="empty"):
            policy_version_hash((empty,), root=tmp_path)

    def test_project_root_is_discovered(self) -> None:
        root = project_root()

        assert (root / "pyproject.toml").is_file()
        assert all((root / name).is_file() for name in POLICY_CONFIG_FILES)


class TestSnapshotContentHash:
    def test_hash_tracks_real_content_not_time(self) -> None:
        base = snapshot_content_hash(_context())

        # The same facts hash identically.
        assert snapshot_content_hash(_context()) == base
        # Different account money is a different snapshot.
        assert snapshot_content_hash(_context(nav=Decimal("99999"))) != base
        # A different capture time alone is a different snapshot too.
        later = datetime(2026, 10, 1, 12, 1, tzinfo=UTC)
        assert snapshot_content_hash(_context(captured_at=later)) != base

    def test_hash_is_not_a_timestamp(self) -> None:
        digest = snapshot_content_hash(_context())

        assert len(digest) == 64
        assert NOW.isoformat() not in digest
        assert "2026" not in digest
