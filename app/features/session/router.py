import re
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

router = Router()

# Dedicated FSM State for String Session
class StringSessionState(StatesGroup):
    waiting_for_otp = State()
    waiting_for_2fa = State()

@router.message(Command("string"))
async def cmd_string(message: Message, state: FSMContext):
    args = message.text.split()
    if len(args) < 4:
        await message.reply("⚠️ **Usage:** `/string <api_id> <api_hash> <phone_number>`", parse_mode="Markdown")
        return

    api_id = int(args[1])
    api_hash = args[2]
    phone_number = args[3]

    client = TelegramClient(None, api_id, api_hash)
    await client.connect()
    
    try:
        sent_code = await client.send_code_request(phone_number)
        
        # Save temp memory into FSM context
        await state.update_data(
            api_id=api_id,
            api_hash=api_hash,
            phone_number=phone_number,
            phone_code_hash=sent_code.phone_code_hash,
            client=client
        )
        
        # ACTIVATE STATE TO LISTEN TO NEXT OTP MESSAGE
        await state.set_state(StringSessionState.waiting_for_otp)
        
        await message.reply(
            "📩 **OTP Authorization Sent via Telegram!**\n\n"
            "Check your official Telegram client for authentication code.\n"
            "Send code formatted like `1 2 3 4 5` or `12345`.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await client.disconnect()
        await message.reply(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")


# OTP Handler (Fixes spaces & captures user input properly)
@router.message(StringSessionState.waiting_for_otp)
async def process_otp(message: Message, state: FSMContext):
    # Auto-clean spaces, backticks, or dashes entered by user
    raw_code = message.text.replace(" ", "").replace("`", "").replace("-", "").strip()
    
    if not raw_code.isdigit():
        await message.reply("⚠️ Invalid OTP format. Please send digits only (e.g. `3 7 1 5 9`).")
        return

    data = await state.get_data()
    client: TelegramClient = data["client"]

    try:
        await client.sign_in(
            phone=data["phone_number"],
            code=raw_code,
            phone_code_hash=data["phone_code_hash"]
        )
        
        # Generate String Session
        string_session = client.session.save()
        await client.disconnect()
        await state.clear()

        await message.reply(
            f"✅ **Session Generated Successfully!**\n\n`{string_session}`",
            parse_mode="Markdown"
        )

    except SessionPasswordNeededError:
        await state.set_state(StringSessionState.waiting_for_2fa)
        await message.reply("🔐 **2FA Password Required!**\nPlease enter your Two-Step Verification password.")

    except PhoneCodeInvalidError:
        await message.reply("❌ **Invalid OTP Code.** Please check and try again.")
    except Exception as e:
        await client.disconnect()
        await state.clear()
        await message.reply(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")


# 2FA Password Handler
@router.message(StringSessionState.waiting_for_2fa)
async def process_2fa(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    client: TelegramClient = data["client"]

    try:
        await client.sign_in(password=password)
        string_session = client.session.save()
        await client.disconnect()
        await state.clear()

        await message.reply(
            f"✅ **Session Generated Successfully!**\n\n`{string_session}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await client.disconnect()
        await state.clear()
        await message.reply(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")
