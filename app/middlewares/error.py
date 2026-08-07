from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from app.core.exceptions import FeatureDisabledError, NoProvidersAvailableError
from app.core.logger import setup_logger

logger = setup_logger()

class PlatformErrorMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        try:
            return await handler(event, data)
        except FeatureDisabledError as e:
            if isinstance(event, Message): await event.reply(f"🔒 {str(e)}")
            elif isinstance(event, CallbackQuery): await event.answer(str(e), show_alert=True)
        except NoProvidersAvailableError:
            msg = "⚠️ Service is temporarily unavailable. Please try again later."
            if isinstance(event, Message): await event.reply(msg)
            elif isinstance(event, CallbackQuery): await event.answer(msg, show_alert=True)
        except Exception as e:
            logger.error({"event": "unhandled_error", "error": str(e)}, exc_info=True)
            if isinstance(event, Message): await event.reply("⚠️ Internal system error occurred.")
