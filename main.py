import os
from aiohttp import web
from app.core.bootstrap import ApplicationBootstrap
from app.core.logger import setup_logger
from app.core.health import liveness_handler, readiness_handler, health_check_handler

logger = setup_logger()


def main() -> None:
    logger.info({"event": "process_start", "message": "Bootstrapping Shade Utility Platform V8"})

    bootstrap = ApplicationBootstrap()
    app = bootstrap.create_app()

    # Liveness: is the process alive?
    app.router.add_get("/health/live", liveness_handler)
    # Readiness: can the bot serve traffic?
    app.router.add_get("/health/ready", readiness_handler)
    # Backward-compat alias
    app.router.add_get("/health", health_check_handler)

    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port, access_log=None)


if __name__ == "__main__":
    main()
