from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.db import Database
from app.storage import MonitorStorage
from app.telegram_bot import TelegramBot


class TelegramBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "monitor.db"
        self.storage = MonitorStorage(Database(str(db_path)))
        self.bot = TelegramBot("test-token", self.storage)
        self.bot.send_message = AsyncMock()

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_start_auto_subscribes_chat(self) -> None:
        update = {
            "update_id": 1,
            "message": {
                "text": "/start",
                "chat": {"id": 1001},
                "from": {"username": "alice", "first_name": "Alice", "last_name": "Admin"},
            },
        }

        await self.bot.handle_update(
            update,
            status_renderer=lambda: "cached",
            active_status_checker=AsyncMock(return_value="checked"),
            services_renderer=lambda: "services",
            recent_events_renderer=lambda: "events",
            targets_renderer=lambda: "targets",
            target_upserter=lambda target: None,
            target_remover=lambda target_name: False,
        )

        subscribers = self.storage.active_subscribers()
        self.assertEqual(len(subscribers), 1)
        self.assertEqual(subscribers[0]["chat_id"], "1001")
        self.bot.send_message.assert_awaited()
        self.assertIn("notifications are now ON", self.bot.send_message.await_args.args[1])

    async def test_status_runs_active_checker(self) -> None:
        checker = AsyncMock(return_value="fresh report")
        update = {
            "update_id": 2,
            "message": {
                "text": "/status",
                "chat": {"id": 1002},
                "from": {"username": "bob", "first_name": "Bob"},
            },
        }

        await self.bot.handle_update(
            update,
            status_renderer=lambda: "cached",
            active_status_checker=checker,
            services_renderer=lambda: "services",
            recent_events_renderer=lambda: "events",
            targets_renderer=lambda: "targets",
            target_upserter=lambda target: None,
            target_remover=lambda target_name: False,
        )

        checker.assert_awaited_once()
        self.bot.send_message.assert_awaited_with("1002", "fresh report")


if __name__ == "__main__":
    unittest.main()
