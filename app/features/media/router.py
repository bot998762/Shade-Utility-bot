from aiogram import Router, Bot
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command
from app.platform.capability import FeatureManifest, CapabilityRegistry
from app.services.ocr_service import OCRService
from app.services.shortener_service import ShortenerService
from app.services.translator_service import TranslatorService
from app.utils import qr

manifest = FeatureManifest(name="MediaTools", version="1.0.0", category="Utility")
router = Router()

@router.message(Command("ocr"))
async def cmd_ocr(message: Message, bot: Bot, ocr_service: OCRService, registry: CapabilityRegistry):
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

@router.message(Command("short"))
async def cmd_short(message: Message, shortener_service: ShortenerService):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/short <url>`", parse_mode="Markdown")
        return
    url = await shortener_service.shorten_url(args[1].strip())
    await message.reply(f"🌐 **Shortened URL:**\n{url}", parse_mode="Markdown")

@router.message(Command("tr"))
async def cmd_translate(message: Message, translator_service: TranslatorService):
    args = message.text.split()
    target_lang = args[1].lower() if len(args) > 1 else "en"
    text = ""
    if message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif len(args) > 2:
        text = message.text.split(maxsplit=2)[2]

    if not text:
        await message.reply("❌ Reply to text or type: `/tr <lang> <text>`", parse_mode="Markdown")
        return

    translated = await translator_service.translate(text, target_lang)
    await message.reply(f"🌍 **Translation ({target_lang}):**\n{translated}")

@router.message(Command("qr"))
async def cmd_qr(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/qr <text_or_url>`", parse_mode="Markdown")
        return
    bio = qr.generate_qr_buffer(args[1])
    try:
        input_file = BufferedInputFile(bio.getvalue(), filename="qrcode.png")
        await message.reply_photo(photo=input_file, caption=f"🔳 **QR Code for:**\n`{args[1]}`", parse_mode="Markdown")
    finally:
        bio.close()

@router.message(Command("qrscan"))
async def cmd_qrscan(message: Message, bot: Bot):
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply("❌ Reply to a QR photo with `/qrscan`.")
        return
    status = await message.reply("🔍 Scanning...")
    photo = message.reply_to_message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    photo_bytes = await bot.download_file(file_info.file_path)
    res = qr.scan_qr_from_bytes(photo_bytes.read())
    await status.edit_text(f"✅ **QR Result:**\n`{res}`" if res else "❌ No QR code detected.", parse_mode="Markdown")
