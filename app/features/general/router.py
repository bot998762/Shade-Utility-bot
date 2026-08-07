from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from app.platform.capability import FeatureManifest

manifest = FeatureManifest(name="GeneralTools", version="1.0.0", category="Core")
router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, bot_username: str = "ShadeUtilityBot"):
    text = (
        f"⚡ **Welcome to Shade Utility Bot!** ⚡\n"
        f"───────────────────────────\n"
        f"👋 Hi **{message.from_user.first_name}**, main **Shade Ecosystem** ka official assistant hoon!\n\n"
        f"🚀 **Available Commands:**\n"
        f"• `/start` - Start Bot\n"
        f"• `/ocr` - Reply to image to extract text\n"
        f"• `/diag` - System Diagnostics (Admin)"
    )
    await message.reply(text, parse_mode="Markdown")
