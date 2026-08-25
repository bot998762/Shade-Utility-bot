"""
Session Feature — Telegram String Session Generator
====================================================
Supports two login methods selectable after API credentials are entered:

  1. QR Login (recommended) — out-of-band scan; avoids Telegram's
     "code previously shared by your account" security block entirely.
  2. OTP Login — phone number + verification code received via SMS or
     push notification on a DIFFERENT device.  Works when the user
     receives the code via SMS; may fail if Telegram routes the code
     through the same Telegram session (security block).  QR is the
     safer default.

State machine:
  IDLE
  └─(cmd_string)──► WAITING_API_ID
                    └─(api_id ok)──► WAITING_API_HASH
                                     └─(api_hash ok)──► WAITING_METHOD
                                                        ├─(QR button)──► [bg tasks] ──► AUTHENTICATED
                                                        │                            └─► WAITING_FOR_2FA ──► AUTHENTICATED
                                                        └─(OTP button)──► WAITING_PHONE ──► WAITING_OTP
                                                                                            ├─► AUTHENTICATED
                                                                                            └─► WAITING_FOR_2FA ──► AUTHENTICATED
  Any state ──(Cancel button)──► IDLE
"""

import io
import time
import asyncio
from datetime import datetime, timezone
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    PhoneCodeInvalidError,
    PasswordHashInvalidError,
)

from app.platform.capability import FeatureManifest
from app.utils.qr import generate_qr_buffer
from app.core.logger import setup_logger

manifest = FeatureManifest(
    name="session",
    description="Telegram String Session Generator via QR or OTP Login",
    version="3.0.0",
    category="Auth",
)

router = Router()
logger = setup_logger()

SESSION_TIMEOUT_SECS = 120   # displayed initial QR lifetime
QR_COUNTDOWN_INTERVAL = 5    # seconds between caption edits (flood-safe)

# Per-user runtime state:
# { user_id: { client, qr_login, task, countdown_task, chat_id, method,
#              phone, phone_code_hash, qr_msg_id, created_at } }
ACTIVE_CLIENTS: dict[int, dict] = {}


# ---------------------------------------------------------------------------
# FSM states
# ---------------------------------------------------------------------------

class StringSessionState(StatesGroup):
    waiting_for_api_id   = State()   # step 1: user sends API ID
    waiting_for_api_hash = State()   # step 2: user sends API HASH
    waiting_for_method   = State()   # step 3: inline button (QR / OTP)
    waiting_for_phone    = State()   # OTP: user sends phone number
    waiting_for_otp      = State()   # OTP: user sends verification code
    waiting_for_2fa      = State()   # shared: user sends 2FA password


# ---------------------------------------------------------------------------
# Session-scoped keyboard helpers
# ---------------------------------------------------------------------------

def _method_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔢 OTP Login", callback_data="ses_method_otp"),
            InlineKeyboardButton(text="📱 QR Login",  callback_data="ses_method_qr"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="ses_cancel")],
    ])


def _qr_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh QR", callback_data="ses_qr_refresh")],
        [InlineKeyboardButton(text="❌ Cancel",      callback_data="ses_cancel")],
    ])


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="ses_cancel")],
    ])


def _qr_caption(remaining_secs: int) -> str:
    return (
        "📱 **Telegram QR Login**\n"
        "────────────────────\n"
        "Scan this QR using:\n\n"
        "*Telegram → Settings → Devices → Link Desktop Device*\n\n"
        f"⏳ Expires in: {remaining_secs}s"
    )


# ---------------------------------------------------------------------------
# Cleanup — cancels all background tasks and disconnects Telethon client.
# CRITICAL: never cancel the currently-executing task from within itself.
# ---------------------------------------------------------------------------

async def _cleanup_user_session(user_id: int) -> None:
    """Cancel background tasks and disconnect Telethon client for *user_id*."""
    session_data = ACTIVE_CLIENTS.pop(user_id, None)
    if session_data is None:
        return

    current = asyncio.current_task()

    for task_key in ("task", "countdown_task"):
        task: asyncio.Task | None = session_data.get(task_key)
        if task and not task.done() and task is not current:
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


# ---------------------------------------------------------------------------
# QR countdown + auto-refresh background task
# ---------------------------------------------------------------------------

async def _qr_countdown(
    user_id: int,
    bot: Bot,
    chat_id: int,
    initial_msg_id: int,
    state: FSMContext,
) -> None:
    """
    Edits the QR photo caption every QR_COUNTDOWN_INTERVAL seconds with an
    accurate remaining-time display.  When the QR token is about to expire,
    calls qr_login.recreate() to obtain a fresh token and replaces the image.
    Falls back to a manual 🔄 Refresh QR button if recreate() fails.
    Terminates cleanly on CancelledError (cleanup called externally).
    """
    current_msg_id = initial_msg_id
    try:
        while True:
            await asyncio.sleep(QR_COUNTDOWN_INTERVAL)

            session_data = ACTIVE_CLIENTS.get(user_id)
            if not session_data:
                return  # session was cleaned up

            qr_login = session_data.get("qr_login")
            if qr_login is None:
                return

            now = datetime.now(timezone.utc)
            try:
                remaining = max(0.0, (qr_login.expires - now).total_seconds())
            except Exception:
                remaining = 0.0

            if remaining <= QR_COUNTDOWN_INTERVAL:
                # Token about to expire — try automatic recreate
                try:
                    await qr_login.recreate()
                    session_data["qr_login"] = qr_login

                    now2 = datetime.now(timezone.utc)
                    try:
                        new_remaining = max(0, int((qr_login.expires - now2).total_seconds()))
                    except Exception:
                        new_remaining = SESSION_TIMEOUT_SECS

                    qr_buf = generate_qr_buffer(qr_login.url)
                    try:
                        qr_bytes = qr_buf.getvalue()
                    finally:
                        qr_buf.close()

                    new_file = BufferedInputFile(qr_bytes, filename="login_qr.png")
                    caption   = _qr_caption(new_remaining)

                    try:
                        await bot.edit_message_media(
                            chat_id=chat_id,
                            message_id=current_msg_id,
                            media=InputMediaPhoto(
                                media=new_file,
                                caption=caption,
                                parse_mode="Markdown",
                            ),
                            reply_markup=_qr_kb(),
                        )
                        session_data["qr_msg_id"] = current_msg_id
                    except TelegramBadRequest:
                        # Cannot edit — send fresh photo
                        new_msg = await bot.send_photo(
                            chat_id=chat_id,
                            photo=BufferedInputFile(qr_bytes, filename="login_qr.png"),
                            caption=caption,
                            parse_mode="Markdown",
                            reply_markup=_qr_kb(),
                        )
                        current_msg_id = new_msg.message_id
                        session_data["qr_msg_id"] = current_msg_id

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning({
                        "event": "qr_recreate_failed",
                        "user_id": user_id,
                        "error": type(exc).__name__,
                    })
                    # Recreate failed — show manual refresh button
                    try:
                        await bot.edit_message_caption(
                            chat_id=chat_id,
                            message_id=current_msg_id,
                            caption=(
                                "⚠️ **QR code expired.**\n\n"
                                "Press **🔄 Refresh QR** to generate a new one."
                            ),
                            parse_mode="Markdown",
                            reply_markup=_qr_kb(),
                        )
                    except Exception:
                        pass
                    return  # countdown ends; user presses Refresh or Cancel

            else:
                # Normal countdown tick — just update caption
                try:
                    await bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=current_msg_id,
                        caption=_qr_caption(int(remaining)),
                        parse_mode="Markdown",
                        reply_markup=_qr_kb(),
                    )
                except TelegramBadRequest:
                    pass  # "message is not modified" or already deleted
                except Exception:
                    pass

    except asyncio.CancelledError:
        raise  # propagate cleanly so cleanup can finish


# ---------------------------------------------------------------------------
# QR authorization wait background task
# ---------------------------------------------------------------------------

async def _wait_for_qr(
    user_id: int,
    state: FSMContext,
    bot: Bot,
    chat_id: int,
) -> None:
    """
    Waits indefinitely for the QR to be scanned.
    Countdown and QR refresh are handled concurrently by _qr_countdown.

    Success path  → extract StringSession, send to user, clean up.
    2FA path      → set FSM state, prompt for password, keep client alive.
    Error/cancel  → report to user, clean up.
    """
    session_data = ACTIVE_CLIENTS.get(user_id)
    if session_data is None:
        return

    qr_login = session_data["qr_login"]
    client: TelegramClient = session_data["client"]

    try:
        try:
            await qr_login.wait(timeout=None)  # countdown task handles expiry/refresh
        except SessionPasswordNeededError:
            # QR was scanned, but account has 2FA
            _stop_countdown(user_id, session_data)
            await state.set_state(StringSessionState.waiting_for_2fa)
            session_data["method"] = "qr"
            await bot.send_message(
                chat_id,
                "🔐 **Two-Step Verification required.**\n\n"
                "Please send your 2FA password:",
                parse_mode="Markdown",
                reply_markup=_cancel_kb(),
            )
            return

        # Authorized ✓
        string_session: str = client.session.save()
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.info({"event": "session_generated", "user_id": user_id, "method": "qr"})
        await bot.send_message(
            chat_id,
            "✅ **Authentication successful!**\n\n"
            "Your String Session:\n\n"
            f"`{string_session}`\n\n"
            "⚠️ Keep this session string private.",
            parse_mode="Markdown",
        )

    except asyncio.CancelledError:
        raise  # cleanup handles the rest
    except Exception as exc:
        logger.error({
            "event": "session_qr_error",
            "user_id": user_id,
            "error": type(exc).__name__,
        })
        await _cleanup_user_session(user_id)
        await state.clear()
        await bot.send_message(
            chat_id,
            f"❌ Authentication error: `{type(exc).__name__}`",
            parse_mode="Markdown",
        )


def _stop_countdown(user_id: int, session_data: dict) -> None:
    """Cancel countdown task without waiting (called from within wait task)."""
    ct: asyncio.Task | None = session_data.get("countdown_task")
    if ct and not ct.done() and ct is not asyncio.current_task():
        ct.cancel()


# ---------------------------------------------------------------------------
# /string — entry point (starts conversation)
# ---------------------------------------------------------------------------

@router.message(Command("string"))
async def cmd_string(message: Message, state: FSMContext) -> None:
    """Begin /string flow: clean up any prior attempt, ask for API ID."""
    user_id = message.from_user.id

    if user_id in ACTIVE_CLIENTS:
        await _cleanup_user_session(user_id)
    await state.clear()

    await state.set_state(StringSessionState.waiting_for_api_id)
    await message.reply(
        "🔑 **String Session Generator**\n"
        "────────────────────\n"
        "Obtain credentials at https://my.telegram.org\n\n"
        "Please send your **API ID** (numbers only):",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )


# ---------------------------------------------------------------------------
# Cancel (any state)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "ses_cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    if user_id in ACTIVE_CLIENTS:
        await _cleanup_user_session(user_id)
    await state.clear()
    try:
        # Photo messages use edit_caption; text messages use edit_text
        if callback.message.photo:
            await callback.message.edit_caption("❌ Session generation cancelled.")
        else:
            await callback.message.edit_text("❌ Session generation cancelled.")
    except TelegramBadRequest:
        await callback.message.answer("❌ Session generation cancelled.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Conversation step 1 — API ID
# ---------------------------------------------------------------------------

@router.message(StringSessionState.waiting_for_api_id)
async def recv_api_id(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        api_id = int(text)
        if api_id <= 0:
            raise ValueError("must be positive")
    except ValueError:
        await message.reply(
            "❌ API ID must be a positive integer. Please try again:",
            reply_markup=_cancel_kb(),
        )
        return

    await state.update_data(api_id=api_id)
    await state.set_state(StringSessionState.waiting_for_api_hash)
    await message.reply(
        "Now send your **API HASH** (32-character hex string):",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )


# ---------------------------------------------------------------------------
# Conversation step 2 — API HASH
# ---------------------------------------------------------------------------

@router.message(StringSessionState.waiting_for_api_hash)
async def recv_api_hash(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) != 32 or not all(c in "0123456789abcdef" for c in text.lower()):
        await message.reply(
            "❌ API HASH must be a 32-character hex string. Please try again:",
            reply_markup=_cancel_kb(),
        )
        return

    await state.update_data(api_hash=text)
    await state.set_state(StringSessionState.waiting_for_method)
    await message.reply(
        "🔐 **Choose Login Method**\n"
        "────────────────────\n"
        "Select your authentication method:\n\n"
        "• **QR Login** — scan a QR code *(recommended, most reliable)*\n"
        "• **OTP Login** — phone number + verification code\n"
        "  ⚠️ OTP works only when the code arrives via SMS, not Telegram",
        parse_mode="Markdown",
        reply_markup=_method_kb(),
    )


# ---------------------------------------------------------------------------
# Method selection — QR
# ---------------------------------------------------------------------------

@router.callback_query(StringSessionState.waiting_for_method, F.data == "ses_method_qr")
async def cb_method_qr(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback.answer()
    await callback.message.edit_text("📱 Starting QR login…", reply_markup=None)

    user_id  = callback.from_user.id
    chat_id  = callback.message.chat.id
    data     = await state.get_data()
    api_id   = data["api_id"]
    api_hash = data["api_hash"]

    await _start_qr_login(user_id, chat_id, api_id, api_hash, state, bot)


# ---------------------------------------------------------------------------
# Method selection — OTP
# ---------------------------------------------------------------------------

@router.callback_query(StringSessionState.waiting_for_method, F.data == "ses_method_otp")
async def cb_method_otp(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "📞 **OTP Login**\n"
        "────────────────────\n"
        "⚠️ *OTP login works reliably only when Telegram sends the code via SMS.*\n"
        "If you receive the code inside the Telegram app on your phone,\n"
        "login may fail with a Telegram security error — use QR login instead.\n\n"
        "Please send your **phone number** (international format, e.g. +1234567890):",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await state.set_state(StringSessionState.waiting_for_phone)


# ---------------------------------------------------------------------------
# QR login startup helper
# ---------------------------------------------------------------------------

async def _start_qr_login(
    user_id: int,
    chat_id: int,
    api_id: int,
    api_hash: str,
    state: FSMContext,
    bot: Bot,
) -> None:
    """Connect Telethon client, generate first QR, launch countdown + wait tasks."""
    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.connect()
        qr_login = await client.qr_login()
    except FloodWaitError as exc:
        try:
            await client.disconnect()
        except Exception:
            pass
        await bot.send_message(
            chat_id,
            f"⏳ Too many login attempts. Please wait **{exc.seconds}s** and try again.",
            parse_mode="Markdown",
        )
        await state.clear()
        return
    except Exception as exc:
        try:
            await client.disconnect()
        except Exception:
            pass
        logger.error({"event": "session_connect_error", "error": type(exc).__name__})
        await bot.send_message(
            chat_id,
            f"❌ Connection failed: `{type(exc).__name__}`\n"
            "Please verify your API credentials.",
            parse_mode="Markdown",
        )
        await state.clear()
        return

    # Compute real initial countdown from the token's expiry
    now = datetime.now(timezone.utc)
    try:
        remaining = max(0, int((qr_login.expires - now).total_seconds()))
    except Exception:
        remaining = SESSION_TIMEOUT_SECS

    qr_buf = generate_qr_buffer(qr_login.url)
    try:
        qr_bytes = qr_buf.getvalue()
    finally:
        qr_buf.close()

    qr_msg = await bot.send_photo(
        chat_id=chat_id,
        photo=BufferedInputFile(qr_bytes, filename="login_qr.png"),
        caption=_qr_caption(remaining),
        parse_mode="Markdown",
        reply_markup=_qr_kb(),
    )

    ACTIVE_CLIENTS[user_id] = {
        "client":         client,
        "qr_login":       qr_login,
        "qr_msg_id":      qr_msg.message_id,
        "chat_id":        chat_id,
        "method":         "qr",
        "created_at":     time.monotonic(),
        "task":           None,
        "countdown_task": None,
    }

    countdown_task = asyncio.create_task(
        _qr_countdown(user_id, bot, chat_id, qr_msg.message_id, state),
        name=f"qr_countdown_{user_id}",
    )
    wait_task = asyncio.create_task(
        _wait_for_qr(user_id, state, bot, chat_id),
        name=f"qr_session_{user_id}",
    )
    ACTIVE_CLIENTS[user_id]["task"]           = wait_task
    ACTIVE_CLIENTS[user_id]["countdown_task"] = countdown_task

    # FSM state cleared: QR phase is driven by background tasks + inline buttons
    await state.clear()


# ---------------------------------------------------------------------------
# Manual QR refresh button
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "ses_qr_refresh")
async def cb_qr_refresh(callback: CallbackQuery, bot: Bot) -> None:
    """Generate a genuinely new valid QR for the user on demand."""
    await callback.answer("Generating new QR code…")
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    session_data = ACTIVE_CLIENTS.get(user_id)
    if not session_data:
        try:
            await callback.message.edit_caption(
                "❌ Session expired. Please run `/string` again.",
                parse_mode="Markdown",
            )
        except TelegramBadRequest:
            await callback.message.answer(
                "❌ Session expired. Please run `/string` again.",
                parse_mode="Markdown",
            )
        return

    qr_login = session_data.get("qr_login")
    if not qr_login:
        await callback.message.answer(
            "❌ Session state lost. Please run `/string` again.",
            parse_mode="Markdown",
        )
        return

    try:
        await qr_login.recreate()
        session_data["qr_login"] = qr_login

        now = datetime.now(timezone.utc)
        try:
            remaining = max(0, int((qr_login.expires - now).total_seconds()))
        except Exception:
            remaining = SESSION_TIMEOUT_SECS

        qr_buf = generate_qr_buffer(qr_login.url)
        try:
            qr_bytes = qr_buf.getvalue()
        finally:
            qr_buf.close()

        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(
                    media=BufferedInputFile(qr_bytes, filename="login_qr.png"),
                    caption=_qr_caption(remaining),
                    parse_mode="Markdown",
                ),
                reply_markup=_qr_kb(),
            )
            session_data["qr_msg_id"] = callback.message.message_id
        except TelegramBadRequest:
            new_msg = await bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(qr_bytes, filename="login_qr.png"),
                caption=_qr_caption(remaining),
                parse_mode="Markdown",
                reply_markup=_qr_kb(),
            )
            session_data["qr_msg_id"] = new_msg.message_id

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning({
            "event": "qr_refresh_failed",
            "user_id": user_id,
            "error": type(exc).__name__,
        })
        await callback.answer("❌ Failed to refresh QR. Try `/string` again.")


# ---------------------------------------------------------------------------
# OTP flow — phone number
# ---------------------------------------------------------------------------

@router.message(StringSessionState.waiting_for_phone)
async def recv_phone(message: Message, state: FSMContext) -> None:
    phone = (message.text or "").strip()
    if not phone.startswith("+") or len(phone) < 7:
        await message.reply(
            "❌ Use international format, e.g. +1234567890:",
            reply_markup=_cancel_kb(),
        )
        return

    data     = await state.get_data()
    api_id   = data["api_id"]
    api_hash = data["api_hash"]
    user_id  = message.from_user.id
    chat_id  = message.chat.id

    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.connect()
        result = await client.send_code_request(phone)
    except FloodWaitError as exc:
        try:
            await client.disconnect()
        except Exception:
            pass
        await message.reply(
            f"⏳ Too many requests. Please wait **{exc.seconds}s** and try again.",
            parse_mode="Markdown",
        )
        await state.clear()
        return
    except Exception as exc:
        try:
            await client.disconnect()
        except Exception:
            pass
        logger.error({"event": "otp_send_error", "error": type(exc).__name__})
        await message.reply(
            f"❌ Failed to send code: `{type(exc).__name__}`\n"
            "Verify your credentials or use QR login.",
            parse_mode="Markdown",
        )
        await state.clear()
        return

    ACTIVE_CLIENTS[user_id] = {
        "client":          client,
        "chat_id":         chat_id,
        "method":          "otp",
        "phone":           phone,
        "phone_code_hash": result.phone_code_hash,
        "created_at":      time.monotonic(),
        "task":            None,
        "countdown_task":  None,
    }

    await state.update_data(phone=phone, phone_code_hash=result.phone_code_hash)
    await state.set_state(StringSessionState.waiting_for_otp)
    await message.reply(
        "📨 A verification code has been sent.\n\n"
        "⚠️ *If the code arrives via Telegram (not SMS), the login may be blocked.*\n"
        "Cancel and use QR login in that case.\n\n"
        "Please send the **verification code**:",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )


# ---------------------------------------------------------------------------
# OTP flow — verification code
# ---------------------------------------------------------------------------

@router.message(StringSessionState.waiting_for_otp)
async def recv_otp(message: Message, state: FSMContext) -> None:
    code    = (message.text or "").strip()
    user_id = message.from_user.id

    session_data = ACTIVE_CLIENTS.get(user_id)
    if not session_data:
        await state.clear()
        await message.reply(
            "❌ Session expired. Please run `/string` again.",
            parse_mode="Markdown",
        )
        return

    client: TelegramClient = session_data["client"]
    phone:            str  = session_data["phone"]
    phone_code_hash:  str  = session_data["phone_code_hash"]

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
    except SessionPasswordNeededError:
        await state.set_state(StringSessionState.waiting_for_2fa)
        session_data["method"] = "otp"
        await message.reply(
            "🔐 **Two-Step Verification required.**\n\n"
            "Please send your 2FA password:",
            parse_mode="Markdown",
            reply_markup=_cancel_kb(),
        )
        return
    except PhoneCodeInvalidError:
        await message.reply(
            "❌ Incorrect verification code. Please try again:",
            reply_markup=_cancel_kb(),
        )
        return
    except Exception as exc:
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.error({
            "event": "otp_signin_error",
            "user_id": user_id,
            "error": type(exc).__name__,
        })
        await message.reply(
            f"❌ Login failed: `{type(exc).__name__}`\n"
            "If Telegram blocked the code, please use QR login instead.",
            parse_mode="Markdown",
        )
        return

    string_session: str = client.session.save()
    await _cleanup_user_session(user_id)
    await state.clear()
    logger.info({"event": "session_generated", "user_id": user_id, "method": "otp"})
    await message.reply(
        "✅ **Authentication successful!**\n\n"
        "Your String Session:\n\n"
        f"`{string_session}`\n\n"
        "⚠️ Keep this session string private.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# 2FA — shared by QR and OTP paths
# ---------------------------------------------------------------------------

@router.message(StringSessionState.waiting_for_2fa)
async def process_2fa(message: Message, state: FSMContext) -> None:
    """Handle 2FA password after QR scan or OTP code triggers the 2FA prompt."""
    user_id = message.from_user.id

    if user_id not in ACTIVE_CLIENTS:
        await state.clear()
        await message.reply(
            "❌ Session expired. Please restart with `/string`.",
            parse_mode="Markdown",
        )
        return

    password     = (message.text or "").strip()
    session_data = ACTIVE_CLIENTS[user_id]
    client: TelegramClient = session_data["client"]

    try:
        await client.sign_in(password=password)
        string_session: str = client.session.save()
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.info({"event": "session_generated_2fa", "user_id": user_id})
        await message.reply(
            "✅ **Authentication successful!**\n\n"
            "Your String Session:\n\n"
            f"`{string_session}`\n\n"
            "⚠️ Keep this session string private.",
            parse_mode="Markdown",
        )
    except PasswordHashInvalidError:
        await message.reply(
            "❌ Incorrect 2FA password. Please try again:",
            reply_markup=_cancel_kb(),
        )
    except Exception as exc:
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.error({
            "event": "session_2fa_error",
            "user_id": user_id,
            "error": type(exc).__name__,
        })
        await message.reply(
            f"❌ **2FA Error:** `{type(exc).__name__}`\n"
            "Please try `/string` again.",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Lifecycle hook — called by bootstrap on bot shutdown
# ---------------------------------------------------------------------------

async def shutdown_all_sessions() -> None:
    """Gracefully close all active Telethon sessions on bot shutdown."""
    user_ids = list(ACTIVE_CLIENTS.keys())
    logger.info({"event": "session_shutdown", "active_sessions": len(user_ids)})
    for user_id in user_ids:
        await _cleanup_user_session(user_id)
