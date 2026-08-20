"""
Health / Readiness Endpoints
==============================
GET /health/live   — Liveness: is the process alive and its loop running?
GET /health/ready  — Readiness: can the bot currently serve traffic?

Design notes:
- Never call rate-limited external APIs in health checks.
- Readiness is derived from in-memory state set during startup/shutdown.
- A single GET /health is also kept as a backward-compat alias to /health/ready.
"""

import time
from aiohttp import web

# Shared readiness state mutated by bootstrap
_readiness: dict = {
    "ready": False,
    "bot_task_ok": False,
    "http_session_ok": False,
    "features_loaded": 0,
    "start_time": None,
    "degraded_features": [],
}


def set_ready(
    *,
    bot_task_ok: bool,
    http_session_ok: bool,
    features_loaded: int,
    degraded_features: list[str],
) -> None:
    """Called by bootstrap once startup succeeds."""
    _readiness["ready"] = True
    _readiness["bot_task_ok"] = bot_task_ok
    _readiness["http_session_ok"] = http_session_ok
    _readiness["features_loaded"] = features_loaded
    _readiness["degraded_features"] = degraded_features
    _readiness["start_time"] = time.time()


def set_not_ready(reason: str = "shutdown") -> None:
    """Called by bootstrap during shutdown."""
    _readiness["ready"] = False
    _readiness["shutdown_reason"] = reason


async def liveness_handler(request: web.Request) -> web.Response:
    """
    Liveness: the process and its event loop are alive.
    Always 200 as long as the process can handle an HTTP request.
    """
    return web.json_response({"status": "alive", "service": "Shade Utility Platform"})


async def readiness_handler(request: web.Request) -> web.Response:
    """
    Readiness: the bot is initialised and able to serve commands.
    Returns 503 during startup or after shutdown begins.
    """
    r = _readiness
    if not r["ready"]:
        return web.json_response(
            {"status": "not_ready", "reason": r.get("shutdown_reason", "initializing")},
            status=503,
        )

    uptime = time.time() - r["start_time"] if r["start_time"] else 0
    payload = {
        "status": "ready",
        "uptime_seconds": round(uptime, 1),
        "bot_polling": r["bot_task_ok"],
        "http_session": r["http_session_ok"],
        "features_loaded": r["features_loaded"],
        "degraded_features": r["degraded_features"],
    }

    # Degraded = ready but with warnings (some optional features failed)
    if r["degraded_features"]:
        payload["status"] = "degraded"

    # If critical subsystems are down, return 503
    if not r["bot_task_ok"] or not r["http_session_ok"]:
        payload["status"] = "unhealthy"
        return web.json_response(payload, status=503)

    return web.json_response(payload, status=200)


# Backward-compat alias
async def health_check_handler(request: web.Request) -> web.Response:
    return await readiness_handler(request)
