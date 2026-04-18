from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import MonitorTarget
from .db import Database


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class StoredTargetState:
    target_name: str
    severity: str
    status_text: str
    latency_ms: float | None
    last_checked_at: str
    last_changed_at: str
    consecutive_failures: int
    consecutive_successes: int
    last_alerted_at: str | None
    details_json: dict[str, Any]


class MonitorStorage:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_subscriber(self, chat_id: str, username: str | None, first_name: str | None, last_name: str | None) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO subscribers (chat_id, username, first_name, last_name, is_active)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(chat_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    is_active = 1
                """,
                (chat_id, username, first_name, last_name),
            )
            conn.commit()

    def deactivate_subscriber(self, chat_id: str) -> None:
        with self.db.connection() as conn:
            conn.execute("UPDATE subscribers SET is_active = 0 WHERE chat_id = ?", (chat_id,))
            conn.commit()

    def active_subscribers(self) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT chat_id, username, first_name, last_name, subscribed_at, email, email_notifications_enabled
                FROM subscribers
                WHERE is_active = 1
                ORDER BY subscribed_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def set_subscriber_email(self, chat_id: str, email: str, enabled: bool = True) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE subscribers
                SET email = ?, email_notifications_enabled = ?
                WHERE chat_id = ?
                """,
                (email, 1 if enabled else 0, chat_id),
            )
            conn.commit()

    def set_email_notifications_enabled(self, chat_id: str, enabled: bool) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE subscribers
                SET email_notifications_enabled = ?
                WHERE chat_id = ?
                """,
                (1 if enabled else 0, chat_id),
            )
            conn.commit()

    def get_subscriber(self, chat_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT chat_id, username, first_name, last_name, subscribed_at, is_active, email, email_notifications_enabled
                FROM subscribers
                WHERE chat_id = ?
                """,
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def active_email_subscribers(self) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT chat_id, username, first_name, last_name, subscribed_at, email
                FROM subscribers
                WHERE is_active = 1
                  AND email_notifications_enabled = 1
                  AND email IS NOT NULL
                  AND TRIM(email) <> ''
                ORDER BY subscribed_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_offset(self) -> int:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT update_offset FROM telegram_offsets WHERE singleton_key = 'telegram'"
            ).fetchone()
        return int(row["update_offset"]) if row else 0

    def set_offset(self, offset: int) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO telegram_offsets (singleton_key, update_offset)
                VALUES ('telegram', ?)
                ON CONFLICT(singleton_key) DO UPDATE SET update_offset = excluded.update_offset
                """,
                (offset,),
            )
            conn.commit()

    def get_state(self, target_name: str) -> StoredTargetState | None:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT target_name, severity, status_text, latency_ms, last_checked_at, last_changed_at,
                       consecutive_failures, consecutive_successes, last_alerted_at, details_json
                FROM monitor_state
                WHERE target_name = ?
                """,
                (target_name,),
            ).fetchone()
        if not row:
            return None
        return StoredTargetState(
            target_name=row["target_name"],
            severity=row["severity"],
            status_text=row["status_text"],
            latency_ms=row["latency_ms"],
            last_checked_at=row["last_checked_at"],
            last_changed_at=row["last_changed_at"],
            consecutive_failures=row["consecutive_failures"],
            consecutive_successes=row["consecutive_successes"],
            last_alerted_at=row["last_alerted_at"],
            details_json=json.loads(row["details_json"] or "{}"),
        )

    def list_states(self, include_inactive: bool = False) -> list[StoredTargetState]:
        query = """
            SELECT ms.target_name, ms.severity, ms.status_text, ms.latency_ms, ms.last_checked_at, ms.last_changed_at,
                   ms.consecutive_failures, ms.consecutive_successes, ms.last_alerted_at, ms.details_json
            FROM monitor_state ms
        """
        if not include_inactive:
            query += """
                INNER JOIN monitor_targets mt
                  ON mt.target_name = ms.target_name
                 AND mt.is_active = 1
            """
        query += " ORDER BY ms.target_name ASC"
        with self.db.connection() as conn:
            rows = conn.execute(query).fetchall()
        return [
            StoredTargetState(
                target_name=row["target_name"],
                severity=row["severity"],
                status_text=row["status_text"],
                latency_ms=row["latency_ms"],
                last_checked_at=row["last_checked_at"],
                last_changed_at=row["last_changed_at"],
                consecutive_failures=row["consecutive_failures"],
                consecutive_successes=row["consecutive_successes"],
                last_alerted_at=row["last_alerted_at"],
                details_json=json.loads(row["details_json"] or "{}"),
            )
            for row in rows
        ]

    def save_state(self, state: StoredTargetState) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO monitor_state (
                    target_name, severity, status_text, latency_ms, last_checked_at, last_changed_at,
                    consecutive_failures, consecutive_successes, last_alerted_at, details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(target_name) DO UPDATE SET
                    severity = excluded.severity,
                    status_text = excluded.status_text,
                    latency_ms = excluded.latency_ms,
                    last_checked_at = excluded.last_checked_at,
                    last_changed_at = excluded.last_changed_at,
                    consecutive_failures = excluded.consecutive_failures,
                    consecutive_successes = excluded.consecutive_successes,
                    last_alerted_at = excluded.last_alerted_at,
                    details_json = excluded.details_json
                """,
                (
                    state.target_name,
                    state.severity,
                    state.status_text,
                    state.latency_ms,
                    state.last_checked_at,
                    state.last_changed_at,
                    state.consecutive_failures,
                    state.consecutive_successes,
                    state.last_alerted_at,
                    json.dumps(state.details_json),
                ),
            )
            conn.commit()

    def delete_state(self, target_name: str) -> None:
        with self.db.connection() as conn:
            conn.execute("DELETE FROM monitor_state WHERE target_name = ?", (target_name,))
            conn.execute("DELETE FROM monitor_events WHERE target_name = ?", (target_name,))
            conn.commit()

    def log_event(self, target_name: str, severity: str, status_text: str, details_json: dict[str, Any]) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO monitor_events (target_name, severity, status_text, details_json)
                VALUES (?, ?, ?, ?)
                """,
                (target_name, severity, status_text, json.dumps(details_json)),
            )
            conn.commit()

    def ensure_targets(self, targets: list[MonitorTarget]) -> None:
        legacy_aliases = {
            "patra-dev": "patradev",
        }
        with self.db.connection() as conn:
            for target in targets:
                config_json = self._target_to_json(target)
                conn.execute(
                    """
                    INSERT INTO monitor_targets (target_name, kind, config_json, is_active, updated_at)
                    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(target_name) DO UPDATE SET
                        kind = excluded.kind,
                        config_json = excluded.config_json,
                        is_active = 1,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (target.name, target.kind, config_json),
                )
            for alias_name, canonical_name in legacy_aliases.items():
                alias_row = conn.execute(
                    "SELECT target_name FROM monitor_targets WHERE target_name = ?",
                    (alias_name,),
                ).fetchone()
                canonical_row = conn.execute(
                    "SELECT target_name FROM monitor_targets WHERE target_name = ? AND is_active = 1",
                    (canonical_name,),
                ).fetchone()
                if alias_row and canonical_row:
                    conn.execute(
                        "UPDATE monitor_targets SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE target_name = ?",
                        (alias_name,),
                    )
            conn.commit()
        for alias_name, canonical_name in legacy_aliases.items():
            if self.get_target(canonical_name):
                self.delete_state(alias_name)

    def upsert_target(self, target: MonitorTarget, is_active: bool = True) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO monitor_targets (target_name, kind, config_json, is_active, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(target_name) DO UPDATE SET
                    kind = excluded.kind,
                    config_json = excluded.config_json,
                    is_active = excluded.is_active,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (target.name, target.kind, self._target_to_json(target), 1 if is_active else 0),
            )
            conn.commit()

    def delete_target(self, target_name: str) -> bool:
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM monitor_targets WHERE target_name = ?", (target_name,))
            conn.commit()
        return cursor.rowcount > 0

    def list_targets(self, include_inactive: bool = False) -> list[MonitorTarget]:
        query = """
            SELECT target_name, kind, config_json, is_active
            FROM monitor_targets
        """
        params: tuple[Any, ...] = ()
        if not include_inactive:
            query += " WHERE is_active = 1"
        query += " ORDER BY target_name ASC"
        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._target_from_row(dict(row)) for row in rows]

    def get_target(self, target_name: str) -> MonitorTarget | None:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT target_name, kind, config_json, is_active
                FROM monitor_targets
                WHERE target_name = ?
                """,
                (target_name,),
            ).fetchone()
        return self._target_from_row(dict(row)) if row else None

    def touch_alert_time(self, target_name: str, alerted_at: str | None = None) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE monitor_state SET last_alerted_at = ? WHERE target_name = ?",
                (alerted_at or utc_now_iso(), target_name),
            )
            conn.commit()

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, target_name, severity, status_text, created_at, details_json
                FROM monitor_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            payload = dict(row)
            payload["details_json"] = json.loads(payload["details_json"] or "{}")
            items.append(payload)
        return items

    def _target_to_json(self, target: MonitorTarget) -> str:
        return json.dumps(
            {
                "url": target.url,
                "host": target.host,
                "port": target.port,
                "method": target.method,
                "expected_status_codes": list(target.expected_status_codes),
                "expected_json_field": target.expected_json_field,
                "expected_json_value": target.expected_json_value,
                "timeout_seconds": target.timeout_seconds,
                "verify_tls": target.verify_tls,
                "follow_redirects": target.follow_redirects,
            }
        )

    def _target_from_row(self, row: dict[str, Any]) -> MonitorTarget:
        payload = json.loads(row.get("config_json") or "{}")
        return MonitorTarget(
            name=row["target_name"],
            kind=row["kind"],
            url=payload.get("url"),
            host=payload.get("host"),
            port=payload.get("port"),
            method=payload.get("method", "GET"),
            expected_status_codes=tuple(payload.get("expected_status_codes", [200])),
            expected_json_field=payload.get("expected_json_field"),
            expected_json_value=payload.get("expected_json_value"),
            timeout_seconds=float(payload.get("timeout_seconds", 10.0)),
            verify_tls=bool(payload.get("verify_tls", True)),
            follow_redirects=bool(payload.get("follow_redirects", True)),
        )
