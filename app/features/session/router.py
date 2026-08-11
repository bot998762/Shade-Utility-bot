import re
import asyncio
from types import SimpleNamespace
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

# Feature Manifest required by app/features/__init__.py
manifest = SimpleNamespace(
    name="session",
    description="Telegram String Session Generator Feature",
    version="1.0.0"
)

router = Router()

# Global runtime memory cache for Telethon clients
ACTIVE_CLIENTS = {}

class StringSessionState(StatesGroup):
    waiting_for_otp = State()
    waiting_for_2fa = State()


@router.message(Command("string"))
async def cmd_string(message: Message, state: FSMContext):
    args = message.text.split()
    if len(args) < 4:
        await message.reply("⚠️ **Usage:** `/string <api_id> <api_hash> <phone_number>`", parse_mode="Markdown")
        return

    try:
        api_id = int(args[1])
        api_hash = args[2].strip()
        phone_number = args[3].strip()
    except ValueError:
        await message.reply("❌ Invalid API ID. It must be a number.")
        return

    user_id = message.from_user.id

    if user_id in ACTIVE_CLIENTS:
        try:
            await ACTIVE_CLIENTS[user_id]["client"].disconnect()
        except Exception:
            pass
        del ACTIVE_CLIENTS[user_id]

    client = TelegramClient(None, api_id, api_hash)
    await client.connect()

    try:
        sent_code = await client.send_code_request(phone_number)
        
        ACTIVE_CLIENTS[user_id] = {
            "client": client,
            "phone_number": phone_number,
            "phone_code_hash": sent_code.phone_code_hash
        }

        await state.set_state(StringSessionState.waiting_for_otp)

        await message.reply(
            "📩 **OTP Authorization Sent via Telegram!**\n\n"
            "Check your official Telegram client for authentication code.\n"
            "Simply send code below (e.g. `82123` or `8 2 1 2 3`).",
            parse_mode="Markdown"
        )
    except Exception as e:
        await client.disconnect()
        if user_id in ACTIVE_CLIENTS:
            del ACTIVE_CLIENTS[user_id]
        await message.reply(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")


@router.message(StringSessionState.waiting_for_otp)
async def process_otp(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if user_id not in ACTIVE_CLIENTS:
        await state.clear()
        await message.reply("❌ Session timed out. Please run `/string` command again.")
        return

    # Extracts only numeric digits from user message
    raw_code = re.sub(r"\D", "", message.text.strip())

    if not raw_code:
        await message.reply("⚠️ Invalid OTP format. Please send digits only.")
        return

    session_data = ACTIVE_CLIENTS[user_id]
    client: TelegramClient = session_data["client"]

    try:
        await client.sign_in(
            phone=session_data["phone_number"],
            code=raw_code,
            phone_code_hash=session_data["phone_code_hash"]
        )

        string_session = client.session.save()
        await client.disconnect()
        del ACTIVE_CLIENTS[user_id]
        await state.clear()

        await message.reply(
            f"✅ **Session Generated Successfully!**\n\n`{string_session}`",
            parse_mode="Markdown"
        )

    except SessionPasswordNeededError:
        await state.set_state(StringSessionState.waiting_for_2fa)
        await message.reply("🔐 **2FA Password Required!**\nPlease enter your Two-Step Verification password below.")

    except PhoneCodeInvalidError:
        await message.reply("❌ **Invalid OTP Code.** Please double check and send again.")

    except Exception as e:
        await client.disconnect()
        if user_id in ACTIVE_CLIENTS:
            del ACTIVE_CLIENTS[user_id]
        await state.clear()
        await message.reply(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")


@router.message(StringSessionState.waiting_for_2fa)
async def process_2fa(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if user_id not in ACTIVE_CLIENTS:
        await state.clear()
        await message.reply("❌ Session expired. Please restart with `/string`.")
        return

    password = message.text.strip()
    session_data = ACTIVE_CLIENTS[user_id]
    client: TelegramClient = session_data["client"]

    try:
        await client.sign_in(password=password)
        string_session = client.session.save()
        await client.disconnect()
        del ACTIVE_CLIENTS[user_id]
        await state.clear()

        await message.reply(
            f"✅ **Session Generated Successfully!**\n\n`{string_session}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await client.disconnect()
        if user_id in ACTIVE_CLIENTS:
            del ACTIVE_CLIENTS[user_id]
        await state.clear()
        await message.reply(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")
