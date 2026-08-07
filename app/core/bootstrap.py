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
from app.providers.url_providers import TinyURLProvider, CleanURIProvider
from app.services.ocr_service import OCRService
from app.services.shortener_service import ShortenerService
from app.services.translator_service import TranslatorService

from app.middlewares.di import PlatformDIMiddleware
from app.middlewares.error import PlatformErrorMiddleware
from app.features import load_features

logger = setup_logger()

class ApplicationBootstrap:
    def __init__(self):
        self.start_time = time.time()
        self.app = web.Application()
        self.bot = Bot(token=settings.BOT_TOKEN)
        self.dp = Dispatcher()
        
        self.capability_registry = CapabilityRegistry()
        self.event_bus = EventBus()
        self.http_session = None
        self.bot_username = "ShadeUtilityBot"

    def create_app(self) -> web.Application:
        self.app.on_startup.append(self.on_startup)
        self.app.on_cleanup.append(self.on_shutdown)
        return self.app

    async def on_startup(self, app: web.Application):
        logger.info({"event": "startup_begin"})
        try:
            settings.validate_startup()
            
            self.http_session = aiohttp.ClientSession()
            
            bot_info = await self.bot.get_me()
            self.bot_username = bot_info.username
            
            # Setup Failover Engines
            ocr_engine = ProviderFailoverEngine("OCR")
            ocr_engine.register_provider(OCRSpaceProvider(self.http_session), CircuitBreaker("OCRSpace", failure_threshold=2))
            ocr_engine.register_provider(DummyFallbackOCRProvider(self.http_session), CircuitBreaker("FallbackOCR"))
            
            url_engine = ProviderFailoverEngine("URLShortener")
            url_engine.register_provider(TinyURLProvider(self.http_session), CircuitBreaker("TinyURL", failure_threshold=2))
            url_engine.register_provider(CleanURIProvider(self.http_session), CircuitBreaker("CleanURI", failure_threshold=2))
            
            self.ocr_service = OCRService(ocr_engine, self.event_bus)
            self.shortener_service = ShortenerService(url_engine)
            self.translator_service = TranslatorService()
            
            self.dp.message.middleware(PlatformErrorMiddleware())
            self.dp.callback_query.middleware(PlatformErrorMiddleware())
            self.dp.message.middleware(PlatformDIMiddleware(self))
            self.dp.callback_query.middleware(PlatformDIMiddleware(self))
            
            load_features(self.dp, self.capability_registry)
            
            logger.info({"event": "features_loaded", "count": len(self.capability_registry.features)})
            
            await self.bot.delete_webhook(drop_pending_updates=True)
            app['bot_task'] = asyncio.create_task(self.dp.start_polling(self.bot))
            
        except Exception as e:
            logger.critical({"event": "startup_failed", "error": str(e)})
            await self._rollback_resources()
            raise SystemExit("Startup Failed.")

    async def on_shutdown(self, app: web.Application):
        await self._rollback_resources()
        if 'bot_task' in app:
            app['bot_task'].cancel()

    async def _rollback_resources(self):
        await self.bot.session.close()
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
