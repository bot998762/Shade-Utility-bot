import time
import asyncio
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher

from app.core.config import settings
from app.core.logger import setup_logger
from app.platform.capability import CapabilityRegistry
from app.platform.event_bus import EventBus
from app.platform.failover import ProviderFailoverEngine
from app.core.circuit_breaker import CircuitBreaker

from app.providers.ocr_providers import OCRSpaceProvider, DummyFallbackOCRProvider
from app.services.ocr_service import OCRService

from app.middlewares.di import PlatformDIMiddleware
from app.middlewares.error import PlatformErrorMiddleware
from app.features import load_features

logger = setup_logger()

class ApplicationBootstrap:
    """Enterprise Atomic Initialization & Rollback Manager"""
    
    def __init__(self):
        self.start_time = time.time()
        self.app = web.Application()
        self.bot = Bot(token=settings.BOT_TOKEN)
        self.dp = Dispatcher()
        
        # Platform Components
        self.capability_registry = CapabilityRegistry()
        self.event_bus = EventBus()
        self.http_session = None

    def create_app(self) -> web.Application:
        self.app.on_startup.append(self.on_startup)
        self.app.on_cleanup.append(self.on_shutdown)
        return self.app

    async def on_startup(self, app: web.Application):
        """Atomic Startup with Rollback"""
        logger.info({"event": "atomic_startup_start"})
        try:
            settings.validate_startup()
            
            self.http_session = aiohttp.ClientSession()
            
            # Phase 3: Setup Failover Engine
            ocr_engine = ProviderFailoverEngine("OCR")
            ocr_engine.register_provider(OCRSpaceProvider(self.http_session), CircuitBreaker("OCRSpace", failure_threshold=2))
            ocr_engine.register_provider(DummyFallbackOCRProvider(self.http_session), CircuitBreaker("FallbackOCR"))
            
            self.ocr_service = OCRService(ocr_engine, self.event_bus)
            
            # Phase 5: Subscribe to events
            self.event_bus.subscribe("ocr_processed", lambda p: logger.info({"event": "sub_analytics", "data": p}))
            
            # Middlewares
            self.dp.message.middleware(PlatformErrorMiddleware())
            self.dp.callback_query.middleware(PlatformErrorMiddleware())
            self.dp.message.middleware(PlatformDIMiddleware(self))
            self.dp.callback_query.middleware(PlatformDIMiddleware(self))
            
            # Phase 1: Feature Plugin Loading with Isolation
            load_features(self.dp, self.capability_registry)
            
            # Phase 6: Diagnostic Startup Report
            self._print_startup_report()
            
            app['bot_task'] = asyncio.create_task(self.dp.start_polling(self.bot))
            
        except Exception as e:
            logger.critical({"event": "startup_failed", "error": str(e)})
            await self._rollback_resources()
            raise SystemExit("Startup Failed. Resources rolled back.")

    def _print_startup_report(self):
        loaded = len(self.capability_registry.features)
        failed = len(self.capability_registry.failed_loads)
        logger.info(f"--- STARTUP REPORT ---")
        logger.info(f"Loaded Features : {loaded}")
        logger.info(f"Failed Plugins  : {failed}")
        if failed > 0:
            logger.warning(f"Failed Details  : {self.capability_registry.failed_loads}")
        logger.info(f"----------------------")

    async def on_shutdown(self, app: web.Application):
        await self._rollback_resources()
        if 'bot_task' in app:
            app['bot_task'].cancel()

    async def _rollback_resources(self):
        """Failure Ownership: Ensures no zombie resources leak"""
        logger.info({"event": "rollback_triggered"})
        await self.bot.session.close()
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
