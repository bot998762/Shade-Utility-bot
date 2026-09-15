"""
Architecture & regression tests for Shade Utility Platform.
Tests that require third-party packages (aiogram, aiohttp, telethon)
are skipped when packages are unavailable in the test environment.
All pure-Python and AST-based checks run unconditionally.
"""

import ast
import sys
import os
import time
import asyncio
import unittest
import importlib
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def _try_import(name):
    try:
        return importlib.import_module(name), None
    except ImportError as exc:
        return None, str(exc)

# Probe availability
_aiogram, _no_aiogram = _try_import("aiogram")
_aiohttp, _no_aiohttp = _try_import("aiohttp")
_qrcode, _no_qrcode  = _try_import("qrcode")
_pydantic, _no_pydantic = _try_import("pydantic_settings")

needs_aiogram = unittest.skipIf(_no_aiogram, f"aiogram not installed: {_no_aiogram}")
needs_aiohttp = unittest.skipIf(_no_aiohttp, f"aiohttp not installed: {_no_aiohttp}")
needs_qrcode  = unittest.skipIf(_no_qrcode, f"qrcode not installed: {_no_qrcode}")
needs_pydantic = unittest.skipIf(_no_pydantic, f"pydantic_settings not installed: {_no_pydantic}")


# ───────────────────────────────────────────────────────────────
# PHASE 0 — SYNTAX VALIDATION (no deps)
# ───────────────────────────────────────────────────────────────
class TestSyntaxValidity(unittest.TestCase):
    """Every Python source file must parse without SyntaxError."""

    def test_no_syntax_errors(self):
        errors = []
        for path in PROJECT_ROOT.rglob("*.py"):
            if "backup" in str(path):
                continue
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                errors.append(f"{path.relative_to(PROJECT_ROOT)}: {exc}")
        self.assertEqual(errors, [], msg="Syntax errors:\n" + "\n".join(errors))


# ───────────────────────────────────────────────────────────────
# PHASE 1 — CIRCUIT BREAKER (pure python)
# ───────────────────────────────────────────────────────────────
class TestCircuitBreaker(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app.core.circuit_breaker import CircuitBreaker
        self.CB = CircuitBreaker

    async def test_closed_passes_through(self):
        cb = self.CB("t", failure_threshold=3)
        async def ok(): return "ok"
        self.assertEqual(await cb.call(ok), "ok")
        self.assertEqual(cb.state, "CLOSED")

    async def test_opens_after_threshold(self):
        cb = self.CB("t", failure_threshold=2)
        async def fail(): raise ValueError("boom")
        for _ in range(2):
            with self.assertRaises(ValueError):
                await cb.call(fail)
        self.assertEqual(cb.state, "OPEN")

    async def test_open_raises_circuit_open_error(self):
        from app.core.exceptions import CircuitOpenError
        cb = self.CB("t", failure_threshold=1)
        async def fail(): raise ValueError()
        with self.assertRaises(ValueError):
            await cb.call(fail)
        with self.assertRaises(CircuitOpenError):
            await cb.call(fail)

    async def test_half_open_recovery(self):
        cb = self.CB("t", failure_threshold=1, recovery_timeout=0)
        async def fail(): raise ValueError()
        with self.assertRaises(ValueError):
            await cb.call(fail)
        cb.last_failure_time = 0
        async def ok(): return "ok"
        result = await cb.call(ok)
        self.assertEqual(result, "ok")
        self.assertEqual(cb.state, "CLOSED")
        self.assertEqual(cb.failures, 0)


# ───────────────────────────────────────────────────────────────
# PHASE 2 — FAILOVER ENGINE (pure python)
# ───────────────────────────────────────────────────────────────
class TestProviderFailoverEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app.platform.failover import ProviderFailoverEngine
        from app.core.circuit_breaker import CircuitBreaker
        self.Engine = ProviderFailoverEngine
        self.CB = CircuitBreaker

    async def test_primary_succeeds(self):
        engine = self.Engine("test")
        p = MagicMock(); p.do = AsyncMock(return_value="primary")
        engine.register_provider(p, self.CB("p1"))
        self.assertEqual(await engine.execute("do"), "primary")

    async def test_failover_to_secondary(self):
        engine = self.Engine("test")
        p1 = MagicMock(); p1.do = AsyncMock(side_effect=Exception("down"))
        p2 = MagicMock(); p2.do = AsyncMock(return_value="secondary")
        engine.register_provider(p1, self.CB("p1"))
        engine.register_provider(p2, self.CB("p2"))
        self.assertEqual(await engine.execute("do"), "secondary")

    async def test_all_fail_raises(self):
        from app.core.exceptions import NoProvidersAvailableError
        engine = self.Engine("test")
        p = MagicMock(); p.do = AsyncMock(side_effect=Exception("down"))
        engine.register_provider(p, self.CB("p1"))
        with self.assertRaises(NoProvidersAvailableError):
            await engine.execute("do")


# ───────────────────────────────────────────────────────────────
# PHASE 3 — CAPABILITY REGISTRY (pure python)
# ───────────────────────────────────────────────────────────────
class TestCapabilityRegistry(unittest.TestCase):
    def setUp(self):
        from app.platform.capability import CapabilityRegistry, FeatureManifest
        self.registry = CapabilityRegistry()
        self.FM = FeatureManifest

    def test_register_and_query(self):
        self.registry.register(self.FM(name="X", version="1", category="c"))
        self.assertTrue(self.registry.is_enabled("X"))

    def test_toggle_disable(self):
        self.registry.register(self.FM(name="Y", version="1", category="c"))
        self.registry.toggle("Y", False)
        self.assertFalse(self.registry.is_enabled("Y"))

    def test_require_raises_when_disabled(self):
        from app.core.exceptions import FeatureDisabledError
        self.registry.register(self.FM(name="Z", version="1", category="c"))
        self.registry.toggle("Z", False)
        with self.assertRaises(FeatureDisabledError):
            self.registry.require("Z")

    def test_unknown_is_enabled(self):
        self.assertTrue(self.registry.is_enabled("NoSuchFeature"))

    def test_session_manifest_is_feature_manifest(self):
        """Regression: session manifest must not be SimpleNamespace (missing .enabled)."""
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "manifest":
                        if isinstance(node.value, ast.Call):
                            fn = node.value.func
                            n = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                            self.assertNotEqual(n, "SimpleNamespace",
                                "session manifest must not be SimpleNamespace")


# ───────────────────────────────────────────────────────────────
# PHASE 4 — FEATURE LOADER ISOLATION (needs aiogram)
# ───────────────────────────────────────────────────────────────
@needs_aiogram
class TestFeatureLoaderIsolation(unittest.TestCase):
    def test_broken_feature_skipped_others_loaded(self):
        import app.features as feat_pkg
        dp = MagicMock()
        from app.platform.capability import CapabilityRegistry
        registry = CapabilityRegistry()
        bad_mod = MagicMock(spec=[])  # no .manifest, no .router
        with patch.dict(sys.modules, {"app.features._bad.router": bad_mod}):
            with patch.object(feat_pkg, "FEATURE_MODULES", ["app.features._bad.router"]):
                feat_pkg.load_features(dp, registry)
        dp.include_router.assert_not_called()


# ───────────────────────────────────────────────────────────────
# PHASE 5 — HEALTH ENDPOINTS (needs aiohttp)
# ───────────────────────────────────────────────────────────────
@needs_aiohttp
class TestHealthEndpoints(unittest.IsolatedAsyncioTestCase):
    """
    Tests for the health / readiness endpoints in app.core.health.

    set_ready() stores LIVE object references (bot_task, http_session).
    readiness_handler() calls bot_task.done() and http_session.closed on
    every request, so mocks must reflect those live properties correctly.
    """

    def _make_live_task(self, done: bool = False) -> MagicMock:
        """Return a mock asyncio.Task whose .done() returns the given bool."""
        t = MagicMock()
        t.done.return_value = done
        return t

    def _make_live_session(self, closed: bool = False) -> MagicMock:
        """Return a mock aiohttp.ClientSession whose .closed returns the given bool."""
        s = MagicMock()
        s.closed = closed
        return s

    def _reset(self):
        """Reset _readiness to its initial not-ready state using the actual dict keys."""
        from app.core import health
        health._readiness.update({
            "ready": False,
            "bot_task": None,
            "http_session": None,
            "features_loaded": 0,
            "start_time": None,
            "degraded_features": [],
            "shutdown_reason": None,
        })
        return health

    async def test_liveness_always_200(self):
        h = self._reset()
        resp = await h.liveness_handler(MagicMock())
        self.assertEqual(resp.status, 200)

    async def test_readiness_503_before_startup(self):
        h = self._reset()
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 503)

    async def test_readiness_200_after_set_ready(self):
        h = self._reset()
        h.set_ready(
            bot_task=self._make_live_task(done=False),
            http_session=self._make_live_session(closed=False),
            features_loaded=5,
            degraded_features=[],
        )
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 200)

    async def test_readiness_503_when_bot_task_dead(self):
        h = self._reset()
        h.set_ready(
            bot_task=self._make_live_task(done=True),   # task has finished → unhealthy
            http_session=self._make_live_session(closed=False),
            features_loaded=5,
            degraded_features=[],
        )
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 503)

    async def test_degraded_status_with_failed_features(self):
        import json as _json
        h = self._reset()
        h.set_ready(
            bot_task=self._make_live_task(done=False),
            http_session=self._make_live_session(closed=False),
            features_loaded=4,
            degraded_features=["X"],
        )
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 200)
        body = _json.loads(resp.body)
        self.assertEqual(body["status"], "degraded")

    async def test_set_not_ready_returns_503(self):
        h = self._reset()
        h.set_ready(
            bot_task=self._make_live_task(done=False),
            http_session=self._make_live_session(closed=False),
            features_loaded=5,
            degraded_features=[],
        )
        h.set_not_ready("shutdown")
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 503)


# ───────────────────────────────────────────────────────────────
# PHASE 6 — ADMIN CHECK SECURITY (AST, no aiogram import)
# ───────────────────────────────────────────────────────────────
class TestAdminCheckAST(unittest.TestCase):
    """Verify fail-closed logic in admin router via AST without importing aiogram."""

    def _parse_admin(self):
        return ast.parse((PROJECT_ROOT / "app/features/admin/router.py").read_text())

    def test_admin_check_fails_closed_on_zero(self):
        """_is_admin must return False when ADMIN_ID == 0."""
        tree = self._parse_admin()
        src = ast.unparse(tree)
        # The function must NOT have a branch that returns True when ADMIN_ID == 0
        self.assertIn("ADMIN_ID == 0", src, "fail-closed guard not found")
        self.assertIn("return False", src, "fail-closed return False not found")

    def test_no_return_true_on_zero(self):
        """Ensure the branch for ADMIN_ID==0 returns False, not True."""
        tree = self._parse_admin()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_is_admin":
                fn_src = ast.unparse(node)
                # Should not contain pattern: if ... == 0: return True
                self.assertNotIn("== 0:\n        return True", fn_src)


# ───────────────────────────────────────────────────────────────
# PHASE 7 — SESSION FEATURE ARCHITECTURE (AST, no telethon)
# ───────────────────────────────────────────────────────────────
class TestSessionFeatureArchitecture(unittest.TestCase):
    def setUp(self):
        self.src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.tree = ast.parse(self.src)

    def test_otp_has_security_warning(self):
        """OTP is implemented but must carry an explicit security warning in source."""
        # send_code_request is now present (OTP implemented with user-facing warning)
        self.assertIn("send_code_request", self.src)
        # The security caveat must be documented in the source
        self.assertIn("security", self.src.lower())

    def test_no_phone_number_argument(self):
        """Phone number must not be a /string command argument."""
        # Find cmd_string handler and check its usage string
        self.assertNotIn("phone_number", self.src.split("api_hash")[1] if "api_hash" in self.src else "")

    def test_qr_login_used(self):
        self.assertIn("qr_login", self.src)

    def test_session_timeout_defined(self):
        self.assertIn("SESSION_TIMEOUT", self.src)

    def test_shutdown_hook_exported(self):
        self.assertIn("shutdown_all_sessions", self.src)

    def test_telethon_disconnected_in_cleanup(self):
        self.assertIn("disconnect", self.src)

    def test_session_string_not_in_logger(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr in ("info","error","warning","debug"):
                    call_src = ast.unparse(node)
                    self.assertNotIn("string_session", call_src,
                        f"string_session in log call at line {node.lineno}")

    def test_cleanup_handles_missing_user(self):
        """_cleanup_user_session must handle user not in dict gracefully."""
        self.assertIn("pop(user_id, None)", self.src)

    def test_state_cleared_on_all_paths(self):
        """state.clear() must appear to ensure FSM doesn't get stuck."""
        self.assertIn("state.clear()", self.src)


# ───────────────────────────────────────────────────────────────
# PHASE 8 — SHUTDOWN ORDER (AST)
# ───────────────────────────────────────────────────────────────
class TestShutdownOrderAST(unittest.TestCase):
    def _parse_bootstrap(self):
        src = (PROJECT_ROOT / "app/core/bootstrap.py").read_text()
        return src, ast.parse(src)

    def test_bot_task_cancelled_before_http_close(self):
        src, tree = self._parse_bootstrap()
        fn_src = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_shutdown":
                fn_src = ast.unparse(node)
                break
        self.assertIn("bot_task", fn_src, "on_shutdown must cancel the bot_task")
        self.assertIn("cancel()", fn_src, "on_shutdown must call bot_task.cancel()")

    def test_http_closed_in_separate_method(self):
        src, _ = self._parse_bootstrap()
        self.assertIn("_close_http_resources", src)

    def test_telethon_cleanup_called_in_shutdown(self):
        src, _ = self._parse_bootstrap()
        self.assertIn("shutdown_all_sessions", src)

    def test_set_not_ready_called_in_shutdown(self):
        src, _ = self._parse_bootstrap()
        self.assertIn("set_not_ready", src)


# ───────────────────────────────────────────────────────────────
# PHASE 9 — CRYPTO UTILITIES (pure python)
# ───────────────────────────────────────────────────────────────
class TestCryptoUtils(unittest.TestCase):
    def setUp(self):
        from app.utils import crypto
        self.c = crypto

    def test_uuid_format(self):
        import re
        self.assertRegex(self.c.gen_uuid(),
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

    def test_password_lengths(self):
        for n in (8, 16, 32, 64):
            self.assertEqual(len(self.c.gen_password(n)), n)

    def test_b64_roundtrip(self):
        s = "Hello, Shade Bot!"
        self.assertEqual(self.c.b64_decode(self.c.b64_encode(s)), s)

    def test_url_roundtrip(self):
        s = "hello world & foo=bar"
        self.assertEqual(self.c.url_decode(self.c.url_encode(s)), s)

    def test_hash_known_values(self):
        result = self.c.gen_hashes("test")
        md5, sha256, sha512, sha3_224, sha3_256, sha3_384, sha3_512, blake2b, blake2s = result
        # Existing algorithms — values must remain identical to the pre-Phase-2A baseline
        self.assertEqual(md5, "098f6bcd4621d373cade4e832627b4f6")
        self.assertEqual(len(sha256), 64)
        self.assertEqual(len(sha512), 128)

    def test_hash_returns_nine_values(self):
        """gen_hashes must return exactly 9 values (3 original + 4 SHA-3 + 2 BLAKE2)."""
        result = self.c.gen_hashes("test")
        self.assertEqual(len(result), 9)

    def test_sha3_224_known_vector(self):
        _, _, _, sha3_224, _, _, _, _, _ = self.c.gen_hashes("test")
        self.assertEqual(sha3_224, "3797bf0afbbfca4a7bbba7602a2b552746876517a7f9b7ce2db0ae7b")
        self.assertEqual(len(sha3_224), 56)

    def test_sha3_256_known_vector(self):
        _, _, _, _, sha3_256, _, _, _, _ = self.c.gen_hashes("test")
        self.assertEqual(sha3_256, "36f028580bb02cc8272a9a020f4200e346e276ae664e45ee80745574e2f5ab80")
        self.assertEqual(len(sha3_256), 64)

    def test_sha3_384_known_vector(self):
        _, _, _, _, _, sha3_384, _, _, _ = self.c.gen_hashes("test")
        self.assertEqual(sha3_384, "e516dabb23b6e30026863543282780a3ae0dccf05551cf0295178d7ff0f1b41eecb9db3ff219007c4e097260d58621bd")
        self.assertEqual(len(sha3_384), 96)

    def test_sha3_512_known_vector(self):
        _, _, _, _, _, _, sha3_512, _, _ = self.c.gen_hashes("test")
        self.assertEqual(sha3_512, "9ece086e9bac491fac5c1d1046ca11d737b92a2b2ebd93f005d7b710110c0a678288166e7fbe796883a4f2e9b3ca9f484f521d0ce464345cc1aec96779149c14")
        self.assertEqual(len(sha3_512), 128)

    def test_blake2b_known_vector(self):
        _, _, _, _, _, _, _, blake2b, _ = self.c.gen_hashes("test")
        self.assertEqual(blake2b, "a71079d42853dea26e453004338670a53814b78137ffbed07603a41d76a483aa9bc33b582f77d30a65e6f29a896c0411f38312e1d66e0bf16386c86a89bea572")
        self.assertEqual(len(blake2b), 128)

    def test_blake2s_known_vector(self):
        _, _, _, _, _, _, _, _, blake2s = self.c.gen_hashes("test")
        self.assertEqual(blake2s, "f308fc02ce9172ad02a7d75800ecfc027109bc67987ea32aba9b8dcc7b10150e")
        self.assertEqual(len(blake2s), 64)

    def test_hash_empty_string(self):
        """gen_hashes must handle empty string without exception."""
        import hashlib
        result = self.c.gen_hashes("")
        self.assertEqual(len(result), 9)
        # MD5 of empty string is a known constant
        self.assertEqual(result[0], "d41d8cd98f00b204e9800998ecf8427e")

    def test_hash_all_hex_output(self):
        """All 9 returned values must be valid lowercase hex strings."""
        import re
        for digest in self.c.gen_hashes("hello"):
            self.assertRegex(digest, r'^[0-9a-f]+$', f"Not valid hex: {digest}")

    def test_existing_md5_unchanged(self):
        """MD5 of 'test' must still be the exact pre-Phase-2A value."""
        md5 = self.c.gen_hashes("test")[0]
        self.assertEqual(md5, "098f6bcd4621d373cade4e832627b4f6")

    def test_existing_sha256_length_unchanged(self):
        """SHA-256 digest must still be 64 hex chars."""
        self.assertEqual(len(self.c.gen_hashes("test")[1]), 64)

    def test_existing_sha512_length_unchanged(self):
        """SHA-512 digest must still be 128 hex chars."""
        self.assertEqual(len(self.c.gen_hashes("test")[2]), 128)

    def test_strength_weak(self):
        self.assertIn("Weak", self.c.check_password_strength("abc"))

    def test_strength_strong(self):
        self.assertIn("Strong", self.c.check_password_strength("Str0ng!Pass#2024"))


# ───────────────────────────────────────────────────────────────
# PHASE 10 — QR UTILITY (needs qrcode+Pillow)
# ───────────────────────────────────────────────────────────────
@needs_qrcode
class TestQRUtility(unittest.TestCase):
    def test_generate_qr_returns_png(self):
        from app.utils.qr import generate_qr_buffer
        buf = generate_qr_buffer("https://example.com")
        data = buf.getvalue(); buf.close()
        self.assertEqual(data[:4], b"\x89PNG")


# ───────────────────────────────────────────────────────────────
# PHASE 10B — QR DataOverflowError handler (AST + unit)
# ───────────────────────────────────────────────────────────────
class TestQRDataOverflowHandling(unittest.TestCase):
    """Verify Phase 2B: DataOverflowError caught and surfaced as a user-friendly message."""

    def _get_cmd_qr_src(self) -> str:
        import ast
        src = open("app/features/media/router.py").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_qr":
                return ast.unparse(node)
        self.fail("cmd_qr handler not found in media/router.py")

    def test_dataoverflow_import_present(self):
        """QRDataOverflowError (qrcode.exceptions.DataOverflowError) must be imported."""
        src = open("app/features/media/router.py").read()
        self.assertIn(
            "DataOverflowError",
            src,
            "qrcode.exceptions.DataOverflowError must be imported in media/router.py",
        )

    def test_dataoverflow_caught_specifically(self):
        """cmd_qr must have an except clause for QRDataOverflowError, not bare Exception."""
        import ast
        src = open("app/features/media/router.py").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_qr":
                fn_src = ast.unparse(node)
                self.assertIn(
                    "QRDataOverflowError",
                    fn_src,
                    "cmd_qr must catch QRDataOverflowError by name",
                )
                return
        self.fail("cmd_qr not found")

    def test_dataoverflow_not_broad_except(self):
        """The DataOverflow handler must NOT use a bare except Exception in the generation block."""
        import ast, re
        cmd_src = self._get_cmd_qr_src()
        # The fix must be targeted: except QRDataOverflowError (or DataOverflowError)
        # A bare 'except Exception' swallowing all errors is forbidden
        # We verify generate_qr_buffer is NOT inside a bare except-Exception block
        # by checking the handler source for the pattern
        self.assertNotIn(
            "except Exception",
            cmd_src,
            "cmd_qr must not use bare 'except Exception' to catch DataOverflowError",
        )

    def test_dataoverflow_user_message_content(self):
        """The overflow error reply must mention shortening the input — no traceback in reply text."""
        import ast, re
        src = open("app/features/media/router.py").read()
        tree = ast.parse(src)
        reply_strings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_qr":
                # Extract string literals from all await message.reply() calls inside cmd_qr
                for call in ast.walk(node):
                    if (isinstance(call, ast.Call) and
                            isinstance(call.func, ast.Attribute) and
                            call.func.attr == "reply"):
                        for arg in call.args:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                reply_strings.append(arg.value)
        # The overflow reply must guide the user to shorten input
        overflow_replies = [s for s in reply_strings if "large" in s.lower() or "shorten" in s.lower()]
        self.assertTrue(
            len(overflow_replies) >= 1,
            "Overflow error reply must mention the data is too large or suggest shortening",
        )
        # None of the user-facing reply strings should expose a Python traceback
        for reply in reply_strings:
            self.assertNotIn("Traceback", reply, "Reply must not contain Python traceback")
            self.assertNotIn("File \"", reply, "Reply must not contain file paths from tracebacks")

    def test_dataoverflow_reply_uses_html_mode(self):
        """The overflow error reply must use parse_mode=HTML (consistent with handler)."""
        import ast
        cmd_src = self._get_cmd_qr_src()
        # Confirm the overflow reply branch uses HTML
        self.assertIn(
            'parse_mode=\'HTML\'',
            cmd_src,
            "Overflow error reply must use parse_mode='HTML'",
        )
        self.assertNotIn(
            'parse_mode=\'Markdown\'',
            cmd_src,
            "cmd_qr must not use Markdown parse mode anywhere",
        )

    def test_valid_path_still_uses_generate_qr_buffer(self):
        """The successful code path must still call qr.generate_qr_buffer()."""
        cmd_src = self._get_cmd_qr_src()
        self.assertIn(
            "qr.generate_qr_buffer(content)",
            cmd_src,
            "Valid path must still call qr.generate_qr_buffer(content)",
        )

    def test_finally_block_still_closes_bio(self):
        """The existing try/finally that closes bio must be preserved."""
        cmd_src = self._get_cmd_qr_src()
        self.assertIn("bio.close()", cmd_src, "bio.close() in finally block must be preserved")
        self.assertIn("finally", cmd_src, "finally block must be preserved")

    def test_unexpected_exception_not_swallowed(self):
        """Only QRDataOverflowError is caught — verified structurally via AST.

        The except clause in cmd_qr must name QRDataOverflowError explicitly.
        No bare 'except Exception' or 'except BaseException' exists in the generation
        block, which proves unexpected exceptions propagate to PlatformErrorMiddleware.
        """
        import ast
        src = open("app/features/media/router.py").read()
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_qr":
                # Collect all ExceptHandler nodes inside cmd_qr
                except_handlers = [
                    n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)
                ]
                self.assertGreater(len(except_handlers), 0, "cmd_qr has no except clause")

                for handler in except_handlers:
                    if handler.type is None:
                        self.fail("cmd_qr has a bare 'except:' — unexpected exceptions swallowed")
                    handler_type = ast.unparse(handler.type)
                    self.assertIn(
                        "DataOverflowError",
                        handler_type,
                        f"Unexpected except clause: 'except {handler_type}' — "
                        "only DataOverflowError should be caught in cmd_qr",
                    )
                return
        self.fail("cmd_qr not found in media/router.py")

    @needs_qrcode
    def test_dataoverflow_raised_for_oversized_input(self):
        """generate_qr_buffer must raise DataOverflowError for extremely large input."""
        from qrcode.exceptions import DataOverflowError
        from app.utils.qr import generate_qr_buffer
        # QR Version 40 max binary capacity ~2953 bytes; 10000 'A' chars will overflow
        oversized = "A" * 10000
        with self.assertRaises(DataOverflowError, msg="Oversized input must raise DataOverflowError"):
            generate_qr_buffer(oversized)



class TestSSRFGuardAST(unittest.TestCase):
    """Verify SSRF guard function logic via AST without importing aiogram."""

    def _get_fn_src(self):
        # Guard function was moved to app/utils/network.py (pure-Python, no framework deps)
        src = (PROJECT_ROOT / "app/utils/network.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "is_safe_host":
                return ast.unparse(node)
        return ""

    def test_guard_function_exists(self):
        fn = self._get_fn_src()
        self.assertTrue(bool(fn), "is_safe_host function not found in utils/network.py")

    def test_guards_private_addresses(self):
        # is_private is checked in _is_blocked_addr helper; verify it exists in the module
        full_src = (PROJECT_ROOT / "app/utils/network.py").read_text()
        self.assertIn("is_private", full_src, "SSRF guard must check is_private")
        self.assertIn("is_loopback", full_src, "SSRF guard must check is_loopback")

    def test_guards_link_local(self):
        full_src = (PROJECT_ROOT / "app/utils/network.py").read_text()
        self.assertIn("is_link_local", full_src, "SSRF guard must check is_link_local")

    def test_ip_api_uses_http_free_tier(self):
        # ip-api.com HTTPS requires a paid key; free tier must use http://
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        self.assertIn("http://ip-api.com", src,
            "ip-api.com free tier endpoint must use http://, not https://")


# ───────────────────────────────────────────────────────────────
# PHASE 12 — NO SHARED SESSION CREATION PER REQUEST (AST)
# ───────────────────────────────────────────────────────────────
class TestNoPerRequestSessions(unittest.TestCase):
    """ip and weather handlers must use shared session, not create new ones."""

    def _get_handler_src(self, handler_name: str) -> str:
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == handler_name:
                return ast.unparse(node)
        return ""

    def test_ip_handler_no_client_session_constructor(self):
        src = self._get_handler_src("cmd_ip")
        self.assertNotIn("ClientSession()", src,
            "cmd_ip must not create a new ClientSession per request")

    def test_weather_handler_no_client_session_constructor(self):
        src = self._get_handler_src("cmd_weather")
        self.assertNotIn("ClientSession()", src,
            "cmd_weather must not create a new ClientSession per request")

    def test_both_use_bootstrap_session(self):
        src = self._get_handler_src("cmd_ip")
        self.assertIn("bootstrap_ref", src)
        src2 = self._get_handler_src("cmd_weather")
        self.assertIn("bootstrap_ref", src2)


# ───────────────────────────────────────────────────────────────
# PHASE 13 — CONFIG VALIDATION (needs pydantic_settings)
# ───────────────────────────────────────────────────────────────
@needs_pydantic
class TestConfigValidation(unittest.TestCase):
    def test_empty_token_raises(self):
        from app.core.config import Settings
        with self.assertRaises(ValueError):
            Settings(BOT_TOKEN="").validate_startup()

    def test_valid_token_passes(self):
        from app.core.config import Settings
        Settings(BOT_TOKEN="123:ABC").validate_startup()


# ───────────────────────────────────────────────────────────────
# PHASE 14 — NO SECRETS IN LOG CALLS (AST, no deps)
# ───────────────────────────────────────────────────────────────
class TestNoSecretsInLogs(unittest.TestCase):
    # Only flag logging of SECRET VALUES, not config key names used as event identifiers.
    # Logging "OCR_API_KEY" as a key name in a diagnostic dict is intentional.
    SECRET_VARS = {"BOT_TOKEN", "API_HASH", "api_hash", "string_session"}
    LOG_METHODS = {"info", "error", "warning", "debug", "critical"}

    def test_no_secrets_in_log_calls(self):
        violations = []
        for py_file in PROJECT_ROOT.rglob("*.py"):
            if "backup" in str(py_file) or "tests/" in str(py_file):
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    method = fn.attr if isinstance(fn, ast.Attribute) else None
                    if method in self.LOG_METHODS:
                        call_src = ast.unparse(node)
                        for secret in self.SECRET_VARS:
                            if secret in call_src:
                                violations.append(
                                    f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                                    f"'{secret}' in {method}() call"
                                )
        self.assertEqual(violations, [], msg="\n".join(violations))


# ───────────────────────────────────────────────────────────────
# PHASE 15 — HEALTH ROUTES IN MAIN (AST)
# ───────────────────────────────────────────────────────────────
class TestHealthRoutesInMain(unittest.TestCase):
    def test_liveness_route_registered(self):
        src = (PROJECT_ROOT / "main.py").read_text()
        self.assertIn("/health/live", src)

    def test_readiness_route_registered(self):
        src = (PROJECT_ROOT / "main.py").read_text()
        self.assertIn("/health/ready", src)

    def test_backward_compat_health_route(self):
        src = (PROJECT_ROOT / "main.py").read_text()
        self.assertIn("/health", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
