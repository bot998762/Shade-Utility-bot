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
    user = message.from_user
    chat = message.chat
    text = (
        f"🌐 **Client Request Inspector**\n"
        f"───────────────────────────\n"
        f"👤 **User ID:** `{user.id}`\n"
        f"📛 **Username:** @{user.username or 'None'}\n"
        f"💬 **Chat Context:** `{chat.type}`\n"
        f"🌐 **Language:** `{user.language_code or 'en'}`\n"
        f"───────────────────────────"
    )
    await message.reply(text, parse_mode="Markdown")


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


def _is_safe_host(host: str) -> bool:
    """Basic SSRF guard: reject private/loopback targets."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(host)
        return not (addr.is_private or addr.is_loopback or addr.is_link_local)
    except ValueError:
        # It's a hostname; block obvious internal names
        lower = host.lower()
        return not any(lower == h or lower.endswith(f".{h}") for h in (
            "localhost", "internal", "local", "metadata", "169.254.169.254"
        ))


@router.message(Command("ip"))
async def cmd_ip(message: Message, bootstrap_ref) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/ip <ip_address_or_domain>`", parse_mode="Markdown")
        return
    query = args[1].strip()

    if not _is_safe_host(query):
        await message.reply("❌ Private/reserved addresses are not allowed.", parse_mode="Markdown")
        return

    status = await message.reply("🔍 Executing Network Geo-Lookup...")
    try:
        import aiohttp
        session: aiohttp.ClientSession = bootstrap_ref.http_session
        async with session.get(
            f"https://ip-api.com/json/{query}",  # HTTPS endpoint
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json()
            if data.get("status") == "success":
                res_text = (
                    f"🌐 **Network Geo-Lookup Result**\n"
                    f"───────────────────────────\n"
                    f"📍 **Target:** `{data.get('query')}`\n"
                    f"🏳️ **Country:** {data.get('country')} ({data.get('countryCode')})\n"
                    f"🏙️ **City/Region:** {data.get('city')}, {data.get('regionName')}\n"
                    f"📡 **ISP Provider:** {data.get('isp')}\n"
                    f"🕒 **Timezone:** `{data.get('timezone')}`\n"
                    f"───────────────────────────"
                )
                await status.edit_text(res_text, parse_mode="Markdown")
            else:
                await status.edit_text(f"❌ Lookup failed for `{query}`.", parse_mode="Markdown")
    except Exception as exc:
        await status.edit_text(f"❌ Network Query Error: `{type(exc).__name__}`", parse_mode="Markdown")


@router.message(Command("weather"))
async def cmd_weather(message: Message, bootstrap_ref) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/weather <city_name>`", parse_mode="Markdown")
        return
    city = args[1].strip()
    if len(city) > 100:
        await message.reply("❌ City name too long.", parse_mode="Markdown")
        return

    status = await message.reply(f"⛅ Fetching weather for **{city}**...", parse_mode="Markdown")
    try:
        import aiohttp
        session: aiohttp.ClientSession = bootstrap_ref.http_session
        async with session.get(
            f"https://wttr.in/{quote(city)}?format=j1",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                await status.edit_text(f"❌ Location query failed: `{city}`", parse_mode="Markdown")
                return
            data = await resp.json()
            current = data["current_condition"][0]
            area = data["nearest_area"][0]
            res_text = (
                f"⛅ **Weather: {area['areaName'][0]['value']}, {area['country'][0]['value']}**\n"
                f"───────────────────────────\n"
                f"🌡️ **Temperature:** `{current['temp_C']}°C` (Feels `{current['FeelsLikeC']}°C`)\n"
                f"☁️ **Condition:** {current['weatherDesc'][0]['value']}\n"
                f"💧 **Humidity:** `{current['humidity']}%`\n"
                f"💨 **Wind:** `{current['windspeedKmph']} km/h`\n"
                f"───────────────────────────"
            )
            await status.edit_text(res_text, parse_mode="Markdown")
    except Exception as exc:
        await status.edit_text(f"❌ Weather Error: `{type(exc).__name__}`", parse_mode="Markdown")


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    text = "📌 **Telegram Identity Matrix:**\n───────────────────────────\n"
    text += f"👤 **Your User ID:** `{message.from_user.id}`\n"
    text += f"💬 **Chat Context ID:** `{message.chat.id}`\n"
    text += f"📱 **Chat Type:** `{message.chat.type}`\n"
    if message.message_thread_id:
        text += f"🧵 **Topic Thread ID:** `{message.message_thread_id}`\n"
    if message.reply_to_message:
        replied_user = message.reply_to_message.from_user
        text += (
            f"\n📩 **Replied Target:**\n"
            f"• **User ID:** `{replied_user.id}`\n"
            f"• **Name:** {replied_user.first_name}\n"
            f"• **Message ID:** `{message.reply_to_message.message_id}`\n"
        )
    text += "───────────────────────────"
    await message.reply(text, parse_mode="Markdown")


@router.message(Command("info"))
async def cmd_info(message: Message) -> None:
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    username = f"@{target.username}" if target.username else "None"
    is_premium = "Active 🌟" if getattr(target, "is_premium", False) else "Standard"
    info_text = (
        f"👤 **Telegram Profile Metadata**\n"
        f"───────────────────────────\n"
        f"• **First Name:** {target.first_name}\n"
        f"• **Last Name:** {target.last_name or 'None'}\n"
        f"• **Username:** {username}\n"
        f"• **Numeric ID:** `{target.id}`\n"
        f"• **Premium Rank:** {is_premium}\n"
        f"• **Entity Type:** {'Bot 🤖' if target.is_bot else 'User 👤'}\n"
        f"───────────────────────────"
    )
    await message.reply(info_text, parse_mode="Markdown")
