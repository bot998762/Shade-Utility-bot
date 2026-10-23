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
from app.core.logger import setup_logger
from app.utils import safe_url as _su

manifest = FeatureManifest(name="MediaTools", version="1.0.0", category="Utility")
router = Router()
logger = setup_logger()


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
async def cmd_short(
    message: Message,
    shortener_service: ShortenerService,
    bootstrap_ref,
) -> None:
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
        await _cmd_short_expand(message, args[2].strip(), bootstrap_ref)
        return

    # Existing shortening path — UNCHANGED
    url = await shortener_service.shorten_url(args[1].strip())
    # Shortened URLs contain only safe chars; escape for correctness
    e_url = _html.escape(url)
    await message.reply(f"🌐 <b>Shortened Direct Link:</b>\n{e_url}", parse_mode="HTML")


# Initial-URL rejection reasons -> user-facing text (no host/IP echoed back).
_EXPAND_URL_ERRORS = {
    "scheme": "❌ Only http:// and https:// URLs are supported.",
    "credentials": "❌ URLs containing credentials are not supported.",
    "port": "❌ Invalid port in URL.",
    "blocked": "❌ Private/reserved host in URL — cannot expand.",
}

_MAX_REDIRECTS = _su.MAX_REDIRECTS


async def _cmd_short_expand(message, raw_url: str, bootstrap_ref=None) -> None:
    """
    CHG-024 — SSRF-hardened URL expansion.

    Security decisions are NOT made here by inspecting hostname strings. The
    guarded session (bootstrap.expand_session) validates the resolved
    destination addresses at connection time, and app.utils.safe_url
    validates the URL and every redirect target before it is requested.
    This handler only maps outcomes to user-facing text.
    """
    import html as _html

    try:
        target = _su.validate_public_http_url(raw_url)
    except _su.UnsafeURLError as exc:
        await message.reply(
            _EXPAND_URL_ERRORS.get(exc.code, "❌ Invalid URL format."),
            parse_mode="HTML",
        )
        return

    # Fail closed: never fall back to an unguarded session.
    session = getattr(bootstrap_ref, "expand_session", None)
    if session is None or getattr(session, "closed", False):
        await message.reply("❌ URL expansion is temporarily unavailable.", parse_mode="HTML")
        return

    status = await message.reply(
        f"🔍 Tracing <code>{_html.escape(raw_url[:100])}</code>...",
        parse_mode="HTML",
    )

    try:
        result = await _su.trace_redirects(session, target)
    except _su.RedirectBlockedError as exc:
        logger.warning({"event": "short_expand_redirect_blocked", "reason": exc.code})
        if exc.code == "scheme":
            text = "⛔ Redirect to non-HTTP scheme blocked."
        else:
            text = "⛔ Redirect to a private, internal or invalid destination blocked."
        await status.edit_text(text, parse_mode="HTML")
        return
    except _su.RedirectLoopError:
        await status.edit_text("⛔ Redirect loop detected — expansion stopped.", parse_mode="HTML")
        return
    except Exception as exc:
        kind = _su.classify_network_error(exc)
        logger.warning({
            "event": "short_expand_failed",
            "kind": kind,
            "error": type(exc).__name__,
        })
        text = {
            "blocked": "⛔ Destination is not allowed — cannot expand.",
            "timeout": "⏱️ The request timed out while tracing.",
        }.get(kind, "⏱️ Network error while tracing the URL.")
        await status.edit_text(text, parse_mode="HTML")
        return

    hops = result.hops
    final = hops[-1]
    hop_count = len(hops) - 1
    e_final = _html.escape(final)
    if hop_count == 0 and not result.truncated:
        # No HTTP redirect (3xx + Location) was seen. That does NOT prove the
        # URL is the real destination: some shorteners (e.g. v.gd) answer with
        # a landing/preview page that only shows the target as a clickable link.
        text = (
            "🔗 <b>URL Expansion:</b>\n"
            "No HTTP redirect was detected for:\n"
            f"<code>{e_final}</code>\n"
            "ℹ️ This may be a landing or preview page, so the actual destination may differ."
        )
    else:
        hop_lines = "\n".join(f"  {i+1}. <code>{_html.escape(h)}</code>" for i, h in enumerate(hops))
        text = (
            f"🔗 <b>URL Expansion ({hop_count} redirect{'s' if hop_count != 1 else ''}):</b>\n"
            f"{hop_lines}\n"
            f"───────────────────────────\n"
        )
        if result.truncated:
            text += f"⚠️ Stopped after {_MAX_REDIRECTS} redirects — the chain continues.\n<b>Last URL reached:</b> <code>{e_final}</code>"
        else:
            text += f"✅ <b>Final destination:</b> <code>{e_final}</code>"
    await status.edit_text(text, parse_mode="HTML")


@router.message(Command("tr"))
async def cmd_translate(
    message: Message,
    translator_service: TranslatorService,
) -> None:
    # Translation is under development. The full implementation (providers,
    # orchestrator, services) is preserved and will be wired up in a future
    # release. For now, every /tr invocation returns the upcoming-feature notice.
    await message.reply(
        "🌐 <b>Translation — Coming Soon!</b>\n\n"
        "Translation is currently under development and will be available "
        "in a future update.\n\n"
        "Stay tuned for upcoming updates!",
        parse_mode="HTML",
    )


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
