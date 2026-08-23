import json
import time
from datetime import datetime
from urllib.parse import quote
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from app.platform.capability import FeatureManifest
from app.keyboards.inline_kb import main_menu_kb, category_dev_kb
from app.utils import crypto
from app.utils.network import is_safe_host as _is_safe_host
from app.core.logger import setup_logger

logger = setup_logger()

manifest = FeatureManifest(name="GeneralTools", version="1.0.0", category="Core")
router = Router()

HELP_MANUAL_TEXT = """📖 **SHADE UTILITY — ADVANCED USER MANUAL**
───────────────────────────

⚙️ **DEVELOPER & CRYPTO TOOLS**
• `/epoch <timestamp|date>` ➔ Convert Unix timestamp to ISO UTC or vice versa.
• `/urlen <text>` ➔ Percent-encode string for safe URL query transmission.
• `/urlde <text>` ➔ Decode percent-encoded URL string back to plain text.
• `/b64en <text>` ➔ Convert string to standard Base64 representation.
• `/b64de <string>` ➔ Decode Base64 encoded payload back to plain text.
• `/hash <text>` ➔ Calculate MD5, SHA-256, and SHA-512 hashes simultaneously.
• `/password [length]` ➔ Generate high-entropy cryptographic password (8-64 chars).
• `/checkpwd <password>` ➔ Evaluate entropy score and character complexity.
• `/uuid` ➔ Generate a cryptographically secure random UUIDv4 string.
• `/jsonfmt <json_str>` ➔ Validate and pretty-print raw JSON payload.

🔑 **TELEGRAM AUTHENTICATION**
• `/string <api_id> <api_hash>` ➔ Generate Telethon String Session via QR login.

📸 **MEDIA & OCR TOOLS**
• Reply photo with `/ocr` ➔ Extract text using multi-engine OCR failover.
• `/qr <text|url>` ➔ Generate downloadable PNG QR Code image.
• Reply image with `/qrscan` ➔ Decode embedded QR code from image.
• Reply text with `/tr <lang>` ➔ Translate text (e.g. `/tr es`, `/tr hi`).

🌐 **NETWORK & SYSTEM TOOLS**
• `/ip <ip|domain>` ➔ Query IP location, ISP, country, and timezone.
• `/weather <city>` ➔ Fetch live temperature, humidity, and forecast.
• `/short <url>` ➔ Shorten long URLs using high-uptime shortener engine.
• `/ua` ➔ Inspect user payload, telegram engine info, and protocol.
• `/info` ➔ Inspect detailed Telegram profile metadata.
• `/id` ➔ Retrieve instant numeric ID for user, chat, thread, or message.
───────────────────────────"""


@router.message(CommandStart())
async def cmd_start(message: Message, bot_username: str = "ShadeUtilityBot") -> None:
    start_banner = (
        f"⚡ **SHADE UTILITY PLATFORM V8** ⚡\n"
        f"───────────────────────────\n"
        f"Hello **{message.from_user.first_name}** 👋\n\n"
        f"Welcome to **Shade Ecosystem** — a high-performance, developer-centric utility suite.\n\n"
        f"🚀 **Core Features Active:**\n"
        f"• 🛠️ **Dev Suite:** Hashes, Encoders, JSON, Timestamps\n"
        f"• 🔐 **Auth Tools:** Telegram String Session Generator\n"
        f"• 📸 **Media Utility:** OCR Parsing, QR Generator/Scanner\n"
        f"• 🌐 **Web Utility:** Network IP Lookup, Weather, Link Shortener\n\n"
        f"👇 Select a category below or type `/help` for the full manual:"
    )
    await message.answer(start_banner, reply_markup=main_menu_kb(bot_username), parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.reply(HELP_MANUAL_TEXT, reply_markup=category_dev_kb(), parse_mode="Markdown")


@router.callback_query(F.data == "cat_dev")
async def handle_dev_cat(call: CallbackQuery) -> None:
    msg = (
        "🛠️ **DEVELOPER & CRYPTO UTILITIES**\n"
        "───────────────────────────\n"
        "⏰ `/epoch <time>` ➔ Timestamp / ISO Date Converter\n"
        "🔗 `/urlen <text>` ➔ URL Encoder\n"
        "🔓 `/urlde <text>` ➔ URL Decoder\n"
        "🔢 `/b64en <text>` ➔ Base64 Encoder\n"
        "🔡 `/b64de <text>` ➔ Base64 Decoder\n"
        "🔐 `/hash <text>` ➔ MD5, SHA256 & SHA512 Hashes\n"
        "🔑 `/password [len]` ➔ Secure Password Generator\n"
        "🛡️ `/checkpwd <pwd>` ➔ Password Complexity Inspector\n"
        "🆔 `/uuid` ➔ Generate Random UUIDv4\n"
        "📋 `/jsonfmt <json>` ➔ Format & Validate JSON Payload\n"
        "───────────────────────────"
    )
    await call.message.edit_text(msg, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()


@router.callback_query(F.data == "cat_session")
async def handle_session_cat(call: CallbackQuery) -> None:
    msg = (
        "🔑 **TELEGRAM STRING SESSION GENERATOR**\n"
        "───────────────────────────\n"
        "Generate a String Session for Telethon via QR login.\n\n"
        "📌 **Usage:**\n"
        "`/string <API_ID> <API_HASH>`\n\n"
        "💡 Get credentials at https://my.telegram.org\n"
        "───────────────────────────"
    )
    await call.message.edit_text(msg, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()


@router.callback_query(F.data == "cat_media")
async def handle_media_cat(call: CallbackQuery) -> None:
    msg = (
        "📸 **MEDIA & OCR UTILITIES**\n"
        "───────────────────────────\n"
        "📝 **Reply photo with** `/ocr` ➔ Extract Text from Image\n"
        "🔳 `/qr <text|url>` ➔ Generate PNG QR Code\n"
        "🔍 **Reply QR photo with** `/qrscan` ➔ Decode Image QR Code\n"
        "🌍 **Reply text with** `/tr <lang>` ➔ Translate Text Language\n"
        "───────────────────────────"
    )
    await call.message.edit_text(msg, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()


@router.callback_query(F.data == "cat_web")
async def handle_web_cat(call: CallbackQuery) -> None:
    msg = (
        "🌐 **WEB & NETWORK UTILITIES**\n"
        "───────────────────────────\n"
        "🌐 `/ip <ip|domain>` ➔ IP Geo-Location & ISP Lookup\n"
        "⛅ `/weather <city>` ➔ Live Meteorological Report\n"
        "🌐 `/short <url>` ➔ Instant Direct Link Shortener\n"
        "🌐 `/ua` ➔ Client Protocol Inspector\n"
        "👤 `/info` ➔ Inspect Profile Metadata\n"
        "📌 `/id` ➔ Numeric ID Inspector\n"
        "───────────────────────────"
    )
    await call.message.edit_text(msg, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()


@router.callback_query(F.data == "menu_help")
async def handle_utils_menu(call: CallbackQuery) -> None:
    await call.message.edit_text(HELP_MANUAL_TEXT, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()


@router.callback_query(F.data == "back_main")
async def back_to_main(call: CallbackQuery, bot_username: str = "ShadeUtilityBot") -> None:
    start_banner = (
        f"⚡ **SHADE UTILITY PLATFORM V8** ⚡\n"
        f"───────────────────────────\n"
        f"Hello **{call.from_user.first_name}** 👋\n\n"
        f"Welcome to **Shade Ecosystem** — a high-performance, developer-centric utility suite.\n\n"
        f"🚀 **Core Features Active:**\n"
        f"• 🛠️ **Dev Suite:** Hashes, Encoders, JSON, Timestamps\n"
        f"• 🔐 **Auth Tools:** Telegram String Session Generator\n"
        f"• 📸 **Media Utility:** OCR Parsing, QR Generator/Scanner\n"
        f"• 🌐 **Web Utility:** Network IP Lookup, Weather, Link Shortener\n\n"
        f"👇 Select a category below or type `/help` for the full manual:"
    )
    await call.message.edit_text(start_banner, reply_markup=main_menu_kb(bot_username), parse_mode="Markdown")
    await call.answer()


@router.message(Command("epoch"))
async def cmd_epoch(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        now = int(time.time())
        dt = datetime.utcfromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S UTC')
        await message.reply(
            f"⏰ **Current Unix Epoch:**\n`{now}`\n\n"
            f"📅 **Formatted UTC:**\n`{dt}`\n\n"
            f"💡 *Usage:* `/epoch <timestamp>` or `/epoch <YYYY-MM-DD>`",
            parse_mode="Markdown",
        )
        return

    val = args[1].strip()
    try:
        if val.isdigit():
            ts = int(val)
            dt = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S UTC')
            await message.reply(f"⏰ **Timestamp:** `{ts}`\n📅 **UTC Date:** `{dt}`", parse_mode="Markdown")
        else:
            dt_obj = datetime.fromisoformat(val)
            ts = int(dt_obj.timestamp())
            await message.reply(f"📅 **Input Date:** `{val}`\n⏰ **Unix Epoch:** `{ts}`", parse_mode="Markdown")
    except Exception:
        await message.reply("❌ **Invalid Date or Timestamp format.**", parse_mode="Markdown")


@router.message(Command("urlen"))
async def cmd_urlen(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/urlen <text>`", parse_mode="Markdown")
        return
    encoded = crypto.url_encode(args[1])
    await message.reply(f"🔗 **URL Encoded Payload:**\n`{encoded}`", parse_mode="Markdown")


@router.message(Command("urlde"))
async def cmd_urlde(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/urlde <text>`", parse_mode="Markdown")
        return
    decoded = crypto.url_decode(args[1])
    await message.reply(f"🔓 **URL Decoded Output:**\n`{decoded}`", parse_mode="Markdown")


@router.message(Command("checkpwd"))
async def cmd_checkpwd(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/checkpwd <password>`", parse_mode="Markdown")
        return
    strength = crypto.check_password_strength(args[1])
    await message.reply(f"🛡️ **Security Entropy Evaluation:**\nStrength: `{strength}`", parse_mode="Markdown")


@router.message(Command("ua"))
async def cmd_ua(message: Message) -> None:
    import html as _html
    user = message.from_user
    chat = message.chat
    # Username can contain underscores: @john_doe → Markdown reads _doe as italic start
    e_user = _html.escape(f"@{user.username}") if user.username else "None"
    e_lang = _html.escape(user.language_code or "en")
    text = (
        f"🌐 <b>Client Request Inspector</b>\n"
        f"───────────────────────────\n"
        f"👤 <b>User ID:</b> <code>{user.id}</code>\n"
        f"📛 <b>Username:</b> {e_user}\n"
        f"💬 <b>Chat Context:</b> <code>{chat.type}</code>\n"
        f"🌐 <b>Language:</b> <code>{e_lang}</code>\n"
        f"───────────────────────────"
    )
    await message.reply(text, parse_mode="HTML")


@router.message(Command("jsonfmt"))
async def cmd_jsonfmt(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/jsonfmt <json_string>`", parse_mode="Markdown")
        return
    try:
        parsed = json.loads(args[1])
        formatted = json.dumps(parsed, indent=4)
        await message.reply(f"📋 **Pretty JSON Output:**\n```json\n{formatted}\n```", parse_mode="Markdown")
    except Exception as exc:
        await message.reply(f"❌ **Invalid JSON:** `{exc}`", parse_mode="Markdown")




@router.message(Command("ip"))
async def cmd_ip(message: Message, bootstrap_ref) -> None:
    import html as _html
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ <b>Usage:</b> <code>/ip &lt;ip_address_or_domain&gt;</code>", parse_mode="HTML")
        return
    query = args[1].strip()

    if not _is_safe_host(query):
        await message.reply("❌ Private/reserved addresses are not allowed.", parse_mode="HTML")
        return

    status = await message.reply("🔍 Executing Network Geo-Lookup...")
    import aiohttp, json as _json, time as _time
    session: aiohttp.ClientSession = bootstrap_ref.http_session
    # ip-api.com: HTTP is the free-tier endpoint; HTTPS requires a paid key.
    url = f"http://ip-api.com/json/{query}"
    t0 = _time.monotonic()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            raw = await resp.text(encoding="utf-8", errors="replace")
            latency_ms = int((_time.monotonic() - t0) * 1000)

            if resp.status == 429:
                logger.warning({"event": "ip_rate_limited", "query": query, "latency_ms": latency_ms})
                await status.edit_text(
                    "⏳ IP lookup service is temporarily rate-limited. Please try again in a moment.",
                    parse_mode="HTML",
                )
                return

            if resp.status != 200:
                logger.warning({
                    "event": "ip_http_error",
                    "query": query,
                    "status": resp.status,
                    "latency_ms": latency_ms,
                })
                await status.edit_text(
                    "❌ IP lookup service is temporarily unavailable.",
                    parse_mode="HTML",
                )
                return

            try:
                data = _json.loads(raw)
            except (_json.JSONDecodeError, ValueError):
                logger.error({
                    "event": "ip_non_json",
                    "query": query,
                    "body_preview": raw[:150],
                    "latency_ms": latency_ms,
                })
                await status.edit_text(
                    "❌ Unexpected response from IP lookup service.",
                    parse_mode="HTML",
                )
                return

            if data.get("status") == "success":
                # Escape all external API strings — ISP names like "AT&T", "O2_Mobile" etc.
                e_query   = _html.escape(str(data.get("query", "")))
                e_country = _html.escape(str(data.get("country", "")))
                e_cc      = _html.escape(str(data.get("countryCode", "")))
                e_city    = _html.escape(str(data.get("city", "")))
                e_region  = _html.escape(str(data.get("regionName", "")))
                e_isp     = _html.escape(str(data.get("isp", "")))
                e_tz      = _html.escape(str(data.get("timezone", "")))
                res_text = (
                    f"🌐 <b>Network Geo-Lookup Result</b>\n"
                    f"───────────────────────────\n"
                    f"📍 <b>Target:</b> <code>{e_query}</code>\n"
                    f"🏳️ <b>Country:</b> {e_country} ({e_cc})\n"
                    f"🏙️ <b>City/Region:</b> {e_city}, {e_region}\n"
                    f"📡 <b>ISP Provider:</b> {e_isp}\n"
                    f"🕒 <b>Timezone:</b> <code>{e_tz}</code>\n"
                    f"───────────────────────────"
                )
                await status.edit_text(res_text, parse_mode="HTML")
            else:
                fail_msg = _html.escape(str(data.get("message", "unknown")))
                e_q = _html.escape(query)
                logger.info({"event": "ip_lookup_failed", "query": query, "reason": data.get("message")})
                await status.edit_text(
                    f"❌ Could not look up <code>{e_q}</code>: {fail_msg}",
                    parse_mode="HTML",
                )

    except aiohttp.ServerTimeoutError:
        logger.warning({"event": "ip_timeout", "query": query})
        await status.edit_text("⏱️ IP lookup timed out. Please try again.", parse_mode="HTML")
    except aiohttp.ClientConnectorError as exc:
        logger.error({"event": "ip_connection_error", "error": type(exc).__name__})
        await status.edit_text("❌ Cannot reach IP lookup service.", parse_mode="HTML")
    except Exception as exc:
        logger.error({"event": "ip_unexpected_error", "query": query, "error": type(exc).__name__})
        await status.edit_text("❌ IP lookup error. Please try again later.", parse_mode="HTML")


@router.message(Command("weather"))
async def cmd_weather(message: Message, bootstrap_ref) -> None:
    import html as _html
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ <b>Usage:</b> <code>/weather &lt;city_name&gt;</code>", parse_mode="HTML")
        return
    city = args[1].strip()
    if len(city) > 100:
        await message.reply("❌ City name too long.", parse_mode="HTML")
        return

    e_city = _html.escape(city)
    status = await message.reply(f"⛅ Fetching weather for <b>{e_city}</b>...", parse_mode="HTML")
    import aiohttp, json as _json, time as _time
    session: aiohttp.ClientSession = bootstrap_ref.http_session
    from urllib.parse import quote_plus
    url = f"https://wttr.in/{quote_plus(city)}?format=j1"
    t0 = _time.monotonic()
    try:
        async with session.get(
            url,
            headers={"Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            raw = await resp.text(encoding="utf-8", errors="replace")
            latency_ms = int((_time.monotonic() - t0) * 1000)

            if resp.status != 200:
                logger.warning({
                    "event": "weather_http_error",
                    "city": city,
                    "status": resp.status,
                    "latency_ms": latency_ms,
                })
                await status.edit_text(
                    "❌ Weather service is temporarily unavailable. Please try again.",
                    parse_mode="HTML",
                )
                return

            try:
                data = _json.loads(raw)
            except (_json.JSONDecodeError, ValueError):
                logger.info({
                    "event": "weather_city_not_found",
                    "city": city,
                    "latency_ms": latency_ms,
                    "body_preview": raw[:120],
                })
                await status.edit_text(
                    f"❌ Location <b>{e_city}</b> not found.\n"
                    f"Try a more specific name, e.g. <code>/weather London, UK</code>",
                    parse_mode="HTML",
                )
                return

            if "current_condition" not in data or "nearest_area" not in data:
                logger.error({
                    "event": "weather_unexpected_schema",
                    "city": city,
                    "keys": list(data.keys())[:10],
                })
                await status.edit_text(
                    "❌ Unexpected response from weather service.",
                    parse_mode="HTML",
                )
                return

            try:
                current = data["current_condition"][0]
                area    = data["nearest_area"][0]
                # Escape all external-API strings — ISP/city/description can contain &, <, >
                e_area    = _html.escape(str(area["areaName"][0]["value"]))
                e_country = _html.escape(str(area["country"][0]["value"]))
                e_desc    = _html.escape(str(current["weatherDesc"][0]["value"]))
                res_text = (
                    f"⛅ <b>Weather: {e_area}, {e_country}</b>\n"
                    f"───────────────────────────\n"
                    f"🌡️ <b>Temperature:</b> <code>{current['temp_C']}°C</code>"
                    f" (Feels <code>{current['FeelsLikeC']}°C</code>)\n"
                    f"☁️ <b>Condition:</b> {e_desc}\n"
                    f"💧 <b>Humidity:</b> <code>{current['humidity']}%</code>\n"
                    f"💨 <b>Wind:</b> <code>{current['windspeedKmph']} km/h</code>\n"
                    f"───────────────────────────"
                )
                await status.edit_text(res_text, parse_mode="HTML")
            except (KeyError, IndexError, TypeError) as exc:
                logger.error({
                    "event": "weather_schema_mismatch",
                    "city": city,
                    "error": type(exc).__name__,
                })
                await status.edit_text(
                    "❌ Could not parse weather data. Please try again.",
                    parse_mode="HTML",
                )

    except aiohttp.ServerTimeoutError:
        logger.warning({"event": "weather_timeout", "city": city})
        await status.edit_text("⏱️ Weather service timed out. Please try again.", parse_mode="HTML")
    except aiohttp.ClientConnectorError as exc:
        logger.error({"event": "weather_connection_error", "error": type(exc).__name__})
        await status.edit_text("❌ Cannot reach weather service.", parse_mode="HTML")
    except Exception as exc:
        logger.error({"event": "weather_unexpected_error", "city": city, "error": type(exc).__name__})
        await status.edit_text("❌ Weather service error. Please try again later.", parse_mode="HTML")


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    import html as _html
    # Use HTML mode — numeric IDs and chat types are always safe,
    # but first_name of the replied user can contain _ * etc.
    text = (
        "📌 <b>Telegram Identity Matrix:</b>\n"
        "───────────────────────────\n"
        f"👤 <b>Your User ID:</b> <code>{message.from_user.id}</code>\n"
        f"💬 <b>Chat Context ID:</b> <code>{message.chat.id}</code>\n"
        f"📱 <b>Chat Type:</b> <code>{message.chat.type}</code>\n"
    )
    if message.message_thread_id:
        text += f"🧵 <b>Topic Thread ID:</b> <code>{message.message_thread_id}</code>\n"
    if message.reply_to_message:
        replied_user = message.reply_to_message.from_user
        if replied_user is None:
            text += (
                f"\n📩 <b>Replied Message:</b>\n"
                f"• <b>Message ID:</b> <code>{message.reply_to_message.message_id}</code>\n"
                f"• <b>Sender:</b> Anonymous / Channel\n"
            )
        else:
            e_name = _html.escape(replied_user.first_name or "")
            text += (
                f"\n📩 <b>Replied Target:</b>\n"
                f"• <b>User ID:</b> <code>{replied_user.id}</code>\n"
                f"• <b>Name:</b> {e_name}\n"
                f"• <b>Message ID:</b> <code>{message.reply_to_message.message_id}</code>\n"
            )
    text += "───────────────────────────"
    await message.reply(text, parse_mode="HTML")


@router.message(Command("info"))
async def cmd_info(message: Message) -> None:
    import html as _html
    target = (
        message.reply_to_message.from_user
        if message.reply_to_message
        else message.from_user
    )
    # from_user is None for channel posts and anonymous admins
    if target is None:
        await message.reply(
            "❌ Cannot inspect this message type.\n"
            "It appears to be from a channel or anonymous sender.",
        )
        return

    # html.escape() every user-controlled field — underscore/asterisk/backtick in
    # first_name or username cause TelegramBadRequest in Markdown mode.
    e_first  = _html.escape(target.first_name or "")
    e_last   = _html.escape(target.last_name or "None")
    e_user   = _html.escape(f"@{target.username}") if target.username else "None"
    is_premium = "Active 🌟" if getattr(target, "is_premium", False) else "Standard"
    entity   = "Bot 🤖" if target.is_bot else "User 👤"

    info_text = (
        f"👤 <b>Telegram Profile Metadata</b>\n"
        f"───────────────────────────\n"
        f"• <b>First Name:</b> {e_first}\n"
        f"• <b>Last Name:</b> {e_last}\n"
        f"• <b>Username:</b> {e_user}\n"
        f"• <b>Numeric ID:</b> <code>{target.id}</code>\n"
        f"• <b>Premium Rank:</b> {is_premium}\n"
        f"• <b>Entity Type:</b> {entity}\n"
        f"───────────────────────────"
    )
    await message.reply(info_text, parse_mode="HTML")
