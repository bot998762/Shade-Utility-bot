"""
Health / Readiness Endpoints
==============================
GET /health/live  — Liveness: is the process and event-loop alive?
GET /health/ready — Readiness: are critical subsystems actually operational?

Design principles:
- Liveness is stateless: always 200 while the process can respond.
- Readiness reflects LIVE state, not a one-time snapshot set at startup.
  bot_task and http_session are stored as real object references;
  their live .done() / .closed properties are checked on every request.
- No external API calls on any health route.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING
from aiohttp import web

if TYPE_CHECKING:
    import aiohttp as _aiohttp

# Mutable state — updated by bootstrap
_readiness: dict = {
    "ready": False,
    # Live object references (checked on every /health/ready request)
    "bot_task": None,        # asyncio.Task | None
    "http_session": None,    # aiohttp.ClientSession | None
    # Static metadata set once at startup
    "features_loaded": 0,
    "degraded_features": [],
    "start_time": None,
    # Shutdown reason (set by set_not_ready)
    "shutdown_reason": None,
}


def set_ready(
    *,
    bot_task: "asyncio.Task",
    http_session: "_aiohttp.ClientSession",
    features_loaded: int,
    degraded_features: list[str],
) -> None:
    """Called once by bootstrap after successful startup.
    Stores LIVE references — not snapshotted booleans."""
    _readiness.update({
        "ready": True,
        "bot_task": bot_task,
        "http_session": http_session,
        "features_loaded": features_loaded,
        "degraded_features": list(degraded_features),
        "start_time": time.time(),
        "shutdown_reason": None,
    })


def set_not_ready(reason: str = "shutdown") -> None:
    """Called by bootstrap at shutdown start."""
    _readiness["ready"] = False
    _readiness["shutdown_reason"] = reason


async def liveness_handler(request: web.Request) -> web.Response:
    """
    Liveness: the process and event loop are alive.
    Always 200 while the process can handle HTTP requests.
    """
    return web.json_response({"status": "alive", "service": "Shade Utility Platform"})


async def readiness_handler(request: web.Request) -> web.Response:
    """
    Readiness: bot can currently serve Telegram commands.
    Derives status from LIVE object references, not a cached boolean.
    """
    if not _readiness["ready"]:
        return web.json_response(
            {
                "status": "not_ready",
                "reason": _readiness.get("shutdown_reason") or "initializing",
            },
            status=503,
        )

    # --- Live checks (not cached booleans) ---
    bot_task: asyncio.Task | None = _readiness["bot_task"]
    http_session = _readiness["http_session"]

    bot_alive = bot_task is not None and not bot_task.done()
    http_ok = http_session is not None and not http_session.closed

    start_time = _readiness["start_time"]
    uptime = round(time.time() - start_time, 1) if start_time else 0

    payload = {
        "uptime_seconds": uptime,
        "bot_polling": bot_alive,
        "http_session": http_ok,
        "features_loaded": _readiness["features_loaded"],
        "degraded_features": _readiness["degraded_features"],
    }

    # Critical subsystem down → 503
    if not bot_alive or not http_ok:
        payload["status"] = "unhealthy"
        return web.json_response(payload, status=503)

    # Optional features degraded → 200 with warning
    if _readiness["degraded_features"]:
        payload["status"] = "degraded"
        return web.json_response(payload, status=200)

    payload["status"] = "ready"
    return web.json_response(payload, status=200)


# Backward-compat alias
async def health_check_handler(request: web.Request) -> web.Response:
    return await readiness_handler(request)
