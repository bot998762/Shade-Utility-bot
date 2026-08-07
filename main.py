import os
from aiohttp import web
from app.core.bootstrap import ApplicationBootstrap
from app.core.logger import setup_logger
from app.core.health import health_check_handler

logger = setup_logger()

def main():
    logger.info({"event": "process_start", "message": "Bootstrapping Shade Utility Platform V8"})
    
    bootstrap = ApplicationBootstrap()
    app = bootstrap.create_app()
    
    # Register dedicated health route
    app.router.add_get("/health", health_check_handler)
    
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port, access_log=None)

if __name__ == "__main__":
    main()
