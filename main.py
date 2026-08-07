import os
from aiohttp import web
from app.core.bootstrap import ApplicationBootstrap
from app.core.logger import setup_logger

logger = setup_logger()

def main():
    logger.info({"event": "process_start", "message": "Bootstrapping V8 Control Plane Platform"})
    
    bootstrap = ApplicationBootstrap()
    app = bootstrap.create_app()
    
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port, access_log=None)

if __name__ == "__main__":
    main()
