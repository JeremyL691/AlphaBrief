"""M15-W02: durable alert lifecycle.

Covers AC-M15-W02-02/03: alerts persist severity, dedupe key, first
and last occurrence, count, acknowledgement, escalation, resolution,
incident link, and scrubbed evidence across restart; webhook or
external sink failure never deletes or resolves the local alert and
repeated equivalent events do not create an unbounded alert storm.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alphabrief_core import AlertStore

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> AlertStore:
    return AlertStore(path=tmp_path / "alerts.ndjson")


class TestAlertPersistence:
    def test_alert_persists_full_state(self, store: AlertStore) -> None:
        alert = store.raise_alert(
            dedupe_key="cycle:failed:2026-08-14",
            severity="critical",
            evidence={"cycle_id": "cycle-1", "detail": "cycle failed"},
            incident_link="incident-1",
            now=NOW,
        )
        assert alert.severity == "critical"
        assert alert.dedupe_key == "cycle:failed:2026-08-14"
        assert alert.first_occurrence == alert.last_occurrence
        assert alert.count == 1
        assert alert.incident_link == "incident-1"
        assert alert.evidence == {"cycle_id": "cycle-1", "detail": "cycle failed"}

    def test_evidence_is_scrubbed(self, store: AlertStore) -> None:
        full_id = "account-" + "12345678901234567890"
        alert = store.raise_alert(
            dedupe_key="secrets:1",
            severity="warning",
            evidence={"account_id": full_id, "token": "Bearer " + "abc123"},
            now=NOW,
        )
        assert full_id not in str(alert.evidence)
        assert "abc123" not in str(alert.evidence)

    def test_state_transitions(self, store: AlertStore) -> None:
        alert = store.raise_alert(dedupe_key="k1", severity="warning", now=NOW)
        assert store.acknowledge(alert.alert_id).acknowledged is True
        assert store.escalate(alert.alert_id).escalated is True
        assert store.resolve(alert.alert_id).resolved is True

    def test_unknown_alert_raises(self, store: AlertStore) -> None:
        with pytest.raises(KeyError, match="unknown alert"):
            store.acknowledge("alert_9999")

    def test_survives_restart(self, tmp_path: Path) -> None:
        path = tmp_path / "alerts.ndjson"
        first = AlertStore(path=path)
        alert = first.raise_alert(dedupe_key="k1", severity="critical", now=NOW)
        first.acknowledge(alert.alert_id)
        # A new store over the same file sees the persisted state.
        reopened = AlertStore(path=path)
        restored = reopened.get(alert.alert_id)
        assert restored is not None
        assert restored.acknowledged is True
        assert restored.severity == "critical"


class TestDedupeAndStorm:
    def test_repeated_events_dedupe_not_storm(self, store: AlertStore) -> None:
        first = store.raise_alert(dedupe_key="k1", severity="warning", now=NOW)
        for _ in range(50):
            store.raise_alert(dedupe_key="k1", severity="warning", now=NOW)
        alerts = store.list_alerts()
        assert len(alerts) == 1
        assert alerts[0].count == 51
        assert alerts[0].alert_id == first.alert_id

    def test_distinct_keys_create_distinct_alerts(self, store: AlertStore) -> None:
        store.raise_alert(dedupe_key="k1", severity="warning", now=NOW)
        store.raise_alert(dedupe_key="k2", severity="critical", now=NOW)
        assert len(store.list_alerts()) == 2

    def test_sink_failure_never_deletes_or_resolves(
        self, store: AlertStore
    ) -> None:
        alert = store.raise_alert(dedupe_key="k1", severity="critical", now=NOW)
        preserved = store.sink_failure(alert.alert_id)
        assert preserved.resolved is False
        assert preserved.acknowledged is False
        assert store.get(alert.alert_id) is not None

    def test_resolution_is_explicit_only(self, store: AlertStore) -> None:
        alert = store.raise_alert(dedupe_key="k1", severity="warning", now=NOW)
        store.raise_alert(dedupe_key="k1", severity="warning", now=NOW)
        # Repeated events refresh occurrence, never auto-resolve.
        current = store.get(alert.alert_id)
        assert current is not None
        assert current.resolved is False
        assert current.count == 2

    def test_list_is_ordered_and_deterministic(self, store: AlertStore) -> None:
        store.raise_alert(dedupe_key="b", severity="warning", now=NOW)
        store.raise_alert(dedupe_key="a", severity="warning", now=NOW)
        alerts = store.list_alerts()
        assert [a.alert_id for a in alerts] == sorted(
            a.alert_id for a in alerts
        )
