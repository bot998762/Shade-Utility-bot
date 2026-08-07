from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.platform.capability import FeatureManifest, CapabilityRegistry
from app.services.ocr_service import OCRService

manifest = FeatureManifest(name="MediaTools", version="1.0.0", category="Utility")
router = Router()

@router.message(Command("ocr"))
async def cmd_ocr(message: Message, bot, ocr_service: OCRService, registry: CapabilityRegistry):
    registry.require("MediaTools")
    
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply("❌ Reply to an image with `/ocr` to extract text.")
        return
        
    status = await message.reply("📝 Processing image...")
    photo = message.reply_to_message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    photo_bytes = await bot.download_file(file_info.file_path)
    
    text = await ocr_service.extract_text(photo_bytes.read(), message.from_user.id)
    await status.edit_text(f"📝 **Extracted Text:**\n`{text}`" if text else "❌ No text found.", parse_mode="Markdown")
