from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import load_settings
from .db import Database
from .email_notifier import EmailNotifier
from .monitor import MonitorEngine
from .storage import MonitorStorage
from .telegram_bot import TelegramBot


class AppState:
    def __init__(self) -> None:
        settings = load_settings()
        self.settings = settings
        self.db = Database(settings.db_path)
        self.storage = MonitorStorage(self.db)
        self.storage.ensure_targets(settings.targets)
        self.bot = TelegramBot(settings.telegram_bot_token, self.storage)
        self.email_notifier = EmailNotifier(settings, self.storage)
        self.engine = MonitorEngine(settings, self.storage, self.bot, self.email_notifier)
        self.stop_event = asyncio.Event()
        self.tasks: list[asyncio.Task] = []


async def monitor_loop(state: AppState) -> None:
    while not state.stop_event.is_set():
        try:
            await state.engine.check_all()
        except Exception:
            pass
        try:
            await asyncio.wait_for(state.stop_event.wait(), timeout=state.settings.monitor_interval_seconds)
        except asyncio.TimeoutError:
            continue


async def telegram_loop(state: AppState) -> None:
    offset = state.storage.get_offset()
    while not state.stop_event.is_set():
        try:
            updates = await state.bot.get_updates(offset=offset, timeout_seconds=state.settings.telegram_poll_interval_seconds)
            for update in updates:
                offset = max(offset, int(update["update_id"]) + 1)
                await state.bot.handle_update(
                    update,
                    status_renderer=state.engine.render_status_report,
                    active_status_checker=_check_and_render_report(state),
                    services_renderer=_render_services_report(state),
                    recent_events_renderer=_render_recent_events(state),
                    targets_renderer=_render_targets(state),
                    target_upserter=_target_upserter(state),
                    target_remover=_target_remover(state),
                )
            state.storage.set_offset(offset)
        except Exception:
            await asyncio.sleep(state.settings.telegram_poll_interval_seconds)


def _check_and_render_report(state: AppState):
    async def _inner() -> str:
        await state.engine.check_all()
        return state.engine.render_status_report()

    return _inner


def _render_services_report(state: AppState):
    def _inner() -> str:
        states = state.storage.list_states()
        if not states:
            names = ", ".join(target.name for target in state.storage.list_targets())
            return f"PATRA monitored services:\n- configured targets: {names}\n- no checks recorded yet"
        lines = ["PATRA monitored services:"]
        for service_state in states:
            lines.append(f"- {service_state.target_name}: {service_state.severity} ({service_state.status_text})")
        return "\n".join(lines)

    return _inner


def _render_recent_events(state: AppState):
    def _inner() -> str:
        events = state.storage.recent_events(limit=5)
        if not events:
            return "No abnormal monitor events have been recorded yet."
        lines = ["Recent PATRA monitor events:"]
        for event in events:
            lines.append(
                f"- {event['created_at']} | {event['target_name']} | {event['severity']} | {event['status_text']}"
            )
        return "\n".join(lines)

    return _inner


def _render_targets(state: AppState):
    def _inner() -> str:
        targets = state.storage.list_targets()
        if not targets:
            return "No monitor targets are configured."
        lines = ["Configured monitor targets:"]
        for target in targets:
            location = target.url or f"{target.host}:{target.port}"
            lines.append(f"- {target.name} [{target.kind}] -> {location}")
        return "\n".join(lines)

    return _inner


def _target_upserter(state: AppState):
    def _inner(target) -> None:
        state.storage.upsert_target(target)

    return _inner


def _target_remover(state: AppState):
    def _inner(target_name: str) -> bool:
        return state.storage.delete_target(target_name)

    return _inner


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = AppState()
    app.state.monitor = state
    state.tasks = [
        asyncio.create_task(monitor_loop(state)),
        asyncio.create_task(telegram_loop(state)),
    ]
    yield
    state.stop_event.set()
    for task in state.tasks:
        task.cancel()
    await asyncio.gather(*state.tasks, return_exceptions=True)


app = FastAPI(title="PATRA Server Monitor", version="0.2.1", lifespan=lifespan)


@app.get("/")
async def root():
    return {"service": "patra-server-monitor", "message": "PATRA 5-pod monitor is running."}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/monitor/status")
async def monitor_status():
    state = app.state.monitor
    return {
        "targets": [
            {
                "target_name": target_state.target_name,
                "severity": target_state.severity,
                "status_text": target_state.status_text,
                "latency_ms": target_state.latency_ms,
                "last_checked_at": target_state.last_checked_at,
                "last_changed_at": target_state.last_changed_at,
                "consecutive_failures": target_state.consecutive_failures,
                "consecutive_successes": target_state.consecutive_successes,
                "details": target_state.details_json,
            }
            for target_state in state.storage.list_states()
        ],
        "subscribers": len(state.storage.active_subscribers()),
        "email_subscribers": len(state.storage.active_email_subscribers()),
        "configured_targets": len(state.storage.list_targets()),
        "report": state.engine.render_status_report(),
    }


@app.get("/monitor/subscribers")
async def monitor_subscribers():
    state = app.state.monitor
    return {
        "telegram_subscribers": state.storage.active_subscribers(),
        "email_subscribers": state.storage.active_email_subscribers(),
    }


@app.get("/monitor/targets")
async def monitor_targets():
    state = app.state.monitor
    targets = state.storage.list_targets(include_inactive=True)
    return {
        "targets": [
            {
                "name": target.name,
                "kind": target.kind,
                "url": target.url,
                "host": target.host,
                "port": target.port,
                "expected_status_codes": list(target.expected_status_codes),
                "expected_json_field": target.expected_json_field,
                "expected_json_value": target.expected_json_value,
                "timeout_seconds": target.timeout_seconds,
                "verify_tls": target.verify_tls,
                "follow_redirects": target.follow_redirects,
            }
            for target in targets
        ]
    }


@app.post("/monitor/check-now")
async def monitor_check_now():
    state = app.state.monitor
    results = await state.engine.check_all()
    return {"checked": len(results), "report": state.engine.render_status_report()}


@app.get("/monitor/events")
async def monitor_events(limit: int = 50):
    state = app.state.monitor
    return {"events": state.storage.recent_events(limit=limit)}
