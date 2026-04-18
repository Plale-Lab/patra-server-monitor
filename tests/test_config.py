from __future__ import annotations

import json
import os
import unittest
from contextlib import contextmanager

from app.config import load_settings


@contextmanager
def patched_environ(values: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class LoadSettingsTests(unittest.TestCase):
    def test_load_settings_uses_default_targets(self) -> None:
        with patched_environ(
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "MONITOR_DB_PATH": "D:/temp/patra-monitor-test.db",
                "MONITOR_TARGETS_JSON": None,
            }
        ):
            settings = load_settings()

        self.assertEqual(settings.telegram_bot_token, "test-token")
        self.assertEqual(len(settings.targets), 5)
        self.assertEqual(settings.targets[0].name, "patra")
        self.assertEqual(settings.targets[1].name, "patradev")
        self.assertEqual(settings.targets[2].expected_json_field, "status")
        self.assertEqual(settings.targets[2].expected_json_value, "ok")
        self.assertEqual(settings.targets[3].kind, "tls")
        self.assertEqual(settings.targets[3].port, 443)
        self.assertFalse(settings.targets[3].verify_tls)
        self.assertFalse(settings.targets[4].follow_redirects)
        self.assertEqual(settings.targets[4].expected_status_codes, (200, 302, 401, 403))

    def test_load_settings_parses_custom_targets(self) -> None:
        payload = json.dumps(
            [
                {
                    "name": "custom-http",
                    "kind": "http",
                    "url": "https://example.com/healthz",
                    "expected_status_codes": [200, 204],
                    "expected_json_field": "status",
                    "expected_json_value": "ok",
                    "verify_tls": False,
                },
                {
                    "name": "custom-tcp",
                    "kind": "tcp",
                    "host": "localhost",
                    "port": 5432,
                },
            ]
        )
        with patched_environ(
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "MONITOR_DB_PATH": "D:/temp/patra-monitor-test.db",
                "MONITOR_TARGETS_JSON": payload,
            }
        ):
            settings = load_settings()

        self.assertEqual(len(settings.targets), 2)
        self.assertEqual(settings.targets[0].expected_status_codes, (200, 204))
        self.assertFalse(settings.targets[0].verify_tls)
        self.assertTrue(settings.targets[0].follow_redirects)
        self.assertEqual(settings.targets[1].host, "localhost")
        self.assertEqual(settings.targets[1].port, 5432)


if __name__ == "__main__":
    unittest.main()
