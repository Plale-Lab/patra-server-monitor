from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import MonitorTarget, Settings
from app.db import Database
from app.email_notifier import EmailNotifier
from app.monitor import MonitorEngine
from app.storage import MonitorStorage


class MonitorEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "monitor.db"
        self.storage = MonitorStorage(Database(str(db_path)))
        self.settings = Settings(
            telegram_bot_token="test-token",
            db_path=str(db_path),
            monitor_interval_seconds=30,
            request_timeout_seconds=10,
            telegram_poll_interval_seconds=5,
            failure_threshold=2,
            recovery_threshold=1,
            reminder_interval_minutes=30,
            targets=[
                MonitorTarget(
                    name="patrabackend",
                    kind="http",
                    url="https://example.com/healthz",
                )
            ],
            smtp_host=None,
            smtp_port=587,
            smtp_username=None,
            smtp_password=None,
            smtp_from_email=None,
            smtp_starttls=True,
            smtp_ssl=False,
        )
        self.bot = AsyncMock()
        self.storage.ensure_targets(self.settings.targets)
        self.email_notifier = AsyncMock(spec=EmailNotifier)
        self.engine = MonitorEngine(self.settings, self.storage, self.bot, self.email_notifier)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_alerts_after_threshold_and_recovers(self) -> None:
        target = self.settings.targets[0]

        down_result = type(
            "CheckResult",
            (),
            {
                "severity": "down",
                "status_text": "HTTP timeout",
                "latency_ms": None,
                "details": {"url": target.url},
            },
        )()
        healthy_result = type(
            "CheckResult",
            (),
            {
                "severity": "healthy",
                "status_text": "HTTP 200",
                "latency_ms": 12.3,
                "details": {"url": target.url},
            },
        )()

        with patch("app.monitor.run_check", new=AsyncMock(side_effect=[down_result, down_result, healthy_result])):
            decision1 = await self.engine.check_target(target)
            decision2 = await self.engine.check_target(target)
            decision3 = await self.engine.check_target(target)

        self.assertFalse(decision1.should_alert)
        self.assertTrue(decision2.should_alert)
        self.assertIn("is down", decision2.alert_text or "")
        self.assertTrue(decision3.should_alert)
        self.assertIn("healthy again", decision3.alert_text or "")

        events = self.storage.recent_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["severity"], "healthy")
        self.assertEqual(events[1]["severity"], "down")


if __name__ == "__main__":
    unittest.main()
