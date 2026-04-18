from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .checks import run_check
from .config import MonitorTarget, Settings
from .email_notifier import EmailNotifier
from .storage import MonitorStorage, StoredTargetState, utc_now_iso
from .telegram_bot import TelegramBot


@dataclass(slots=True)
class MonitorDecision:
    should_alert: bool
    alert_text: str | None
    state: StoredTargetState


class MonitorEngine:
    def __init__(self, settings: Settings, storage: MonitorStorage, bot: TelegramBot, email_notifier: EmailNotifier) -> None:
        self.settings = settings
        self.storage = storage
        self.bot = bot
        self.email_notifier = email_notifier

    async def check_all(self) -> list[StoredTargetState]:
        results: list[StoredTargetState] = []
        for target in self.storage.list_targets():
            decision = await self.check_target(target)
            results.append(decision.state)
            if decision.should_alert and decision.alert_text:
                await self.bot.broadcast(decision.alert_text)
                await self.email_notifier.broadcast(
                    subject=self._email_subject(target.name, decision.state.severity),
                    body=decision.alert_text,
                )
                self.storage.touch_alert_time(target.name)
        return results

    async def check_target(self, target: MonitorTarget) -> MonitorDecision:
        previous = self.storage.get_state(target.name)
        result = await run_check(target)
        now = utc_now_iso()

        prev_failures = previous.consecutive_failures if previous else 0
        prev_successes = previous.consecutive_successes if previous else 0
        is_failure = result.severity in {"down", "degraded"}
        consecutive_failures = prev_failures + 1 if is_failure else 0
        consecutive_successes = prev_successes + 1 if not is_failure else 0

        stable_severity = previous.severity if previous else "healthy"
        if is_failure and consecutive_failures >= self.settings.failure_threshold:
            stable_severity = result.severity
        elif (not is_failure) and consecutive_successes >= self.settings.recovery_threshold:
            stable_severity = "healthy"

        display_status_text = result.status_text
        if is_failure and stable_severity == "healthy":
            display_status_text = (
                f"Failure observed ({consecutive_failures}/{self.settings.failure_threshold}) before alert threshold: "
                f"{result.status_text}"
            )

        changed = False
        if previous is None:
            changed = stable_severity != "healthy"
        elif stable_severity != previous.severity:
            changed = True
        elif previous.status_text != display_status_text and stable_severity != "healthy":
            changed = True

        state = StoredTargetState(
            target_name=target.name,
            severity=stable_severity,
            status_text=display_status_text,
            latency_ms=result.latency_ms,
            last_checked_at=now,
            last_changed_at=now if (changed or previous is None) else previous.last_changed_at,
            consecutive_failures=consecutive_failures,
            consecutive_successes=consecutive_successes,
            last_alerted_at=previous.last_alerted_at if previous else None,
            details_json=result.details,
        )
        self.storage.save_state(state)

        should_alert = False
        alert_text: str | None = None
        if previous is None:
            if stable_severity != "healthy":
                should_alert = True
                alert_text = self._format_alert(target.name, stable_severity, result.status_text, result.details, recovery=False)
        elif stable_severity != previous.severity:
            should_alert = True
            alert_text = self._format_alert(target.name, stable_severity, result.status_text, result.details, recovery=stable_severity == "healthy")
        elif stable_severity != "healthy" and self._should_send_reminder(previous.last_alerted_at):
            should_alert = True
            alert_text = self._format_alert(target.name, stable_severity, result.status_text, result.details, recovery=False, reminder=True)

        if changed or should_alert:
            self.storage.log_event(
                target_name=target.name,
                severity=stable_severity,
                status_text=display_status_text,
                details_json=result.details,
            )

        return MonitorDecision(should_alert=should_alert, alert_text=alert_text, state=state)

    def render_status_report(self) -> str:
        states = self.storage.list_states()
        if not states:
            return "PATRA monitor has not completed a check yet."
        lines = ["PATRA pod status:"]
        for state in states:
            latency = f", {state.latency_ms:.1f} ms" if state.latency_ms is not None else ""
            lines.append(f"- {state.target_name}: {state.severity} ({state.status_text}{latency})")
        return "\n".join(lines)

    def _format_alert(
        self,
        target_name: str,
        severity: str,
        status_text: str,
        details: dict[str, Any],
        *,
        recovery: bool,
        reminder: bool = False,
    ) -> str:
        if recovery:
            header = f"PATRA recovery: {target_name} is healthy again."
        elif reminder:
            header = f"PATRA reminder: {target_name} is still {severity}."
        else:
            header = f"PATRA alert: {target_name} is {severity}."
        lines = [header, f"Status: {status_text}"]
        for key, value in details.items():
            lines.append(f"{key}: {value}")
        lines.append(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        return "\n".join(lines)

    def _email_subject(self, target_name: str, severity: str) -> str:
        if severity == "healthy":
            return f"PATRA recovery: {target_name}"
        return f"PATRA alert: {target_name} is {severity}"

    def _should_send_reminder(self, last_alerted_at: str | None) -> bool:
        if not last_alerted_at:
            return True
        try:
            last = datetime.fromisoformat(last_alerted_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        return datetime.now(timezone.utc) - last >= timedelta(minutes=self.settings.reminder_interval_minutes)
