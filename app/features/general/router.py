import aiohttp
import json
import time
from datetime import datetime
from urllib.parse import quote
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from app.platform.capability import FeatureManifest
from app.keyboards.inline_kb import main_menu_kb, utils_menu_kb
from app.utils import crypto

manifest = FeatureManifest(name="GeneralTools", version="1.0.0", category="Core")
router = Router()

UTILS_LIST = (
    "✨ **SHADE UTILITY — NATIVE COMMANDS** ✨\n\n"
    "⏰ `/epoch <timestamp>` ➔ Convert Epoch/Date\n"
    "🔗 `/urlen <text>` / `/urlde <text>` ➔ URL Encode/Decode\n"
    "🛡️ `/checkpwd <pwd>` ➔ Check Password Strength\n"
    "🌐 `/ua` ➔ Inspect User-Agent & Headers\n"
    "📋 `/jsonfmt <json>` ➔ Validate & Format JSON\n"
    "🌐 `/ip <ip/domain>` ➔ IP & Location Lookup\n"
    "⛅ `/weather <city>` ➔ Check Live Weather\n"
    "🆔 `/id` ➔ Get User, Chat & Reply Msg ID\n"
    "👤 `/info` ➔ Detailed Telegram Profile Info\n"
    "🔑 `/string` ➔ Generate Telegram String Session\n"
    "🔑 `/password [len]` ➔ Generate Strong Password\n"
    "🆔 `/uuid` ➔ Generate UUIDv4\n"
    "🔐 `/hash <text>` ➔ MD5, SHA256 & SHA512 Hashes\n"
    "🔢 `/b64en <text>` / `/b64de <text>` ➔ Base64 Tool\n"
    "🌐 `/short <url>` ➔ Shorten Long Link (Direct)\n"
    "🔳 `/qr <text/url>` ➔ Generate QR Code\n"
    "🔍 Reply with `/qrscan` ➔ Scan QR Code Image\n"
    "🌍 Reply with `/tr <lang>` ➔ Translate Text\n"
    "📝 Reply with `/ocr` ➔ Extract Text from Image\n"
)

@router.message(CommandStart())
async def cmd_start(message: Message, bot_username: str = "ShadeUtilityBot"):
    text = (
        f"⚡ **Welcome to Shade Utility Bot!** ⚡\n"
        f"───────────────────────────\n"
        f"👋 Hi **{message.from_user.first_name}**, main **Shade Ecosystem** ka official fast, lightweight utility assistant hoon!\n\n"
        f"👇 **Choose an option below to get started:**"
    )
    await message.answer(text, reply_markup=main_menu_kb(bot_username), parse_mode="Markdown")

@router.message(Command("epoch"))
async def cmd_epoch(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        now = int(time.time())
        dt = datetime.utcfromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S UTC')
        await message.reply(
            f"⏰ **Current Epoch Time:**\n`{now}`\n"
            f"📅 **UTC Date:** `{dt}`\n\n"
            f"💡 *Usage:* `/epoch <timestamp>` or `/epoch <YYYY-MM-DD>`",
            parse_mode="Markdown"
        )
        return
    
    val = args[1].strip()
    try:
        if val.isdigit():
            ts = int(val)
            dt = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S UTC')
            await message.reply(f"⏰ **Timestamp `{ts}`:**\n📅 `{dt}`", parse_mode="Markdown")
        else:
            dt_obj = datetime.fromisoformat(val)
            ts = int(dt_obj.timestamp())
            await message.reply(f"📅 **Date `{val}`:**\n⏰ Epoch: `{ts}`", parse_mode="Markdown")
    except Exception:
        await message.reply(f"❌ **Error parsing time/date format.**", parse_mode="Markdown")

@router.message(Command("urlen"))
async def cmd_urlen(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/urlen <text>`", parse_mode="Markdown")
        return
    encoded = crypto.url_encode(args[1])
    await message.reply(f"🔗 **URL Encoded:**\n`{encoded}`", parse_mode="Markdown")

@router.message(Command("urlde"))
async def cmd_urlde(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/urlde <text>`", parse_mode="Markdown")
        return
    decoded = crypto.url_decode(args[1])
    await message.reply(f"🔓 **URL Decoded:**\n`{decoded}`", parse_mode="Markdown")

@router.message(Command("checkpwd"))
async def cmd_checkpwd(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/checkpwd <password>`", parse_mode="Markdown")
        return
    strength = crypto.check_password_strength(args[1])
    await message.reply(f"🛡️ **Password Security Assessment:**\nStrength: `{strength}`", parse_mode="Markdown")

@router.message(Command("ua"))
async def cmd_ua(message: Message):
    user = message.from_user
    chat = message.chat
    text = (
        f"🌐 **Client & Request Inspector:**\n"
        f"───────────────\n"
        f"• **User ID:** `{user.id}`\n"
        f"• **Username:** @{user.username or 'None'}\n"
        f"• **Chat Type:** `{chat.type}`\n"
        f"• **Language Code:** `{user.language_code or 'en'}`\n"
        f"• **Platform Protocol:** `Telegram Bot API v8.0`\n"
        f"───────────────"
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
        await message.reply(f"📋 **Formatted JSON:**\n```json\n{formatted}\n```", parse_mode="Markdown")
    except Exception as e:
        await message.reply(f"❌ **Invalid JSON:** `{str(e)}`", parse_mode="Markdown")

@router.message(Command("ip"))
async def cmd_ip(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/ip <ip_address_or_domain>`", parse_mode="Markdown")
        return
    query = args[1].strip()
    status = await message.reply("🔍 Fetching IP / Domain details...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://ip-api.com/json/{query}", timeout=10) as resp:
                data = await resp.json()
                if data.get("status") == "success":
                    res_text = (
                        f"🌐 **IP / Domain Lookup Result:**\n"
                        f"───────────────\n"
                        f"• **Query:** `{data.get('query')}`\n"
                        f"• **Country:** {data.get('country')} ({data.get('countryCode')})\n"
                        f"• **Region:** {data.get('regionName')}\n"
                        f"• **City:** {data.get('city')}\n"
                        f"• **ISP / Org:** {data.get('isp')}\n"
                        f"• **Timezone:** `{data.get('timezone')}`\n"
                        f"───────────────"
                    )
                    await status.edit_text(res_text, parse_mode="Markdown")
                else:
                    await status.edit_text(f"❌ Lookup failed for `{query}`.", parse_mode="Markdown")
    except Exception as e:
        await status.edit_text(f"❌ Error fetching IP data: `{str(e)}`", parse_mode="Markdown")

@router.message(Command("weather"))
async def cmd_weather(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/weather <city_name>`", parse_mode="Markdown")
        return
    city = args[1].strip()
    status = await message.reply(f"⛅ Checking weather for **{city}**...", parse_mode="Markdown")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://wttr.in/{quote(city)}?format=j1", timeout=10) as resp:
                if resp.status != 200:
                    await status.edit_text(f"❌ City not found: `{city}`", parse_mode="Markdown")
                    return
                data = await resp.json()
                current = data['current_condition'][0]
                area = data['nearest_area'][0]
                
                res_text = (
                    f"⛅ **Weather Report: {area['areaName'][0]['value']}, {area['country'][0]['value']}**\n"
                    f"───────────────\n"
                    f"• **Condition:** {current['weatherDesc'][0]['value']}\n"
                    f"• **Temperature:** `{current['temp_C']}°C` (Feels like `{current['FeelsLikeC']}°C`)\n"
                    f"• **Humidity:** `{current['humidity']}%`\n"
                    f"• **Wind Speed:** `{current['windspeedKmph']} km/h`\n"
                    f"───────────────"
                )
                await status.edit_text(res_text, parse_mode="Markdown")
    except Exception as e:
        await status.edit_text(f"❌ Error fetching weather: `{str(e)}`", parse_mode="Markdown")

@router.message(Command("id"))
async def cmd_id(message: Message):
    text = "📌 **Telegram ID Details:**\n───────────────\n"
    text += f"👤 **Your User ID:** `{message.from_user.id}`\n"
    text += f"💬 **Chat ID:** `{message.chat.id}`\n"
    text += f"📱 **Chat Type:** `{message.chat.type}`\n"
    
    if message.message_thread_id:
        text += f"🧵 **Topic Thread ID:** `{message.message_thread_id}`\n"

    if message.reply_to_message:
        replied_user = message.reply_to_message.from_user
        text += f"\n📩 **Replied Message Details:**\n"
        text += f"• **Replied User ID:** `{replied_user.id}`\n"
        text += f"• **Replied User Name:** {replied_user.first_name}\n"
        text += f"• **Message ID:** `{message.reply_to_message.message_id}`\n"

    text += "───────────────\n💡 *Tap any ID to copy instantly!*"
    await message.reply(text, parse_mode="Markdown")

@router.message(Command("info"))
async def cmd_info(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    username = f"@{target.username}" if target.username else "None"
    is_premium = "Yes 🌟" if getattr(target, 'is_premium', False) else "No"
    
    info_text = (
        f"👤 **Telegram Profile Info:**\n"
        f"───────────────\n"
        f"• **First Name:** {target.first_name}\n"
        f"• **Last Name:** {target.last_name or 'None'}\n"
        f"• **Username:** {username}\n"
        f"• **User ID:** `{target.id}`\n"
        f"• **Telegram Premium:** {is_premium}\n"
        f"• **Is Bot:** {'Yes 🤖' if target.is_bot else 'No 👤'}\n"
        f"───────────────"
    )
    await message.reply(info_text, parse_mode="Markdown")

@router.callback_query(F.data == "cmd_string_info")
async def handle_string_info(call: CallbackQuery):
    msg = (
        "🔐 **Telegram String Session Generator**\n\n"
        "To generate Telethon / Pyrogram String session, send command:\n"
        "`/string <API_ID> <API_HASH> <PHONE_NUMBER>`\n\n"
        "**Example:**\n"
        "`/string 123456 abcdef1234567890 +919876543210`"
    )
    await call.message.edit_text(msg, reply_markup=utils_menu_kb(), parse_mode="Markdown")
    await call.answer()

@router.callback_query(F.data == "back_main")
async def back_to_main(call: CallbackQuery, bot_username: str = "ShadeUtilityBot"):
    text = f"⚡ **Shade Utility Main Menu** ⚡"
    await call.message.edit_text(text, reply_markup=main_menu_kb(bot_username), parse_mode="Markdown")
    await call.answer()

@router.callback_query(F.data == "menu_utils")
async def handle_utils_menu(call: CallbackQuery):
    await call.message.edit_text(text=UTILS_LIST, reply_markup=utils_menu_kb(), parse_mode="Markdown")
    await call.answer()

@router.callback_query(F.data.startswith("coming_soon_"))
async def handle_coming_soon(call: CallbackQuery):
    tool_name = call.data.split("_")[2].capitalize()
    await call.answer(text=f"⏳ {tool_name} Tools are under development! 🚀", show_alert=True)
