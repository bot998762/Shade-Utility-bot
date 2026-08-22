"""
Session Feature — Telegram String Session Generator
====================================================
Uses QR-based login (not OTP-over-chat) to avoid Telegram's
"code previously shared" security block. The OTP flow requires
the user to forward a login code *through* the same Telegram
session being authenticated, which Telegram's security layer
detects and blocks. QR login is the supported out-of-band path.

State machine:
  IDLE → (cmd_string) → QR_PENDING → (scan) → AUTHENTICATED
                                             → 2FA_REQUIRED → (process_2fa) → AUTHENTICATED
                                     → TIMEOUT / ERROR → IDLE
"""

import time
import asyncio
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError

from app.platform.capability import FeatureManifest
from app.utils.qr import generate_qr_buffer
from app.core.logger import setup_logger

manifest = FeatureManifest(
    name="session",
    description="Telegram String Session Generator via QR Login",
    version="2.0.0",
    category="Auth",
)

router = Router()
logger = setup_logger()

SESSION_TIMEOUT_SECS = 120  # QR scan window

# Per-user state: { user_id: { client, qr_login, task, chat_id, created_at } }
ACTIVE_CLIENTS: dict[int, dict] = {}


class StringSessionState(StatesGroup):
    waiting_for_2fa = State()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _cleanup_user_session(user_id: int) -> None:
    """Cancel background task and disconnect Telethon client for a user."""
    session_data = ACTIVE_CLIENTS.pop(user_id, None)
    if session_data is None:
        return

    task: asyncio.Task | None = session_data.get("task")
    # Never cancel or await the current task from within itself —
    # doing so causes a 2-second dead-wait on every QR timeout.
    if task and not task.done() and task is not asyncio.current_task():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass

    client: TelegramClient | None = session_data.get("client")
    if client:
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass


async def _wait_for_qr(
    user_id: int,
    state: FSMContext,
    bot: Bot,
    chat_id: int,
) -> None:
    """
    Background task: wait for QR scan, then either:
    - deliver session string (success), or
    - prompt for 2FA (SessionPasswordNeededError), or
    - report timeout / error.
    """
    session_data = ACTIVE_CLIENTS.get(user_id)
    if session_data is None:
        return

    qr_login = session_data["qr_login"]
    client: TelegramClient = session_data["client"]

    try:
        try:
            await asyncio.wait_for(qr_login.wait(), timeout=SESSION_TIMEOUT_SECS)
        except asyncio.TimeoutError:
            await _cleanup_user_session(user_id)
            await state.clear()
            await bot.send_message(
                chat_id,
                "⏱️ QR code expired. Run `/string` again to get a new one.",
                parse_mode="Markdown",
            )
            return
        except SessionPasswordNeededError:
            # QR scanned successfully but account has 2FA
            # Keep client alive; process_2fa will call sign_in(password=…)
            await state.set_state(StringSessionState.waiting_for_2fa)
            await bot.send_message(
                chat_id,
                "🔐 **Two-Step Verification required.**\n"
                "Please send your 2FA password below.",
                parse_mode="Markdown",
            )
            return

        # Authenticated — extract and deliver session
        string_session: str = client.session.save()
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.info({"event": "session_generated", "user_id": user_id})
        await bot.send_message(
            chat_id,
            "✅ **Session Generated Successfully!**\n\n"
            "⚠️ *Copy and delete this message immediately.*\n\n"
            f"`{string_session}`",
            parse_mode="Markdown",
        )

    except asyncio.CancelledError:
        # Cleanup already called by whoever cancelled the task
        raise
    except Exception as exc:
        logger.error({"event": "session_qr_error", "user_id": user_id, "error": type(exc).__name__})
        await _cleanup_user_session(user_id)
        await state.clear()
        await bot.send_message(
            chat_id,
            f"❌ Authentication error: `{type(exc).__name__}`",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@router.message(Command("string"))
async def cmd_string(message: Message, state: FSMContext, bot: Bot) -> None:
    """
    Initiate QR-based Telegram session generation.
    Usage: /string <api_id> <api_hash>
    """
    args = message.text.split()
    if len(args) < 3:
        await message.reply(
            "⚠️ **Usage:** `/string <api_id> <api_hash>`\n\n"
            "• Obtain credentials at https://my.telegram.org\n"
            "• A QR code will appear — scan it in **Telegram → Settings → Devices**\n"
            "• No OTP codes are transmitted through this chat",
            parse_mode="Markdown",
        )
        return

    try:
        api_id = int(args[1])
        api_hash = args[2].strip()
        if len(api_hash) != 32 or not all(c in "0123456789abcdef" for c in api_hash.lower()):
            raise ValueError("api_hash must be a 32-character hex string")
    except ValueError as exc:
        await message.reply(f"❌ Invalid credentials: {exc}")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Clean up any in-progress session for this user
    if user_id in ACTIVE_CLIENTS:
        await _cleanup_user_session(user_id)
    await state.clear()

    client = TelegramClient(StringSession(), api_id, api_hash)

    try:
        await client.connect()
        qr_login = await client.qr_login()

        qr_buf = generate_qr_buffer(qr_login.url)
        try:
            qr_file = BufferedInputFile(qr_buf.getvalue(), filename="login_qr.png")
        finally:
            qr_buf.close()

        ACTIVE_CLIENTS[user_id] = {
            "client": client,
            "qr_login": qr_login,
            "chat_id": chat_id,
            "created_at": time.monotonic(),
            "task": None,
        }

        await message.reply_photo(
            photo=qr_file,
            caption=(
                "📱 **Scan this QR code with Telegram**\n\n"
                "Go to: *Settings → Devices → Link Desktop Device*\n\n"
                f"⏱️ Expires in {SESSION_TIMEOUT_SECS} seconds."
            ),
            parse_mode="Markdown",
        )

        task = asyncio.create_task(
            _wait_for_qr(user_id, state, bot, chat_id),
            name=f"qr_session_{user_id}",
        )
        ACTIVE_CLIENTS[user_id]["task"] = task

    except FloodWaitError as exc:
        try:
            await client.disconnect()
        except Exception:
            pass
        ACTIVE_CLIENTS.pop(user_id, None)
        await message.reply(
            f"⏳ Too many login attempts. Please wait **{exc.seconds} seconds** and try again.",
            parse_mode="Markdown",
        )
    except Exception as exc:
        try:
            await client.disconnect()
        except Exception:
            pass
        ACTIVE_CLIENTS.pop(user_id, None)
        logger.error({"event": "session_connect_error", "error": type(exc).__name__})
        await message.reply(
            f"❌ Connection failed: `{type(exc).__name__}`\n"
            "Please verify your API credentials.",
            parse_mode="Markdown",
        )


@router.message(StringSessionState.waiting_for_2fa)
async def process_2fa(message: Message, state: FSMContext) -> None:
    """Handle 2FA password after QR scan confirms the account requires it."""
    user_id = message.from_user.id

    if user_id not in ACTIVE_CLIENTS:
        await state.clear()
        await message.reply("❌ Session expired. Please restart with `/string`.", parse_mode="Markdown")
        return

    password = message.text.strip()
    session_data = ACTIVE_CLIENTS[user_id]
    client: TelegramClient = session_data["client"]

    try:
        await client.sign_in(password=password)
        string_session: str = client.session.save()
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.info({"event": "session_generated_2fa", "user_id": user_id})
        await message.reply(
            "✅ **Session Generated Successfully!**\n\n"
            "⚠️ *Copy and delete this message immediately.*\n\n"
            f"`{string_session}`",
            parse_mode="Markdown",
        )
    except Exception as exc:
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.error({"event": "session_2fa_error", "user_id": user_id, "error": type(exc).__name__})
        await message.reply(
            f"❌ **2FA Error:** `{type(exc).__name__}`\n"
            "Incorrect password or unexpected error. Please try `/string` again.",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Lifecycle hook (called by bootstrap during shutdown)
# ---------------------------------------------------------------------------

async def shutdown_all_sessions() -> None:
    """Gracefully close all active Telethon sessions on bot shutdown."""
    user_ids = list(ACTIVE_CLIENTS.keys())
    logger.info({"event": "session_shutdown", "active_sessions": len(user_ids)})
    for user_id in user_ids:
        await _cleanup_user_session(user_id)
