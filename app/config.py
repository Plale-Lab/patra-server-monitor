from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal


CheckKind = Literal["http", "tcp", "tls"]


@dataclass(slots=True)
class MonitorTarget:
    name: str
    kind: CheckKind
    url: str | None = None
    host: str | None = None
    port: int | None = None
    method: str = "GET"
    expected_status_codes: tuple[int, ...] = (200,)
    expected_json_field: str | None = None
    expected_json_value: str | None = None
    timeout_seconds: float = 10.0
    verify_tls: bool = True
    follow_redirects: bool = True


@dataclass(slots=True)
class Settings:
    telegram_bot_token: str
    db_path: str
    monitor_interval_seconds: int
    request_timeout_seconds: int
    telegram_poll_interval_seconds: int
    failure_threshold: int
    recovery_threshold: int
    reminder_interval_minutes: int
    targets: list[MonitorTarget]
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_from_email: str | None
    smtp_starttls: bool
    smtp_ssl: bool


def _default_targets(timeout_seconds: int) -> list[MonitorTarget]:
    return [
        MonitorTarget(
            name="patra",
            kind="http",
            url="https://patra.pods.icicleai.tapis.io/",
            timeout_seconds=timeout_seconds,
        ),
        MonitorTarget(
            name="patradev",
            kind="http",
            url="https://patradev.pods.icicleai.tapis.io/",
            timeout_seconds=timeout_seconds,
        ),
        MonitorTarget(
            name="patrabackend",
            kind="http",
            url="https://patrabackend.pods.icicleai.tapis.io/healthz",
            expected_json_field="status",
            expected_json_value="ok",
            timeout_seconds=timeout_seconds,
        ),
        MonitorTarget(
            name="patradb",
            kind="tls",
            host="patradb.pods.icicleai.tapis.io",
            port=443,
            timeout_seconds=timeout_seconds,
            verify_tls=False,
        ),
        MonitorTarget(
            name="patradbeaver",
            kind="http",
            url="https://patradbeaver.pods.icicleai.tapis.io/",
            expected_status_codes=(200, 302, 401, 403),
            timeout_seconds=timeout_seconds,
            follow_redirects=False,
        ),
    ]


def _parse_targets(raw: str | None, timeout_seconds: int) -> list[MonitorTarget]:
    if not raw:
        return _default_targets(timeout_seconds)

    payload = json.loads(raw)
    return [
        MonitorTarget(
            name=item["name"],
            kind=item["kind"],
            url=item.get("url"),
            host=item.get("host"),
            port=item.get("port"),
            method=item.get("method", "GET").upper(),
            expected_status_codes=tuple(item.get("expected_status_codes", [200])),
            expected_json_field=item.get("expected_json_field"),
            expected_json_value=item.get("expected_json_value"),
            timeout_seconds=float(item.get("timeout_seconds", timeout_seconds)),
            verify_tls=bool(item.get("verify_tls", True)),
            follow_redirects=bool(item.get("follow_redirects", True)),
        )
        for item in payload
    ]


def load_settings() -> Settings:
    timeout_seconds = int(os.getenv("MONITOR_REQUEST_TIMEOUT_SECONDS", "10"))
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required.")

    return Settings(
        telegram_bot_token=bot_token,
        db_path=os.getenv("MONITOR_DB_PATH", "/data/patra-monitor.db"),
        monitor_interval_seconds=int(os.getenv("MONITOR_INTERVAL_SECONDS", "30")),
        request_timeout_seconds=timeout_seconds,
        telegram_poll_interval_seconds=int(os.getenv("TELEGRAM_POLL_INTERVAL_SECONDS", "5")),
        failure_threshold=int(os.getenv("MONITOR_FAILURE_THRESHOLD", "2")),
        recovery_threshold=int(os.getenv("MONITOR_RECOVERY_THRESHOLD", "1")),
        reminder_interval_minutes=int(os.getenv("MONITOR_REMINDER_INTERVAL_MINUTES", "30")),
        targets=_parse_targets(os.getenv("MONITOR_TARGETS_JSON"), timeout_seconds),
        smtp_host=os.getenv("SMTP_HOST") or None,
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME") or None,
        smtp_password=os.getenv("SMTP_PASSWORD") or None,
        smtp_from_email=os.getenv("SMTP_FROM_EMAIL") or None,
        smtp_starttls=os.getenv("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes", "on"},
        smtp_ssl=os.getenv("SMTP_SSL", "false").lower() in {"1", "true", "yes", "on"},
    )
