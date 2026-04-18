from __future__ import annotations

import asyncio
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import MonitorTarget


@dataclass(slots=True)
class CheckResult:
    severity: str
    status_text: str
    latency_ms: float | None
    details: dict[str, Any]


async def run_check(target: MonitorTarget) -> CheckResult:
    if target.kind == "tls":
        return await _run_tls_check(target)
    if target.kind == "tcp":
        return await _run_tcp_check(target)
    return await _run_http_check(target)


async def _run_http_check(target: MonitorTarget) -> CheckResult:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=target.timeout_seconds,
            verify=target.verify_tls,
            follow_redirects=target.follow_redirects,
        ) as client:
            response = await client.request(target.method, target.url or "")
        latency_ms = (time.perf_counter() - started) * 1000
        if response.status_code not in target.expected_status_codes:
            return CheckResult(
                severity="down",
                status_text=f"Unexpected HTTP status {response.status_code}",
                latency_ms=latency_ms,
                details={"status_code": response.status_code, "url": target.url},
            )
        if target.expected_json_field:
            payload = response.json()
            actual = payload.get(target.expected_json_field)
            if str(actual) != str(target.expected_json_value):
                return CheckResult(
                    severity="degraded",
                    status_text=f"Unexpected JSON field {target.expected_json_field}={actual!r}",
                    latency_ms=latency_ms,
                    details={"url": target.url, "payload": payload},
                )
        return CheckResult(
            severity="healthy",
            status_text=f"HTTP {response.status_code}",
            latency_ms=latency_ms,
            details={"status_code": response.status_code, "url": target.url},
        )
    except httpx.TimeoutException:
        return CheckResult("down", "HTTP timeout", None, {"url": target.url})
    except Exception as exc:
        return CheckResult("down", f"HTTP error: {exc}", None, {"url": target.url, "error": str(exc)})


async def _run_tcp_check(target: MonitorTarget) -> CheckResult:
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(target.host or "", target.port or 0),
            timeout=target.timeout_seconds,
        )
        writer.close()
        await writer.wait_closed()
        latency_ms = (time.perf_counter() - started) * 1000
        return CheckResult("healthy", "TCP connection succeeded", latency_ms, {"host": target.host, "port": target.port})
    except (TimeoutError, asyncio.TimeoutError):
        return CheckResult("down", "TCP timeout", None, {"host": target.host, "port": target.port})
    except (OSError, socket.error) as exc:
        return CheckResult("down", f"TCP error: {exc}", None, {"host": target.host, "port": target.port, "error": str(exc)})


async def _run_tls_check(target: MonitorTarget) -> CheckResult:
    started = time.perf_counter()
    ssl_context = ssl.create_default_context()
    if not target.verify_tls:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host=target.host or "",
                port=target.port or 0,
                ssl=ssl_context,
                server_hostname=target.host or None,
            ),
            timeout=target.timeout_seconds,
        )
        writer.close()
        await writer.wait_closed()
        latency_ms = (time.perf_counter() - started) * 1000
        return CheckResult(
            "healthy",
            "TLS handshake succeeded",
            latency_ms,
            {"host": target.host, "port": target.port},
        )
    except (TimeoutError, asyncio.TimeoutError):
        return CheckResult("down", "TLS timeout", None, {"host": target.host, "port": target.port})
    except (ssl.SSLError, OSError, socket.error) as exc:
        return CheckResult(
            "down",
            f"TLS error: {exc}",
            None,
            {"host": target.host, "port": target.port, "error": str(exc)},
        )
