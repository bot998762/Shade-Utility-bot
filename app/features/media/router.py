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
from qrcode.exceptions import DataOverflowError as QRDataOverflowError
from app.platform.capability import FeatureManifest, CapabilityRegistry
from app.services.ocr_service import OCRService
from app.services.shortener_service import ShortenerService
from app.services.translator_service import TranslatorService
from app.utils import qr
from app.core.exceptions import ProviderAPIError

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
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply(
            "❌ <b>Usage:</b>\n"
            "• <code>/short &lt;url&gt;</code> — shorten a URL\n"
            "• <code>/short expand &lt;url&gt;</code> — trace a short URL to its destination",
            parse_mode="HTML",
        )
        return

    # Phase 2J — URL expansion subcommand
    if args[1].lower() == "expand":
        if len(args) < 3:
            await message.reply(
                "❌ <b>Usage:</b> <code>/short expand &lt;url&gt;</code>",
                parse_mode="HTML",
            )
            return
        await _cmd_short_expand(message, args[2].strip())
        return

    # Existing shortening path — UNCHANGED
    url = await shortener_service.shorten_url(args[1].strip())
    # Shortened URLs contain only safe chars; escape for correctness
    e_url = _html.escape(url)
    await message.reply(f"🌐 <b>Shortened Direct Link:</b>\n{e_url}", parse_mode="HTML")


async def _cmd_short_expand(message, raw_url: str) -> None:
    """
    Phase 2J — SSRF-safe URL expansion.

    is_safe_host() is the security authority for every redirect hop.
    We NEVER follow a redirect to a private/internal address.
    """
    import html as _html
    import aiohttp as _aiohttp
    from urllib.parse import urlparse as _urlparse
    from app.utils.network import is_safe_host as _safe

    _MAX_REDIRECTS = 5

    # Validate the initial URL
    try:
        parsed = _urlparse(raw_url)
        if parsed.scheme not in ("http", "https"):
            await message.reply("❌ Only http:// and https:// URLs are supported.", parse_mode="HTML")
            return
        if not parsed.netloc:
            raise ValueError("empty host")
        initial_host = parsed.hostname or ""
    except Exception:
        await message.reply("❌ Invalid URL format.", parse_mode="HTML")
        return

    if not _safe(initial_host):
        await message.reply("❌ Private/reserved host in URL — cannot expand.", parse_mode="HTML")
        return

    status = await message.reply(
        f"🔍 Tracing <code>{_html.escape(raw_url[:100])}</code>...",
        parse_mode="HTML",
    )

    hops: list[str] = [raw_url]
    current_url = raw_url

    try:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=15, connect=5)
        connector = aiohttp.TCPConnector(limit=5)
        async with aiohttp.ClientSession(connector=connector) as session:
            for _ in range(_MAX_REDIRECTS):
                try:
                    async with session.head(
                        current_url,
                        allow_redirects=False,
                        timeout=timeout,
                        headers={"User-Agent": "ShadeUtility/2J URLExpander"},
                    ) as resp:
                        if resp.status not in (301, 302, 303, 307, 308):
                            break  # not a redirect — we've reached the final destination
                        location = resp.headers.get("Location", "")
                        if not location:
                            break
                        # Resolve relative redirects
                        if location.startswith("/"):
                            p = _urlparse(current_url)
                            location = f"{p.scheme}://{p.netloc}{location}"
                        # SSRF guard: validate EVERY redirect destination before following
                        try:
                            redir_parsed = _urlparse(location)
                            redir_host = redir_parsed.hostname or ""
                            if redir_parsed.scheme not in ("http", "https"):
                                await status.edit_text(
                                    f"⛔ Redirect to non-HTTP scheme blocked: "
                                    f"<code>{_html.escape(redir_parsed.scheme)}</code>",
                                    parse_mode="HTML",
                                )
                                return
                            if not _safe(redir_host):
                                await status.edit_text(
                                    f"⛔ Redirect to private/internal host blocked: "
                                    f"<code>{_html.escape(redir_host)}</code>",
                                    parse_mode="HTML",
                                )
                                return
                        except Exception:
                            await status.edit_text(
                                "⛔ Redirect destination could not be validated — expansion stopped.",
                                parse_mode="HTML",
                            )
                            return

                        hops.append(location)
                        current_url = location
                except (aiohttp.ServerTimeoutError, aiohttp.ClientConnectorError,
                        aiohttp.ClientError) as exc:
                    await status.edit_text(
                        f"⏱️ Network error while tracing: <code>{_html.escape(type(exc).__name__)}</code>",
                        parse_mode="HTML",
                    )
                    return
    except Exception as exc:
        logger.error({"event": "short_expand_error", "error": type(exc).__name__})
        await status.edit_text("❌ Unexpected error during URL expansion.", parse_mode="HTML")
        return

    final = hops[-1]
    hop_count = len(hops) - 1
    e_final = _html.escape(final)
    if hop_count == 0:
        result = f"🔗 <b>URL Expansion:</b>\nNo redirects found — URL already points directly to:\n<code>{e_final}</code>"
    else:
        hop_lines = "\n".join(f"  {i+1}. <code>{_html.escape(h)}</code>" for i, h in enumerate(hops))
        result = (
            f"🔗 <b>URL Expansion ({hop_count} redirect{'s' if hop_count != 1 else ''}):</b>\n"
            f"{hop_lines}\n"
            f"───────────────────────────\n"
            f"✅ <b>Final destination:</b> <code>{e_final}</code>"
        )
    await status.edit_text(result, parse_mode="HTML")


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
    except ProviderAPIError as e:
        await message.reply(f"⚠️ {_html.escape(str(e))}", parse_mode="HTML")


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
    try:
        bio = qr.generate_qr_buffer(content)
    except QRDataOverflowError:
        await message.reply(
            "❌ <b>Data too large for QR code.</b>\n"
            "QR codes support up to ~2,900 bytes. Please shorten the text and try again.",
            parse_mode="HTML",
        )
        return
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
    # Phase 2K: multi-QR detection with type metadata
    results = qr.scan_qr_all_from_bytes(photo_bytes.read())
    if not results:
        await status.edit_text("❌ No QR code detected in image.")
        return
    if len(results) == 1:
        r = results[0]
        e_data = _html.escape(r["data"])
        e_type = _html.escape(r["type"])
        await status.edit_text(
            f"✅ <b>Decoded QR Output</b> <i>({e_type})</i>:\n<code>{e_data}</code>",
            parse_mode="HTML",
        )
    else:
        lines = [f"✅ <b>{len(results)} codes detected:</b>"]
        for i, r in enumerate(results, 1):
            e_data = _html.escape(r["data"])
            e_type = _html.escape(r["type"])
            lines.append(
                f"───────────────────────────\n"
                f"<b>#{i}</b> <i>({e_type})</i>\n<code>{e_data}</code>"
            )
        await status.edit_text("\n".join(lines), parse_mode="HTML")
