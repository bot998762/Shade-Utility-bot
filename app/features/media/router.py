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
from app.utils import telegram_text as _tt

manifest = FeatureManifest(name="MediaTools", version="1.0.0", category="Utility")
router = Router()
logger = setup_logger()

# CHG-028 — /ocr output must never exceed Telegram's message size. A result that
# fits one message is sent exactly as before; longer text is split into at most
# _OCR_MAX_MESSAGES escaped <code> blocks with an explicit truncation notice.
_OCR_MAX_MESSAGES = 4
_OCR_RULE = "───────────────────────────"
_OCR_TITLE = "📝 OCR Extracted Result:"
_OCR_FOOTER = "Tap text block to copy."
# Worst-case literal (non-markup) text around a chunk, used to size the chunks.
_OCR_CHUNK_OVERHEAD = (
    f"📝 OCR Extracted Result (part {_OCR_MAX_MESSAGES} of {_OCR_MAX_MESSAGES}):\n"
    f"{_OCR_RULE}\n\n{_OCR_RULE}\n{_OCR_FOOTER}\n"
    "⚠️ Output truncated: 9999999 more characters not shown."
)


def _ocr_single_html(text: str) -> str:
    return (
        f"📝 <b>OCR Extracted Result:</b>\n"
        f"{_OCR_RULE}\n"
        f"<code>{_html.escape(text)}</code>\n"
        f"{_OCR_RULE}\n"
        f"<i>{_OCR_FOOTER}</i>"
    )


def _ocr_messages(text: str) -> list[str]:
    """HTML messages for an OCR result, each within Telegram's size limit."""
    single_visible = f"{_OCR_TITLE}\n{_OCR_RULE}\n{text}\n{_OCR_RULE}\n{_OCR_FOOTER}"
    if _tt.fits(single_visible):
        return [_ocr_single_html(text)]
    chunks = _tt.split_text(text, _tt.chunk_room(_OCR_CHUNK_OVERHEAD))
    shown = chunks[:_OCR_MAX_MESSAGES]
    omitted = len(text) - sum(len(c) for c in shown)
    total = len(shown)
    messages = []
    for index, chunk in enumerate(shown, start=1):
        body = (
            f"📝 <b>OCR Extracted Result (part {index} of {total}):</b>\n"
            f"{_OCR_RULE}\n"
            f"<code>{_html.escape(chunk)}</code>\n"
            f"{_OCR_RULE}\n"
            f"<i>{_OCR_FOOTER}</i>"
        )
        if index == total and omitted > 0:
            body += f"\n⚠️ Output truncated: {omitted} more characters not shown."
        messages.append(body)
    return messages


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
    status_resolved = False
    try:
        photo = message.reply_to_message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file_info.file_path)

        extracted_text = await ocr_service.extract_text(photo_bytes.read(), message.from_user.id)

        if extracted_text:
            # OCR output can contain any character including backticks, asterisks,
            # underscores: every chunk is html.escape()d inside <code>.
            messages = _ocr_messages(extracted_text)
            await status.edit_text(messages[0], parse_mode="HTML")
            status_resolved = True
            for part in messages[1:]:
                await message.reply(part, parse_mode="HTML")
        else:
            await status.edit_text("❌ No optical text detected in image payload.")
            status_resolved = True
    except Exception:
        # Do not leave the user on "Processing…". The original error is always
        # re-raised so the error middleware keeps logging and replying as before.
        if not status_resolved:
            try:
                await status.edit_text("❌ OCR failed. Please try again.")
            except Exception as edit_exc:  # noqa: BLE001 - secondary failure; original re-raised below
                logger.warning({"event": "ocr_status_update_failed", "error": type(edit_exc).__name__})
        raise


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


# CHG-029 — /short expand replies must stay within Telegram's message size.
# A chain of long tracking URLs can exceed it (each hop may be up to
# safe_url.MAX_URL_LENGTH characters). Replies that fit are built exactly as
# before; only oversized ones use the compact form below, in which every
# shortened URL is an explicitly labelled, incomplete prefix.
_EXPAND_MARKER_RESERVE = 70   # worst-case visible text of one "(shortened: …)" label
_EXPAND_MIN_HOP_UNITS = 40    # smallest prefix worth showing for an intermediate hop


def _expand_full_text(hops: list[str], truncated: bool) -> str:
    """The standard expansion reply (unchanged since CHG-025)."""
    import html as _html

    final = hops[-1]
    hop_count = len(hops) - 1
    e_final = _html.escape(final)
    if hop_count == 0 and not truncated:
        # No HTTP redirect (3xx + Location) was seen. That does NOT prove the
        # URL is the real destination: some shorteners (e.g. v.gd) answer with
        # a landing/preview page that only shows the target as a clickable link.
        return (
            "🔗 <b>URL Expansion:</b>\n"
            "No HTTP redirect was detected for:\n"
            f"<code>{e_final}</code>\n"
            "ℹ️ This may be a landing or preview page, so the actual destination may differ."
        )
    hop_lines = "\n".join(f"  {i+1}. <code>{_html.escape(h)}</code>" for i, h in enumerate(hops))
    text = (
        f"🔗 <b>URL Expansion ({hop_count} redirect{'s' if hop_count != 1 else ''}):</b>\n"
        f"{hop_lines}\n"
        f"───────────────────────────\n"
    )
    if truncated:
        text += f"⚠️ Stopped after {_MAX_REDIRECTS} redirects — the chain continues.\n<b>Last URL reached:</b> <code>{e_final}</code>"
    else:
        text += f"✅ <b>Final destination:</b> <code>{e_final}</code>"
    return text


def _expand_prefix(url: str, max_units: int) -> str:
    """Longest prefix of ``url`` within ``max_units`` UTF-16 units (code-point safe)."""
    chunks = _tt.split_text(url, max_units)
    return chunks[0] if chunks else ""


def _expand_shortened(url: str, max_units: int) -> tuple[str, str]:
    """(escaped_code_html, label_html) for a URL shown within ``max_units``.

    A URL that fits is returned complete with no label. Otherwise the result is
    an escaped prefix followed by an explicit "shortened / incomplete" label.
    Escaping happens after truncation, so no entity is ever cut.
    """
    import html as _html

    if _tt.utf16_len(url) <= max_units:
        return f"<code>{_html.escape(url)}</code>", ""
    prefix = _expand_prefix(url, max_units)
    return (
        f"<code>{_html.escape(prefix)}</code>…",
        f" <i>(shortened: first {len(prefix)} of {len(url)} characters — incomplete)</i>",
    )


def _expansion_text(hops: list[str], truncated: bool) -> str:
    """HTML reply for a finished trace, always within the unsplit message budget."""
    full = _expand_full_text(hops, truncated)
    if _tt.fits(_tt.html_visible_text(full)):
        return full

    budget = _tt.SINGLE_MESSAGE_BUDGET
    final = hops[-1]
    hop_count = len(hops) - 1
    head = (
        f"🔗 <b>URL Expansion ({hop_count} redirect{'s' if hop_count != 1 else ''}, "
        "long URLs shortened):</b>\n"
    )
    rule = "───────────────────────────\n"
    if truncated:
        final_label = f"⚠️ Stopped after {_MAX_REDIRECTS} redirects — the chain continues.\n<b>Last URL reached"
    else:
        final_label = "✅ <b>Final destination"
    note = (
        "\nℹ️ URLs marked “shortened” are incomplete prefixes, not usable links."
    )
    # Visible-text overhead of everything except the URLs and shortening labels.
    skeleton = _tt.html_visible_len(
        head + "".join(f"  {i+1}. \n" for i in range(len(hops))) + rule + final_label + " (shortened): " + note
    )
    reserve = _EXPAND_MARKER_RESERVE * (len(hops) + 1)
    free = budget - skeleton - reserve

    # The final destination keeps priority: complete whenever it fits.
    final_room = max(free - _EXPAND_MIN_HOP_UNITS * len(hops), _EXPAND_MIN_HOP_UNITS)
    final_units = min(_tt.utf16_len(final), final_room)
    hop_room = max(free - final_units, 0)

    # Share the remaining room: short hops stay complete and free their
    # unused share for longer ones (water-filling).
    units = [_tt.utf16_len(h) for h in hops]
    allowance = [0] * len(hops)
    pending = list(range(len(hops)))
    remaining = hop_room
    while pending:
        share = remaining // len(pending)
        fits_now = [i for i in pending if units[i] <= share]
        if not fits_now:
            for i in pending:
                allowance[i] = max(share, _EXPAND_MIN_HOP_UNITS)
            break
        for i in fits_now:
            allowance[i] = units[i]
            remaining -= units[i]
            pending.remove(i)

    def build(final_cap: int, caps: list[int]) -> tuple[str, bool]:
        lines, any_short = [], False
        for i, h in enumerate(hops):
            code, label = _expand_shortened(h, caps[i])
            any_short = any_short or bool(label)
            lines.append(f"  {i+1}. {code}{label}")
        f_code, f_label = _expand_shortened(final, final_cap)
        any_short = any_short or bool(f_label)
        shortened_final = " (shortened)" if f_label else ""
        text = (
            head + "\n".join(lines) + "\n" + rule
            + f"{final_label}{shortened_final}:</b> {f_code}{f_label}"
        )
        if any_short:
            text += note
        return text, any_short

    # Defensive loop: the allocation above targets the budget; tighten until the
    # measured visible size really fits (it normally succeeds on the first pass).
    caps = allowance[:]
    final_cap = final_units
    for _ in range(8):
        text, _short = build(final_cap, caps)
        over = _tt.html_visible_len(text) - budget
        if over <= 0:
            return text
        caps = [max(c - (over // len(hops) + 8), _EXPAND_MIN_HOP_UNITS) for c in caps]
        if all(c == _EXPAND_MIN_HOP_UNITS for c in caps):
            final_cap = max(final_cap - over - 8, _EXPAND_MIN_HOP_UNITS)
    return text


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

    try:
        await status.edit_text(_expansion_text(result.hops, result.truncated), parse_mode="HTML")
    except Exception:
        # CHG-029: do not leave the user on "Tracing…". The original error is
        # always re-raised so the error middleware keeps logging and replying.
        try:
            await status.edit_text("❌ Could not display the expansion result. Please try again.")
        except Exception as edit_exc:  # noqa: BLE001 - secondary failure; original re-raised below
            logger.warning({"event": "short_expand_status_update_failed", "error": type(edit_exc).__name__})
        raise


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


# Telegram limits a photo caption to 1024 characters AFTER entity parsing (HTML
# tags removed, entities such as &lt; counted as one character). A QR code can
# hold more than that, so the caption must never simply repeat the input.
# 900 is a conservative budget; length is measured in UTF-16 code units, which
# is how Telegram counts, so astral characters (emoji) count as two.
_QR_CAPTION_LIMIT = 900
_QR_CAPTION_PREVIEW_CHARS = 200
_QR_CAPTION_TITLE = "🔳 Generated QR Code Matrix:\n"

# CHG-027 — dense-code hint. Decided on the actual QR version (module density),
# not on input length: version v has 17 + 4v modules per side. Version 29 is
# 133 modules per side. In an approximate screen-display simulation (image
# shown ~480 px wide, light blur + JPEG) zbar first failed to decode at
# version 29 (~3.4 px per module); below it decoding held. This is a
# heuristic from a simulation, not a camera test. Typical lowercase text
# reaches version 29 at about 1,200 characters (all-uppercase about 1,700).
_QR_DENSE_VERSION = 29


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _build_qr_caption(content: str, version: int | None = None) -> str:
    """HTML caption for the QR photo, always within Telegram's limit.

    Input that fits the budget keeps the original caption byte-for-byte.
    Longer input is shown as a short escaped preview plus a truncation
    notice; the QR image itself always carries the full text. Escaping is
    applied after truncation and truncation is by code point, so neither an
    HTML entity nor a character is ever cut in half.

    When ``version`` (the QR version actually used) is at or above
    ``_QR_DENSE_VERSION`` a short scanning hint is appended. It makes no claim
    that the code was decoded or verified; an unknown version adds nothing.
    """
    warning = ""
    if version is not None and version >= _QR_DENSE_VERSION:
        warning = (
            f"\n⚠️ Dense QR code (version {version}): it may be hard to scan "
            "from a screen. Zoom in or use a dedicated scanner."
        )
    if _utf16_len(_QR_CAPTION_TITLE) + _utf16_len(content) + _utf16_len(warning) <= _QR_CAPTION_LIMIT:
        return f"🔳 <b>Generated QR Code Matrix:</b>\n<code>{_html.escape(content)}</code>{warning}"
    preview = content[:_QR_CAPTION_PREVIEW_CHARS]
    return (
        "🔳 <b>Generated QR Code Matrix:</b>\n"
        f"<code>{_html.escape(preview)}</code>…\n"
        f"ℹ️ Input truncated: showing the first {len(preview)} of {len(content)} "
        f"characters. The QR code contains the full text.{warning}"
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
        bio, qr_version = qr.generate_qr_with_version(content)
    except QRDataOverflowError:
        # Capacity depends on the content's encoding mode (digits, uppercase
        # alphanumeric, or bytes) and on error correction, so no fixed limit
        # is promised here.
        await message.reply(
            "❌ <b>Data too large for QR code.</b>\n"
            "Capacity depends on the text and its encoding. "
            "Please shorten the input and try again.",
            parse_mode="HTML",
        )
        return
    try:
        input_file = BufferedInputFile(bio.getvalue(), filename="qrcode.png")
        # User-supplied QR content can contain any characters; the caption is
        # escaped and length-limited by _build_qr_caption (CHG-026).
        await message.reply_photo(
            photo=input_file,
            caption=_build_qr_caption(content, qr_version),
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
