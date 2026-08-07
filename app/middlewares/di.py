from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from app.core.bootstrap import ApplicationBootstrap

class PlatformDIMiddleware(BaseMiddleware):
    def __init__(self, bootstrap: ApplicationBootstrap):
        self.bootstrap = bootstrap

    async def __call__(self, handler, event: TelegramObject, data: dict):
        data['registry'] = self.bootstrap.capability_registry
        data['event_bus'] = self.bootstrap.event_bus
        data['bootstrap_ref'] = self.bootstrap
        data['ocr_service'] = self.bootstrap.ocr_service
        return await handler(event, data)
