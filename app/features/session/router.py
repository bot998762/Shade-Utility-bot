from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.platform.capability import FeatureManifest
from telethon import TelegramClient
from telethon.sessions import StringSession

manifest = FeatureManifest(name="SessionGen", version="1.0.0", category="Utility")
router = Router()

@router.message(Command("string"))
async def cmd_string_gen(message: Message):
    args = message.text.split()
    if len(args) < 4:
        await message.reply(
            "🔑 **Telegram String Session Helper**\n\n"
            "**Usage:**\n"
            "`/string <API_ID> <API_HASH> <PHONE_NUMBER>`\n\n"
            "**Example:**\n"
            "`/string 1234567 0123456789abcdef0123456789abcdef +919876543210`\n\n"
            "💡 *Get API_ID and API_HASH from my.telegram.org*",
            parse_mode="Markdown"
        )
        return

    api_id = args[1]
    api_hash = args[2]
    phone = args[3]

    if not api_id.isdigit():
        await message.reply("❌ Invalid API_ID. It must be numeric.")
        return

    status = await message.reply("🔄 Initializing Telethon Session Client...")
    
    try:
        client = TelegramClient(StringSession(), int(api_id), api_hash)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            await status.edit_text(
                "📩 **OTP Sent via Telegram!**\n\n"
                "Please check your Telegram app for login code.\n"
                "*(Safety feature: Send OTP with space like `1 2 3 4 5` to prevent auto-expiry)*",
                parse_mode="Markdown"
            )
            await client.disconnect()
        else:
            session_str = client.session.save()
            await client.disconnect()
            await status.edit_text(f"✅ **String Session Generated:**\n\n`{session_str}`", parse_mode="Markdown")
    except Exception as e:
        await status.edit_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")
