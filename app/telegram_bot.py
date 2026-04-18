from __future__ import annotations

from typing import Any

import httpx

from .config import MonitorTarget
from .storage import MonitorStorage


class TelegramBot:
    def __init__(self, token: str, storage: MonitorStorage) -> None:
        self.token = token
        self.storage = storage
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def get_updates(self, offset: int, timeout_seconds: int = 30) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=timeout_seconds + 10) as client:
            response = await client.get(
                f"{self.base_url}/getUpdates",
                params={"offset": offset, "timeout": timeout_seconds},
            )
            response.raise_for_status()
            payload = response.json()
            return payload.get("result", [])

    async def send_message(self, chat_id: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()

    async def broadcast(self, text: str) -> None:
        for subscriber in self.storage.active_subscribers():
            try:
                await self.send_message(str(subscriber["chat_id"]), text)
            except Exception:
                continue

    async def handle_update(
        self,
        update: dict[str, Any],
        *,
        status_renderer,
        active_status_checker,
        services_renderer,
        recent_events_renderer,
        targets_renderer,
        target_upserter,
        target_remover,
    ) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id"))
        text = (message.get("text") or "").strip()
        from_user = message.get("from") or {}
        if not chat_id or not text.startswith("/"):
            return

        command, _, arguments = text.partition(" ")
        arguments = arguments.strip()

        if command == "/help":
            await self.send_message(chat_id, self._help_text())
            return

        if command == "/start":
            self.storage.upsert_subscriber(
                chat_id=chat_id,
                username=from_user.get("username"),
                first_name=from_user.get("first_name"),
                last_name=from_user.get("last_name"),
            )
            await self.send_message(
                chat_id,
                "PATRA server monitor bot is running and notifications are now ON for this chat.\n\n"
                + self._help_text(),
            )
            return

        if command in {"/subscribe", "/notification_on", "/notifacation_on"}:
            self.storage.upsert_subscriber(
                chat_id=chat_id,
                username=from_user.get("username"),
                first_name=from_user.get("first_name"),
                last_name=from_user.get("last_name"),
            )
            await self.send_message(chat_id, "Subscribed. You will now receive PATRA pod alerts and recovery notices.")
            return

        if command in {"/unsubscribe", "/notification_off", "/notifacation_off"}:
            self.storage.deactivate_subscriber(chat_id)
            await self.send_message(chat_id, "Unsubscribed. You will no longer receive PATRA pod alerts.")
            return

        if command == "/status":
            report = await active_status_checker()
            await self.send_message(chat_id, report)
            return

        if command == "/services":
            await self.send_message(chat_id, services_renderer())
            return

        if command == "/events":
            await self.send_message(chat_id, recent_events_renderer())
            return

        if command == "/subscribers":
            count = len(self.storage.active_subscribers())
            await self.send_message(chat_id, f"Active monitor subscribers: {count}")
            return

        if command == "/email":
            if not arguments or "@" not in arguments:
                await self.send_message(chat_id, "Usage: /email your.name@example.org")
                return
            self.storage.set_subscriber_email(chat_id, arguments, enabled=True)
            await self.send_message(chat_id, f"Email alerts enabled for {arguments}")
            return

        if command == "/email_on":
            subscriber = self.storage.get_subscriber(chat_id)
            if not subscriber or not subscriber.get("email"):
                await self.send_message(chat_id, "No email saved yet. Use /email your.name@example.org first.")
                return
            self.storage.set_email_notifications_enabled(chat_id, True)
            await self.send_message(chat_id, f"Email alerts re-enabled for {subscriber['email']}")
            return

        if command == "/email_off":
            self.storage.set_email_notifications_enabled(chat_id, False)
            await self.send_message(chat_id, "Email alerts disabled for this chat.")
            return

        if command == "/email_status":
            subscriber = self.storage.get_subscriber(chat_id)
            if not subscriber or not subscriber.get("email"):
                await self.send_message(chat_id, "No email registered for this chat.")
                return
            enabled = bool(subscriber.get("email_notifications_enabled"))
            state_text = "ON" if enabled else "OFF"
            await self.send_message(chat_id, f"Email alerts are {state_text} for {subscriber['email']}")
            return

        if command == "/targets":
            await self.send_message(chat_id, targets_renderer())
            return

        if command == "/target_remove":
            if not arguments:
                await self.send_message(chat_id, "Usage: /target_remove target_name")
                return
            removed = target_remover(arguments)
            if removed:
                await self.send_message(chat_id, f"Removed target `{arguments}` from the monitor list.")
            else:
                await self.send_message(chat_id, f"Target `{arguments}` was not found.")
            return

        if command == "/target_http":
            target = self._parse_target_http(arguments, verify_tls=True, follow_redirects=True)
            if not target:
                await self.send_message(chat_id, "Usage: /target_http name https://service.example")
                return
            target_upserter(target)
            await self.send_message(chat_id, f"Added HTTP target `{target.name}` -> {target.url}")
            return

        if command == "/target_http_insecure":
            target = self._parse_target_http(arguments, verify_tls=False, follow_redirects=True)
            if not target:
                await self.send_message(chat_id, "Usage: /target_http_insecure name https://service.example")
                return
            target_upserter(target)
            await self.send_message(chat_id, f"Added insecure-HTTP target `{target.name}` -> {target.url}")
            return

        if command == "/target_http_auth":
            target = self._parse_target_http(
                arguments,
                verify_tls=True,
                follow_redirects=False,
                expected_status_codes=(200, 302, 401, 403),
            )
            if not target:
                await self.send_message(chat_id, "Usage: /target_http_auth name https://service.example")
                return
            target_upserter(target)
            await self.send_message(chat_id, f"Added auth-protected HTTP target `{target.name}` -> {target.url}")
            return

        if command == "/target_tcp":
            target = self._parse_target_socket(arguments, kind="tcp")
            if not target:
                await self.send_message(chat_id, "Usage: /target_tcp name host port")
                return
            target_upserter(target)
            await self.send_message(chat_id, f"Added TCP target `{target.name}` -> {target.host}:{target.port}")
            return

        if command == "/target_tls":
            target = self._parse_target_socket(arguments, kind="tls")
            if not target:
                await self.send_message(chat_id, "Usage: /target_tls name host port")
                return
            target_upserter(target)
            await self.send_message(chat_id, f"Added TLS target `{target.name}` -> {target.host}:{target.port}")
            return

        await self.send_message(chat_id, self._help_text())

    def _parse_target_http(
        self,
        arguments: str,
        *,
        verify_tls: bool,
        follow_redirects: bool,
        expected_status_codes: tuple[int, ...] = (200,),
    ) -> MonitorTarget | None:
        parts = arguments.split()
        if len(parts) != 2:
            return None
        name, url = parts
        return MonitorTarget(
            name=name,
            kind="http",
            url=url,
            expected_status_codes=expected_status_codes,
            verify_tls=verify_tls,
            follow_redirects=follow_redirects,
        )

    def _parse_target_socket(self, arguments: str, *, kind: str) -> MonitorTarget | None:
        parts = arguments.split()
        if len(parts) != 3:
            return None
        name, host, port_text = parts
        try:
            port = int(port_text)
        except ValueError:
            return None
        return MonitorTarget(name=name, kind=kind, host=host, port=port)

    def _help_text(self) -> str:
        return (
            "Available commands:\n"
            "/status - run an immediate health check across all monitored targets\n"
            "/services - show the latest known status for each monitored target\n"
            "/events - show the most recent abnormal monitor events\n"
            "/targets - list configured monitor targets\n"
            "/target_http name https://service - add/update an HTTP target\n"
            "/target_http_insecure name https://service - add/update an HTTP target without TLS verification\n"
            "/target_http_auth name https://service - add/update an auth-protected HTTP target that may return 302/401/403\n"
            "/target_tcp name host port - add/update a TCP target\n"
            "/target_tls name host port - add/update a TLS handshake target\n"
            "/target_remove name - remove a target from monitoring\n"
            "/notification_on - enable Telegram alerts for this chat\n"
            "/notification_off - disable Telegram alerts for this chat\n"
            "/email your.name@example.org - set your email and enable email alerts\n"
            "/email_on - re-enable email alerts for your saved email\n"
            "/email_off - disable email alerts for this chat\n"
            "/email_status - show the current email alert setting\n"
            "/subscribers - show how many chats are subscribed\n"
            "/help - show this command list"
        )
