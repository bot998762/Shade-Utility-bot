"""
Media Feature Router
====================
All dynamic/external content (OCR text, QR input, translation output,
scanned QR result) is sent using parse_mode="HTML" with html.escape()
on every user- or API-supplied string.

Rationale: legacy Markdown parse_mode=Markdown fails silently or raises
TelegramBadRequest when the content contains _ * [ ] or backtick characters.
For example, OCR text from an image of code, a QR code encoding a URL with
underscores, or translated text in non-Latin scripts can all trigger this.
"""

import html as _html
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
async def cmd_ocr(
    message: Message,
    bot: Bot,
    ocr_service: OCRService,
    registry: CapabilityRegistry,
) -> None:
    registry.require("MediaTools")
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply("❌ Reply to an image message with <code>/ocr</code>.", parse_mode="HTML")
        return

    status = await message.reply("📝 Processing Image OCR...")
    photo = message.reply_to_message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    photo_bytes = await bot.download_file(file_info.file_path)

    extracted_text = await ocr_service.extract_text(photo_bytes.read(), message.from_user.id)

    if extracted_text:
        # OCR output can contain any character including backticks, asterisks, underscores
        e_text = _html.escape(extracted_text)
        res_text = (
            f"📝 <b>OCR Extracted Result:</b>\n"
            f"───────────────────────────\n"
            f"<code>{e_text}</code>\n"
            f"───────────────────────────\n"
            f"<i>Tap text block to copy.</i>"
        )
        await status.edit_text(res_text, parse_mode="HTML")
    else:
        await status.edit_text("❌ No optical text detected in image payload.")


@router.message(Command("short"))
async def cmd_short(message: Message, shortener_service: ShortenerService) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ <b>Usage:</b> <code>/short &lt;url&gt;</code>", parse_mode="HTML")
        return
    url = await shortener_service.shorten_url(args[1].strip())
    # Shortened URLs contain only safe chars; escape for correctness
    e_url = _html.escape(url)
    await message.reply(f"🌐 <b>Shortened Direct Link:</b>\n{e_url}", parse_mode="HTML")


@router.message(Command("tr"))
async def cmd_translate(
    message: Message,
    translator_service: TranslatorService,
) -> None:
    args = message.text.split()
    target_lang = args[1].lower() if len(args) > 1 else "en"
    text = ""
    if message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif len(args) > 2:
        text = message.text.split(maxsplit=2)[2]

    if not text:
        await message.reply(
            "❌ Reply to text or format: <code>/tr &lt;lang&gt; &lt;text&gt;</code>",
            parse_mode="HTML",
        )
        return

    try:
        translated = await translator_service.translate(text, target_lang)
        # Translation output can contain any character in the target language
        e_translated = _html.escape(translated)
        e_lang = _html.escape(target_lang.upper())
        await message.reply(
            f"🌍 <b>Translation ({e_lang}):</b>\n{e_translated}",
            parse_mode="HTML",
        )
    except TimeoutError as te:
        await message.reply(f"⏱️ {_html.escape(str(te))}", parse_mode="HTML")
    except ValueError as ve:
        await message.reply(f"❌ {_html.escape(str(ve))}", parse_mode="HTML")


@router.message(Command("qr"))
async def cmd_qr(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "❌ <b>Usage:</b> <code>/qr &lt;text_or_url&gt;</code>",
            parse_mode="HTML",
        )
        return
    content = args[1]
    bio = qr.generate_qr_buffer(content)
    try:
        input_file = BufferedInputFile(bio.getvalue(), filename="qrcode.png")
        # User-supplied QR content can contain any characters — escape for HTML caption
        e_content = _html.escape(content)
        await message.reply_photo(
            photo=input_file,
            caption=f"🔳 <b>Generated QR Code Matrix:</b>\n<code>{e_content}</code>",
            parse_mode="HTML",
        )
    finally:
        bio.close()


@router.message(Command("qrscan"))
async def cmd_qrscan(message: Message, bot: Bot) -> None:
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply("❌ Reply to a QR photo message with <code>/qrscan</code>.", parse_mode="HTML")
        return
    status = await message.reply("🔍 Scanning QR Code Payload...")
    photo = message.reply_to_message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    photo_bytes = await bot.download_file(file_info.file_path)
    res = qr.scan_qr_from_bytes(photo_bytes.read())
    if res:
        # QR content can encode any data — URL-encoded payloads, arbitrary text
        e_res = _html.escape(res)
        await status.edit_text(
            f"✅ <b>Decoded QR Output:</b>\n<code>{e_res}</code>",
            parse_mode="HTML",
        )
    else:
        await status.edit_text("❌ No QR code detected in image.")
