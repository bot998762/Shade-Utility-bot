import aiohttp
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

HELP_MANUAL_TEXT = (
    "📖 **SHADE UTILITY — ADVANCED USER MANUAL**
"
    "───────────────────────────

"
    "⚙️ **DEVELOPER & CRYPTO TOOLS**
"
    "• `/epoch <timestamp|date>` ➔ Convert Unix timestamp to ISO UTC or vice versa.
"
    "• `/urlen <text>` ➔ Percent-encode string for safe URL query transmission.
"
    "• `/urlde <text>` ➔ Decode percent-encoded URL string back to plain text.
"
    "• `/b64en <text>` ➔ Convert string to standard Base64 representation.
"
    "• `/b64de <string>` ➔ Decode Base64 encoded payload back to plain text.
"
    "• `/hash <text>` ➔ Calculate MD5, SHA-256, and SHA-512 hashes simultaneously.
"
    "• `/password [length]` ➔ Generate high-entropy cryptographic password (8-64 chars).
"
    "• `/checkpwd <password>` ➔ Evaluate entropy score and character complexity.
"
    "• `/uuid` ➔ Generate a cryptographically secure random UUIDv4 string.
"
    "• `/jsonfmt <json_str>` ➔ Validate and pretty-print raw JSON payload.

"
    "🔑 **TELEGRAM AUTHENTICATION**
"
    "• `/string` ➔ Interactively generate Telethon/Pyrogram String Session.

"
    "📸 **MEDIA & OCR TOOLS**
"
    "• Reply photo with `/ocr` ➔ Extract text using multi-engine OCR failover.
"
    "• `/qr <text|url>` ➔ Generate downloadable PNG QR Code image.
"
    "• Reply image with `/qrscan` ➔ Decode embedded QR code from image.
"
    "• Reply text with `/tr <lang>` ➔ Translate text (e.g. `/tr es`, `/tr hi`).

"
    "🌐 **NETWORK & SYSTEM TOOLS**
"
    "• `/ip <ip|domain>` ➔ Query IP location, ISP, country, and timezone.
"
    "• `/weather <city>` ➔ Fetch live temperature, humidity, and forecast.
"
    "• `/short <url>` ➔ Shorten long URLs using high-uptime shortener engine.
"
    "• `/ua` ➔ Inspect user payload, telegram engine info, and protocol.
"
    "• `/info` ➔ Inspect detailed Telegram profile metadata.
"
    "• `/id` ➔ Retrieve instant numeric ID for user, chat, thread, or message.
"
    "───────────────────────────"
)

@router.message(CommandStart())
async def cmd_start(message: Message, bot_username: str = "ShadeUtilityBot"):
    start_banner = (
        f"⚡ **SHADE UTILITY PLATFORM V8** ⚡
"
        f"───────────────────────────
"
        f"Hello **{message.from_user.first_name}** 👋

"
        f"Welcome to **Shade Ecosystem** — a high-performance, stateless, developer-centric utility suite built for speed, accuracy, and reliability.

"
        f"🚀 **Core Features Active:**
"
        f"• 🛠️ **Dev Suite:** Hashes, Encoders, JSON, Timestamps
"
        f"• 🔐 **Auth Tools:** Telegram String Session Generator
"
        f"• 📸 **Media Utility:** OCR Parsing, QR Generator/Scanner
"
        f"• 🌐 **Web Utility:** Network IP Lookup, Weather, Link Shortener

"
        f"👇 Select a category below or type `/help` for the full manual:"
    )
    await message.answer(start_banner, reply_markup=main_menu_kb(bot_username), parse_mode="Markdown")

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.reply(HELP_MANUAL_TEXT, reply_markup=category_dev_kb(), parse_mode="Markdown")

@router.callback_query(F.data == "cat_dev")
async def handle_dev_cat(call: CallbackQuery):
    msg = (
        "🛠️ **DEVELOPER & CRYPTO UTILITIES**
"
        "───────────────────────────
"
        "⏰ `/epoch <time>` ➔ Timestamp / ISO Date Converter
"
        "🔗 `/urlen <text>` ➔ URL Encoder
"
        "🔓 `/urlde <text>` ➔ URL Decoder
"
        "🔢 `/b64en <text>` ➔ Base64 Encoder
"
        "🔡 `/b64de <text>` ➔ Base64 Decoder
"
        "🔐 `/hash <text>` ➔ MD5, SHA256 & SHA512 Hashes
"
        "🔑 `/password [len]` ➔ Secure Password Generator
"
        "🛡️ `/checkpwd <pwd>` ➔ Password Complexity Inspector
"
        "🆔 `/uuid` ➔ Generate Random UUIDv4
"
        "📋 `/jsonfmt <json>` ➔ Format & Validate JSON Payload
"
        "───────────────────────────"
    )
    await call.message.edit_text(msg, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()

@router.callback_query(F.data == "cat_session")
async def handle_session_cat(call: CallbackQuery):
    msg = (
        "🔑 **TELEGRAM STRING SESSION GENERATOR**
"
        "───────────────────────────
"
        "Generate String Session for Telethon and Pyrogram frameworks.

"
        "📌 **Usage Command:**
"
        "`/string <API_ID> <API_HASH> <PHONE_NUMBER>`

"
        "💡 **Example:**
"
        "`/string 123456 abcdef1234567890 +919876543210`
"
        "───────────────────────────"
    )
    await call.message.edit_text(msg, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()

@router.callback_query(F.data == "cat_media")
async def handle_media_cat(call: CallbackQuery):
    msg = (
        "📸 **MEDIA & OCR UTILITIES**
"
        "───────────────────────────
"
        "📝 **Reply photo with** `/ocr` ➔ Extract Text from Image
"
        "🔳 `/qr <text|url>` ➔ Generate PNG QR Code
"
        "🔍 **Reply QR photo with** `/qrscan` ➔ Decode Image QR Code
"
        "🌍 **Reply text with** `/tr <lang>` ➔ Translate Text Language
"
        "───────────────────────────"
    )
    await call.message.edit_text(msg, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()

@router.callback_query(F.data == "cat_web")
async def handle_web_cat(call: CallbackQuery):
    msg = (
        "🌐 **WEB & NETWORK UTILITIES**
"
        "───────────────────────────
"
        "🌐 `/ip <ip|domain>` ➔ IP Geo-Location & ISP Lookup
"
        "⛅ `/weather <city>` ➔ Live Meteorological Report
"
        "🌐 `/short <url>` ➔ Instant Direct Link Shortener
"
        "🌐 `/ua` ➔ Client Protocol Inspector
"
        "👤 `/info` ➔ Inspect Profile Metadata
"
        "📌 `/id` ➔ Numeric ID Inspector
"
        "───────────────────────────"
    )
    await call.message.edit_text(msg, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()

@router.callback_query(F.data == "menu_help")
async def handle_utils_menu(call: CallbackQuery):
    await call.message.edit_text(HELP_MANUAL_TEXT, reply_markup=category_dev_kb(), parse_mode="Markdown")
    await call.answer()

@router.callback_query(F.data == "back_main")
async def back_to_main(call: CallbackQuery, bot_username: str = "ShadeUtilityBot"):
    start_banner = (
        f"⚡ **SHADE UTILITY PLATFORM V8** ⚡
"
        f"───────────────────────────
"
        f"Hello **{call.from_user.first_name}** 👋

"
        f"Welcome to **Shade Ecosystem** — a high-performance, stateless, developer-centric utility suite built for speed, accuracy, and reliability.

"
        f"🚀 **Core Features Active:**
"
        f"• 🛠️ **Dev Suite:** Hashes, Encoders, JSON, Timestamps
"
        f"• 🔐 **Auth Tools:** Telegram String Session Generator
"
        f"• 📸 **Media Utility:** OCR Parsing, QR Generator/Scanner
"
        f"• 🌐 **Web Utility:** Network IP Lookup, Weather, Link Shortener

"
        f"👇 Select a category below or type `/help` for the full manual:"
    )
    await call.message.edit_text(start_banner, reply_markup=main_menu_kb(bot_username), parse_mode="Markdown")
    await call.answer()

@router.message(Command("epoch"))
async def cmd_epoch(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        now = int(time.time())
        dt = datetime.utcfromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S UTC')
        await message.reply(
            f"⏰ **Current Unix Epoch:**
`{now}`

"
            f"📅 **Formatted UTC:**
`{dt}`

"
            f"💡 *Usage:* `/epoch <timestamp>` or `/epoch <YYYY-MM-DD>`",
            parse_mode="Markdown"
        )
        return
    
    val = args[1].strip()
    try:
        if val.isdigit():
            ts = int(val)
            dt = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S UTC')
            await message.reply(f"⏰ **Timestamp:** `{ts}`
📅 **UTC Date:** `{dt}`", parse_mode="Markdown")
        else:
            dt_obj = datetime.fromisoformat(val)
            ts = int(dt_obj.timestamp())
            await message.reply(f"📅 **Input Date:** `{val}`
⏰ **Unix Epoch:** `{ts}`", parse_mode="Markdown")
    except Exception:
        await message.reply("❌ **Invalid Date or Timestamp format.**", parse_mode="Markdown")

@router.message(Command("urlen"))
async def cmd_urlen(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/urlen <text>`", parse_mode="Markdown")
        return
    encoded = crypto.url_encode(args[1])
    await message.reply(f"🔗 **URL Encoded Payload:**
`{encoded}`", parse_mode="Markdown")

@router.message(Command("urlde"))
async def cmd_urlde(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/urlde <text>`", parse_mode="Markdown")
        return
    decoded = crypto.url_decode(args[1])
    await message.reply(f"🔓 **URL Decoded Output:**
`{decoded}`", parse_mode="Markdown")

@router.message(Command("checkpwd"))
async def cmd_checkpwd(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/checkpwd <password>`", parse_mode="Markdown")
        return
    strength = crypto.check_password_strength(args[1])
    await message.reply(f"🛡️ **Security Entropy Evaluation:**
Strength Score: `{strength}`", parse_mode="Markdown")

@router.message(Command("ua"))
async def cmd_ua(message: Message):
    user = message.from_user
    chat = message.chat
    text = (
        f"🌐 **Client Request Inspector**
"
        f"───────────────────────────
"
        f"👤 **User ID:** `{user.id}`
"
        f"📛 **Username:** @{user.username or 'None'}
"
        f"💬 **Chat Context:** `{chat.type}`
"
        f"🌐 **Language:** `{user.language_code or 'en'}`
"
        f"⚡ **Engine Protocol:** `Telegram Engine API v8.0`
"
        f"───────────────────────────"
    )
    await message.reply(text, parse_mode="Markdown")

@router.message(Command("jsonfmt"))
async def cmd_jsonfmt(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/jsonfmt <json_string>`", parse_mode="Markdown")
        return
    try:
        parsed = json.loads(args[1])
        formatted = json.dumps(parsed, indent=4)
        await message.reply(f"📋 **Pretty JSON Output:**
```json
{formatted}
```", parse_mode="Markdown")
    except Exception as e:
        await message.reply(f"❌ **Invalid JSON Payload:** `{str(e)}`", parse_mode="Markdown")

@router.message(Command("ip"))
async def cmd_ip(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/ip <ip_address_or_domain>`", parse_mode="Markdown")
        return
    query = args[1].strip()
    status = await message.reply("🔍 Executing Network Geo-Lookup...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://ip-api.com/json/{query}", timeout=10) as resp:
                data = await resp.json()
                if data.get("status") == "success":
                    res_text = (
                        f"🌐 **Network Geo-Lookup Result**
"
                        f"───────────────────────────
"
                        f"📍 **Target:** `{data.get('query')}`
"
                        f"🏳️ **Country:** {data.get('country')} ({data.get('countryCode')})
"
                        f"🏙️ **City/Region:** {data.get('city')}, {data.get('regionName')}
"
                        f"📡 **ISP Provider:** {data.get('isp')}
"
                        f"🕒 **Timezone:** `{data.get('timezone')}`
"
                        f"───────────────────────────"
                    )
                    await status.edit_text(res_text, parse_mode="Markdown")
                else:
                    await status.edit_text(f"❌ Lookup failed for target `{query}`.", parse_mode="Markdown")
    except Exception as e:
        await status.edit_text(f"❌ Network Query Error: `{str(e)}`", parse_mode="Markdown")

@router.message(Command("weather"))
async def cmd_weather(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/weather <city_name>`", parse_mode="Markdown")
        return
    city = args[1].strip()
    status = await message.reply(f"⛅ Fetching meteorological data for **{city}**...", parse_mode="Markdown")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://wttr.in/{quote(city)}?format=j1", timeout=10) as resp:
                if resp.status != 200:
                    await status.edit_text(f"❌ Location query failed: `{city}`", parse_mode="Markdown")
                    return
                data = await resp.json()
                current = data['current_condition'][0]
                area = data['nearest_area'][0]
                
                res_text = (
                    f"⛅ **Weather: {area['areaName'][0]['value']}, {area['country'][0]['value']}**
"
                    f"───────────────────────────
"
                    f"🌡️ **Temperature:** `{current['temp_C']}°C` (Feels like `{current['FeelsLikeC']}°C`)
"
                    f"☁️ **Condition:** {current['weatherDesc'][0]['value']}
"
                    f"💧 **Humidity Index:** `{current['humidity']}%`
"
                    f"💨 **Wind Velocity:** `{current['windspeedKmph']} km/h`
"
                    f"───────────────────────────"
                )
                await status.edit_text(res_text, parse_mode="Markdown")
    except Exception as e:
        await status.edit_text(f"❌ Weather Provider Error: `{str(e)}`", parse_mode="Markdown")

@router.message(Command("id"))
async def cmd_id(message: Message):
    text = "📌 **Telegram Identity Matrix:**
───────────────────────────
"
    text += f"👤 **Your User ID:** `{message.from_user.id}`
"
    text += f"💬 **Chat Context ID:** `{message.chat.id}`
"
    text += f"📱 **Chat Type:** `{message.chat.type}`
"
    
    if message.message_thread_id:
        text += f"🧵 **Topic Thread ID:** `{message.message_thread_id}`
"

    if message.reply_to_message:
        replied_user = message.reply_to_message.from_user
        text += f"
📩 **Replied Context Target:**
"
        text += f"• **Replied User ID:** `{replied_user.id}`
"
        text += f"• **Replied Name:** {replied_user.first_name}
"
        text += f"• **Message ID:** `{message.reply_to_message.message_id}`
"

    text += "───────────────────────────
💡 *Tap any value block to copy instantly.*"
    await message.reply(text, parse_mode="Markdown")

@router.message(Command("info"))
async def cmd_info(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    username = f"@{target.username}" if target.username else "None"
    is_premium = "Active 🌟" if getattr(target, 'is_premium', False) else "Standard"
    
    info_text = (
        f"👤 **Telegram Profile Metadata**
"
        f"───────────────────────────
"
        f"• **First Name:** {target.first_name}
"
        f"• **Last Name:** {target.last_name or 'None'}
"
        f"• **Username:** {username}
"
        f"• **Numeric ID:** `{target.id}`
"
        f"• **Premium Rank:** {is_premium}
"
        f"• **Account Entity:** {'Bot 🤖' if target.is_bot else 'User 👤'}
"
        f"───────────────────────────"
    )
    await message.reply(info_text, parse_mode="Markdown")
