"""
ApplicationBootstrap
====================
Owns startup and shutdown sequencing.

Startup contract (atomic):
  1. Validate config
  2. Open HTTP session
  3. Verify bot token (get_me)
  4. Build services
  5. Register middleware
  6. Load features (isolated; partial failure allowed)
  7. Start polling task
  8. Mark readiness

Shutdown contract (ordered):
  1. Mark not-ready (stop accepting new health check OKs)
  2. Cancel & await polling task
  3. Close Telethon sessions
  4. Close HTTP session
  5. Close Bot session

If startup fails at any step, _rollback_resources() cleans up
whatever was already opened before raising SystemExit.
"""

import time
import asyncio
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher

from app.core.config import settings
from app.core.logger import setup_logger
from app.core.health import set_ready, set_not_ready
from app.platform.capability import CapabilityRegistry
from app.platform.event_bus import EventBus
from app.platform.failover import ProviderFailoverEngine
from app.core.circuit_breaker import CircuitBreaker

from app.providers.ocr_providers import OCRSpaceProvider, DummyFallbackOCRProvider
from app.providers.url_providers import CleanURIProvider, VGdURLProvider
from app.services.ocr_service import OCRService
from app.services.shortener_service import ShortenerService
from app.services.translator_service import TranslatorService

from app.middlewares.di import PlatformDIMiddleware
from app.middlewares.error import PlatformErrorMiddleware
from app.features import load_features

logger = setup_logger()

_SENTINEL = object()


class ApplicationBootstrap:
    def __init__(self) -> None:
        self.start_time = time.time()
        self.app = web.Application()
        self.bot = Bot(token=settings.BOT_TOKEN)
        self.dp = Dispatcher()

        self.capability_registry = CapabilityRegistry()
        self.event_bus = EventBus()
        self.http_session: aiohttp.ClientSession | None = None
        self.bot_username = "ShadeUtilityBot"

        # Services (set during on_startup)
        self.ocr_service: OCRService | None = None
        self.shortener_service: ShortenerService | None = None
        self.translator_service: TranslatorService | None = None

    def create_app(self) -> web.Application:
        self.app.on_startup.append(self.on_startup)
        self.app.on_cleanup.append(self.on_shutdown)
        return self.app

    async def on_startup(self, app: web.Application) -> None:
        logger.info({"event": "startup_begin"})
        try:
            settings.validate_startup()

            self.http_session = aiohttp.ClientSession()

            bot_info = await self.bot.get_me()
            self.bot_username = bot_info.username

            # --- Services ---
            ocr_engine = ProviderFailoverEngine("OCR")
            ocr_engine.register_provider(
                OCRSpaceProvider(self.http_session),
                CircuitBreaker("OCRSpace", failure_threshold=2),
            )
            ocr_engine.register_provider(
                DummyFallbackOCRProvider(self.http_session),
                CircuitBreaker("FallbackOCR"),
            )

            url_engine = ProviderFailoverEngine("URLShortener")
            url_engine.register_provider(
                CleanURIProvider(self.http_session),
                CircuitBreaker("CleanURI", failure_threshold=2),
            )
            url_engine.register_provider(
                VGdURLProvider(self.http_session),
                CircuitBreaker("VGdURL", failure_threshold=2),
            )

            self.ocr_service = OCRService(ocr_engine, self.event_bus)
            self.shortener_service = ShortenerService(url_engine)
            self.translator_service = TranslatorService()

            # --- Middleware ---
            self.dp.message.middleware(PlatformErrorMiddleware())
            self.dp.callback_query.middleware(PlatformErrorMiddleware())
            self.dp.message.middleware(PlatformDIMiddleware(self))
            self.dp.callback_query.middleware(PlatformDIMiddleware(self))

            # --- Features (isolated; partial failure ok) ---
            loaded_names, failed_modules = load_features(self.dp, self.capability_registry)
            features_loaded = len(loaded_names)
            # degraded = modules that failed to load (never entered registry)
            degraded = failed_modules

            # --- Polling ---
            await self.bot.delete_webhook(drop_pending_updates=True)
            bot_task = asyncio.create_task(
                self.dp.start_polling(self.bot),
                name="bot_polling",
            )
            app["bot_task"] = bot_task

            # --- Mark ready (pass LIVE object references, not boolean snapshots) ---
            set_ready(
                bot_task=bot_task,
                http_session=self.http_session,
                features_loaded=features_loaded,
                degraded_features=degraded,
            )

            logger.info({
                "event": "startup_complete",
                "features_loaded": features_loaded,
                "degraded": degraded,
                "bot_username": self.bot_username,
            })

        except Exception as exc:
            logger.critical({"event": "startup_failed", "error": str(exc)})
            await self._rollback_resources(app)
            raise SystemExit("Startup failed.") from exc

    async def on_shutdown(self, app: web.Application) -> None:
        logger.info({"event": "shutdown_begin"})
        set_not_ready("shutdown")

        # 1. Stop the polling task first so no new updates are processed
        bot_task = app.get("bot_task")
        if bot_task and not bot_task.done():
            bot_task.cancel()
            try:
                await asyncio.wait_for(bot_task, timeout=10.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        # 2. Clean up Telethon sessions
        try:
            from app.features.session_manager.router import shutdown_all_sm_sessions
            await shutdown_all_sm_sessions()
        except Exception as exc:
            logger.warning({"event": "sm_shutdown_error", "error": str(exc)})
        try:
            from app.features.session.router import shutdown_all_sessions
            await shutdown_all_sessions()
        except Exception as exc:
            logger.warning({"event": "session_shutdown_error", "error": str(exc)})

        # 3. Close HTTP resources
        await self._close_http_resources()
        logger.info({"event": "shutdown_complete"})

    async def _rollback_resources(self, app: web.Application | None = None) -> None:
        """Best-effort cleanup of partially-initialised resources."""
        if app:
            bot_task = app.get("bot_task")
            if bot_task and not bot_task.done():
                bot_task.cancel()
                try:
                    await asyncio.wait_for(bot_task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass

        await self._close_http_resources()

    async def _close_http_resources(self) -> None:
        if self.http_session and not self.http_session.closed:
            try:
                await self.http_session.close()
            except Exception as exc:
                logger.warning({"event": "http_session_close_error", "error": str(exc)})

        try:
            await self.bot.session.close()
        except Exception as exc:
            logger.warning({"event": "bot_session_close_error", "error": str(exc)})
