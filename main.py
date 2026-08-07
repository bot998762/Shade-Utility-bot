import os
from aiohttp import web
from app.core.bootstrap import ApplicationBootstrap
from app.core.logger import setup_logger

logger = setup_logger()

async def health_check_handler(request):
    """Dedicated health check endpoint for Render monitoring"""
    return web.json_response({
        "status": "healthy",
        "service": "Shade Utility Platform V8",
        "uptime_status": "operational"
    }, status=200)

def main():
    logger.info({"event": "process_start", "message": "Bootstrapping Shade Utility Platform V8"})
    
    bootstrap = ApplicationBootstrap()
    app = bootstrap.create_app()
    
    # Explicit /health route
    app.router.add_get("/health", health_check_handler)
    
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port, access_log=None)

if __name__ == "__main__":
    main()
