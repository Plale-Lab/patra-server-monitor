from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.config import MonitorTarget
from app.storage import MonitorStorage, StoredTargetState


class MonitorStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "monitor.db"
        self.storage = MonitorStorage(Database(str(db_path)))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_subscriber_lifecycle(self) -> None:
        self.storage.upsert_subscriber("1001", "alice", "Alice", "Admin")
        self.storage.upsert_subscriber("1002", "bob", "Bob", None)

        subscribers = self.storage.active_subscribers()
        self.assertEqual(len(subscribers), 2)
        self.assertEqual(subscribers[0]["chat_id"], "1001")

        self.storage.deactivate_subscriber("1002")
        subscribers = self.storage.active_subscribers()
        self.assertEqual(len(subscribers), 1)
        self.assertEqual(subscribers[0]["chat_id"], "1001")

    def test_email_preferences_and_target_management(self) -> None:
        self.storage.upsert_subscriber("1001", "alice", "Alice", "Admin")
        self.storage.set_subscriber_email("1001", "alice@example.org", enabled=True)

        subscriber = self.storage.get_subscriber("1001")
        self.assertEqual(subscriber["email"], "alice@example.org")
        self.assertEqual(subscriber["email_notifications_enabled"], 1)

        email_subscribers = self.storage.active_email_subscribers()
        self.assertEqual(len(email_subscribers), 1)
        self.assertEqual(email_subscribers[0]["email"], "alice@example.org")

        target = MonitorTarget(name="patradb", kind="tls", host="db.example.org", port=443)
        self.storage.ensure_targets([target])
        self.assertEqual(len(self.storage.list_targets()), 1)

        updated_target = MonitorTarget(name="patradb", kind="tcp", host="db.example.org", port=5432)
        self.storage.upsert_target(updated_target)
        loaded_target = self.storage.get_target("patradb")
        self.assertEqual(loaded_target.kind, "tcp")
        self.assertEqual(loaded_target.port, 5432)

        removed = self.storage.delete_target("patradb")
        self.assertTrue(removed)
        self.assertEqual(self.storage.list_targets(), [])

    def test_legacy_alias_is_deactivated_when_canonical_target_exists(self) -> None:
        legacy_target = MonitorTarget(name="patra-dev", kind="http", url="https://legacy.example.org/")
        canonical_target = MonitorTarget(name="patradev", kind="http", url="https://current.example.org/")
        self.storage.upsert_target(legacy_target)
        self.storage.save_state(
            StoredTargetState(
                target_name="patra-dev",
                severity="down",
                status_text="legacy failure",
                latency_ms=None,
                last_checked_at="2026-03-30T20:00:00+00:00",
                last_changed_at="2026-03-30T20:00:00+00:00",
                consecutive_failures=3,
                consecutive_successes=0,
                last_alerted_at=None,
                details_json={"url": legacy_target.url},
            )
        )

        self.storage.ensure_targets([canonical_target])

        active_names = [target.name for target in self.storage.list_targets()]
        all_names = [target.name for target in self.storage.list_targets(include_inactive=True)]
        self.assertIn("patradev", active_names)
        self.assertNotIn("patra-dev", active_names)
        self.assertIn("patra-dev", all_names)
        self.assertIsNone(self.storage.get_state("patra-dev"))

    def test_state_round_trip_and_event_log(self) -> None:
        state = StoredTargetState(
            target_name="patrabackend",
            severity="down",
            status_text="HTTP timeout",
            latency_ms=None,
            last_checked_at="2026-03-27T10:00:00+00:00",
            last_changed_at="2026-03-27T10:00:00+00:00",
            consecutive_failures=2,
            consecutive_successes=0,
            last_alerted_at=None,
            details_json={"url": "https://patrabackend.example/healthz"},
        )
        self.storage.save_state(state)
        self.storage.log_event(
            target_name="patrabackend",
            severity="down",
            status_text="HTTP timeout",
            details_json={"reason": "timeout"},
        )

        stored = self.storage.get_state("patrabackend")
        self.assertIsNotNone(stored)
        self.assertEqual(stored.severity, "down")
        self.assertEqual(stored.details_json["url"], "https://patrabackend.example/healthz")

        events = self.storage.recent_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "down")
        self.assertEqual(events[0]["details_json"]["reason"], "timeout")


if __name__ == "__main__":
    unittest.main()
