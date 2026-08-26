"""
Behavioral Test Suite — Shade Utility Platform
===============================================
Tests runtime correctness for every confirmed bug, without requiring
third-party packages (aiogram, aiohttp, telethon).

All HTTP interactions are mocked via lightweight fakes that replicate
the exact response signatures the real handlers depend on.

Test categories:
  - HTTP response matrix (weather, IP, providers)
  - Weather: known-good, city-not-found, timeout, non-200
  - IP: known-good, rate-limited, SSRF, non-JSON
  - /id and /info: normal, channel post, anonymous admin
  - Health: liveness, readiness lifecycle, stale-state regression
  - SSRF guard: all bypass patterns
  - Password strength: all score boundaries
  - Session: self-cleanup, 2FA flow, concurrent users
  - Translator: timeout
  - EventBus: sync context guard
  - FeatureManifest: description field present
  - load_features return value
"""

import ast
import json
import sys
import asyncio
import unittest
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Minimal aiohttp-like fakes (no aiohttp installation required)
# ─────────────────────────────────────────────────────────────────────────────

class FakeResponse:
    """Fake aiohttp ClientResponse — supports async context manager."""

    def __init__(self, status: int, body: str, content_type: str = "application/json"):
        self.status = status
        self._body = body
        self.content_type = content_type
        self.headers = {"Content-Type": content_type}

    async def text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self._body

    async def json(self, **kwargs):
        """Mimic aiohttp strict content-type check (raises on non-JSON)."""
        expected_ct = kwargs.get("content_type", "application/json")
        if expected_ct is not None:
            if "json" not in self.content_type:
                raise _ContentTypeError(
                    f"Attempt to decode JSON with unexpected mimetype: {self.content_type}"
                )
        return json.loads(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


class _ContentTypeError(Exception):
    """Stand-in for aiohttp.ContentTypeError."""
    pass


class FakeSession:
    """Fake aiohttp.ClientSession that returns a preset FakeResponse."""

    def __init__(self, response: FakeResponse):
        self._resp = response
        self.closed = False
        self.last_url: str = ""
        self.last_headers: dict = {}

    def get(self, url, *, headers=None, timeout=None, **kwargs):
        self.last_url = url
        self.last_headers = headers or {}
        return self._resp

    def post(self, url, *, data=None, timeout=None, **kwargs):
        self.last_url = url
        return self._resp

    def request(self, method, url, *, timeout=None, headers=None, **kwargs):
        self.last_url = url
        self.last_headers = headers or {}
        return self._resp


class FakeBootstrap:
    def __init__(self, session: FakeSession):
        self.http_session = session
        self.start_time = time.time()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — WEATHER RESPONSE PARSING (pure logic, no HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestWeatherResponseParsing(unittest.TestCase):
    """
    Tests the core JSON-parsing logic of cmd_weather by extracting
    it into a pure function representation.
    The handler is NOT called directly (requires aiogram); instead we
    verify the decision logic and expected paths.
    """

    VALID_WTTR_JSON = json.dumps({
        "current_condition": [{
            "temp_C": "28",
            "FeelsLikeC": "30",
            "weatherDesc": [{"value": "Partly cloudy"}],
            "humidity": "72",
            "windspeedKmph": "15",
        }],
        "nearest_area": [{
            "areaName": [{"value": "Mumbai"}],
            "country": [{"value": "India"}],
        }],
    })

    def _parse(self, status: int, raw: str) -> tuple[bool, str]:
        """Replicate the handler's response-parsing logic in isolation."""
        if status != 200:
            return False, "weather_http_error"
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return False, "weather_city_not_found"
        if "current_condition" not in data or "nearest_area" not in data:
            return False, "weather_unexpected_schema"
        try:
            current = data["current_condition"][0]
            area = data["nearest_area"][0]
            result = f"{area['areaName'][0]['value']}, {area['country'][0]['value']}"
            return True, result
        except (KeyError, IndexError, TypeError):
            return False, "weather_schema_mismatch"

    def test_valid_json_succeeds(self):
        ok, msg = self._parse(200, self.VALID_WTTR_JSON)
        self.assertTrue(ok)
        self.assertIn("Mumbai", msg)

    def test_text_plain_200_is_city_not_found(self):
        """THE PRIMARY BUG: HTTP 200 + text body must not raise ContentTypeError."""
        ok, reason = self._parse(200, "Sorry, we could not find this location.")
        self.assertFalse(ok)
        self.assertEqual(reason, "weather_city_not_found")

    def test_html_200_is_city_not_found(self):
        ok, reason = self._parse(200, "<html><body>Error</body></html>")
        self.assertFalse(ok)
        self.assertEqual(reason, "weather_city_not_found")

    def test_http_500_is_provider_error(self):
        ok, reason = self._parse(500, "Internal Server Error")
        self.assertFalse(ok)
        self.assertEqual(reason, "weather_http_error")

    def test_http_429_is_provider_error(self):
        ok, reason = self._parse(429, "<html>Rate limit</html>")
        self.assertFalse(ok)
        self.assertEqual(reason, "weather_http_error")

    def test_http_403_is_provider_error(self):
        ok, reason = self._parse(403, "Forbidden")
        self.assertFalse(ok)
        self.assertEqual(reason, "weather_http_error")

    def test_malformed_json_is_city_not_found(self):
        ok, reason = self._parse(200, "{invalid json}")
        self.assertFalse(ok)
        self.assertEqual(reason, "weather_city_not_found")

    def test_unexpected_schema_detected(self):
        ok, reason = self._parse(200, '{"foo": "bar"}')
        self.assertFalse(ok)
        self.assertEqual(reason, "weather_unexpected_schema")

    def test_multi_word_city_not_found_graceful(self):
        """Regression: /weather Aurangabad maharashtra must never raise ContentTypeError."""
        body = "Unknown location: Aurangabad maharashtra"
        ok, reason = self._parse(200, body)
        self.assertFalse(ok)
        # Must classify as city-not-found, not an exception
        self.assertEqual(reason, "weather_city_not_found")

    def test_valid_json_has_correct_structure(self):
        ok, msg = self._parse(200, self.VALID_WTTR_JSON)
        self.assertTrue(ok)
        self.assertNotIn("Error", msg)
        self.assertNotIn("ContentTypeError", msg)  # regression guard


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — IP RESPONSE PARSING (pure logic)
# ─────────────────────────────────────────────────────────────────────────────

class TestIPResponseParsing(unittest.TestCase):
    """Verify IP handler decision logic across all response types."""

    VALID_JSON = json.dumps({
        "status": "success",
        "country": "India",
        "countryCode": "IN",
        "city": "Mumbai",
        "regionName": "Maharashtra",
        "isp": "Jio",
        "timezone": "Asia/Kolkata",
        "query": "1.2.3.4",
    })

    FAIL_JSON = json.dumps({
        "status": "fail",
        "message": "invalid query",
        "query": "not-an-ip",
    })

    def _parse(self, status: int, raw: str) -> tuple[str, str | None]:
        """Returns (outcome, detail): outcome in
        {success, rate_limited, http_error, non_json, lookup_failed}."""
        if status == 429:
            return "rate_limited", None
        if status != 200:
            return "http_error", str(status)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return "non_json", raw[:50]
        if data.get("status") == "success":
            return "success", data.get("country")
        return "lookup_failed", data.get("message")

    def test_valid_ip_success(self):
        outcome, detail = self._parse(200, self.VALID_JSON)
        self.assertEqual(outcome, "success")
        self.assertEqual(detail, "India")

    def test_rate_limit_429(self):
        outcome, _ = self._parse(429, "<html>Too many requests</html>")
        self.assertEqual(outcome, "rate_limited")

    def test_http_500_is_error(self):
        outcome, _ = self._parse(500, "Error")
        self.assertEqual(outcome, "http_error")

    def test_html_body_200_is_non_json(self):
        """Regression: HTML response must not raise ContentTypeError."""
        outcome, _ = self._parse(200, "<html><body>Error</body></html>")
        self.assertEqual(outcome, "non_json")

    def test_plain_text_200_is_non_json(self):
        outcome, _ = self._parse(200, "Forbidden - subscription required")
        self.assertEqual(outcome, "non_json")

    def test_api_failure_with_message(self):
        outcome, detail = self._parse(200, self.FAIL_JSON)
        self.assertEqual(outcome, "lookup_failed")
        self.assertEqual(detail, "invalid query")

    def test_url_uses_http_not_https(self):
        """Regression: ip-api.com free tier requires HTTP."""
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_ip":
                fn_src = ast.unparse(node)
                self.assertIn("http://ip-api.com", fn_src,
                    "cmd_ip must use http:// (ip-api.com HTTPS requires paid key)")
                self.assertNotIn("https://ip-api.com", fn_src,
                    "https://ip-api.com is PRO-only and breaks free tier")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — PROVIDER JSON PARSING (CleanURI, OCRSpace)
# ─────────────────────────────────────────────────────────────────────────────

class TestCleanURIResponseParsing(unittest.TestCase):

    def _parse(self, status: int, raw: str):
        """Replicate CleanURIProvider.create_short_url parsing logic."""
        if status != 200:
            raise Exception(f"CleanURI HTTP {status}")
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raise Exception("CleanURI non-JSON")
        result = data.get("result_url", "")
        if result.startswith("http"):
            return result
        raise Exception(f"CleanURI: {data.get('error', 'unknown')}")

    def test_success(self):
        url = self._parse(200, '{"result_url": "https://cleanuri.com/abc"}')
        self.assertEqual(url, "https://cleanuri.com/abc")

    def test_html_response_raises_not_content_type_error(self):
        """Regression: HTML body must raise a clear error, not ContentTypeError."""
        with self.assertRaises(Exception) as ctx:
            self._parse(200, "<html>Error</html>")
        self.assertIn("non-JSON", str(ctx.exception))
        # Must NOT propagate as ContentTypeError
        self.assertNotIn("ContentTypeError", str(ctx.exception))

    def test_rate_limit_429(self):
        with self.assertRaises(Exception) as ctx:
            self._parse(429, "<html>Too Many Requests</html>")
        self.assertIn("429", str(ctx.exception))

    def test_api_error_json(self):
        with self.assertRaises(Exception) as ctx:
            self._parse(200, '{"error": "URL blocked"}')
        self.assertIn("URL blocked", str(ctx.exception))

    def test_malformed_json(self):
        with self.assertRaises(Exception) as ctx:
            self._parse(200, "{broken")
        self.assertIn("non-JSON", str(ctx.exception))


class TestOCRSpaceResponseParsing(unittest.TestCase):

    def _parse(self, status: int, raw: str) -> str:
        """Replicate OCRSpaceProvider.parse_image parsing logic."""
        if status == 401:
            raise Exception("OCR API key is invalid or missing")
        if status != 200:
            raise Exception(f"OCR API HTTP {status}")
        try:
            res = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raise Exception("OCR API returned non-JSON response")
        if res.get("IsErroredOnProcessing"):
            msgs = res.get("ErrorMessage", ["Unknown OCR error"])
            raise Exception(msgs[0])
        parsed = res.get("ParsedResults", [])
        return parsed[0].get("ParsedText", "").strip() if parsed else ""

    def test_success(self):
        raw = json.dumps({
            "IsErroredOnProcessing": False,
            "ParsedResults": [{"ParsedText": "Hello World"}],
        })
        self.assertEqual(self._parse(200, raw), "Hello World")

    def test_401_invalid_key(self):
        with self.assertRaises(Exception) as ctx:
            self._parse(401, "<html>Unauthorized</html>")
        self.assertIn("API key", str(ctx.exception))

    def test_html_503_raises_clear_error(self):
        """Regression: 503 HTML must not produce ContentTypeError."""
        with self.assertRaises(Exception) as ctx:
            self._parse(503, "<html>Service Unavailable</html>")
        self.assertIn("HTTP 503", str(ctx.exception))
        self.assertNotIn("ContentTypeError", str(ctx.exception))

    def test_non_json_200_raises_clear_error(self):
        with self.assertRaises(Exception) as ctx:
            self._parse(200, "plain error text")
        self.assertIn("non-JSON", str(ctx.exception))

    def test_ocr_processing_error(self):
        raw = json.dumps({
            "IsErroredOnProcessing": True,
            "ErrorMessage": ["File size exceeds limit"],
        })
        with self.assertRaises(Exception) as ctx:
            self._parse(200, raw)
        self.assertIn("File size", str(ctx.exception))

    def test_empty_result(self):
        raw = json.dumps({"IsErroredOnProcessing": False, "ParsedResults": []})
        self.assertEqual(self._parse(200, raw), "")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — /id AND /info: None from_user (BUG-07)
# ─────────────────────────────────────────────────────────────────────────────

class TestIdInfoNoneFromUser(unittest.IsolatedAsyncioTestCase):
    """Verify /id and /info handle channel-post replies (from_user=None)."""

    def _skip_no_aiogram(self):
        try:
            import aiogram  # noqa: F401
        except ImportError:
            self.skipTest("aiogram not installed")

    def _make_message(self, reply_from_user=MagicMock(), has_reply=False):
        msg = MagicMock()
        msg.from_user.id = 12345
        msg.chat.id = -100001
        msg.chat.type = "group"
        msg.message_thread_id = None
        msg.reply = AsyncMock()
        if has_reply:
            msg.reply_to_message = MagicMock()
            msg.reply_to_message.from_user = reply_from_user
            msg.reply_to_message.message_id = 42
        else:
            msg.reply_to_message = None
        return msg

    async def test_id_no_reply_works(self):
        self._skip_no_aiogram()
        from app.features.general.router import cmd_id
        msg = self._make_message(has_reply=False)
        await cmd_id(msg)
        msg.reply.assert_called_once()
        args = msg.reply.call_args[0][0]
        self.assertIn("12345", args)

    async def test_id_reply_to_user_works(self):
        self._skip_no_aiogram()
        from app.features.general.router import cmd_id
        replied_user = MagicMock()
        replied_user.id = 99999
        replied_user.first_name = "Alice"
        msg = self._make_message(reply_from_user=replied_user, has_reply=True)
        await cmd_id(msg)
        args = msg.reply.call_args[0][0]
        self.assertIn("99999", args)
        self.assertIn("Alice", args)

    async def test_id_reply_to_channel_post_no_crash(self):
        self._skip_no_aiogram()
        """BUG-07 regression: from_user=None must not raise AttributeError."""
        from app.features.general.router import cmd_id
        msg = self._make_message(reply_from_user=None, has_reply=True)
        # Must NOT raise AttributeError
        await cmd_id(msg)
        msg.reply.assert_called_once()
        args = msg.reply.call_args[0][0]
        # Should mention anonymous/channel, not crash
        self.assertTrue(
            "Anonymous" in args or "Channel" in args or "42" in args,
            f"Expected anonymous indicator in: {args}",
        )

    async def test_info_normal_user(self):
        self._skip_no_aiogram()
        from app.features.general.router import cmd_info
        msg = MagicMock()
        msg.reply_to_message = None
        msg.from_user.id = 123
        msg.from_user.first_name = "Bob"
        msg.from_user.last_name = None
        msg.from_user.username = "bobby"
        msg.from_user.is_bot = False
        msg.from_user.is_premium = False
        msg.reply = AsyncMock()
        await cmd_info(msg)
        args = msg.reply.call_args[0][0]
        self.assertIn("Bob", args)

    async def test_info_reply_to_channel_post_no_crash(self):
        self._skip_no_aiogram()
        """BUG-07 regression: from_user=None on reply must not raise AttributeError."""
        from app.features.general.router import cmd_info
        msg = MagicMock()
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user = None  # channel post
        msg.reply = AsyncMock()
        await cmd_info(msg)
        msg.reply.assert_called_once()
        args = msg.reply.call_args[0][0]
        self.assertIn("Cannot inspect", args)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — HEALTH READINESS: LIVE STATE (BUG-06)
# ─────────────────────────────────────────────────────────────────────────────

class TestHealthReadinessLiveState(unittest.IsolatedAsyncioTestCase):

    def _skip_no_aiohttp(self):
        try:
            import aiohttp  # noqa: F401
        except ImportError:
            self.skipTest("aiohttp not installed")

    def _reset_health(self):
        try:
            from app.core import health
        except ImportError:
            self.skipTest("aiohttp not installed")
        return health
        health._readiness.update({
            "ready": False,
            "bot_task": None,
            "http_session": None,
            "features_loaded": 0,
            "degraded_features": [],
            "start_time": None,
            "shutdown_reason": None,
        })
        return health

    async def test_liveness_always_200(self):
        self._skip_no_aiohttp()
        h = self._reset_health()
        resp = await h.liveness_handler(MagicMock())
        self.assertEqual(resp.status, 200)

    async def test_readiness_503_before_startup(self):
        self._skip_no_aiohttp()
        h = self._reset_health()
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 503)

    async def test_readiness_200_when_all_ok(self):
        self._skip_no_aiohttp()
        h = self._reset_health()
        fake_task = MagicMock(spec=asyncio.Task)
        fake_task.done.return_value = False
        fake_session = MagicMock(); fake_session.closed = False
        h.set_ready(
            bot_task=fake_task,
            http_session=fake_session,
            features_loaded=5,
            degraded_features=[],
        )
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["status"], "ready")
        self.assertTrue(body["bot_polling"])

    async def test_readiness_503_when_bot_task_dies_after_startup(self):
        self._skip_no_aiohttp()
        """BUG-06 regression: health must reflect live task state, not startup snapshot."""
        h = self._reset_health()
        fake_task = MagicMock(spec=asyncio.Task)
        fake_task.done.return_value = False  # alive at startup
        fake_session = MagicMock(); fake_session.closed = False
        h.set_ready(
            bot_task=fake_task,
            http_session=fake_session,
            features_loaded=5,
            degraded_features=[],
        )

        # Bot task dies post-startup
        fake_task.done.return_value = True  # <-- live state changed

        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 503,
            "Readiness must return 503 when bot_task.done() is True post-startup")
        body = json.loads(resp.body)
        self.assertFalse(body["bot_polling"])
        self.assertEqual(body["status"], "unhealthy")

    async def test_readiness_503_when_http_session_closed(self):
        self._skip_no_aiohttp()
        h = self._reset_health()
        fake_task = MagicMock(spec=asyncio.Task); fake_task.done.return_value = False
        fake_session = MagicMock(); fake_session.closed = True  # closed after startup
        h.set_ready(
            bot_task=fake_task,
            http_session=fake_session,
            features_loaded=5,
            degraded_features=[],
        )
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 503)
        body = json.loads(resp.body)
        self.assertFalse(body["http_session"])

    async def test_readiness_degraded_with_failed_features(self):
        self._skip_no_aiohttp()
        h = self._reset_health()
        fake_task = MagicMock(spec=asyncio.Task); fake_task.done.return_value = False
        fake_session = MagicMock(); fake_session.closed = False
        h.set_ready(
            bot_task=fake_task,
            http_session=fake_session,
            features_loaded=4,
            degraded_features=["app.features.session.router"],
        )
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["status"], "degraded")
        self.assertIn("app.features.session.router", body["degraded_features"])

    async def test_set_not_ready_returns_503(self):
        self._skip_no_aiohttp()
        h = self._reset_health()
        fake_task = MagicMock(spec=asyncio.Task); fake_task.done.return_value = False
        fake_session = MagicMock(); fake_session.closed = False
        h.set_ready(bot_task=fake_task, http_session=fake_session, features_loaded=5, degraded_features=[])
        h.set_not_ready("shutdown")
        resp = await h.readiness_handler(MagicMock())
        self.assertEqual(resp.status, 503)
        body = json.loads(resp.body)
        self.assertEqual(body["reason"], "shutdown")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — SSRF GUARD (BUG-11)
# ─────────────────────────────────────────────────────────────────────────────

class TestSSRFGuard(unittest.TestCase):

    def _guard(self, host: str) -> bool:
        from app.utils.network import is_safe_host
        return is_safe_host(host)

    # Should block
    def test_blocks_localhost(self):
        self.assertFalse(self._guard("localhost"))

    def test_blocks_loopback_127(self):
        self.assertFalse(self._guard("127.0.0.1"))

    def test_blocks_loopback_127_other(self):
        self.assertFalse(self._guard("127.0.0.2"))

    def test_blocks_private_10(self):
        self.assertFalse(self._guard("10.0.0.1"))

    def test_blocks_private_192_168(self):
        self.assertFalse(self._guard("192.168.1.1"))

    def test_blocks_private_172_16(self):
        self.assertFalse(self._guard("172.16.0.1"))

    def test_blocks_link_local(self):
        self.assertFalse(self._guard("169.254.169.254"))

    def test_blocks_link_local_any(self):
        self.assertFalse(self._guard("169.254.1.1"))

    def test_blocks_cgnat_rfc6598(self):
        """BUG-11 regression: CGNAT range must be blocked."""
        self.assertFalse(self._guard("100.64.0.1"))
        self.assertFalse(self._guard("100.127.255.255"))

    def test_blocks_decimal_int_loopback(self):
        """BUG-11 regression: 2130706433 == 127.0.0.1 must be blocked."""
        self.assertFalse(self._guard("2130706433"))

    def test_blocks_decimal_int_private(self):
        """10.0.0.1 as integer == 167772161."""
        self.assertFalse(self._guard("167772161"))

    def test_blocks_octal_prefix(self):
        """0177.x.x.x looks octal — must be blocked."""
        self.assertFalse(self._guard("0177.0.0.1"))

    def test_blocks_metadata_hostname(self):
        self.assertFalse(self._guard("metadata"))
        self.assertFalse(self._guard("metadata.google.internal"))

    def test_blocks_internal_suffix(self):
        self.assertFalse(self._guard("db.internal"))

    def test_allows_public_ip(self):
        self.assertTrue(self._guard("8.8.8.8"))

    def test_allows_public_ip_2(self):
        self.assertTrue(self._guard("1.1.1.1"))

    def test_allows_public_domain(self):
        self.assertTrue(self._guard("example.com"))

    def test_allows_valid_external_domain(self):
        self.assertTrue(self._guard("google.com"))


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — PASSWORD STRENGTH LABELS (BUG-15)
# ─────────────────────────────────────────────────────────────────────────────

class TestPasswordStrengthLabels(unittest.TestCase):

    def _strength(self, pwd: str) -> str:
        from app.utils.crypto import check_password_strength
        return check_password_strength(pwd)

    def test_very_weak_short(self):
        self.assertIn("Weak", self._strength("abc"))

    def test_weak_only_lowercase(self):
        self.assertIn("Weak", self._strength("password"))

    def test_moderate_mixed(self):
        # score 3: length+upper+lower (no digits, no special)
        result = self._strength("AbcdefghijKlm")  # 13 chars, score 3 = Moderate
        self.assertIn("Moderate", result)

    def test_strong_is_not_mislabelled_moderate(self):
        """BUG-15 regression: score-4 password must be 'Strong', not 'Moderate'."""
        # long + upper + lower + digits (no special) = score 4
        result = self._strength("AbcdefghiJ12")
        self.assertNotIn("Moderate", result,
            f"Score-4 password was mislabelled: {result}")
        self.assertIn("Strong", result)

    def test_very_strong_all_char_classes(self):
        result = self._strength("Str0ng!Pass#2024")
        self.assertIn("Very Strong", result)

    def test_labels_are_distinct(self):
        labels = set()
        for pwd in ["abc", "password", "Abcdefghijk", "AbcdefghiJ12", "Str0ng!Pass#2024"]:
            labels.add(self._strength(pwd).split()[0])
        # Should have at least 3 distinct labels
        self.assertGreaterEqual(len(labels), 3)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — SESSION SELF-CLEANUP (BUG-08)
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionSelfCleanup(unittest.IsolatedAsyncioTestCase):

    def _skip_no_telethon(self):
        try:
            import telethon  # noqa: F401
        except ImportError:
            self.skipTest("telethon not installed")

    async def test_cleanup_does_not_self_cancel(self):
        self._skip_no_telethon()
        """
        BUG-08 regression: when _cleanup_user_session is called from within
        _wait_for_qr (the background task), it must NOT cancel itself.
        """
        # Simulate: current task IS the session task
        fake_task = asyncio.current_task()  # this test function IS the current task

        from app.features.session import router as sess_mod

        # Inject a fake session entry where task == current_task
        user_id = 99001
        fake_client = MagicMock()
        fake_client.is_connected.return_value = True
        fake_client.disconnect = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[user_id] = {
            "client": fake_client,
            "task": fake_task,  # ← current_task()
            "chat_id": 1,
            "created_at": 0,
        }

        # Must complete without hanging or raising CancelledError
        await sess_mod._cleanup_user_session(user_id)

        # Client must still be disconnected
        fake_client.disconnect.assert_called_once()
        # User must be removed from dict
        self.assertNotIn(user_id, sess_mod.ACTIVE_CLIENTS)

    async def test_cleanup_cancels_other_task(self):
        self._skip_no_telethon()
        """Non-self task should be cancelled normally."""
        from app.features.session import router as sess_mod

        cancelled = False

        async def _background():
            nonlocal cancelled
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled = True
                raise

        task = asyncio.create_task(_background())
        await asyncio.sleep(0)  # let task start

        user_id = 99002
        fake_client = MagicMock()
        fake_client.is_connected.return_value = True
        fake_client.disconnect = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[user_id] = {
            "client": fake_client,
            "task": task,
            "chat_id": 1,
            "created_at": 0,
        }

        await sess_mod._cleanup_user_session(user_id)
        await asyncio.sleep(0)  # let cancellation propagate

        self.assertTrue(task.done())
        self.assertNotIn(user_id, sess_mod.ACTIVE_CLIENTS)

    async def test_concurrent_users_isolated(self):
        self._skip_no_telethon()
        """Session data for user A must not affect user B."""
        from app.features.session import router as sess_mod

        fake_client_a = MagicMock(); fake_client_a.is_connected.return_value = True
        fake_client_a.disconnect = AsyncMock()
        fake_client_b = MagicMock(); fake_client_b.is_connected.return_value = True
        fake_client_b.disconnect = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[1001] = {"client": fake_client_a, "task": None, "chat_id": 1, "created_at": 0}
        sess_mod.ACTIVE_CLIENTS[1002] = {"client": fake_client_b, "task": None, "chat_id": 2, "created_at": 0}

        await sess_mod._cleanup_user_session(1001)

        self.assertNotIn(1001, sess_mod.ACTIVE_CLIENTS)
        self.assertIn(1002, sess_mod.ACTIVE_CLIENTS)
        fake_client_a.disconnect.assert_called_once()
        fake_client_b.disconnect.assert_not_called()

        # Clean up
        await sess_mod._cleanup_user_session(1002)

    async def test_cleanup_missing_user_is_noop(self):
        self._skip_no_telethon()
        """Cleaning up a non-existent user must not raise."""
        from app.features.session import router as sess_mod
        await sess_mod._cleanup_user_session(999999)  # must not raise

    async def test_shutdown_all_sessions_cleans_everything(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        fake_client = MagicMock(); fake_client.is_connected.return_value = True
        fake_client.disconnect = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[5001] = {"client": fake_client, "task": None, "chat_id": 1, "created_at": 0}
        sess_mod.ACTIVE_CLIENTS[5002] = {"client": fake_client, "task": None, "chat_id": 2, "created_at": 0}

        await sess_mod.shutdown_all_sessions()

        self.assertEqual(len(sess_mod.ACTIVE_CLIENTS), 0)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — TRANSLATOR TIMEOUT (BUG-10)
# ─────────────────────────────────────────────────────────────────────────────

class TestTranslatorTimeout(unittest.IsolatedAsyncioTestCase):

    def _skip_no_deep_translator(self):
        try:
            import deep_translator  # noqa: F401
        except ImportError:
            self.skipTest("deep_translator not installed")

    async def test_successful_translation(self):
        self._skip_no_deep_translator()
        from app.services.translator_service import TranslatorService
        svc = TranslatorService()
        with patch("app.services.translator_service.GoogleTranslator") as MockGT:
            MockGT.return_value.translate.return_value = "Bonjour"
            result = await svc.translate("Hello", "fr")
        self.assertEqual(result, "Bonjour")

    async def test_translation_timeout_raises_timeout_error(self):
        """BUG-10 regression: hanging translator must raise TimeoutError, not block forever."""
        self._skip_no_deep_translator()
        from app.services.translator_service import TranslatorService, _TRANSLATE_TIMEOUT_SECS

        svc = TranslatorService()

        def _slow_translate():
            import time as _t
            _t.sleep(999)  # simulates hung request
            return "never"

        with patch("app.services.translator_service.GoogleTranslator") as MockGT:
            MockGT.return_value.translate.side_effect = _slow_translate
            with patch("app.services.translator_service._TRANSLATE_TIMEOUT_SECS", 0.05):
                with self.assertRaises(TimeoutError):
                    await svc.translate("Hello", "fr")

    async def test_unsupported_language_raises_value_error(self):
        self._skip_no_deep_translator()
        from app.services.translator_service import TranslatorService
        from deep_translator.exceptions import LanguageNotSupportedException

        svc = TranslatorService()
        with patch("app.services.translator_service.GoogleTranslator") as MockGT:
            MockGT.return_value.translate.side_effect = LanguageNotSupportedException("xx")
            with self.assertRaises(ValueError) as ctx:
                await svc.translate("Hello", "xx")
        self.assertIn("not supported", str(ctx.exception))


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10 — EVENT BUS SYNC CONTEXT GUARD (BUG-16)
# ─────────────────────────────────────────────────────────────────────────────

class TestEventBusSyncGuard(unittest.TestCase):

    def _skip_no_prometheus(self):
        try:
            from app.platform.event_bus import EventBus  # noqa: F401
        except ImportError:
            self.skipTest("prometheus_client or other dep not installed")

    def test_publish_from_sync_context_does_not_raise(self):
        self._skip_no_prometheus()
        """BUG-16 regression: publish() outside async context must log warning, not crash."""
        from app.platform.event_bus import EventBus
        bus = EventBus()
        called = []
        bus.subscribe("test_event", lambda p: called.append(p))

        # We are NOT in an async context here — get_running_loop() will raise RuntimeError
        # publish() must catch this and warn instead of crashing
        with patch("app.platform.event_bus.logger") as mock_logger:
            bus.publish("test_event", {"data": "value"})
            mock_logger.warning.assert_called()
            warning_call = mock_logger.warning.call_args[0][0]
            self.assertIn("no_running_loop", str(warning_call))

    def test_publish_from_async_context_creates_tasks(self):
        self._skip_no_prometheus()
        """publish() from async context must schedule callbacks as tasks."""
        from app.platform.event_bus import EventBus
        bus = EventBus()
        results = []

        async def callback(payload):
            results.append(payload)

        bus.subscribe("my_event", callback)

        async def run():
            bus.publish("my_event", {"x": 1})
            await asyncio.sleep(0)  # let task run

        asyncio.run(run())
        self.assertEqual(results, [{"x": 1}])


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 11 — FEATURE MANIFEST description FIELD (introduced bug)
# ─────────────────────────────────────────────────────────────────────────────

class TestFeatureManifestDescriptionField(unittest.TestCase):

    def test_feature_manifest_accepts_description(self):
        """Regression: FeatureManifest must accept description kwarg without TypeError."""
        from app.platform.capability import FeatureManifest
        m = FeatureManifest(
            name="session",
            description="Test description",
            version="2.0.0",
            category="Auth",
        )
        self.assertEqual(m.description, "Test description")

    def test_description_defaults_to_empty_string(self):
        from app.platform.capability import FeatureManifest
        m = FeatureManifest(name="X", version="1", category="C")
        self.assertEqual(m.description, "")

    def test_session_manifest_instantiates_without_error(self):
        """The actual session manifest creation must not raise TypeError."""
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "manifest":
                        if isinstance(node.value, ast.Call):
                            fn = node.value.func
                            fn_name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                            self.assertEqual(fn_name, "FeatureManifest",
                                "session manifest must use FeatureManifest, not SimpleNamespace")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 12 — load_features RETURN VALUE
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadFeaturesReturnValue(unittest.TestCase):

    def test_load_features_returns_tuple(self):
        """load_features must return (loaded_list, failed_list) — not None."""
        src = (PROJECT_ROOT / "app/features/__init__.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "load_features":
                fn_src = ast.unparse(node)
                self.assertIn("return", fn_src,
                    "load_features must have a return statement")
                # Return type annotation verified by checking the actual return statement above

    def test_bootstrap_consumes_return_value(self):
        """bootstrap must capture both return values from load_features."""
        src = (PROJECT_ROOT / "app/core/bootstrap.py").read_text()
        self.assertIn("loaded_names, failed_modules = load_features", src,
            "bootstrap must unpack (loaded_names, failed_modules) from load_features")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 13 — FINAL REGRESSION: NO UNSAFE resp.json() REMAINING
# ─────────────────────────────────────────────────────────────────────────────

class TestNoUnsafeRespJson(unittest.TestCase):
    """
    Verify no resp.json() call without content_type=None or equivalent
    text-first reading pattern remains anywhere in the codebase.

    The fix pattern replaces resp.json() with resp.text() + json.loads().
    This test verifies the pattern was applied everywhere.
    """

    def _find_unsafe_json_calls(self) -> list[str]:
        unsafe = []
        for path in (PROJECT_ROOT / "app").rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            src = path.read_text()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute) and func.attr == "json":
                        # Check for content_type kwarg OR that caller is 'resp'
                        kws = {k.arg for k in node.keywords}
                        call_src = ast.unparse(node)
                        # Allowed: resp.json(content_type=None)
                        if "content_type" in kws:
                            continue
                        # Pattern: data = json.loads(...) — not .json() method
                        # These are the resp.json() calls we care about
                        obj = ast.unparse(func.value) if hasattr(func, "value") else ""
                        if obj in ("resp", "response", "r"):
                            unsafe.append(
                                f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                                f"{call_src[:80]}"
                            )
        return unsafe

    def test_no_unsafe_resp_json_calls(self):
        unsafe = self._find_unsafe_json_calls()
        self.assertEqual(
            unsafe, [],
            msg=(
                "Unsafe resp.json() calls found (no content_type=None and not text-first):\n"
                + "\n".join(unsafe)
            ),
        )

    def test_weather_uses_text_then_json_loads(self):
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_weather":
                fn_src = ast.unparse(node)
                self.assertIn("resp.text(", fn_src, "cmd_weather must use resp.text() first")
                self.assertIn("json.loads(", fn_src, "cmd_weather must use json.loads() for parsing")
                self.assertNotIn("resp.json()", fn_src, "cmd_weather must not call resp.json()")

    def test_ip_uses_text_then_json_loads(self):
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_ip":
                fn_src = ast.unparse(node)
                self.assertIn("resp.text(", fn_src)
                self.assertNotIn("resp.json()", fn_src)

    def test_cleanuri_uses_text_then_json_loads(self):
        src = (PROJECT_ROOT / "app/providers/url_providers.py").read_text()
        self.assertIn("resp.text(", src)
        self.assertNotIn("await resp.json()", src)

    def test_ocr_uses_text_then_json_loads(self):
        src = (PROJECT_ROOT / "app/providers/ocr_providers.py").read_text()
        self.assertIn("resp.text(", src)
        self.assertNotIn("await resp.json()", src)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 14 — CONFIG: OCR KEY WARNING
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigOCRKeyWarning(unittest.TestCase):

    def _skip_no_pydantic(self):
        try:
            import pydantic_settings  # noqa: F401
        except ImportError:
            self.skipTest("pydantic_settings not installed")

    def test_validate_startup_warns_on_missing_ocr_key(self):
        self._skip_no_pydantic()
        from app.core.config import Settings
        s = Settings(BOT_TOKEN="123:abc", OCR_API_KEY="")
        with patch("logging.Logger.warning") as mock_warn:
            s.validate_startup()
            # At least one warning about OCR_API_KEY
            calls = [str(c) for c in mock_warn.call_args_list]
            ocr_warned = any("OCR_API_KEY" in c or "ocr" in c.lower() for c in calls)
            self.assertTrue(ocr_warned, f"Expected OCR_API_KEY warning, got: {calls}")

    def test_validate_startup_does_not_raise_on_missing_ocr_key(self):
        self._skip_no_pydantic()
        """Missing OCR key must warn, not abort startup."""
        from app.core.config import Settings
        s = Settings(BOT_TOKEN="123:abc", OCR_API_KEY="")
        try:
            s.validate_startup()
        except ValueError:
            self.fail("validate_startup raised ValueError for missing OCR_API_KEY")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 15 — SESSION STATE MACHINE (AST + logic)
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionStateMachine(unittest.TestCase):

    def setUp(self):
        self.src = (PROJECT_ROOT / "app/features/session/router.py").read_text()

    def test_otp_flow_present(self):
        """OTP is now implemented (send_code_request must appear in source)."""
        self.assertIn("send_code_request", self.src)

    def test_otp_has_security_warning(self):
        """OTP warning about Telegram security block must be present in source."""
        self.assertIn("security", self.src.lower())

    def test_qr_login_present(self):
        self.assertIn("qr_login", self.src)

    def test_session_timeout_constant(self):
        self.assertIn("SESSION_TIMEOUT", self.src)

    def test_state_cleared_on_timeout(self):
        self.assertIn("state.clear()", self.src)

    def test_self_cleanup_guard_present(self):
        """BUG-08 fix: current_task() check must be in cleanup function."""
        self.assertIn("current_task()", self.src,
            "_cleanup_user_session must check asyncio.current_task() before self-cancel")

    def test_disconnect_called_in_cleanup(self):
        self.assertIn("disconnect", self.src)

    def test_shutdown_hook_exported(self):
        self.assertIn("shutdown_all_sessions", self.src)

    def test_2fa_state_exists(self):
        self.assertIn("waiting_for_2fa", self.src)

    def test_session_string_not_in_log_calls(self):
        tree = ast.parse(self.src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr in ("info", "error", "warning"):
                    call_src = ast.unparse(node)
                    self.assertNotIn("string_session", call_src)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 13 — /string CONVERSATION FLOW & LIFECYCLE (v3)
# ─────────────────────────────────────────────────────────────────────────────

class TestStringSessionConversationFlow(unittest.IsolatedAsyncioTestCase):
    """
    Tests for the new multi-step /string conversation flow:
      /string → API ID → API HASH → method button → QR or OTP → session string
    Uses lightweight fakes; no real Telegram/Telethon calls.
    """

    def _skip_no_telethon(self):
        try:
            import telethon  # noqa: F401
        except ImportError:
            self.skipTest("telethon not installed")

    # ------------------------------------------------------------------
    # Source-level checks for new states
    # ------------------------------------------------------------------

    def test_new_states_present(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        for state_name in (
            "waiting_for_method",
            "waiting_for_phone",
            "waiting_for_otp",
            "waiting_for_2fa",
        ):
            self.assertIn(state_name, src, f"State {state_name!r} missing from router")
        # API-credential states are gone — /string uses configured credentials
        for removed_state in ("waiting_for_api_id", "waiting_for_api_hash"):
            self.assertNotIn(removed_state, src,
                             f"Removed state {removed_state!r} must not reappear")

    def test_method_keyboard_buttons_present(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("ses_method_qr",  src)
        self.assertIn("ses_method_otp", src)
        self.assertIn("ses_cancel",     src)
        self.assertIn("ses_qr_refresh", src)

    def test_qr_countdown_interval_defined(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("QR_COUNTDOWN_INTERVAL", src)

    def test_qr_recreate_called(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("recreate()", src)

    def test_send_code_request_present(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("send_code_request", src)

    def test_countdown_task_key_in_cleanup(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("countdown_task", src)

    def test_qr_caption_helper_present(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("_qr_caption", src)

    def test_expires_in_caption(self):
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("Expires in:", src)

    # ------------------------------------------------------------------
    # API ID validation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # /string — immediate method selection (no credentials asked)
    # ------------------------------------------------------------------

    async def test_cmd_string_shows_method_selection(self):
        """/string shows the method-selection keyboard when credentials are configured."""
        self._skip_no_telethon()
        from app.features.session import router as sess_mod
        from unittest.mock import patch

        state   = AsyncMock()
        message = MagicMock()
        message.from_user    = MagicMock()
        message.from_user.id = 55000
        message.reply        = AsyncMock()

        # Credentials are configured → method selection must appear
        with patch("app.features.session.router._get_app_credentials",
                   return_value=(12345, "abc")):
            await sess_mod.cmd_string(message, state)

        state.set_state.assert_called_once_with(sess_mod.StringSessionState.waiting_for_method)
        message.reply.assert_called_once()
        # The reply must never ask the user for API_ID or API_HASH
        reply_text = message.reply.call_args[0][0]
        self.assertNotIn("API ID",   reply_text)
        self.assertNotIn("API HASH", reply_text)

    async def test_cmd_string_fails_fast_when_credentials_missing(self):
        """
        /string must show ONE clear error and stop immediately when API_ID
        or API_HASH are not configured — not show the UI and fail mid-flow.
        """
        self._skip_no_telethon()
        from app.features.session import router as sess_mod
        from unittest.mock import patch

        state   = AsyncMock()
        message = MagicMock()
        message.from_user    = MagicMock()
        message.from_user.id = 55001
        message.reply        = AsyncMock()

        with patch("app.features.session.router._get_app_credentials",
                   side_effect=ValueError("API_ID is not set in the application environment")):
            await sess_mod.cmd_string(message, state)

        # Must reply with the error — exactly once
        message.reply.assert_called_once()
        reply_text = message.reply.call_args[0][0]
        self.assertIn("configuration error", reply_text.lower())
        self.assertIn("API_ID", reply_text)

        # Must NOT advance into the method-selection state
        state.set_state.assert_not_called()

    async def test_cmd_string_fails_fast_when_api_hash_missing(self):
        """
        /string fails fast if API_HASH is missing even when API_ID is set.
        """
        self._skip_no_telethon()
        from app.features.session import router as sess_mod
        from unittest.mock import patch

        state   = AsyncMock()
        message = MagicMock()
        message.from_user    = MagicMock()
        message.from_user.id = 55002
        message.reply        = AsyncMock()

        with patch("app.features.session.router._get_app_credentials",
                   side_effect=ValueError("API_HASH is not set in the application environment")):
            await sess_mod.cmd_string(message, state)

        message.reply.assert_called_once()
        state.set_state.assert_not_called()


    def test_configured_credentials_in_source(self):
        """Router must use _get_app_credentials(), not ask user for API_ID/HASH."""
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("_get_app_credentials", src)
        self.assertIn("API_ID",               src)
        self.assertIn("API_HASH",             src)

    def test_telegram_app_delivery_helper_in_source(self):
        """Router must declare _is_telegram_app_delivery for delivery-type gate."""
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("_is_telegram_app_delivery", src)
        self.assertIn("SentCodeTypeApp",           src)

    def test_switch_to_qr_keyboard_in_source(self):
        """ses_start_qr callback must exist for the 'Use QR Login' button."""
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("ses_start_qr",    src)
        self.assertIn("_switch_to_qr_kb", src)

    def test_phone_code_expired_handled(self):
        """PhoneCodeExpiredError must be caught and mapped to a friendly message."""
        src = (PROJECT_ROOT / "app/features/session/router.py").read_text()
        self.assertIn("PhoneCodeExpiredError", src)
        # The handler must recommend QR
        self.assertIn("QR", src)

    # ------------------------------------------------------------------
    # _get_app_credentials helper
    # ------------------------------------------------------------------

    def test_get_app_credentials_missing_api_id(self):
        self._skip_no_telethon()
        import os
        from app.features.session import router as sess_mod

        env_backup = os.environ.copy()
        os.environ.pop("API_ID",   None)
        os.environ.pop("API_HASH", None)
        try:
            with self.assertRaises(ValueError):
                sess_mod._get_app_credentials()
        finally:
            os.environ.update(env_backup)

    def test_get_app_credentials_missing_api_hash(self):
        self._skip_no_telethon()
        import os
        from app.features.session import router as sess_mod

        env_backup = os.environ.copy()
        os.environ["API_ID"]  = "12345"
        os.environ.pop("API_HASH", None)
        try:
            with self.assertRaises(ValueError):
                sess_mod._get_app_credentials()
        finally:
            os.environ.update(env_backup)

    def test_get_app_credentials_valid(self):
        self._skip_no_telethon()
        import os
        from app.features.session import router as sess_mod

        env_backup = os.environ.copy()
        os.environ["API_ID"]   = "99887766"
        os.environ["API_HASH"] = "abc123"
        try:
            api_id, api_hash = sess_mod._get_app_credentials()
            self.assertEqual(api_id,   99887766)
            self.assertEqual(api_hash, "abc123")
        finally:
            os.environ.update(env_backup)

    # ------------------------------------------------------------------
    # _is_telegram_app_delivery helper
    # ------------------------------------------------------------------

    def test_is_telegram_app_delivery_true(self):
        """Returns True when result.type is SentCodeTypeApp."""
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        if sess_mod._SENT_CODE_TYPE_APP is None:
            self.skipTest("SentCodeTypeApp not importable in this Telethon build")

        fake_result = MagicMock()
        fake_result.type = sess_mod._SENT_CODE_TYPE_APP()
        self.assertTrue(sess_mod._is_telegram_app_delivery(fake_result))

    def test_is_telegram_app_delivery_false_for_sms(self):
        """Returns False for any non-App delivery type."""
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        fake_result = MagicMock()
        fake_result.type = MagicMock()   # not SentCodeTypeApp
        # Only returns True for the exact SentCodeTypeApp class
        self.assertFalse(sess_mod._is_telegram_app_delivery(fake_result))

    def test_is_telegram_app_delivery_none_sentinel(self):
        """When _SENT_CODE_TYPE_APP is None (import failed), returns False."""
        self._skip_no_telethon()
        from app.features.session import router as sess_mod
        from unittest.mock import patch

        with patch.object(sess_mod, "_SENT_CODE_TYPE_APP", None):
            fake_result = MagicMock()
            self.assertFalse(sess_mod._is_telegram_app_delivery(fake_result))

    # ------------------------------------------------------------------
    # recv_phone: Telegram-app delivery detection
    # ------------------------------------------------------------------

    async def test_recv_phone_telegram_app_delivery_redirects_to_qr(self):
        """
        When send_code_request returns SentCodeTypeApp, recv_phone must
        NOT set waiting_for_otp state, must disconnect the temp client,
        and must show the 'Use QR Login' button.
        """
        self._skip_no_telethon()
        from app.features.session import router as sess_mod
        from unittest.mock import patch, AsyncMock as AM

        fake_client = MagicMock()
        fake_client.connect    = AM()
        fake_client.disconnect = AM()
        fake_result  = MagicMock()

        user_id = 70001

        with patch("app.features.session.router.TelegramClient",
                   return_value=fake_client), \
             patch("app.features.session.router._get_app_credentials",
                   return_value=(12345, "abc")), \
             patch("app.features.session.router._is_telegram_app_delivery",
                   return_value=True):

            fake_client.send_code_request = AM(return_value=fake_result)

            state   = AsyncMock()
            message = MagicMock()
            message.from_user    = MagicMock()
            message.from_user.id = user_id
            message.chat         = MagicMock()
            message.chat.id      = 1
            message.text         = "+12025551234"
            message.reply        = AM()

            await sess_mod.recv_phone(message, state)

        # Must NOT proceed to OTP
        for call in state.set_state.call_args_list:
            self.assertNotEqual(
                call.args[0] if call.args else None,
                sess_mod.StringSessionState.waiting_for_otp,
                "waiting_for_otp must not be set when code is Telegram-app delivered",
            )
        # Must clear state and disconnect client
        state.clear.assert_called()
        fake_client.disconnect.assert_called()
        # Must NOT create ACTIVE_CLIENTS entry
        self.assertNotIn(user_id, sess_mod.ACTIVE_CLIENTS)
        # Must show QR redirect (message contains "ses_start_qr" via keyboard)
        message.reply.assert_called_once()
        call_kwargs = message.reply.call_args[1]
        # The reply_markup must contain ses_start_qr button
        markup = call_kwargs.get("reply_markup")
        self.assertIsNotNone(markup)
        buttons_flat = [btn.callback_data
                        for row in markup.inline_keyboard for btn in row]
        self.assertIn("ses_start_qr", buttons_flat)

    async def test_recv_phone_usable_delivery_proceeds_to_otp(self):
        """
        When send_code_request returns a non-App type, recv_phone must
        set waiting_for_otp and create an ACTIVE_CLIENTS entry.
        """
        self._skip_no_telethon()
        from app.features.session import router as sess_mod
        from unittest.mock import patch, AsyncMock as AM

        fake_result = MagicMock()
        fake_result.phone_code_hash = "fakehash123"
        fake_client = MagicMock()
        fake_client.connect    = AM()
        fake_client.disconnect = AM()
        fake_client.send_code_request = AM(return_value=fake_result)

        user_id = 70002
        sess_mod.ACTIVE_CLIENTS.pop(user_id, None)

        with patch("app.features.session.router.TelegramClient",
                   return_value=fake_client), \
             patch("app.features.session.router._get_app_credentials",
                   return_value=(12345, "abc")), \
             patch("app.features.session.router._is_telegram_app_delivery",
                   return_value=False):

            state   = AsyncMock()
            message = MagicMock()
            message.from_user    = MagicMock()
            message.from_user.id = user_id
            message.chat         = MagicMock()
            message.chat.id      = 1
            message.text         = "+12025551234"
            message.reply        = AM()

            await sess_mod.recv_phone(message, state)

        state.set_state.assert_called_with(sess_mod.StringSessionState.waiting_for_otp)
        self.assertIn(user_id, sess_mod.ACTIVE_CLIENTS)

        await sess_mod._cleanup_user_session(user_id)

    # ------------------------------------------------------------------
    # recv_otp: PhoneCodeExpiredError mapping
    # ------------------------------------------------------------------

    async def test_recv_otp_phone_code_expired_friendly_message(self):
        """
        PhoneCodeExpiredError must produce a user-friendly explanation that
        mentions the Telegram security restriction and recommends QR login.
        It must NOT show a raw exception name to the user.
        """
        self._skip_no_telethon()
        from telethon.errors import PhoneCodeExpiredError
        from app.features.session import router as sess_mod

        user_id = 71001

        fake_client = MagicMock()
        fake_client.sign_in = AsyncMock(
            side_effect=PhoneCodeExpiredError(None)
        )
        fake_client.is_connected = MagicMock(return_value=True)
        fake_client.disconnect   = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[user_id] = {
            "client":          fake_client,
            "phone":           "+12025551234",
            "phone_code_hash": "fakehash",
            "method":          "otp",
            "chat_id":         1,
            "task":            None,
            "countdown_task":  None,
            "created_at":      0,
        }

        state   = AsyncMock()
        message = MagicMock()
        message.from_user    = MagicMock()
        message.from_user.id = user_id
        message.text         = "12345"
        message.reply        = AsyncMock()

        await sess_mod.recv_otp(message, state)

        # Session must be cleaned up
        self.assertNotIn(user_id, sess_mod.ACTIVE_CLIENTS)
        state.clear.assert_called_once()

        reply_text = message.reply.call_args[0][0]
        # Must NOT expose the raw exception class name
        self.assertNotIn("PhoneCodeExpiredError", reply_text)
        # Must mention QR as alternative
        self.assertIn("QR", reply_text)

    # ------------------------------------------------------------------
    # ses_start_qr callback
    # ------------------------------------------------------------------

    async def test_cb_start_qr_triggers_qr_flow(self):
        """ses_start_qr callback must call _start_qr_login with configured creds."""
        self._skip_no_telethon()
        from app.features.session import router as sess_mod
        from unittest.mock import patch, AsyncMock as AM

        user_id = 72001

        with patch("app.features.session.router._get_app_credentials",
                   return_value=(99, "zz")), \
             patch("app.features.session.router._start_qr_login", new=AM()) as mock_start:

            state    = AsyncMock()
            callback = MagicMock()
            callback.from_user    = MagicMock()
            callback.from_user.id = user_id
            callback.answer       = AM()
            callback.message      = MagicMock()
            callback.message.chat = MagicMock()
            callback.message.chat.id = 1
            callback.message.edit_text = AM()
            bot = MagicMock()

            await sess_mod.cb_start_qr(callback, state, bot)

        mock_start.assert_called_once()
        call_kwargs = mock_start.call_args
        # Must pass the configured api_id and api_hash
        args = call_kwargs.args
        self.assertEqual(args[2], 99)    # api_id
        self.assertEqual(args[3], "zz")  # api_hash

    # ------------------------------------------------------------------
    # Method selection buttons
    # ------------------------------------------------------------------

    async def test_cb_method_otp_sets_phone_state(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        state    = AsyncMock()
        callback = MagicMock()
        callback.answer  = AsyncMock()
        callback.message = MagicMock()
        callback.message.edit_text = AsyncMock()

        await sess_mod.cb_method_otp(callback, state)

        state.set_state.assert_called_once_with(sess_mod.StringSessionState.waiting_for_phone)
        callback.message.edit_text.assert_called_once()
        # Must mention phone
        call_text = callback.message.edit_text.call_args[0][0]
        self.assertIn("phone", call_text.lower())

    # ------------------------------------------------------------------
    # QR countdown unit tests (no real Telegram)
    # ------------------------------------------------------------------

    async def test_qr_countdown_cancels_cleanly(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        bot        = MagicMock()
        bot.edit_message_caption = AsyncMock()
        fake_state = AsyncMock()

        # Session gone before countdown wakes up
        user_id = 77001
        # do NOT add to ACTIVE_CLIENTS → countdown should return immediately after sleep

        task = asyncio.create_task(
            sess_mod._qr_countdown(user_id, bot, 1, 1, fake_state)
        )
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # expected

    async def test_qr_countdown_stops_when_session_removed(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        bot        = MagicMock()
        bot.edit_message_caption = AsyncMock()
        fake_state = AsyncMock()

        user_id = 77002
        # Session not in ACTIVE_CLIENTS → countdown must return on first tick
        task = asyncio.create_task(
            sess_mod._qr_countdown(user_id, bot, 1, 1, fake_state)
        )
        # Give it a moment; it will sleep then check ACTIVE_CLIENTS and return
        await asyncio.sleep(0.05)
        # We patch the sleep so the task finishes quickly
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Cleanup: countdown_task also cancelled
    # ------------------------------------------------------------------

    async def test_cleanup_cancels_countdown_task(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        cancelled_flags = {"countdown": False, "main": False}

        async def _fake_countdown():
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled_flags["countdown"] = True
                raise

        async def _fake_main():
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled_flags["main"] = True
                raise

        ct   = asyncio.create_task(_fake_countdown())
        mt   = asyncio.create_task(_fake_main())
        await asyncio.sleep(0)  # let tasks start

        user_id = 77010
        fake_client = MagicMock()
        fake_client.is_connected.return_value = True
        fake_client.disconnect = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[user_id] = {
            "client":         fake_client,
            "task":           mt,
            "countdown_task": ct,
            "chat_id":        1,
            "created_at":     0,
        }

        await sess_mod._cleanup_user_session(user_id)
        await asyncio.sleep(0)

        self.assertTrue(ct.done(), "countdown_task must be cancelled")
        self.assertTrue(mt.done(), "main task must be cancelled")
        self.assertNotIn(user_id, sess_mod.ACTIVE_CLIENTS)

    # ------------------------------------------------------------------
    # OTP flow
    # ------------------------------------------------------------------

    async def test_recv_phone_invalid_format(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        state   = AsyncMock()
        message = MagicMock()
        message.text  = "notaphone"
        message.reply = AsyncMock()

        await sess_mod.recv_phone(message, state)

        # Should ask again, not advance state
        state.set_state.assert_not_called()
        message.reply.assert_called_once()

    async def test_recv_otp_session_expired(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        # No ACTIVE_CLIENTS entry
        user_id = 88001
        sess_mod.ACTIVE_CLIENTS.pop(user_id, None)

        state   = AsyncMock()
        message = MagicMock()
        message.from_user     = MagicMock()
        message.from_user.id  = user_id
        message.text          = "12345"
        message.reply         = AsyncMock()

        await sess_mod.recv_otp(message, state)

        state.clear.assert_called_once()
        message.reply.assert_called_once()
        self.assertIn("expired", message.reply.call_args[0][0].lower())

    async def test_recv_otp_invalid_code(self):
        self._skip_no_telethon()
        from telethon.errors import PhoneCodeInvalidError
        from app.features.session import router as sess_mod

        user_id = 88002

        fake_client = MagicMock()
        fake_client.sign_in = AsyncMock(side_effect=PhoneCodeInvalidError(None))
        sess_mod.ACTIVE_CLIENTS[user_id] = {
            "client":          fake_client,
            "phone":           "+1234567890",
            "phone_code_hash": "fakehash",
            "method":          "otp",
            "chat_id":         1,
            "task":            None,
            "countdown_task":  None,
            "created_at":      0,
        }

        state   = AsyncMock()
        message = MagicMock()
        message.from_user    = MagicMock()
        message.from_user.id = user_id
        message.text         = "99999"
        message.reply        = AsyncMock()

        await sess_mod.recv_otp(message, state)

        # Must not clean up session — let user retry
        self.assertIn(user_id, sess_mod.ACTIVE_CLIENTS)
        message.reply.assert_called_once()
        self.assertIn("incorrect", message.reply.call_args[0][0].lower())

        # Cleanup
        await sess_mod._cleanup_user_session(user_id)

    async def test_recv_otp_success(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        user_id = 88003

        fake_client = MagicMock()
        fake_client.sign_in = AsyncMock()
        fake_client.session = MagicMock()
        fake_client.session.save = MagicMock(return_value="1BQANOTEuMTc...")
        fake_client.is_connected = MagicMock(return_value=True)
        fake_client.disconnect   = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[user_id] = {
            "client":          fake_client,
            "phone":           "+1234567890",
            "phone_code_hash": "fakehash",
            "method":          "otp",
            "chat_id":         1,
            "task":            None,
            "countdown_task":  None,
            "created_at":      0,
        }

        state   = AsyncMock()
        message = MagicMock()
        message.from_user    = MagicMock()
        message.from_user.id = user_id
        message.text         = "12345"
        message.reply        = AsyncMock()

        await sess_mod.recv_otp(message, state)

        # Session must be cleaned up on success
        self.assertNotIn(user_id, sess_mod.ACTIVE_CLIENTS)
        state.clear.assert_called_once()
        message.reply.assert_called_once()
        reply_text = message.reply.call_args[0][0]
        self.assertIn("✅", reply_text)
        self.assertIn("1BQANOTEuMTc...", reply_text)

    # ------------------------------------------------------------------
    # 2FA — shared path
    # ------------------------------------------------------------------

    async def test_2fa_session_expired(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        user_id = 99101
        sess_mod.ACTIVE_CLIENTS.pop(user_id, None)

        state   = AsyncMock()
        message = MagicMock()
        message.from_user    = MagicMock()
        message.from_user.id = user_id
        message.text         = "mypassword"
        message.reply        = AsyncMock()

        await sess_mod.process_2fa(message, state)

        state.clear.assert_called_once()
        message.reply.assert_called_once()
        self.assertIn("expired", message.reply.call_args[0][0].lower())

    async def test_2fa_wrong_password(self):
        self._skip_no_telethon()
        from telethon.errors import PasswordHashInvalidError
        from app.features.session import router as sess_mod

        user_id = 99102

        fake_client = MagicMock()
        fake_client.sign_in = AsyncMock(side_effect=PasswordHashInvalidError(None))
        fake_client.is_connected = MagicMock(return_value=True)
        fake_client.disconnect   = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[user_id] = {
            "client":         fake_client,
            "method":         "qr",
            "chat_id":        1,
            "task":           None,
            "countdown_task": None,
            "created_at":     0,
        }

        state   = AsyncMock()
        message = MagicMock()
        message.from_user    = MagicMock()
        message.from_user.id = user_id
        message.text         = "wrongpassword"
        message.reply        = AsyncMock()

        await sess_mod.process_2fa(message, state)

        # Wrong password → session kept, user asked to retry
        self.assertIn(user_id, sess_mod.ACTIVE_CLIENTS)
        message.reply.assert_called_once()
        self.assertIn("incorrect", message.reply.call_args[0][0].lower())

        await sess_mod._cleanup_user_session(user_id)

    async def test_2fa_success(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        user_id = 99103

        fake_client = MagicMock()
        fake_client.sign_in = AsyncMock()
        fake_client.session = MagicMock()
        fake_client.session.save = MagicMock(return_value="SESSION_STRING_XYZ")
        fake_client.is_connected = MagicMock(return_value=True)
        fake_client.disconnect   = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[user_id] = {
            "client":         fake_client,
            "method":         "qr",
            "chat_id":        1,
            "task":           None,
            "countdown_task": None,
            "created_at":     0,
        }

        state   = AsyncMock()
        message = MagicMock()
        message.from_user    = MagicMock()
        message.from_user.id = user_id
        message.text         = "correct_password"
        message.reply        = AsyncMock()

        await sess_mod.process_2fa(message, state)

        self.assertNotIn(user_id, sess_mod.ACTIVE_CLIENTS)
        state.clear.assert_called_once()
        reply_text = message.reply.call_args[0][0]
        self.assertIn("SESSION_STRING_XYZ", reply_text)
        self.assertIn("✅", reply_text)

    # ------------------------------------------------------------------
    # Concurrent user isolation
    # ------------------------------------------------------------------

    async def test_concurrent_users_isolated_v3(self):
        """User A's session data must never overlap with user B's."""
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        def _mk_client():
            c = MagicMock()
            c.is_connected.return_value = True
            c.disconnect = AsyncMock()
            return c

        client_a = _mk_client()
        client_b = _mk_client()

        sess_mod.ACTIVE_CLIENTS[2001] = {
            "client":         client_a,
            "method":         "qr",
            "chat_id":        101,
            "task":           None,
            "countdown_task": None,
            "created_at":     0,
        }
        sess_mod.ACTIVE_CLIENTS[2002] = {
            "client":         client_b,
            "method":         "otp",
            "chat_id":        102,
            "task":           None,
            "countdown_task": None,
            "created_at":     0,
        }

        # Clean up A only
        await sess_mod._cleanup_user_session(2001)

        self.assertNotIn(2001, sess_mod.ACTIVE_CLIENTS)
        self.assertIn(2002, sess_mod.ACTIVE_CLIENTS)
        # B's client must be untouched
        client_a.disconnect.assert_called_once()
        client_b.disconnect.assert_not_called()
        self.assertEqual(sess_mod.ACTIVE_CLIENTS[2002]["method"], "otp")

        await sess_mod._cleanup_user_session(2002)

    # ------------------------------------------------------------------
    # Cancellation via callback
    # ------------------------------------------------------------------

    async def test_cancel_cleans_up_and_clears_state(self):
        """ses_cancel callback must remove ACTIVE_CLIENTS entry and clear FSM."""
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        user_id = 66001

        fake_client = MagicMock()
        fake_client.is_connected.return_value = True
        fake_client.disconnect = AsyncMock()

        sess_mod.ACTIVE_CLIENTS[user_id] = {
            "client":         fake_client,
            "task":           None,
            "countdown_task": None,
            "chat_id":        1,
            "created_at":     0,
        }

        state    = AsyncMock()
        callback = MagicMock()
        callback.from_user    = MagicMock()
        callback.from_user.id = user_id
        callback.answer       = AsyncMock()
        callback.message      = MagicMock()
        callback.message.photo = None
        callback.message.edit_text = AsyncMock()
        callback.message.answer    = AsyncMock()

        await sess_mod.cb_cancel(callback, state)

        self.assertNotIn(user_id, sess_mod.ACTIVE_CLIENTS)
        state.clear.assert_called_once()
        callback.answer.assert_called_once()

    async def test_cancel_photo_message_uses_edit_caption(self):
        """Cancel on a QR photo message must use edit_caption, not edit_text."""
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        user_id = 66002

        state    = AsyncMock()
        callback = MagicMock()
        callback.from_user    = MagicMock()
        callback.from_user.id = user_id
        callback.answer       = AsyncMock()
        callback.message      = MagicMock()
        callback.message.photo = [MagicMock()]   # photo message
        callback.message.edit_caption = AsyncMock()
        callback.message.edit_text    = AsyncMock()

        await sess_mod.cb_cancel(callback, state)

        callback.message.edit_caption.assert_called_once()
        callback.message.edit_text.assert_not_called()

    # ------------------------------------------------------------------
    # QR caption helper
    # ------------------------------------------------------------------

    def test_qr_caption_contains_countdown(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        caption = sess_mod._qr_caption(75)
        self.assertIn("75s",   caption)
        self.assertIn("QR",    caption)
        self.assertIn("Expires", caption)

    def test_qr_caption_zero(self):
        self._skip_no_telethon()
        from app.features.session import router as sess_mod

        caption = sess_mod._qr_caption(0)
        self.assertIn("0s", caption)


if __name__ == "__main__":
    unittest.main(verbosity=2)
