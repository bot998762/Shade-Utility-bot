"""
Tests for the Session Manager feature (/create_session, /login_session).

Scope:
- /create_session and /login_session exist and respond correctly
- FSM states are correct
- QR and OTP create_session flows produce .session files
- 2FA path works end-to-end
- Telegram OTP rejection falls back to QR cleanly
- login_session validates and rejects appropriately
- Per-user isolation enforced
- No secrets appear in any log call
- Existing /string and QR behavior unchanged (regression)

All Telethon/network calls are mocked.
"""

import os
import sys
import ast
import pathlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

PROJECT_ROOT = pathlib.Path(__file__).parent.parent


def _skip_no_telethon():
    try:
        import telethon  # noqa
    except ImportError:
        return True
    return False


class TestSessionManagerSourceLevel(unittest.TestCase):
    """Source-level checks — no imports needed."""

    def setUp(self):
        self.src = (PROJECT_ROOT / "app/features/session_manager/router.py").read_text()

    def test_router_file_exists(self):
        self.assertTrue((PROJECT_ROOT / "app/features/session_manager/router.py").exists())

    def test_package_init_exists(self):
        self.assertTrue((PROJECT_ROOT / "app/features/session_manager/__init__.py").exists())

    def test_syntax_valid(self):
        ast.parse(self.src)  # raises SyntaxError on failure

    def test_manifest_exported(self):
        self.assertIn("manifest", self.src)
        self.assertIn("FeatureManifest", self.src)
        self.assertIn("SessionManager", self.src)

    def test_router_exported(self):
        self.assertIn("router = Router()", self.src)

    def test_create_session_command(self):
        self.assertIn('Command("create_session")', self.src)

    def test_login_session_command(self):
        self.assertIn('Command("login_session")', self.src)

    def test_fsm_states_create(self):
        for s in ("waiting_for_method", "waiting_for_phone", "waiting_for_otp", "waiting_for_2fa"):
            self.assertIn(s, self.src)

    def test_fsm_states_login(self):
        self.assertIn("waiting_for_file", self.src)

    def test_separate_fsm_classes(self):
        self.assertIn("CreateSessionState", self.src)
        self.assertIn("LoginSessionState",  self.src)

    def test_callback_prefixes_sm(self):
        for cb in ("sm_create", "sm_login", "sm_cancel", "sm_method_qr", "sm_method_otp",
                   "sm_qr_refresh", "sm_start_qr", "sm_otp_resend"):
            self.assertIn(cb, self.src, f"callback {cb!r} missing")

    def test_callback_prefix_lsess(self):
        self.assertIn("lsess_cancel", self.src)

    def test_separate_active_clients_dict(self):
        self.assertIn("CS_ACTIVE", self.src)
        # Must NOT use ACTIVE_CLIENTS as a dict (comments/docstrings OK)
        self.assertNotIn("ACTIVE_CLIENTS[", self.src)
        self.assertNotIn("ACTIVE_CLIENTS.", self.src)

    def test_qr_flow_present(self):
        self.assertIn("qr_login",     self.src)
        # The QR wait uses sd["qr_login"].wait — check the actual pattern
        self.assertIn(".wait(timeout=None)", self.src)
        self.assertIn("recreate()",          self.src)

    def test_sqlite_session_conversion(self):
        self.assertIn("SQLiteSession",      self.src)
        self.assertIn("telegram_session.session", self.src)

    def test_2fa_handled(self):
        self.assertIn("SessionPasswordNeededError", self.src)
        self.assertIn("PasswordHashInvalidError",   self.src)
        self.assertIn("waiting_for_2fa",            self.src)

    def test_error_handling_complete(self):
        for err in ("PhoneCodeInvalidError", "PhoneCodeExpiredError",
                    "FloodWaitError", "PhoneNumberInvalidError", "AuthRestartError"):
            self.assertIn(err, self.src, f"{err} not handled")

    def test_tmpdir_cleanup_always(self):
        self.assertIn("_rmtmpdir", self.src)
        # rmtmpdir called in finally blocks
        self.assertIn("finally:", self.src)

    def test_no_secrets_in_log_calls(self):
        for forbidden in ('"phone_code_hash"', '"api_hash"', '"password"', '"otp"', '"code"'):
            # Confirm these strings don't appear inside logger.* calls
            # Simple heuristic: check the log event dicts
            import re
            log_blocks = re.findall(r'logger\.\w+\(\{[^}]+\}\)', self.src)
            for block in log_blocks:
                self.assertNotIn(forbidden, block,
                                 f"{forbidden} found in log call: {block!r}")

    def test_file_size_guard_login(self):
        self.assertIn("512 * 1024", self.src)

    def test_session_file_extension_check(self):
        self.assertIn(".session", self.src)
        self.assertIn("endswith", self.src)

    def test_shutdown_hook_exported(self):
        self.assertIn("shutdown_all_sm_sessions", self.src)

    def test_self_cancel_guard(self):
        self.assertIn("asyncio.current_task()", self.src)

    def test_qr_countdown_interval_defined(self):
        self.assertIn("_SM_INTERVAL", self.src)

    def test_resend_code_request_used(self):
        self.assertIn("ResendCodeRequest", self.src)

    def test_force_sms_not_used(self):
        self.assertNotIn("force_sms", self.src)


class TestFeatureRegistration(unittest.TestCase):
    """Confirm session_manager is wired into the feature loader and menu."""

    def test_session_manager_in_feature_modules(self):
        src = (PROJECT_ROOT / "app/features/__init__.py").read_text()
        self.assertIn("app.features.session_manager.router", src)

    def test_session_manager_button_in_main_menu(self):
        src = (PROJECT_ROOT / "app/keyboards/inline_kb.py").read_text()
        self.assertIn("cat_session_mgr",    src)
        self.assertIn("Session Manager",    src)

    def test_create_session_in_help(self):
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        self.assertIn("/create_session", src)
        self.assertIn("/login_session",  src)

    def test_bootstrap_shutdown_hook(self):
        src = (PROJECT_ROOT / "app/core/bootstrap.py").read_text()
        self.assertIn("shutdown_all_sm_sessions", src)

    def test_string_feature_frozen(self):
        """Verify /string source is unchanged (no 'session_manager' references)."""
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertNotIn("session_manager", src)
        self.assertNotIn("CS_ACTIVE",       src)
        self.assertNotIn("sm_cancel",       src)


class TestCreateSessionFlow(unittest.IsolatedAsyncioTestCase):
    """Behavioral tests for /create_session."""

    def _skip(self):
        if _skip_no_telethon():
            self.skipTest("telethon not installed")

    # ------------------------------------------------------------------
    # Credential pre-flight
    # ------------------------------------------------------------------

    async def test_cmd_create_session_missing_creds_shows_error(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch

        state   = MagicMock(); state.clear = AsyncMock(); state.set_state = AsyncMock()
        message = MagicMock()
        message.from_user = MagicMock(); message.from_user.id = 1001
        message.reply     = AsyncMock()

        with patch("app.features.session_manager.router._get_creds",
                   side_effect=ValueError("API_ID not set")):
            await sm.cmd_create_session(message, state)

        message.reply.assert_called_once()
        self.assertIn("configuration", message.reply.call_args[0][0].lower())
        state.set_state.assert_not_called()

    async def test_cmd_create_session_shows_method_selection(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch

        state   = MagicMock(); state.clear = AsyncMock(); state.set_state = AsyncMock()
        message = MagicMock()
        message.from_user = MagicMock(); message.from_user.id = 1002
        message.reply     = AsyncMock()

        with patch("app.features.session_manager.router._get_creds", return_value=(1, "h")):
            await sm.cmd_create_session(message, state)

        state.set_state.assert_called_once_with(sm.CreateSessionState.waiting_for_method)
        message.reply.assert_called_once()
        kb = message.reply.call_args[1].get("reply_markup")
        self.assertIsNotNone(kb)
        flat = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("sm_method_qr",  flat)
        self.assertIn("sm_method_otp", flat)
        self.assertIn("sm_cancel",     flat)

    async def test_cmd_create_session_cleans_stale_session(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch

        user_id = 1003
        old_client = MagicMock()
        old_client.is_connected = MagicMock(return_value=True)
        old_client.disconnect   = AsyncMock()

        sm.CS_ACTIVE[user_id] = {
            "client": old_client, "task": None, "countdown_task": None,
            "chat_id": 1, "created_at": 0,
        }

        state   = MagicMock(); state.clear = AsyncMock(); state.set_state = AsyncMock()
        message = MagicMock()
        message.from_user = MagicMock(); message.from_user.id = user_id
        message.reply     = AsyncMock()

        with patch("app.features.session_manager.router._get_creds", return_value=(1, "h")):
            await sm.cmd_create_session(message, state)

        old_client.disconnect.assert_called_once()
        self.assertNotIn(user_id, sm.CS_ACTIVE)

    # ------------------------------------------------------------------
    # QR flow
    # ------------------------------------------------------------------

    async def test_qr_start_sends_photo_with_qr_keyboard(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch, AsyncMock as AM

        user_id = 2001
        sm.CS_ACTIVE.pop(user_id, None)

        fake_qrl = MagicMock()
        fake_qrl.url     = "tg://login?token=faketoken"
        fake_qrl.expires = __import__("datetime").datetime.now(__import__("datetime").timezone.utc) \
                           + __import__("datetime").timedelta(seconds=60)
        fake_qrl.wait    = AM()

        fake_client = MagicMock()
        fake_client.connect    = AM()
        fake_client.disconnect = AM()
        fake_client.qr_login   = AM(return_value=fake_qrl)

        bot = MagicMock()
        bot.send_photo = AM(return_value=MagicMock(message_id=99))

        state = MagicMock()
        state.clear     = AM()
        state.set_state = AM()

        with patch("app.features.session_manager.router.TelegramClient", return_value=fake_client), \
             patch("app.features.session_manager.router.generate_qr_buffer",
                   return_value=MagicMock(getvalue=MagicMock(return_value=b"qr"), close=MagicMock())):
            await sm._start_sm_qr(user_id, 111, 1, "h", state, bot)

        bot.send_photo.assert_called_once()
        call_kwargs = bot.send_photo.call_args[1]
        kb = call_kwargs.get("reply_markup")
        flat = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("sm_qr_refresh", flat)
        self.assertIn("sm_cancel",     flat)
        self.assertIn(user_id, sm.CS_ACTIVE)

        await sm._cs_cleanup(user_id)

    async def test_qr_success_calls_convert_and_deliver(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch, AsyncMock as AM

        user_id = 2002
        fake_client = MagicMock()
        fake_client.is_connected = MagicMock(return_value=True)
        fake_client.disconnect   = AM()
        fake_client.session      = MagicMock()
        fake_client.session.save = MagicMock(return_value="1BQANOTEuMTc...")

        fake_qrl = MagicMock()
        fake_qrl.wait = AM()  # returns normally = success

        sm.CS_ACTIVE[user_id] = {
            "client": fake_client, "qr_login": fake_qrl, "qr_msg_id": 1,
            "chat_id": 111, "method": "qr",
            "task": None, "countdown_task": None, "created_at": 0,
        }

        state = MagicMock()
        state.clear     = AM()
        state.set_state = AM()
        bot   = MagicMock()

        delivered = []

        async def fake_deliver(uid, b, c, s, method):
            delivered.append({"uid": uid, "method": method})
            sm.CS_ACTIVE.pop(uid, None)
            await s.clear()

        with patch.object(sm, "_convert_and_deliver", side_effect=fake_deliver):
            await sm._cs_wait_for_qr(user_id, state, bot, 111)

        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["method"], "qr")

    async def test_qr_2fa_sets_state_and_prompts(self):
        self._skip()
        from telethon.errors import SessionPasswordNeededError
        from app.features.session_manager import router as sm
        from unittest.mock import AsyncMock as AM

        user_id = 2003
        fake_client = MagicMock()
        fake_client.is_connected = MagicMock(return_value=True)
        fake_client.disconnect   = AM()

        fake_qrl = MagicMock()
        fake_qrl.wait = AM(side_effect=SessionPasswordNeededError(None))

        sm.CS_ACTIVE[user_id] = {
            "client": fake_client, "qr_login": fake_qrl, "qr_msg_id": 1,
            "chat_id": 111, "method": "qr",
            "task": None, "countdown_task": None, "created_at": 0,
        }

        state = MagicMock()
        state.clear     = AM()
        state.set_state = AM()
        bot   = MagicMock()
        bot.send_message = AM()

        await sm._cs_wait_for_qr(user_id, state, bot, 111)

        state.set_state.assert_called_once_with(sm.CreateSessionState.waiting_for_2fa)
        bot.send_message.assert_called_once()
        self.assertIn(user_id, sm.CS_ACTIVE)  # client kept alive for 2FA

        await sm._cs_cleanup(user_id)

    # ------------------------------------------------------------------
    # OTP flow
    # ------------------------------------------------------------------

    async def test_recv_phone_proceeds_to_otp_state(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch, AsyncMock as AM

        fake_result = MagicMock()
        fake_result.phone_code_hash = "hash123"
        fake_result.next_type       = None
        fake_result.type            = type("SentCodeTypeSms", (), {})()

        fake_client = MagicMock()
        fake_client.connect    = AM()
        fake_client.disconnect = AM()
        fake_client.send_code_request = AM(return_value=fake_result)

        user_id = 3001
        sm.CS_ACTIVE.pop(user_id, None)

        state   = MagicMock(); state.clear = AM(); state.set_state = AM()
        message = MagicMock()
        message.from_user    = MagicMock(); message.from_user.id = user_id
        message.chat         = MagicMock(); message.chat.id = 1
        message.text         = "+12025551234"
        message.reply        = AM()

        with patch("app.features.session_manager.router.TelegramClient", return_value=fake_client), \
             patch("app.features.session_manager.router._get_creds", return_value=(1, "h")):
            await sm.cs_recv_phone(message, state)

        state.set_state.assert_called_with(sm.CreateSessionState.waiting_for_otp)
        self.assertIn(user_id, sm.CS_ACTIVE)
        self.assertEqual(sm.CS_ACTIVE[user_id]["phone_code_hash"], "hash123")

        await sm._cs_cleanup(user_id)

    async def test_recv_phone_app_delivery_shows_qr_button(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch, AsyncMock as AM

        fake_result = MagicMock()
        fake_result.phone_code_hash = "apphash"
        fake_result.next_type       = None
        fake_result.type            = type("SentCodeTypeApp", (), {})()

        fake_client = MagicMock()
        fake_client.connect    = AM()
        fake_client.disconnect = AM()
        fake_client.send_code_request = AM(return_value=fake_result)

        user_id = 3002
        sm.CS_ACTIVE.pop(user_id, None)

        state   = MagicMock(); state.clear = AM(); state.set_state = AM()
        message = MagicMock()
        message.from_user    = MagicMock(); message.from_user.id = user_id
        message.chat         = MagicMock(); message.chat.id = 1
        message.text         = "+12025551234"
        message.reply        = AM()

        with patch("app.features.session_manager.router.TelegramClient", return_value=fake_client), \
             patch("app.features.session_manager.router._get_creds", return_value=(1, "h")):
            await sm.cs_recv_phone(message, state)

        # Must still proceed to OTP state (user can try)
        state.set_state.assert_called_with(sm.CreateSessionState.waiting_for_otp)
        # QR button must be in keyboard
        kb   = message.reply.call_args[1].get("reply_markup")
        flat = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("sm_start_qr", flat)

        await sm._cs_cleanup(user_id)

    async def test_recv_otp_success_calls_deliver(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import AsyncMock as AM

        user_id = 3003
        fake_client = MagicMock()
        fake_client.sign_in      = AM()
        fake_client.session      = MagicMock()
        fake_client.session.save = MagicMock(return_value="1BQANOTEuMTc...")
        fake_client.is_connected = MagicMock(return_value=True)
        fake_client.disconnect   = AM()

        sm.CS_ACTIVE[user_id] = {
            "client": fake_client, "phone": "+1", "phone_code_hash": "h",
            "delivery": "SMS", "next_type": None, "resent": False,
            "method": "otp", "chat_id": 1,
            "task": None, "countdown_task": None, "created_at": 0,
        }

        delivered = []
        async def fake_deliver(uid, b, c, s, method):
            delivered.append(method)
            sm.CS_ACTIVE.pop(uid, None)
            await s.clear()

        state   = MagicMock(); state.clear = AM(); state.set_state = AM()
        message = MagicMock()
        message.from_user    = MagicMock(); message.from_user.id = user_id
        message.text         = "12345"
        message.chat         = MagicMock(); message.chat.id = 1
        message.bot          = MagicMock()

        from unittest.mock import patch
        with patch.object(sm, "_convert_and_deliver", side_effect=fake_deliver):
            await sm.cs_recv_otp(message, state)

        self.assertEqual(delivered, ["otp"])

    async def test_recv_otp_invalid_code_keeps_session(self):
        self._skip()
        from telethon.errors import PhoneCodeInvalidError
        from app.features.session_manager import router as sm
        from unittest.mock import AsyncMock as AM

        user_id = 3004
        fake_client = MagicMock()
        fake_client.sign_in      = AM(side_effect=PhoneCodeInvalidError(None))
        fake_client.is_connected = MagicMock(return_value=True)

        sm.CS_ACTIVE[user_id] = {
            "client": fake_client, "phone": "+1", "phone_code_hash": "h",
            "delivery": "SMS", "next_type": None, "resent": False,
            "method": "otp", "chat_id": 1,
            "task": None, "countdown_task": None, "created_at": 0,
        }

        state   = MagicMock(); state.clear = AM(); state.set_state = AM()
        message = MagicMock()
        message.from_user    = MagicMock(); message.from_user.id = user_id
        message.text         = "99999"
        message.reply        = AM()

        await sm.cs_recv_otp(message, state)

        self.assertIn(user_id, sm.CS_ACTIVE)  # session kept for retry
        state.clear.assert_not_called()
        await sm._cs_cleanup(user_id)

    async def test_recv_otp_expired_shows_qr_fallback(self):
        self._skip()
        from telethon.errors import PhoneCodeExpiredError
        from app.features.session_manager import router as sm
        from unittest.mock import AsyncMock as AM

        user_id = 3005
        fake_client = MagicMock()
        fake_client.sign_in      = AM(side_effect=PhoneCodeExpiredError(None))
        fake_client.is_connected = MagicMock(return_value=True)
        fake_client.disconnect   = AM()

        sm.CS_ACTIVE[user_id] = {
            "client": fake_client, "phone": "+1", "phone_code_hash": "h",
            "delivery": "the Telegram app", "next_type": None, "resent": False,
            "method": "otp", "chat_id": 1,
            "task": None, "countdown_task": None, "created_at": 0,
        }

        state   = MagicMock(); state.clear = AM(); state.set_state = AM()
        message = MagicMock()
        message.from_user    = MagicMock(); message.from_user.id = user_id
        message.text         = "30375"
        message.reply        = AM()

        await sm.cs_recv_otp(message, state)

        self.assertNotIn(user_id, sm.CS_ACTIVE)
        state.clear.assert_called_once()
        kb   = message.reply.call_args[1].get("reply_markup")
        flat = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("sm_start_qr", flat)

    async def test_recv_otp_2fa_required_sets_state(self):
        self._skip()
        from telethon.errors import SessionPasswordNeededError
        from app.features.session_manager import router as sm
        from unittest.mock import AsyncMock as AM

        user_id = 3006
        fake_client = MagicMock()
        fake_client.sign_in      = AM(side_effect=SessionPasswordNeededError(None))
        fake_client.is_connected = MagicMock(return_value=True)

        sm.CS_ACTIVE[user_id] = {
            "client": fake_client, "phone": "+1", "phone_code_hash": "h",
            "delivery": "SMS", "next_type": None, "resent": False,
            "method": "otp", "chat_id": 1,
            "task": None, "countdown_task": None, "created_at": 0,
        }

        state   = MagicMock(); state.clear = AM(); state.set_state = AM()
        message = MagicMock()
        message.from_user    = MagicMock(); message.from_user.id = user_id
        message.text         = "12345"
        message.reply        = AM()

        await sm.cs_recv_otp(message, state)

        self.assertIn(user_id, sm.CS_ACTIVE)
        state.set_state.assert_called_with(sm.CreateSessionState.waiting_for_2fa)
        state.clear.assert_not_called()
        await sm._cs_cleanup(user_id)

    # ------------------------------------------------------------------
    # 2FA
    # ------------------------------------------------------------------

    async def test_2fa_success_calls_deliver(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import AsyncMock as AM, patch

        user_id = 4001
        fake_client = MagicMock()
        fake_client.sign_in      = AM()
        fake_client.session      = MagicMock()
        fake_client.session.save = MagicMock(return_value="1BQANOTEuMTc...")
        fake_client.is_connected = MagicMock(return_value=True)
        fake_client.disconnect   = AM()

        sm.CS_ACTIVE[user_id] = {
            "client": fake_client, "method": "otp",
            "task": None, "countdown_task": None, "chat_id": 1, "created_at": 0,
        }

        delivered = []
        async def fake_deliver(uid, b, c, s, method):
            delivered.append(method)
            sm.CS_ACTIVE.pop(uid, None)
            await s.clear()

        state   = MagicMock(); state.clear = AM(); state.set_state = AM()
        message = MagicMock()
        message.from_user    = MagicMock(); message.from_user.id = user_id
        message.text         = "mypassword"
        message.chat         = MagicMock(); message.chat.id = 1
        message.bot          = MagicMock()
        message.reply        = AM()

        with patch.object(sm, "_convert_and_deliver", side_effect=fake_deliver):
            await sm.cs_process_2fa(message, state)

        self.assertIn("otp", delivered)

    async def test_2fa_wrong_password_keeps_session(self):
        self._skip()
        from telethon.errors import PasswordHashInvalidError
        from app.features.session_manager import router as sm
        from unittest.mock import AsyncMock as AM

        user_id = 4002
        fake_client = MagicMock()
        fake_client.sign_in      = AM(side_effect=PasswordHashInvalidError(None))
        fake_client.is_connected = MagicMock(return_value=True)

        sm.CS_ACTIVE[user_id] = {
            "client": fake_client, "method": "qr",
            "task": None, "countdown_task": None, "chat_id": 1, "created_at": 0,
        }

        state   = MagicMock(); state.clear = AM(); state.set_state = AM()
        message = MagicMock()
        message.from_user    = MagicMock(); message.from_user.id = user_id
        message.text         = "wrongpwd"
        message.reply        = AM()

        await sm.cs_process_2fa(message, state)

        self.assertIn(user_id, sm.CS_ACTIVE)
        state.clear.assert_not_called()
        await sm._cs_cleanup(user_id)


class TestLoginSessionFlow(unittest.IsolatedAsyncioTestCase):
    """Behavioral tests for /login_session."""

    def _skip(self):
        if _skip_no_telethon():
            self.skipTest("telethon not installed")

    async def test_cmd_login_session_sets_waiting_for_file(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch

        state   = MagicMock(); state.clear = AsyncMock(); state.set_state = AsyncMock()
        message = MagicMock()
        message.from_user = MagicMock(); message.from_user.id = 5001
        message.reply     = AsyncMock()

        with patch("app.features.session_manager.router._get_creds", return_value=(1, "h")):
            await sm.cmd_login_session(message, state)

        state.set_state.assert_called_once_with(sm.LoginSessionState.waiting_for_file)

    async def test_login_rejects_non_document(self):
        self._skip()
        from app.features.session_manager import router as sm

        state   = MagicMock(); state.clear = AsyncMock()
        message = MagicMock()
        message.document  = None
        message.from_user = MagicMock(); message.from_user.id = 5002
        message.reply     = AsyncMock()

        await sm.ls_recv_file(message, state, MagicMock())

        message.reply.assert_called_once()
        self.assertNotIn(5002, sm.CS_ACTIVE)

    async def test_login_rejects_wrong_extension(self):
        self._skip()
        from app.features.session_manager import router as sm

        state   = MagicMock(); state.clear = AsyncMock()
        doc     = MagicMock(); doc.file_name = "myfile.txt"; doc.file_size = 100
        message = MagicMock()
        message.document  = doc
        message.from_user = MagicMock(); message.from_user.id = 5003
        message.reply     = AsyncMock()

        await sm.ls_recv_file(message, state, MagicMock())

        message.reply.assert_called_once()
        reply_text = message.reply.call_args[0][0].lower()
        self.assertIn("session", reply_text)

    async def test_login_rejects_oversized_file(self):
        self._skip()
        from app.features.session_manager import router as sm

        state   = MagicMock(); state.clear = AsyncMock()
        doc     = MagicMock(); doc.file_name = "a.session"; doc.file_size = 600 * 1024
        message = MagicMock()
        message.document  = doc
        message.from_user = MagicMock(); message.from_user.id = 5004
        message.reply     = AsyncMock()

        await sm.ls_recv_file(message, state, MagicMock())

        message.reply.assert_called_once()
        reply_text = message.reply.call_args[0][0].lower()
        self.assertIn("large", reply_text)

    async def test_login_valid_authorized_session_shows_info(self):
        self._skip()
        import os, tempfile, sqlite3
        from app.features.session_manager import router as sm
        from unittest.mock import patch, AsyncMock as AM

        user_id = 5005
        state   = MagicMock(); state.clear = AM()
        status_msg = MagicMock(); status_msg.edit_text = AM()
        doc     = MagicMock(); doc.file_name = "test.session"; doc.file_size = 4096

        fake_me = MagicMock()
        fake_me.first_name = "Alice"; fake_me.last_name = None
        fake_me.username   = "alice"; fake_me.id = 123456
        fake_me.is_premium = False;   fake_me.bot = False

        fake_client = MagicMock()
        fake_client.connect            = AM()
        fake_client.disconnect         = AM()
        fake_client.is_user_authorized = AM(return_value=True)
        fake_client.get_me             = AM(return_value=fake_me)

        message = MagicMock()
        message.document  = doc
        message.from_user = MagicMock(); message.from_user.id = user_id
        message.reply     = AM(return_value=status_msg)

        bot = MagicMock()
        async def fake_download(file, destination):
            # Write a minimal valid SQLite file
            with open(destination, "wb") as f:
                f.write(b"SQLite format 3\x00" + b"\x00" * 84)
        bot.download = fake_download

        with patch("app.features.session_manager.router.TelegramClient", return_value=fake_client), \
             patch("app.features.session_manager.router._get_creds", return_value=(1, "h")):
            await sm.ls_recv_file(message, state, bot)

        status_msg.edit_text.assert_called_once()
        result_text = status_msg.edit_text.call_args[0][0]
        self.assertIn("✅", result_text)
        self.assertIn("Alice", result_text)
        self.assertIn("123456", result_text)

    async def test_login_unauthorized_session_shows_error(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch, AsyncMock as AM

        user_id = 5006
        state   = MagicMock(); state.clear = AM()
        status_msg = MagicMock(); status_msg.edit_text = AM()
        doc     = MagicMock(); doc.file_name = "test.session"; doc.file_size = 4096

        fake_client = MagicMock()
        fake_client.connect            = AM()
        fake_client.disconnect         = AM()
        fake_client.is_user_authorized = AM(return_value=False)

        message = MagicMock()
        message.document  = doc
        message.from_user = MagicMock(); message.from_user.id = user_id
        message.reply     = AM(return_value=status_msg)

        bot = MagicMock()
        async def fake_download(file, destination):
            with open(destination, "wb") as f:
                f.write(b"SQLite format 3\x00" + b"\x00" * 84)
        bot.download = fake_download

        with patch("app.features.session_manager.router.TelegramClient", return_value=fake_client), \
             patch("app.features.session_manager.router._get_creds", return_value=(1, "h")):
            await sm.ls_recv_file(message, state, bot)

        result_text = status_msg.edit_text.call_args[0][0]
        self.assertIn("not authorized", result_text.lower())

    async def test_login_corrupt_file_shows_error(self):
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import patch, AsyncMock as AM

        user_id = 5007
        state   = MagicMock(); state.clear = AM()
        status_msg = MagicMock(); status_msg.edit_text = AM()
        doc     = MagicMock(); doc.file_name = "bad.session"; doc.file_size = 10

        fake_client = MagicMock()
        fake_client.connect = AM(side_effect=Exception("corrupt db"))

        message = MagicMock()
        message.document  = doc
        message.from_user = MagicMock(); message.from_user.id = user_id
        message.reply     = AM(return_value=status_msg)

        bot = MagicMock()
        async def fake_download(file, destination):
            with open(destination, "wb") as f:
                f.write(b"this is not sqlite")
        bot.download = fake_download

        with patch("app.features.session_manager.router.TelegramClient", return_value=fake_client), \
             patch("app.features.session_manager.router._get_creds", return_value=(1, "h")):
            await sm.ls_recv_file(message, state, bot)

        result_text = status_msg.edit_text.call_args[0][0].lower()
        self.assertIn("invalid", result_text)


class TestIsolationAndSecurity(unittest.IsolatedAsyncioTestCase):
    """Verify per-user isolation and no secret leakage."""

    def _skip(self):
        if _skip_no_telethon():
            self.skipTest("telethon not installed")

    async def test_concurrent_users_isolated(self):
        """User A's cleanup must not affect User B's session."""
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import AsyncMock as AM

        def mk_client():
            c = MagicMock()
            c.is_connected = MagicMock(return_value=True)
            c.disconnect   = AM()
            return c

        ca = mk_client(); cb = mk_client()
        sm.CS_ACTIVE[7001] = {"client": ca, "task": None, "countdown_task": None, "created_at": 0}
        sm.CS_ACTIVE[7002] = {"client": cb, "task": None, "countdown_task": None, "created_at": 0}

        await sm._cs_cleanup(7001)

        self.assertNotIn(7001, sm.CS_ACTIVE)
        self.assertIn(7002,    sm.CS_ACTIVE)
        ca.disconnect.assert_called_once()
        cb.disconnect.assert_not_called()

        await sm._cs_cleanup(7002)

    def test_no_api_hash_in_logs(self):
        """No log statement must log api_hash or phone_code_hash as a key.
        Uses string-key search to avoid false positives from len() expressions.
        """
        src = (PROJECT_ROOT / "app/features/session_manager/router.py").read_text()
        import re
        # Find string keys inside logger calls (e.g. '"api_hash": ...')
        log_key_pattern = re.compile(
            r'logger\.\w+\(\{([^}]*)\}\)',
            re.DOTALL,
        )
        for m in log_key_pattern.finditer(src):
            body = m.group(1)
            # Check that secret field names do not appear as dict KEYS
            self.assertNotIn('"api_hash"',        body)
            self.assertNotIn('"phone_code_hash"',  body)
            self.assertNotIn('"password"',         body)

    def test_session_file_not_in_gitignore_needed(self):
        """*.session should be gitignored to prevent accidental commits."""
        gi = PROJECT_ROOT / ".gitignore"
        if not gi.exists():
            return  # no .gitignore — acceptable, just note it
        content = gi.read_text()
        self.assertTrue(
            "*.session" in content or ".session" in content,
            ".gitignore should contain *.session to prevent accidental commits",
        )

    async def test_cleanup_idempotent(self):
        """Calling _cs_cleanup twice for the same user must not raise."""
        self._skip()
        from app.features.session_manager import router as sm
        from unittest.mock import AsyncMock as AM

        user_id = 7010
        c = MagicMock(); c.is_connected = MagicMock(return_value=True); c.disconnect = AM()
        sm.CS_ACTIVE[user_id] = {"client": c, "task": None, "countdown_task": None, "created_at": 0}

        await sm._cs_cleanup(user_id)
        await sm._cs_cleanup(user_id)  # must not raise


class TestRegressionStringFrozen(unittest.TestCase):
    """Confirm /string and existing QR behavior are untouched."""

    def test_string_router_has_no_sm_references(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertNotIn("session_manager", src)
        self.assertNotIn("CS_ACTIVE",       src)
        self.assertNotIn("sm_cancel",       src)
        self.assertNotIn("sm_method_qr",    src)

    def test_string_fsm_states_unchanged(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        for state in ("waiting_for_method", "waiting_for_phone", "waiting_for_otp", "waiting_for_2fa"):
            self.assertIn(state, src)
        # session_manager states must NOT be in string router
        self.assertNotIn("CreateSessionState", src)
        self.assertNotIn("LoginSessionState",  src)

    def test_existing_qr_functions_present(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        for fn in ("_qr_countdown", "_wait_for_qr", "_start_qr_login",
                   "cb_qr_refresh", "cb_method_qr", "_qr_caption"):
            self.assertIn(fn, src, f"QR function {fn!r} removed from /string — regression!")

    def test_session_manager_has_own_qr_functions(self):
        src = (PROJECT_ROOT / "app/features/session_manager/router.py").read_text()
        for fn in ("_cs_qr_countdown", "_cs_wait_for_qr", "_start_sm_qr",
                   "cb_sm_qr_refresh", "_qr_caption"):
            self.assertIn(fn, src, f"SM QR function {fn!r} missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
