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
            "🔑 **Telegram String Session Generator**\n───────────────────────────\n"
            "📌 **Usage Format:**\n"
            "`/string <API_ID> <API_HASH> <PHONE_NUMBER>`\n\n"
            "💡 **Example:**\n"
            "`/string 1234567 0123456789abcdef0123456789abcdef +919876543210`\n"
            "───────────────────────────",
            parse_mode="Markdown"
        )
        return

    api_id = args[1]
    api_hash = args[2]
    phone = args[3]

    if not api_id.isdigit():
        await message.reply("❌ Invalid API_ID format. Numeric value required.")
        return

    status = await message.reply("🔄 Initializing Telethon Client...")
    
    try:
        client = TelegramClient(StringSession(), int(api_id), api_hash)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            await status.edit_text(
                "📩 **OTP Authorization Sent via Telegram!**\n───────────────────────────\n"
                "Check your official Telegram client for authentication code.\n"
                "*(Send code formatted with spaces like `1 2 3 4 5` to prevent revocation)*",
                parse_mode="Markdown"
            )
            await client.disconnect()
        else:
            session_str = client.session.save()
            await client.disconnect()
            await status.edit_text(f"✅ **Generated String Session:**\n\n`{session_str}`", parse_mode="Markdown")
    except Exception as e:
        await status.edit_text(f"❌ **Authentication Error:** `{str(e)}`", parse_mode="Markdown")
