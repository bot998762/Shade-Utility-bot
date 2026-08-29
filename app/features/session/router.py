"""
Session Feature — Telegram String Session Generator
====================================================
Uses the application's own API_ID / API_HASH (from environment).
Users never supply credentials — they only authenticate their Telegram account.

Login methods:
  1. QR Login (recommended) — out-of-band scan; completely avoids Telegram's
     "code previously shared by your account" security restriction.
  2. OTP Login — phone number + verification code.
     • If Telegram's SentCode indicates an alternative delivery method
       (next_type), a "Resend via SMS/Call" button is shown once.
     • The resend uses auth.ResendCode (a legitimate Telegram API call)
       to obtain a fresh code via a non-app channel.
     • If sign_in() is rejected ("previously shared"), the user is offered
       QR login as a fallback.

State machine:
  IDLE
  └─(/string)──► WAITING_METHOD
                 ├─(ses_method_qr / ses_start_qr)──► [bg tasks]──► AUTHENTICATED
                 │                                              └──► WAITING_2FA ──► AUTHENTICATED
                 ├─(ses_method_otp)──► WAITING_PHONE
                 │      └─(phone ok)──► WAITING_OTP [Resend button if next_type set]
                 │                   ├─► AUTHENTICATED
                 │                   └─► WAITING_2FA ──► AUTHENTICATED
                 └─(ses_cancel anywhere)──► IDLE
"""

import os
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
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    PhoneNumberInvalidError,
    AuthRestartError,
)

# ResendCodeRequest sends auth.resendCode(phone_number, phone_code_hash)
# and returns a new SentCode with a fresh phone_code_hash.
# Available in Telethon since 1.x (generated from TL schema).
try:
    from telethon.tl.functions.auth import ResendCodeRequest as _TLResendCodeRequest
except (ImportError, AttributeError):
    _TLResendCodeRequest = None  # guarded at call sites

from app.platform.capability import FeatureManifest
from app.utils.qr import generate_qr_buffer
from app.core.logger import setup_logger

manifest = FeatureManifest(
    name="session",
    description="Telegram String Session Generator via QR or OTP Login",
    version="4.0.0",
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
    waiting_for_method = State()   # /string entry: inline button selection
    waiting_for_phone  = State()   # OTP: user sends phone number
    waiting_for_otp    = State()   # OTP: user sends verification code
    waiting_for_2fa    = State()   # shared: user sends 2FA password


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_app_credentials() -> tuple[int, str]:
    """
    Read API_ID and API_HASH from the process environment.
    Raises ValueError with a descriptive message if either is missing.
    """
    api_id_str = os.environ.get("API_ID", "").strip()
    api_hash   = os.environ.get("API_HASH", "").strip()
    if not api_id_str:
        raise ValueError("API_ID is not set in the application environment")
    if not api_hash:
        raise ValueError("API_HASH is not set in the application environment")
    return int(api_id_str), api_hash


# ---------------------------------------------------------------------------
# Keyboard helpers (session-scoped only)
# ---------------------------------------------------------------------------

def _method_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 QR Login",  callback_data="ses_method_qr"),
            InlineKeyboardButton(text="🔢 OTP Login", callback_data="ses_method_otp"),
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


def _switch_to_qr_kb() -> InlineKeyboardMarkup:
    """Offered when a Telegram-app code delivery is detected."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Use QR Login", callback_data="ses_start_qr")],
        [InlineKeyboardButton(text="❌ Cancel",        callback_data="ses_cancel")],
    ])


def _describe_current_type(result) -> str:
    """
    Human-readable description of how Telegram delivered the login code.
    Uses the type-name of result.type so no brittle isinstance() import needed.
    """
    try:
        name = type(result.type).__name__
    except Exception:
        return "your phone"
    if "App"      in name:
        return "the Telegram app"
    if "Sms"      in name:
        return "SMS"
    if "Call"     in name or "Flash" in name or "Missed" in name:
        return "a phone call"
    if "Email"    in name:
        return "email"
    if "Fragment" in name:
        return "Fragment"
    return "your phone"


def _describe_next_type(next_type) -> str:
    """
    Human-readable label for the next available delivery method.
    next_type is a CodeType* instance from telethon.tl.types.auth.
    (CodeTypeSms, CodeTypeCall, CodeTypeFlashCall, CodeTypeMissedCall)
    """
    if next_type is None:
        return ""
    name = type(next_type).__name__
    if "Sms"   in name:
        return "SMS"
    if "Call"  in name or "Flash" in name or "Missed" in name:
        return "Phone Call"
    return "alternative method"


def _otp_input_kb(next_type=None) -> InlineKeyboardMarkup:
    """
    Keyboard shown on the OTP input prompt.
    Includes a 'Resend via …' button only when Telegram indicated a next_type
    in the SentCode response — i.e. an alternative delivery channel exists.
    """
    rows = []
    if next_type is not None:
        label = _describe_next_type(next_type)
        rows.append([InlineKeyboardButton(
            text=f"📲 Resend via {label}",
            callback_data="ses_otp_resend",
        )])
    rows.append([InlineKeyboardButton(text="❌ Cancel", callback_data="ses_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _qr_caption(remaining_secs: int) -> str:
    return (
        "📱 **Telegram QR Login**\n"
        "────────────────────\n"
        "Scan this QR using:\n\n"
        "*Telegram → Settings → Devices → Link Desktop Device*\n\n"
        f"⏳ Expires in: {remaining_secs}s"
    )


# ---------------------------------------------------------------------------
# Cleanup — cancels background tasks and disconnects Telethon client.
# CRITICAL: never cancel the currently-executing asyncio task from itself.
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
    Terminates cleanly on CancelledError (cleanup is always external).
    """
    current_msg_id = initial_msg_id
    try:
        while True:
            await asyncio.sleep(QR_COUNTDOWN_INTERVAL)

            session_data = ACTIVE_CLIENTS.get(user_id)
            if not session_data:
                return  # session cleaned up externally

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

                    caption = _qr_caption(new_remaining)
                    try:
                        await bot.edit_message_media(
                            chat_id=chat_id,
                            message_id=current_msg_id,
                            media=InputMediaPhoto(
                                media=BufferedInputFile(qr_bytes, filename="login_qr.png"),
                                caption=caption,
                                parse_mode="Markdown",
                            ),
                            reply_markup=_qr_kb(),
                        )
                        session_data["qr_msg_id"] = current_msg_id
                    except TelegramBadRequest:
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
                    # Recreate failed — give user the manual button
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
                # Normal tick — update remaining seconds
                try:
                    await bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=current_msg_id,
                        caption=_qr_caption(int(remaining)),
                        parse_mode="Markdown",
                        reply_markup=_qr_kb(),
                    )
                except TelegramBadRequest:
                    pass  # "message is not modified" — ignore
                except Exception:
                    pass

    except asyncio.CancelledError:
        raise  # propagate so cleanup can finish


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
    Countdown / refresh run concurrently in _qr_countdown.

    Success     → extract StringSession, deliver to user, clean up.
    2FA needed  → set FSM state, prompt for password, keep client alive.
    Error       → report, clean up.
    Cancelled   → propagate; cleanup is external.
    """
    session_data = ACTIVE_CLIENTS.get(user_id)
    if session_data is None:
        return

    qr_login = session_data["qr_login"]
    client: TelegramClient = session_data["client"]

    try:
        try:
            await qr_login.wait(timeout=None)  # countdown task handles timing
        except SessionPasswordNeededError:
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
        raise
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
    """Cancel the countdown task without awaiting (safe within the wait task)."""
    ct: asyncio.Task | None = session_data.get("countdown_task")
    if ct and not ct.done() and ct is not asyncio.current_task():
        ct.cancel()


# ---------------------------------------------------------------------------
# /string — entry point: show login method selection immediately
# ---------------------------------------------------------------------------

@router.message(Command("string"))
async def cmd_string(message: Message, state: FSMContext) -> None:
    """
    Validate application credentials first, then show the method-selection keyboard.

    Failing here — before any UI is shown — gives the user one clear error
    instead of a mid-flow failure after they have already chosen a method and
    entered their phone number.
    """
    user_id = message.from_user.id
    if user_id in ACTIVE_CLIENTS:
        await _cleanup_user_session(user_id)
    await state.clear()

    # ── Credential pre-flight ─────────────────────────────────────────────
    # Verify API_ID / API_HASH are configured BEFORE showing any UI.
    # One clear error here is far better than a mid-flow failure.
    try:
        _get_app_credentials()
    except ValueError as exc:
        await message.reply(
            "❌ **Bot configuration error**\n\n"
            f"`{exc}`\n\n"
            "The bot administrator must set `API_ID` and `API_HASH` in the "
            "application environment before `/string` can be used.",
            parse_mode="Markdown",
        )
        return
    # ─────────────────────────────────────────────────────────────────────

    await state.set_state(StringSessionState.waiting_for_method)
    await message.reply(
        "🔐 **Choose Login Method**\n"
        "────────────────────\n"
        "Select your authentication method:\n\n"
        "• **QR Login** — scan a QR code *(recommended)*\n"
        "• **OTP Login** — phone number + verification code",
        parse_mode="Markdown",
        reply_markup=_method_kb(),
    )


# ---------------------------------------------------------------------------
# Cancel — works from any state
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "ses_cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    if user_id in ACTIVE_CLIENTS:
        await _cleanup_user_session(user_id)
    await state.clear()
    try:
        if callback.message.photo:
            await callback.message.edit_caption("❌ Session generation cancelled.")
        else:
            await callback.message.edit_text("❌ Session generation cancelled.")
    except TelegramBadRequest:
        await callback.message.answer("❌ Session generation cancelled.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Method selection — QR (initial button)
# ---------------------------------------------------------------------------

@router.callback_query(StringSessionState.waiting_for_method, F.data == "ses_method_qr")
async def cb_method_qr(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    try:
        api_id, api_hash = _get_app_credentials()
    except ValueError as exc:
        await callback.message.edit_text(f"❌ Configuration error: {exc}")
        await state.clear()
        return

    await callback.message.edit_text("📱 Starting QR login…", reply_markup=None)
    await _start_qr_login(user_id, chat_id, api_id, api_hash, state, bot)


# ---------------------------------------------------------------------------
# Method selection — OTP (initial button)
# ---------------------------------------------------------------------------

@router.callback_query(StringSessionState.waiting_for_method, F.data == "ses_method_otp")
async def cb_method_otp(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "📞 **OTP Login**\n"
        "────────────────────\n"
        "Please send your **phone number** (international format, e.g. +1234567890):",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await state.set_state(StringSessionState.waiting_for_phone)


# ---------------------------------------------------------------------------
# Switch-to-QR button (shown after Telegram-app code-delivery is detected)
# No state filter — user's FSM state is already cleared at that point.
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "ses_start_qr")
async def cb_start_qr(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Start QR login from the 'Use QR Login' button after app-code detection."""
    await callback.answer()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if user_id in ACTIVE_CLIENTS:
        await _cleanup_user_session(user_id)

    try:
        api_id, api_hash = _get_app_credentials()
    except ValueError as exc:
        try:
            await callback.message.edit_text(f"❌ Configuration error: {exc}")
        except TelegramBadRequest:
            await callback.message.answer(f"❌ Configuration error: {exc}")
        await state.clear()
        return

    try:
        await callback.message.edit_text("📱 Starting QR login…", reply_markup=None)
    except TelegramBadRequest:
        await callback.message.answer("📱 Starting QR login…")

    await _start_qr_login(user_id, chat_id, api_id, api_hash, state, bot)


# ---------------------------------------------------------------------------
# QR login startup helper (shared by cb_method_qr and cb_start_qr)
# ---------------------------------------------------------------------------

async def _start_qr_login(
    user_id: int,
    chat_id: int,
    api_id: int,
    api_hash: str,
    state: FSMContext,
    bot: Bot,
) -> None:
    """Connect Telethon, generate first QR, launch countdown + wait tasks."""
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
            "Please check the application's API credentials.",
            parse_mode="Markdown",
        )
        await state.clear()
        return

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

    # QR phase is driven entirely by background tasks + inline buttons
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
# OTP flow — step 1: phone number
# ---------------------------------------------------------------------------

@router.message(StringSessionState.waiting_for_phone)
async def recv_phone(message: Message, state: FSMContext) -> None:
    """
    Receive phone number and request the Telegram login code.
    Always proceeds to the OTP-input state regardless of the delivery method
    reported by Telegram.  If Telegram later rejects the code at sign-in
    time (e.g. PHONE_CODE_EXPIRED / "previously shared by your account"),
    recv_otp() handles that error and offers the QR-login fallback.
    """
    phone = (message.text or "").strip()
    if not phone.startswith("+") or len(phone) < 7:
        await message.reply(
            "❌ Use international format, e.g. +1234567890:",
            reply_markup=_cancel_kb(),
        )
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    try:
        api_id, api_hash = _get_app_credentials()
    except ValueError as exc:
        await message.reply(f"❌ Configuration error: {exc}")
        await state.clear()
        return

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
    except PhoneNumberInvalidError:
        try:
            await client.disconnect()
        except Exception:
            pass
        await message.reply(
            "❌ That phone number is not valid. "
            "Please check the number and try again:",
            reply_markup=_cancel_kb(),
        )
        # Keep state — let user correct the number without restarting
        return
    except AuthRestartError:
        # Telegram signalled that the auth flow must restart from scratch.
        # Disconnect the temporary client and ask the user to run /string again.
        try:
            await client.disconnect()
        except Exception:
            pass
        logger.warning({"event": "otp_auth_restart_on_send", "user_id": user_id})
        await message.reply(
            "⚠️ Telegram interrupted the login flow and requires a fresh start.\n\n"
            "Please run `/string` again to begin a new login attempt.",
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
            "Please verify the phone number or use QR login.",
            parse_mode="Markdown",
        )
        await state.clear()
        return

    # ── Inspect delivery type and optional next_type ──────────────────────
    # SentCode.next_type (CodeType* instance or None) indicates whether
    # Telegram can resend via an alternative channel (SMS, Call, …).
    # We expose this as a one-shot Resend button — no automatic resends.
    delivery  = _describe_current_type(result)
    next_type = getattr(result, "next_type", None)

    # ── Defensive: discard any stale OTP session for this user ────────────
    # Normally absent at this point (cmd_string clears on /string), but if
    # recv_phone is somehow reached while a session already exists (e.g.
    # on a retry after PhoneNumberInvalidError kept state alive), clean up
    # the old Telethon client before storing the new one to prevent leaks.
    if user_id in ACTIVE_CLIENTS:
        await _cleanup_user_session(user_id)
    # ─────────────────────────────────────────────────────────────────────

    # ── Build OTP prompt and keyboard based on delivery type ─────────────
    # Three cases:
    #   A. Telegram reports an alternative delivery (next_type not None):
    #      → show "Resend via SMS/Call" button; user can switch delivery
    #   B. Code delivered via the Telegram app (SentCodeTypeApp), no fallback:
    #      → warn prominently and offer QR Login NOW, before the user
    #        enters a code that Telegram will very likely reject as
    #        "previously shared by your account".  User can still type the
    #        code — recv_otp handles it — but QR is the right path.
    #   C. Other delivery (SMS, call, fragment …):
    #      → plain prompt; code should work normally
    if next_type is not None:
        next_label = _describe_next_type(next_type)
        prompt = (
            f"📨 Telegram sent the login code via **{delivery}**.\n\n"
            f"If you cannot use that code here, tap "
            f"**Resend via {next_label}** to receive a fresh code "
            f"via {next_label} instead.\n\n"
            "Please send the **verification code**:"
        )
        keyboard = _otp_input_kb(next_type)

    elif delivery == "the Telegram app":
        # SentCodeTypeApp with no SMS/Call fallback.
        # Root cause of "previously shared by your account":
        #   Telegram delivered the code through the user's own Telegram app
        #   session, and its security layer refuses to let a NEW Telethon
        #   client authenticate with a code that travelled through Telegram.
        #   This is a Telegram server-side policy and cannot be bypassed.
        #   Offering QR Login immediately prevents wasted attempts.
        prompt = (
            "📨 Telegram sent the login code via **the Telegram app**.\n\n"
            "⚠️ **Important:** Telegram usually rejects codes delivered this "
            "way when re-entered through another session "
            "(*previously shared by your account*).\n\n"
            "👉 **Use QR Login** — it is the reliable option for your account.\n\n"
            "You may still type the code below if you want to try, but if "
            "Telegram rejects it, the QR option will reappear."
        )
        keyboard = _switch_to_qr_kb()   # "📱 Use QR Login" + "❌ Cancel"
        # User can still type their OTP — recv_otp handles any text message
        # in waiting_for_otp state regardless of which keyboard is shown.

    else:
        prompt = (
            f"📨 A verification code has been sent via {delivery}.\n\n"
            "Please send the **verification code**:"
        )
        keyboard = _otp_input_kb(None)
    # ─────────────────────────────────────────────────────────────────────

    logger.info({
        "event":        "otp_code_requested",
        "user_id":      user_id,
        "delivery":     delivery,
        "hash_len":     len(result.phone_code_hash),
        "has_next_type": next_type is not None,
        "client_id":    id(client),
    })

    ACTIVE_CLIENTS[user_id] = {
        "client":          client,
        "chat_id":         chat_id,
        "method":          "otp",
        "phone":           phone,
        "phone_code_hash": result.phone_code_hash,
        "delivery":        delivery,    # human-readable delivery channel name
        "next_type":       next_type,   # CodeType* or None
        "resent":          False,       # True after one ResendCode call
        "created_at":      time.monotonic(),
        "task":            None,
        "countdown_task":  None,
    }

    await state.set_state(StringSessionState.waiting_for_otp)
    await message.reply(prompt, parse_mode="Markdown", reply_markup=keyboard)


# ---------------------------------------------------------------------------
# OTP resend — one-shot, only when Telegram reported a next_type
# ---------------------------------------------------------------------------

@router.callback_query(StringSessionState.waiting_for_otp, F.data == "ses_otp_resend")
async def cb_otp_resend(callback: CallbackQuery) -> None:
    """
    Resend the Telegram login code via the next available delivery method
    (e.g. SMS after an app-delivered code).

    Rules:
    • Only one resend per OTP session (avoids duplicate codes / FloodWait).
    • Uses auth.ResendCode (Telegram's official resend API, Telethon 1.x).
    • Updates phone_code_hash in session — old hash is invalidated by Telegram.
    • Removes the Resend button after use.
    """
    await callback.answer()
    user_id = callback.from_user.id

    session_data = ACTIVE_CLIENTS.get(user_id)
    if not session_data:
        try:
            await callback.message.edit_text(
                "❌ Session expired. Please run `/string` again.",
                parse_mode="Markdown",
            )
        except TelegramBadRequest:
            pass
        return

    # Guard: only one resend allowed per session
    if session_data.get("resent"):
        await callback.answer(
            "Code already resent. Please enter the code you received.",
            show_alert=True,
        )
        return

    next_type = session_data.get("next_type")
    if next_type is None:
        await callback.answer(
            "No alternative delivery method is available.",
            show_alert=True,
        )
        return

    # Guard: ResendCodeRequest unavailable (shouldn't happen with Telethon 1.x)
    if _TLResendCodeRequest is None:
        await callback.answer(
            "Resend is not supported by the installed Telethon version.",
            show_alert=True,
        )
        return

    client: TelegramClient = session_data["client"]
    phone:           str   = session_data["phone"]
    phone_code_hash: str   = session_data["phone_code_hash"]

    try:
        new_sent = await client(_TLResendCodeRequest(
            phone_number=phone,
            phone_code_hash=phone_code_hash,
        ))
        # Update session — old hash is now invalid
        session_data["phone_code_hash"] = new_sent.phone_code_hash
        session_data["next_type"]       = getattr(new_sent, "next_type", None)
        session_data["resent"]          = True   # block further resends

        method_label = _describe_next_type(next_type)
        logger.info({"event": "otp_resent", "user_id": user_id, "via": method_label})

        try:
            await callback.message.edit_text(
                f"📲 **Code resent via {method_label}.**\n\n"
                "Please send the **verification code** you just received:",
                parse_mode="Markdown",
                reply_markup=_cancel_kb(),   # Resend button removed
            )
        except TelegramBadRequest:
            pass

    except FloodWaitError as exc:
        await callback.answer(
            f"⏳ Please wait {exc.seconds}s before resending.",
            show_alert=True,
        )
    except Exception as exc:
        logger.warning({
            "event": "otp_resend_error",
            "user_id": user_id,
            "error": type(exc).__name__,
        })
        await callback.answer(
            "❌ Could not resend code. Please enter the code you received.",
            show_alert=True,
        )


# ---------------------------------------------------------------------------
# OTP flow — step 2: verification code
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
    phone:           str   = session_data["phone"]
    phone_code_hash: str   = session_data["phone_code_hash"]

    # ── Connectivity guard ────────────────────────────────────────────────
    # Verify the Telethon client is still connected before calling sign_in.
    # A disconnected client would raise a connection error rather than an
    # auth error, which would be confusing to the user.
    if not client.is_connected():
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.warning({"event": "otp_client_disconnected", "user_id": user_id})
        await message.reply(
            "❌ The connection was lost. Please run `/string` again.",
            parse_mode="Markdown",
        )
        return
    # ─────────────────────────────────────────────────────────────────────

    logger.info({
        "event":        "otp_sign_in_attempt",
        "user_id":      user_id,
        "delivery":     session_data.get("delivery", "unknown"),
        "hash_len":     len(phone_code_hash),
        "client_id":    id(client),
        "resent":       session_data.get("resent", False),
    })

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

    except PhoneCodeExpiredError as exc:
        # SCENARIO E — Telegram server-side security restriction.
        # PhoneCodeExpiredError covers two distinct cases:
        #   1. Code genuinely expired (user waited too long).
        #   2. Code delivered via Telegram app; Telegram refuses re-entry
        #      through another session ("previously shared by your account").
        # Both are indistinguishable at the exception level and both require
        # the same action: use QR login.  DO NOT attempt to bypass this.
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.warning({
            "event":     "otp_code_rejected",
            "user_id":   user_id,
            "exception": type(exc).__name__,
            "client_id": id(client),
        })
        await message.reply(
            "⏱️ **Telegram rejected this verification code.**\n\n"
            "This happens when:\n"
            "• The code was delivered via the Telegram app and Telegram "
            "blocks re-entry here (*previously shared by your account*)\n"
            "• The code genuinely expired before you entered it\n\n"
            "👉 Please use **QR Login** for reliable authentication:",
            parse_mode="Markdown",
            reply_markup=_switch_to_qr_kb(),
        )
        return

    except FloodWaitError as exc:
        await _cleanup_user_session(user_id)
        await state.clear()
        await message.reply(
            f"⏳ Too many attempts. Please wait **{exc.seconds}s** before trying again.",
            parse_mode="Markdown",
        )
        return

    except AuthRestartError:
        # Telegram requires the auth flow to be restarted completely.
        # The current phone_code_hash and client state are no longer valid.
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.warning({
            "event":     "otp_auth_restart_on_sign_in",
            "user_id":   user_id,
            "client_id": id(client),
        })
        await message.reply(
            "⚠️ The Telegram login session was interrupted and must restart.\n\n"
            "Please run `/string` to begin a fresh login attempt.",
            parse_mode="Markdown",
        )
        return
    except Exception as exc:
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.error({
            "event":     "otp_signin_error",
            "user_id":   user_id,
            "exception": type(exc).__name__,
            "client_id": id(client),
        })
        await message.reply(
            "❌ Login failed due to an unexpected error.\n"
            "Please use **QR Login** for a more reliable authentication method.",
            parse_mode="Markdown",
        )
        return

    # Success ✓
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
    except AuthRestartError:
        # Telegram invalidated the auth session during 2FA.
        # The client must be discarded and the user must start over.
        await _cleanup_user_session(user_id)
        await state.clear()
        logger.warning({"event": "otp_2fa_auth_restart", "user_id": user_id})
        await message.reply(
            "⚠️ The Telegram session was interrupted during 2FA.\n\n"
            "Please run `/string` to start a fresh login attempt.",
            parse_mode="Markdown",
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
            "❌ 2FA failed due to an unexpected error. Please try `/string` again.",
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
