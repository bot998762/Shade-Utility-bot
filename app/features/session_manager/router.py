"""
Session Manager Feature
=======================
Two commands entirely separate from /string (which is FROZEN).

/create_session
    Authenticate a Telegram account via QR or OTP and export the
    authorised state as a Telethon SQLite .session file.

/login_session
    Upload an existing .session file, validate it is authorised, and
    display safe account information.

Implementation notes:
• Uses its own CS_ACTIVE dict — does NOT share ACTIVE_CLIENTS with /string.
• Uses its own FSM state classes — does NOT share states with /string.
• Uses 'sm_' / 'lsess_' callback prefixes — no collision with 'ses_' prefix.
• Auth flow uses TelegramClient(StringSession()) then converts to SQLite
  file after success, so no temp dir is created before auth completes.
• Temp dirs are created per-user, chmod 700, removed on every exit path.
• No phone numbers, OTPs, 2FA passwords, session data, or API_HASH in logs.
"""

import os
import io
import time
import shutil
import asyncio
import tempfile
from datetime import datetime, timezone

from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    FSInputFile,
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

from app.platform.capability import FeatureManifest
from app.utils.qr import generate_qr_buffer
from app.core.logger import setup_logger

manifest = FeatureManifest(
    name="SessionManager",
    description="Create and validate Telegram .session files",
    version="1.0.0",
    category="Session",
)

router = Router()
logger = setup_logger()

_SM_TIMEOUT   = 120  # displayed QR lifetime
_SM_INTERVAL  = 5    # countdown edit interval (flood-safe)

# Per-user runtime state — completely separate from /string's ACTIVE_CLIENTS
CS_ACTIVE: dict[int, dict] = {}

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _get_creds() -> tuple[int, str]:
    api_id_str = os.environ.get("API_ID",   "").strip()
    api_hash   = os.environ.get("API_HASH",  "").strip()
    if not api_id_str:
        raise ValueError("API_ID is not configured in the application environment")
    if not api_hash:
        raise ValueError("API_HASH is not configured in the application environment")
    return int(api_id_str), api_hash


# ---------------------------------------------------------------------------
# Temporary file helpers
# ---------------------------------------------------------------------------

def _mktmpdir(user_id: int) -> str:
    path = tempfile.mkdtemp(prefix=f"sm_{user_id}_")
    try:
        os.chmod(path, 0o700)
    except Exception:
        pass
    return path


def _rmtmpdir(path: str | None) -> None:
    if path and os.path.exists(path):
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# FSM states — separate classes, no overlap with /string states
# ---------------------------------------------------------------------------

class CreateSessionState(StatesGroup):
    waiting_for_method = State()
    waiting_for_phone  = State()
    waiting_for_otp    = State()
    waiting_for_2fa    = State()


class LoginSessionState(StatesGroup):
    waiting_for_file = State()


# ---------------------------------------------------------------------------
# Keyboards — all use 'sm_' or 'lsess_' prefixes
# ---------------------------------------------------------------------------

def _session_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📁 Create Session", callback_data="sm_create"),
            InlineKeyboardButton(text="📂 Login Session",  callback_data="sm_login"),
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="back_main")],
    ])


def _cs_method_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 QR Login *(recommended)*", callback_data="sm_method_qr")],
        [InlineKeyboardButton(text="🔢 OTP Login",                callback_data="sm_method_otp")],
        [InlineKeyboardButton(text="❌ Cancel",                    callback_data="sm_cancel")],
    ])


def _cs_qr_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh QR", callback_data="sm_qr_refresh")],
        [InlineKeyboardButton(text="❌ Cancel",      callback_data="sm_cancel")],
    ])


def _cs_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="sm_cancel")],
    ])


def _cs_switch_to_qr_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Use QR Login", callback_data="sm_start_qr")],
        [InlineKeyboardButton(text="❌ Cancel",        callback_data="sm_cancel")],
    ])


def _cs_otp_kb(next_type=None) -> InlineKeyboardMarkup:
    rows = []
    if next_type is not None:
        label = _next_type_label(next_type)
        rows.append([InlineKeyboardButton(
            text=f"📲 Resend via {label}", callback_data="sm_otp_resend",
        )])
    rows.append([InlineKeyboardButton(text="❌ Cancel", callback_data="sm_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _login_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="lsess_cancel")],
    ])


def _qr_caption(secs: int) -> str:
    return (
        "📱 **Telegram QR Login**\n"
        "────────────────────\n"
        "Scan this QR using:\n\n"
        "*Telegram → Settings → Devices → Link Desktop Device*\n\n"
        f"⏳ Expires in: {secs}s"
    )


# ---------------------------------------------------------------------------
# Delivery-type helpers (mirrors session/router.py but independent)
# ---------------------------------------------------------------------------

def _current_type_label(result) -> str:
    try:
        name = type(result.type).__name__
    except Exception:
        return "your phone"
    if "App"      in name: return "the Telegram app"
    if "Sms"      in name: return "SMS"
    if "Call"     in name or "Flash" in name or "Missed" in name: return "a phone call"
    if "Email"    in name: return "email"
    if "Fragment" in name: return "Fragment"
    return "your phone"


def _next_type_label(next_type) -> str:
    if next_type is None:
        return ""
    name = type(next_type).__name__
    if "Sms"   in name: return "SMS"
    if "Call"  in name or "Flash" in name or "Missed" in name: return "Phone Call"
    return "alternative method"


# ---------------------------------------------------------------------------
# Cleanup — cancels tasks, disconnects client, removes NO tmpdir here
# (tmpdir is only created in _convert_and_deliver, not during auth)
# ---------------------------------------------------------------------------

async def _cs_cleanup(user_id: int) -> None:
    sd = CS_ACTIVE.pop(user_id, None)
    if sd is None:
        return

    current = asyncio.current_task()
    for key in ("task", "countdown_task"):
        t: asyncio.Task | None = sd.get(key)
        if t and not t.done() and t is not current:
            t.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

    client: TelegramClient | None = sd.get("client")
    if client:
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass


def _stop_countdown(user_id: int, sd: dict) -> None:
    ct: asyncio.Task | None = sd.get("countdown_task")
    if ct and not ct.done() and ct is not asyncio.current_task():
        ct.cancel()


# ---------------------------------------------------------------------------
# StringSession → SQLite .session conversion and delivery
# ---------------------------------------------------------------------------

async def _convert_and_deliver(
    user_id: int, bot: Bot, chat_id: int, state: FSMContext, method: str,
) -> None:
    """
    Post-auth: export the in-memory StringSession to a SQLite .session file,
    send it to the user, then clean up temp files and client state.
    Called from the last success point of every auth path.
    """
    sd = CS_ACTIVE.get(user_id)
    if sd is None:
        return

    client: TelegramClient = sd["client"]
    tmpdir = None

    try:
        # Persist session to SQLite
        session_str = client.session.save()

        tmpdir = _mktmpdir(user_id)
        sess_base = os.path.join(tmpdir, "session")
        sess_file = sess_base + ".session"

        from telethon.sessions import SQLiteSession
        from telethon.sessions import StringSession as _SS

        ss    = _SS(session_str)
        sqls  = SQLiteSession(sess_base)
        sqls.set_dc(ss.dc_id, ss.server_address, ss.port)
        sqls.auth_key = ss.auth_key
        sqls.save()

        if os.path.exists(sess_file):
            try:
                os.chmod(sess_file, 0o600)
            except Exception:
                pass

        logger.info({"event": "sm_session_file_ready", "user_id": user_id, "method": method})

        await bot.send_document(
            chat_id=chat_id,
            document=FSInputFile(path=sess_file, filename="telegram_session.session"),
            caption=(
                "✅ **Session file created successfully!**\n\n"
                "🔐 This `.session` file grants full access to the Telegram account.\n"
                "⚠️ **Keep it private. Never share it.**"
            ),
            parse_mode="Markdown",
        )

    except Exception as exc:
        logger.error({"event": "sm_deliver_error", "user_id": user_id, "error": type(exc).__name__})
        await bot.send_message(
            chat_id,
            "❌ Failed to generate or send the session file. Please try again.",
            parse_mode="Markdown",
        )
    finally:
        _rmtmpdir(tmpdir)
        await _cs_cleanup(user_id)
        await state.clear()


# ---------------------------------------------------------------------------
# QR countdown background task
# ---------------------------------------------------------------------------

async def _cs_qr_countdown(
    user_id: int, bot: Bot, chat_id: int, msg_id: int, state: FSMContext,
) -> None:
    cur_msg_id = msg_id
    try:
        while True:
            await asyncio.sleep(_SM_INTERVAL)

            sd = CS_ACTIVE.get(user_id)
            if not sd:
                return

            qrl = sd.get("qr_login")
            if not qrl:
                return

            now = datetime.now(timezone.utc)
            try:
                remaining = max(0.0, (qrl.expires - now).total_seconds())
            except Exception:
                remaining = 0.0

            if remaining <= _SM_INTERVAL:
                # Auto-recreate QR
                try:
                    await qrl.recreate()
                    sd["qr_login"] = qrl

                    now2 = datetime.now(timezone.utc)
                    try:
                        new_rem = max(0, int((qrl.expires - now2).total_seconds()))
                    except Exception:
                        new_rem = _SM_TIMEOUT

                    buf = generate_qr_buffer(qrl.url)
                    try:
                        qr_bytes = buf.getvalue()
                    finally:
                        buf.close()

                    try:
                        await bot.edit_message_media(
                            chat_id=chat_id, message_id=cur_msg_id,
                            media=InputMediaPhoto(
                                media=BufferedInputFile(qr_bytes, filename="qr.png"),
                                caption=_qr_caption(new_rem), parse_mode="Markdown",
                            ),
                            reply_markup=_cs_qr_kb(),
                        )
                    except TelegramBadRequest:
                        nm = await bot.send_photo(
                            chat_id=chat_id,
                            photo=BufferedInputFile(qr_bytes, filename="qr.png"),
                            caption=_qr_caption(new_rem), parse_mode="Markdown",
                            reply_markup=_cs_qr_kb(),
                        )
                        cur_msg_id = nm.message_id

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning({"event": "sm_qr_recreate_failed", "user_id": user_id, "error": type(exc).__name__})
                    try:
                        await bot.edit_message_caption(
                            chat_id=chat_id, message_id=cur_msg_id,
                            caption="⚠️ **QR expired.** Press **🔄 Refresh QR**.",
                            parse_mode="Markdown", reply_markup=_cs_qr_kb(),
                        )
                    except Exception:
                        pass
                    return
            else:
                try:
                    await bot.edit_message_caption(
                        chat_id=chat_id, message_id=cur_msg_id,
                        caption=_qr_caption(int(remaining)),
                        parse_mode="Markdown", reply_markup=_cs_qr_kb(),
                    )
                except TelegramBadRequest:
                    pass
                except Exception:
                    pass

    except asyncio.CancelledError:
        raise


# ---------------------------------------------------------------------------
# QR wait background task
# ---------------------------------------------------------------------------

async def _cs_wait_for_qr(
    user_id: int, state: FSMContext, bot: Bot, chat_id: int,
) -> None:
    sd = CS_ACTIVE.get(user_id)
    if sd is None:
        return

    try:
        try:
            await sd["qr_login"].wait(timeout=None)
        except SessionPasswordNeededError:
            _stop_countdown(user_id, sd)
            sd["method"] = "qr"
            await state.set_state(CreateSessionState.waiting_for_2fa)
            await bot.send_message(
                chat_id,
                "🔐 **Two-Step Verification required.**\n\nPlease send your 2FA password:",
                parse_mode="Markdown", reply_markup=_cs_cancel_kb(),
            )
            return

        await _convert_and_deliver(user_id, bot, chat_id, state, "qr")

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error({"event": "sm_qr_wait_error", "user_id": user_id, "error": type(exc).__name__})
        await _cs_cleanup(user_id)
        await state.clear()
        await bot.send_message(
            chat_id,
            f"❌ Authentication error: `{type(exc).__name__}`",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# QR login startup helper
# ---------------------------------------------------------------------------

async def _start_sm_qr(
    user_id: int, chat_id: int, api_id: int, api_hash: str,
    state: FSMContext, bot: Bot,
) -> None:
    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.connect()
        qrl = await client.qr_login()
    except FloodWaitError as exc:
        try: await client.disconnect()
        except Exception: pass
        await bot.send_message(chat_id,
            f"⏳ Too many requests. Wait **{exc.seconds}s** and try again.",
            parse_mode="Markdown")
        await state.clear()
        return
    except Exception as exc:
        try: await client.disconnect()
        except Exception: pass
        logger.error({"event": "sm_qr_connect_error", "error": type(exc).__name__})
        await bot.send_message(chat_id,
            f"❌ Connection failed: `{type(exc).__name__}`",
            parse_mode="Markdown")
        await state.clear()
        return

    now = datetime.now(timezone.utc)
    try:
        remaining = max(0, int((qrl.expires - now).total_seconds()))
    except Exception:
        remaining = _SM_TIMEOUT

    buf = generate_qr_buffer(qrl.url)
    try:
        qr_bytes = buf.getvalue()
    finally:
        buf.close()

    qr_msg = await bot.send_photo(
        chat_id=chat_id,
        photo=BufferedInputFile(qr_bytes, filename="qr.png"),
        caption=_qr_caption(remaining),
        parse_mode="Markdown", reply_markup=_cs_qr_kb(),
    )

    CS_ACTIVE[user_id] = {
        "client":         client,
        "qr_login":       qrl,
        "qr_msg_id":      qr_msg.message_id,
        "chat_id":        chat_id,
        "method":         "qr",
        "created_at":     time.monotonic(),
        "task":           None,
        "countdown_task": None,
    }

    cd_task = asyncio.create_task(
        _cs_qr_countdown(user_id, bot, chat_id, qr_msg.message_id, state),
        name=f"sm_cd_{user_id}",
    )
    wt_task = asyncio.create_task(
        _cs_wait_for_qr(user_id, state, bot, chat_id),
        name=f"sm_qr_{user_id}",
    )
    CS_ACTIVE[user_id]["task"]           = wt_task
    CS_ACTIVE[user_id]["countdown_task"] = cd_task

    await state.clear()


# ---------------------------------------------------------------------------
# /create_session command
# ---------------------------------------------------------------------------

@router.message(Command("create_session"))
async def cmd_create_session(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    if user_id in CS_ACTIVE:
        await _cs_cleanup(user_id)
    await state.clear()

    try:
        _get_creds()
    except ValueError as exc:
        await message.reply(
            f"❌ **Bot configuration error**\n\n`{exc}`\n\n"
            "The administrator must set `API_ID` and `API_HASH`.",
            parse_mode="Markdown",
        )
        return

    await state.set_state(CreateSessionState.waiting_for_method)
    await message.reply(
        "📁 **Create Telegram Session**\n"
        "────────────────────\n"
        "Authenticate and export a `.session` file.\n\n"
        "Choose your login method:",
        parse_mode="Markdown", reply_markup=_cs_method_kb(),
    )


# ---------------------------------------------------------------------------
# /login_session command
# ---------------------------------------------------------------------------

@router.message(Command("login_session"))
async def cmd_login_session(message: Message, state: FSMContext) -> None:
    await state.clear()

    try:
        _get_creds()
    except ValueError as exc:
        await message.reply(f"❌ **Bot configuration error**\n\n`{exc}`", parse_mode="Markdown")
        return

    await state.set_state(LoginSessionState.waiting_for_file)
    await message.reply(
        "📂 **Login with Existing Session**\n"
        "────────────────────\n"
        "Please **upload your Telegram `.session` file** as a document.\n\n"
        "⚠️ A `.session` file grants full account access. Only upload files you trust.",
        parse_mode="Markdown", reply_markup=_login_cancel_kb(),
    )


# ---------------------------------------------------------------------------
# Session menu callbacks
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "cat_session_mgr")
async def cb_session_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🔐 **Session Manager**\n"
        "────────────────────\n\n"
        "📁 **Create Session** — Authenticate and export a `.session` file.\n\n"
        "📂 **Login Session** — Validate an existing `.session` file.",
        parse_mode="Markdown", reply_markup=_session_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "sm_create")
async def cb_sm_create(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    if user_id in CS_ACTIVE:
        await _cs_cleanup(user_id)
    await state.clear()

    try:
        _get_creds()
    except ValueError as exc:
        await callback.message.edit_text(f"❌ **Bot configuration error**\n\n`{exc}`", parse_mode="Markdown")
        await callback.answer()
        return

    await state.set_state(CreateSessionState.waiting_for_method)
    await callback.message.edit_text(
        "📁 **Create Telegram Session**\n"
        "────────────────────\n"
        "Choose your login method:",
        parse_mode="Markdown", reply_markup=_cs_method_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "sm_login")
async def cb_sm_login(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    try:
        _get_creds()
    except ValueError as exc:
        await callback.message.edit_text(f"❌ **Bot configuration error**\n\n`{exc}`", parse_mode="Markdown")
        await callback.answer()
        return

    await state.set_state(LoginSessionState.waiting_for_file)
    await callback.message.edit_text(
        "📂 **Login with Existing Session**\n"
        "────────────────────\n"
        "Please **upload your Telegram `.session` file** as a document.",
        parse_mode="Markdown", reply_markup=_login_cancel_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Cancel callbacks
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "sm_cancel")
async def cb_sm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    if user_id in CS_ACTIVE:
        await _cs_cleanup(user_id)
    await state.clear()
    try:
        if callback.message.photo:
            await callback.message.edit_caption("❌ Session operation cancelled.")
        else:
            await callback.message.edit_text("❌ Session operation cancelled.")
    except TelegramBadRequest:
        await callback.message.answer("❌ Session operation cancelled.")
    await callback.answer()


@router.callback_query(F.data == "lsess_cancel")
async def cb_lsess_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await callback.message.edit_text("❌ Login session operation cancelled.")
    except TelegramBadRequest:
        await callback.message.answer("❌ Login session operation cancelled.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Method selection
# ---------------------------------------------------------------------------

@router.callback_query(CreateSessionState.waiting_for_method, F.data == "sm_method_qr")
async def cb_sm_method_qr(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    try:
        api_id, api_hash = _get_creds()
    except ValueError as exc:
        await callback.message.edit_text(f"❌ Configuration error: {exc}")
        await state.clear()
        return

    await callback.message.edit_text("📱 Starting QR login…", reply_markup=None)
    await _start_sm_qr(user_id, chat_id, api_id, api_hash, state, bot)


@router.callback_query(CreateSessionState.waiting_for_method, F.data == "sm_method_otp")
async def cb_sm_method_otp(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "📞 **OTP Login**\n"
        "────────────────────\n"
        "Please send your **phone number** (e.g. +1234567890):",
        parse_mode="Markdown", reply_markup=_cs_cancel_kb(),
    )
    await state.set_state(CreateSessionState.waiting_for_phone)


# ---------------------------------------------------------------------------
# QR Refresh button
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "sm_qr_refresh")
async def cb_sm_qr_refresh(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer("Generating new QR…")
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    sd = CS_ACTIVE.get(user_id)
    if not sd:
        try:
            await callback.message.edit_caption(
                "❌ Session expired. Please run `/create_session` again.",
                parse_mode="Markdown",
            )
        except TelegramBadRequest:
            await callback.message.answer("❌ Session expired. Run /create_session again.")
        return

    qrl = sd.get("qr_login")
    if not qrl:
        await callback.message.answer("❌ State lost. Run /create_session again.")
        return

    try:
        await qrl.recreate()
        sd["qr_login"] = qrl

        now = datetime.now(timezone.utc)
        try:
            remaining = max(0, int((qrl.expires - now).total_seconds()))
        except Exception:
            remaining = _SM_TIMEOUT

        buf = generate_qr_buffer(qrl.url)
        try:
            qr_bytes = buf.getvalue()
        finally:
            buf.close()

        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(
                    media=BufferedInputFile(qr_bytes, filename="qr.png"),
                    caption=_qr_caption(remaining), parse_mode="Markdown",
                ),
                reply_markup=_cs_qr_kb(),
            )
        except TelegramBadRequest:
            nm = await bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(qr_bytes, filename="qr.png"),
                caption=_qr_caption(remaining), parse_mode="Markdown",
                reply_markup=_cs_qr_kb(),
            )

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning({"event": "sm_qr_refresh_failed", "user_id": user_id, "error": type(exc).__name__})
        await callback.answer("❌ Refresh failed. Try /create_session again.", show_alert=True)


# ---------------------------------------------------------------------------
# Switch to QR from OTP rejection
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "sm_start_qr")
async def cb_sm_start_qr(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if user_id in CS_ACTIVE:
        await _cs_cleanup(user_id)

    try:
        api_id, api_hash = _get_creds()
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

    await _start_sm_qr(user_id, chat_id, api_id, api_hash, state, bot)


# ---------------------------------------------------------------------------
# OTP flow — phone number
# ---------------------------------------------------------------------------

@router.message(CreateSessionState.waiting_for_phone)
async def cs_recv_phone(message: Message, state: FSMContext) -> None:
    phone   = (message.text or "").strip()
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not phone.startswith("+") or len(phone) < 7:
        await message.reply("❌ Use international format e.g. +1234567890:", reply_markup=_cs_cancel_kb())
        return

    try:
        api_id, api_hash = _get_creds()
    except ValueError as exc:
        await message.reply(f"❌ Configuration error: {exc}")
        await state.clear()
        return

    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.connect()
        result = await client.send_code_request(phone)
    except FloodWaitError as exc:
        try: await client.disconnect()
        except Exception: pass
        await message.reply(f"⏳ Please wait **{exc.seconds}s** and try again.", parse_mode="Markdown")
        await state.clear()
        return
    except PhoneNumberInvalidError:
        try: await client.disconnect()
        except Exception: pass
        await message.reply("❌ Invalid phone number. Please try again:", reply_markup=_cs_cancel_kb())
        return
    except AuthRestartError:
        try: await client.disconnect()
        except Exception: pass
        await message.reply("⚠️ Telegram interrupted the flow. Run `/create_session` again.", parse_mode="Markdown")
        await state.clear()
        return
    except Exception as exc:
        try: await client.disconnect()
        except Exception: pass
        logger.error({"event": "sm_send_code_error", "error": type(exc).__name__})
        await message.reply(f"❌ Failed to request code: `{type(exc).__name__}`", parse_mode="Markdown")
        await state.clear()
        return

    delivery  = _current_type_label(result)
    next_type = getattr(result, "next_type", None)

    # Discard any previous OTP session for this user
    if user_id in CS_ACTIVE:
        await _cs_cleanup(user_id)

    _req_hash_len = len(result.phone_code_hash)
    logger.info({
        "event": "sm_otp_requested", "user_id": user_id,
        "delivery": delivery, "hash_len": _req_hash_len,
        "has_next_type": next_type is not None,
    })

    CS_ACTIVE[user_id] = {
        "client":          client,
        "phone":           phone,
        "phone_code_hash": result.phone_code_hash,
        "delivery":        delivery,
        "next_type":       next_type,
        "resent":          False,
        "method":          "otp",
        "chat_id":         chat_id,
        "created_at":      time.monotonic(),
        "task":            None,
        "countdown_task":  None,
    }

    # Build context-aware prompt
    if delivery == "the Telegram app" and next_type is None:
        prompt = (
            "📨 Telegram sent the code via **the Telegram app**.\n\n"
            "⚠️ **Important:** Telegram usually rejects codes delivered this way "
            "when re-entered through another session "
            "(*previously shared by your account*).\n\n"
            "👉 **QR Login is strongly recommended** for your account.\n\n"
            "You may still type the code below — if Telegram rejects it, "
            "the QR option will reappear."
        )
        keyboard = _cs_switch_to_qr_kb()
    elif next_type is not None:
        nl = _next_type_label(next_type)
        prompt = (
            f"📨 Telegram sent the code via **{delivery}**.\n\n"
            f"Tap **Resend via {nl}** if you cannot use this code here.\n\n"
            "Please send the **verification code**:"
        )
        keyboard = _cs_otp_kb(next_type)
    else:
        prompt = (
            f"📨 Verification code sent via {delivery}.\n\n"
            "Please send the **verification code**:"
        )
        keyboard = _cs_otp_kb(None)

    await state.set_state(CreateSessionState.waiting_for_otp)
    await message.reply(prompt, parse_mode="Markdown", reply_markup=keyboard)


# ---------------------------------------------------------------------------
# OTP flow — verification code
# ---------------------------------------------------------------------------

@router.message(CreateSessionState.waiting_for_otp)
async def cs_recv_otp(message: Message, state: FSMContext) -> None:
    code    = (message.text or "").strip()
    user_id = message.from_user.id

    sd = CS_ACTIVE.get(user_id)
    if not sd:
        await state.clear()
        await message.reply("❌ Session expired. Run `/create_session` again.", parse_mode="Markdown")
        return

    client: TelegramClient = sd["client"]
    phone           = sd["phone"]
    phone_code_hash = sd["phone_code_hash"]

    if not client.is_connected():
        await _cs_cleanup(user_id)
        await state.clear()
        await message.reply("❌ Connection lost. Run `/create_session` again.", parse_mode="Markdown")
        return

    _otp_hash_len = len(phone_code_hash)
    logger.info({
        "event": "sm_otp_sign_in", "user_id": user_id,
        "hash_len": _otp_hash_len, "client_id": id(client),
    })

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)

    except SessionPasswordNeededError:
        sd["method"] = "otp"
        await state.set_state(CreateSessionState.waiting_for_2fa)
        await message.reply(
            "🔐 **Two-Step Verification required.**\n\nPlease send your 2FA password:",
            parse_mode="Markdown", reply_markup=_cs_cancel_kb(),
        )
        return

    except PhoneCodeInvalidError:
        await message.reply("❌ Incorrect code. Please try again:", reply_markup=_cs_cancel_kb())
        return

    except PhoneCodeExpiredError:
        await _cs_cleanup(user_id)
        await state.clear()
        logger.warning({"event": "sm_otp_code_rejected", "user_id": user_id})
        await message.reply(
            "⏱️ **Telegram rejected this code.**\n\n"
            "This happens when the code was delivered via the Telegram app "
            "and Telegram blocks re-entry (*previously shared by your account*).\n\n"
            "👉 Use **QR Login** instead:",
            parse_mode="Markdown", reply_markup=_cs_switch_to_qr_kb(),
        )
        return

    except FloodWaitError as exc:
        await _cs_cleanup(user_id)
        await state.clear()
        await message.reply(f"⏳ Please wait **{exc.seconds}s** before trying again.", parse_mode="Markdown")
        return

    except AuthRestartError:
        await _cs_cleanup(user_id)
        await state.clear()
        await message.reply("⚠️ Telegram interrupted the session. Run `/create_session` again.", parse_mode="Markdown")
        return

    except Exception as exc:
        await _cs_cleanup(user_id)
        await state.clear()
        logger.error({"event": "sm_otp_error", "user_id": user_id, "exception": type(exc).__name__})
        await message.reply("❌ Login failed. Use **QR Login** for a reliable alternative.", parse_mode="Markdown")
        return

    await _convert_and_deliver(user_id, message.bot, message.chat.id, state, "otp")


# ---------------------------------------------------------------------------
# OTP resend (one-shot, uses Telegram's official ResendCode API)
# ---------------------------------------------------------------------------

try:
    from telethon.tl.functions.auth import ResendCodeRequest as _TLResend
except (ImportError, AttributeError):
    _TLResend = None


@router.callback_query(CreateSessionState.waiting_for_otp, F.data == "sm_otp_resend")
async def cb_sm_otp_resend(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    sd      = CS_ACTIVE.get(user_id)

    if not sd:
        await callback.message.edit_text("❌ Session expired. Run `/create_session` again.", parse_mode="Markdown")
        return
    if sd.get("resent"):
        await callback.answer("Code already resent. Enter the code you received.", show_alert=True)
        return
    if _TLResend is None:
        await callback.answer("Resend not available in this Telethon version.", show_alert=True)
        return
    if sd.get("next_type") is None:
        await callback.answer("No alternative delivery method available.", show_alert=True)
        return

    client          = sd["client"]
    phone           = sd["phone"]
    phone_code_hash = sd["phone_code_hash"]
    next_type       = sd["next_type"]

    try:
        new = await client(_TLResend(phone_number=phone, phone_code_hash=phone_code_hash))
        sd["phone_code_hash"] = new.phone_code_hash
        sd["next_type"]       = getattr(new, "next_type", None)
        sd["resent"]          = True
        label = _next_type_label(next_type)
        logger.info({"event": "sm_otp_resent", "user_id": user_id})
        try:
            await callback.message.edit_text(
                f"📲 **Code resent via {label}.**\n\nPlease send the verification code:",
                parse_mode="Markdown", reply_markup=_cs_cancel_kb(),
            )
        except TelegramBadRequest:
            pass
    except FloodWaitError as exc:
        await callback.answer(f"⏳ Wait {exc.seconds}s before resending.", show_alert=True)
    except Exception as exc:
        logger.warning({"event": "sm_resend_error", "user_id": user_id, "error": type(exc).__name__})
        await callback.answer("❌ Could not resend. Enter the code you received.", show_alert=True)


# ---------------------------------------------------------------------------
# 2FA — shared by QR and OTP paths
# ---------------------------------------------------------------------------

@router.message(CreateSessionState.waiting_for_2fa)
async def cs_process_2fa(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id

    if user_id not in CS_ACTIVE:
        await state.clear()
        await message.reply("❌ Session expired. Run `/create_session` again.", parse_mode="Markdown")
        return

    sd     = CS_ACTIVE[user_id]
    client = sd["client"]

    try:
        await client.sign_in(password=(message.text or "").strip())
        await _convert_and_deliver(user_id, message.bot, message.chat.id, state, sd.get("method", "2fa"))

    except PasswordHashInvalidError:
        await message.reply("❌ Incorrect 2FA password. Please try again:", reply_markup=_cs_cancel_kb())

    except AuthRestartError:
        await _cs_cleanup(user_id)
        await state.clear()
        await message.reply("⚠️ Telegram interrupted the 2FA session. Run `/create_session` again.", parse_mode="Markdown")

    except Exception as exc:
        await _cs_cleanup(user_id)
        await state.clear()
        logger.error({"event": "sm_2fa_error", "user_id": user_id, "error": type(exc).__name__})
        await message.reply("❌ 2FA failed. Please try `/create_session` again.", parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /login_session — upload and validate .session file
# ---------------------------------------------------------------------------

@router.message(LoginSessionState.waiting_for_file)
async def ls_recv_file(message: Message, state: FSMContext, bot: Bot) -> None:
    user_id = message.from_user.id

    if not message.document:
        await message.reply(
            "❌ Please **upload a `.session` file** as a document attachment.",
            parse_mode="Markdown", reply_markup=_login_cancel_kb(),
        )
        return

    doc      = message.document
    filename = doc.file_name or ""

    if not filename.lower().endswith(".session"):
        await message.reply(
            "❌ Only `.session` files are accepted. Please upload a valid Telethon session file.",
            parse_mode="Markdown", reply_markup=_login_cancel_kb(),
        )
        return

    # Guard: reasonable size limit (Telethon session files are tiny SQLite DBs)
    if doc.file_size and doc.file_size > 512 * 1024:
        await message.reply(
            "❌ File too large. A valid `.session` file is typically under 512 KB.",
            reply_markup=_login_cancel_kb(),
        )
        return

    status = await message.reply("🔄 Downloading and validating session…")

    tmpdir = _mktmpdir(user_id)
    sess_base = os.path.join(tmpdir, "uploaded")
    sess_file = sess_base + ".session"

    try:
        # Download file
        await bot.download(file=doc, destination=sess_file)

        if not os.path.exists(sess_file) or os.path.getsize(sess_file) == 0:
            raise ValueError("Downloaded file is empty or missing")

        try:
            os.chmod(sess_file, 0o600)
        except Exception:
            pass

        api_id, api_hash = _get_creds()

        # Load and validate with Telethon
        client = TelegramClient(sess_base, api_id, api_hash)
        try:
            await client.connect()
            is_auth = await client.is_user_authorized()

            if not is_auth:
                await client.disconnect()
                await status.edit_text(
                    "❌ **Session is not authorized.**\n\n"
                    "This session file exists but the account is logged out.\n"
                    "Use `/create_session` to create a fresh authorized session.",
                    parse_mode="Markdown",
                )
                await state.clear()
                return

            me = await client.get_me()
            await client.disconnect()

        except Exception as inner:
            try: await client.disconnect()
            except Exception: pass
            raise inner

        # Show safe non-sensitive account summary
        parts = [me.first_name or ""]
        if me.last_name:
            parts.append(me.last_name)
        full_name = " ".join(parts).strip() or "Unknown"
        uname   = f"@{me.username}" if me.username else "No username"
        premium = "✅ Premium" if getattr(me, "is_premium", False) else "Standard"
        bot_tag = "🤖 Bot" if me.bot else "👤 User"

        await status.edit_text(
            "✅ **Session loaded successfully!**\n"
            "────────────────────\n"
            f"👤 **Name:** {full_name}\n"
            f"📛 **Username:** {uname}\n"
            f"🆔 **User ID:** `{me.id}`\n"
            f"🌟 **Tier:** {premium}\n"
            f"🏷️ **Type:** {bot_tag}\n"
            "────────────────────\n"
            "The session is authorized and valid.",
            parse_mode="Markdown",
        )
        logger.info({"event": "sm_session_validated", "user_id": user_id})
        await state.clear()

    except ValueError as exc:
        await status.edit_text(
            "❌ **Invalid session file.**\n\n"
            "The file could not be opened as a Telethon session. "
            "Please check the file and try again.",
            parse_mode="Markdown",
        )
        await state.clear()
    except Exception as exc:
        logger.error({"event": "sm_session_load_error", "user_id": user_id, "error": type(exc).__name__})
        await status.edit_text(
            "❌ **Invalid or corrupt session file.**\n\n"
            "The file could not be loaded. Please verify it is a valid "
            "Telethon `.session` file.",
            parse_mode="Markdown",
        )
        await state.clear()
    finally:
        _rmtmpdir(tmpdir)


# ---------------------------------------------------------------------------
# Shutdown hook (called by bootstrap on bot stop)
# ---------------------------------------------------------------------------

async def shutdown_all_sm_sessions() -> None:
    uids = list(CS_ACTIVE.keys())
    logger.info({"event": "sm_shutdown", "active": len(uids)})
    for uid in uids:
        await _cs_cleanup(uid)
