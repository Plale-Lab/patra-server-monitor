from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from .config import Settings
from .storage import MonitorStorage


class EmailNotifier:
    def __init__(self, settings: Settings, storage: MonitorStorage) -> None:
        self.settings = settings
        self.storage = storage

    @property
    def enabled(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.smtp_from_email)

    async def broadcast(self, subject: str, body: str) -> None:
        if not self.enabled:
            return
        for subscriber in self.storage.active_email_subscribers():
            email = (subscriber.get("email") or "").strip()
            if not email:
                continue
            try:
                await self.send_email(email, subject, body)
            except Exception:
                continue

    async def send_email(self, to_email: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to_email, subject, body)

    def _send_sync(self, to_email: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.smtp_from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        if self.settings.smtp_ssl:
            with smtplib.SMTP_SSL(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as smtp:
                self._login_if_needed(smtp)
                smtp.send_message(message)
            return

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            if self.settings.smtp_starttls:
                smtp.starttls()
                smtp.ehlo()
            self._login_if_needed(smtp)
            smtp.send_message(message)

    def _login_if_needed(self, smtp: smtplib.SMTP) -> None:
        if self.settings.smtp_username and self.settings.smtp_password:
            smtp.login(self.settings.smtp_username, self.settings.smtp_password)
