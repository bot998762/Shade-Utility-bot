from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from app.platform.capability import FeatureManifest
from app.keyboards.inline_kb import main_menu_kb, utils_menu_kb

manifest = FeatureManifest(name="GeneralTools", version="1.0.0", category="Core")
router = Router()

UTILS_LIST = (
    "✨ **SHADE UTILITY — NATIVE COMMANDS** ✨\n\n"
    "🆔 `/id` ➔ Get User, Chat & Reply Msg ID\n"
    "👤 `/info` ➔ Detailed Telegram Profile Info\n"
    "🔑 `/string` ➔ Generate Telegram String Session\n"
    "🔑 `/password [len]` ➔ Generate Strong Password\n"
    "🆔 `/uuid` ➔ Generate UUIDv4\n"
    "🔐 `/hash <text>` ➔ MD5 & SHA256 Hashes\n"
    "🔢 `/b64en <text>` ➔ Base64 Encode\n"
    "🔡 `/b64de <text>` ➔ Base64 Decode\n"
    "⏰ `/time` ➔ Current Unix Timestamp\n"
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
