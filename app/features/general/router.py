from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from app.platform.capability import FeatureManifest
from app.keyboards.inline_kb import main_menu_kb, utils_menu_kb

manifest = FeatureManifest(name="GeneralTools", version="1.0.0", category="Core")
router = Router()

UTILS_LIST = (
    "✨ **SHADE UTILITY — NATIVE COMMANDS** ✨\n\n"
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
