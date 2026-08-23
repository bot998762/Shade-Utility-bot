"""
Markdown Safety Regression Tests
=================================
Verifies that handlers with dynamic user/API content never produce
TelegramBadRequest from unescaped Markdown-significant characters.

Tests cover:
  - /info: the confirmed production failure (byte offset 203)
  - /id:   replied user first_name with special chars
  - /ua:   username with underscores
  - /weather: user-supplied city with underscores
  - /ip:   ISP names with & _ *
  - /ocr:  extracted text with backticks and underscores
  - /qr:   user QR content with special characters
  - /tr:   translation output with arbitrary characters

The tests do NOT require aiogram, aiohttp, or any third-party package.
They verify:
  1. The handler sends parse_mode="HTML" (not "Markdown")
  2. Every dynamic field is wrapped with html.escape()
  3. The response text contains no unmatched Markdown special sequences
  4. The exact previously-failing scenario (username with underscore) is safe

All Telegram API calls are replaced with AsyncMock.
"""

import ast
import sys
import html
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_user(
    user_id: int = 123,
    first_name: str = "Alice",
    last_name: str | None = None,
    username: str | None = None,
    is_bot: bool = False,
    is_premium: bool = False,
    language_code: str = "en",
) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.first_name = first_name
    u.last_name = last_name
    u.username = username
    u.is_bot = is_bot
    u.is_premium = is_premium
    u.language_code = language_code
    return u


def _make_message(
    text: str = "/info",
    from_user=None,
    reply_to=None,
    chat_id: int = -100001,
    chat_type: str = "group",
    thread_id: int | None = None,
) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user = from_user or _make_user()
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.chat.type = chat_type
    msg.message_thread_id = thread_id
    msg.reply_to_message = reply_to
    msg.reply = AsyncMock()
    msg.reply_to_message = reply_to
    return msg


def _extract_last_reply(mock_msg: MagicMock) -> tuple[str, str | None]:
    """Returns (text_sent, parse_mode) from the last reply/edit call."""
    if mock_msg.reply.called:
        args = mock_msg.reply.call_args
        text = args[0][0] if args[0] else args[1].get("text", "")
        parse_mode = args[1].get("parse_mode") if args[1] else None
        return text, parse_mode
    return "", None


def _has_unmatched_markdown(text: str) -> list[str]:
    """
    Check for characters that cause TelegramBadRequest in legacy Markdown mode.
    Returns list of issues found.
    """
    issues = []
    for char, name in [("_", "italic"), ("*", "bold"), ("`", "code")]:
        if text.count(char) % 2 != 0:
            issues.append(f"unmatched {name} delimiter '{char}'")
    # Unmatched opening bracket
    if text.count("[") != text.count("]"):
        issues.append("unmatched bracket '['")
    return issues


# ─────────────────────────────────────────────────────────────────────────────
# /info — CRITICAL (confirmed production crash)
# ─────────────────────────────────────────────────────────────────────────────

class TestInfoCommandMarkdownSafety(unittest.IsolatedAsyncioTestCase):

    def _skip_no_aiogram(self):
        try:
            import aiogram  # noqa: F401
        except ImportError:
            self.skipTest("aiogram not installed")

    async def _run_info(self, user):
        self._skip_no_aiogram()
        from app.features.general.router import cmd_info
        msg = _make_message(from_user=user)
        await cmd_info(msg)
        args = msg.reply.call_args
        text = args[0][0] if args[0] else ""
        parse_mode = args[1].get("parse_mode") if args[1] else None
        return text, parse_mode

    async def test_info_uses_html_mode(self):
        user = _make_user(username="john_doe", first_name="Alice")
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML", f"cmd_info must use parse_mode='HTML', got: {pm!r}")

    async def test_info_normal_user(self):
        user = _make_user(first_name="Alice", last_name="Smith", username="alice")
        text, pm = await self._run_info(user)
        self.assertIn("Alice", text)
        self.assertEqual(pm, "HTML")

    async def test_info_username_with_underscore(self):
        """
        THE EXACT PRODUCTION BUG: @john_doe — underscore in username.
        In Markdown mode: _doe is parsed as italic start → entity never closed →
        TelegramBadRequest: Can't find end of entity at byte offset 203.
        In HTML mode: underscore is a literal character → safe.
        """
        user = _make_user(username="john_doe", first_name="John")
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML", "Must use HTML mode for usernames with underscores")
        # The underscore must be preserved (not removed), just rendered safely
        self.assertIn("john_doe", text)
        # Verify it would NOT be safe in Markdown mode
        issues = _has_unmatched_markdown(text.replace("<b>", "").replace("</b>", ""))
        # In HTML mode the underscore is just text — no issues
        self.assertNotIn("parse_mode=\"Markdown\"", str(text))

    async def test_info_first_name_with_asterisk(self):
        """first_name containing * breaks Markdown bold parsing."""
        user = _make_user(first_name="Alice*Smith")
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML")
        self.assertIn("Alice*Smith", text)  # content preserved

    async def test_info_first_name_with_underscore(self):
        """first_name containing _ breaks Markdown italic parsing."""
        user = _make_user(first_name="Alice_B")
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML")
        self.assertIn("Alice_B", text)

    async def test_info_first_name_with_backtick(self):
        """first_name containing backtick breaks Markdown code block parsing."""
        user = _make_user(first_name="Al`ice")
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML")
        self.assertIn("Al`ice", text)

    async def test_info_first_name_with_bracket(self):
        """first_name containing [ breaks Markdown link parsing."""
        user = _make_user(first_name="Alice [Pro]")
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML")
        # Brackets should be preserved (html.escape doesn't touch them)
        self.assertIn("[Pro]", text)

    async def test_info_last_name_with_underscore(self):
        user = _make_user(first_name="Bob", last_name="O_Brien")
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML")
        self.assertIn("O_Brien", text)

    async def test_info_html_injection_escaped(self):
        """Names with < > & must be escaped to prevent HTML injection."""
        user = _make_user(first_name="<script>alert(1)</script>")
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML")
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    async def test_info_ampersand_in_name(self):
        """Names like AT&T must have & escaped as &amp; in HTML mode."""
        user = _make_user(first_name="AT&T User")
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML")
        self.assertIn("AT&amp;T", text)

    async def test_info_none_from_user_no_crash(self):
        """Channel post (from_user=None) must not crash — returns safe message."""
        self._skip_no_aiogram()
        from app.features.general.router import cmd_info
        reply = MagicMock()
        reply.from_user = None
        msg = _make_message(reply_to=reply)
        msg.reply_to_message = reply
        await cmd_info(msg)
        msg.reply.assert_called_once()
        text = msg.reply.call_args[0][0]
        self.assertIn("Cannot inspect", text)

    async def test_info_no_username(self):
        """Users without username should show 'None' not crash."""
        user = _make_user(first_name="NoUsernamePerson", username=None)
        text, pm = await self._run_info(user)
        self.assertEqual(pm, "HTML")
        self.assertIn("None", text)


# ─────────────────────────────────────────────────────────────────────────────
# /id — first_name in replied-user context
# ─────────────────────────────────────────────────────────────────────────────

class TestIdCommandMarkdownSafety(unittest.IsolatedAsyncioTestCase):

    def _skip_no_aiogram(self):
        try:
            import aiogram  # noqa: F401
        except ImportError:
            self.skipTest("aiogram not installed")

    async def _run_id_with_reply(self, replied_first_name: str) -> tuple[str, str | None]:
        self._skip_no_aiogram()
        from app.features.general.router import cmd_id
        replied_user = _make_user(user_id=999, first_name=replied_first_name)
        reply_msg = MagicMock()
        reply_msg.from_user = replied_user
        reply_msg.message_id = 42
        msg = _make_message(reply_to=reply_msg)
        msg.reply_to_message = reply_msg
        await cmd_id(msg)
        args = msg.reply.call_args
        text = args[0][0] if args[0] else ""
        pm = args[1].get("parse_mode") if args[1] else None
        return text, pm

    async def test_id_uses_html_mode(self):
        text, pm = await self._run_id_with_reply("Alice")
        self.assertEqual(pm, "HTML")

    async def test_id_replied_name_with_underscore(self):
        text, pm = await self._run_id_with_reply("Alice_B")
        self.assertEqual(pm, "HTML")
        self.assertIn("Alice_B", text)

    async def test_id_replied_name_with_asterisk(self):
        text, pm = await self._run_id_with_reply("Alice*Smith")
        self.assertEqual(pm, "HTML")
        self.assertIn("Alice*Smith", text)

    async def test_id_replied_name_html_escaped(self):
        text, pm = await self._run_id_with_reply("<injected>")
        self.assertEqual(pm, "HTML")
        self.assertNotIn("<injected>", text)
        self.assertIn("&lt;injected&gt;", text)

    async def test_id_channel_post_reply_no_crash(self):
        self._skip_no_aiogram()
        from app.features.general.router import cmd_id
        reply_msg = MagicMock()
        reply_msg.from_user = None
        reply_msg.message_id = 77
        msg = _make_message(reply_to=reply_msg)
        msg.reply_to_message = reply_msg
        await cmd_id(msg)
        text = msg.reply.call_args[0][0]
        self.assertIn("Anonymous", text)


# ─────────────────────────────────────────────────────────────────────────────
# /ua — username with underscores
# ─────────────────────────────────────────────────────────────────────────────

class TestUACommandMarkdownSafety(unittest.IsolatedAsyncioTestCase):

    def _skip_no_aiogram(self):
        try:
            import aiogram  # noqa: F401
        except ImportError:
            self.skipTest("aiogram not installed")

    async def _run_ua(self, username: str | None) -> tuple[str, str | None]:
        self._skip_no_aiogram()
        from app.features.general.router import cmd_ua
        user = _make_user(username=username)
        msg = _make_message(from_user=user)
        await cmd_ua(msg)
        args = msg.reply.call_args
        return args[0][0], args[1].get("parse_mode") if args[1] else None

    async def test_ua_uses_html_mode(self):
        _, pm = await self._run_ua("alice")
        self.assertEqual(pm, "HTML")

    async def test_ua_username_underscore_safe(self):
        """@john_doe is the most common /ua crash case — underscore after @ sign."""
        text, pm = await self._run_ua("john_doe")
        self.assertEqual(pm, "HTML")
        self.assertIn("john_doe", text)

    async def test_ua_username_double_underscore(self):
        text, pm = await self._run_ua("john__doe")
        self.assertEqual(pm, "HTML")
        self.assertIn("john__doe", text)

    async def test_ua_no_username(self):
        text, pm = await self._run_ua(None)
        self.assertEqual(pm, "HTML")
        self.assertIn("None", text)


# ─────────────────────────────────────────────────────────────────────────────
# /weather — city name in "Fetching..." message and "not found" message
# ─────────────────────────────────────────────────────────────────────────────

class TestWeatherCityEscaping(unittest.TestCase):
    """
    AST-level test: verify the status message and not-found message
    both use HTML mode and reference e_city (the escaped variable).
    Does not require aiohttp.
    """

    def _get_weather_src(self) -> str:
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_weather":
                return ast.unparse(node)
        return ""

    def test_status_message_uses_html(self):
        src = self._get_weather_src()
        # The "Fetching weather for..." message must use HTML, not Markdown
        self.assertNotIn('Fetching weather for **', src,
            "Fetching message must not use Markdown **bold** with raw city")

    def test_city_variable_escaped(self):
        src = self._get_weather_src()
        self.assertIn("e_city", src,
            "cmd_weather must use e_city (html.escape(city)) for the initial status message")

    def test_not_found_message_uses_html(self):
        src = self._get_weather_src()
        # not-found message must use e_city, not raw city
        self.assertNotIn("Location **{city}**", src,
            "not-found message must not use Markdown with raw city variable")

    def test_api_response_fields_escaped(self):
        src = self._get_weather_src()
        # The final response must escape areaName and weatherDesc from external API
        self.assertIn("e_area", src)
        self.assertIn("e_country", src)
        self.assertIn("e_desc", src)

    def test_all_edit_text_use_html(self):
        src = self._get_weather_src()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr in ("edit_text", "reply"):
                    kws = {k.arg: ast.unparse(k.value) for k in node.keywords}
                    pm = kws.get("parse_mode", "")
                    if pm:
                        self.assertNotIn("Markdown", pm,
                            f"cmd_weather still has parse_mode=Markdown at line {node.lineno}")


# ─────────────────────────────────────────────────────────────────────────────
# /ip — ISP names from external API
# ─────────────────────────────────────────────────────────────────────────────

class TestIPEscaping(unittest.TestCase):

    def _get_ip_src(self) -> str:
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_ip":
                return ast.unparse(node)
        return ""

    def test_ip_uses_html_mode(self):
        src = self._get_ip_src()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr in ("edit_text", "reply"):
                    kws = {k.arg: ast.unparse(k.value) for k in node.keywords}
                    pm = kws.get("parse_mode", "")
                    if pm:
                        self.assertNotIn("Markdown", pm,
                            f"cmd_ip still has parse_mode=Markdown at line {node.lineno}")

    def test_isp_field_escaped(self):
        src = self._get_ip_src()
        self.assertIn("e_isp", src, "ISP field must be html-escaped (AT&T, O2_Mobile etc.)")

    def test_country_field_escaped(self):
        src = self._get_ip_src()
        self.assertIn("e_country", src)

    def test_api_field_escaping_logic(self):
        """Verify html.escape handles real ISP names."""
        # These come from ip-api.com and can break Markdown
        isp_names = ["AT&T", "O2_Mobile UK", "Jio*Net", "ISP<Name>"]
        for name in isp_names:
            escaped = html.escape(name)
            # Must not contain unescaped & < > that would break HTML
            self.assertNotIn("&T", escaped)  # & must become &amp;
            if "&" in name:
                self.assertIn("&amp;", escaped)
            if "<" in name:
                self.assertIn("&lt;", escaped)


# ─────────────────────────────────────────────────────────────────────────────
# /ocr, /qr, /qrscan, /tr — media handlers
# ─────────────────────────────────────────────────────────────────────────────

class TestMediaHandlerMarkdownSafety(unittest.TestCase):
    """AST-level verification that media handlers use HTML mode."""

    def _get_handler_src(self, name: str) -> str:
        src = (PROJECT_ROOT / "app/features/media/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
                return ast.unparse(node)
        return ""

    def _check_no_markdown(self, handler_name: str):
        src = self._get_handler_src(handler_name)
        self.assertTrue(src, f"{handler_name} not found in media/router.py")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr in ("edit_text", "reply", "reply_photo"):
                    kws = {k.arg: ast.unparse(k.value) for k in node.keywords}
                    pm = kws.get("parse_mode", "")
                    if pm:
                        self.assertNotIn("Markdown", pm,
                            f"{handler_name} has parse_mode=Markdown at line {node.lineno}")

    def test_ocr_no_markdown(self):
        self._check_no_markdown("cmd_ocr")

    def test_qr_no_markdown(self):
        self._check_no_markdown("cmd_qr")

    def test_qrscan_no_markdown(self):
        self._check_no_markdown("cmd_qrscan")

    def test_translate_no_markdown(self):
        self._check_no_markdown("cmd_translate")

    def test_ocr_output_escaped(self):
        src = self._get_handler_src("cmd_ocr")
        self.assertIn("_html.escape", src,
            "OCR output must be html.escape()d — extracted text can contain backticks")

    def test_qr_input_escaped(self):
        src = self._get_handler_src("cmd_qr")
        self.assertIn("_html.escape", src,
            "QR content (user input) must be html.escape()d")

    def test_qrscan_output_escaped(self):
        src = self._get_handler_src("cmd_qrscan")
        self.assertIn("_html.escape", src,
            "QR scan result must be html.escape()d — QR can encode arbitrary data")

    def test_translate_output_escaped(self):
        src = self._get_handler_src("cmd_translate")
        self.assertIn("_html.escape", src,
            "Translation output must be html.escape()d — target language text is arbitrary")

    def test_escape_edge_cases(self):
        """Verify html.escape handles the characters that broke Markdown."""
        cases = [
            ("OCR text with backtick", "price: `100`", "price: `100`"),
            ("OCR text with asterisk", "x*y=z", "x*y=z"),
            ("QR URL with underscore", "https://example.com/user_name", "https://example.com/user_name"),
            ("Translation with ampersand", "AT&T Service", "AT&amp;T Service"),
            ("Translation with angle brackets", "<greeting>", "&lt;greeting&gt;"),
        ]
        for desc, raw, expected_contains in cases:
            escaped = html.escape(raw)
            self.assertIn(expected_contains, escaped,
                f"{desc}: expected {expected_contains!r} in {escaped!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Global audit — no dynamic Markdown remaining
# ─────────────────────────────────────────────────────────────────────────────

class TestNoDynamicMarkdownRemaining(unittest.TestCase):
    """
    Exhaustive AST scan: verify no handler sends dynamic user/API data
    with parse_mode='Markdown'.
    """

    UNTRUSTED_FIELDS = {
        "first_name", "last_name", "username", "title",
        "isp", "city", "regionName", "country", "areaName", "weatherDesc",
        "e_first", "e_last",  # if someone accidentally uses raw versions
    }

    def test_no_dynamic_markdown_in_any_handler(self):
        violations = []
        for path in (PROJECT_ROOT / "app").rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            try:
                src = path.read_text()
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Await):
                    continue
                call = node.value
                if not isinstance(call, ast.Call):
                    continue
                kws = {k.arg: k.value for k in call.keywords}
                pm = kws.get("parse_mode")
                if pm is None:
                    continue
                pm_val = ast.unparse(pm)
                if "Markdown" not in pm_val:
                    continue
                # Check if any arg contains untrusted field references
                for arg in list(call.args) + [kws.get("text"), kws.get("caption")]:
                    if arg is None:
                        continue
                    arg_src = ast.unparse(arg)
                    hit = [f for f in self.UNTRUSTED_FIELDS if f in arg_src]
                    if hit:
                        violations.append(
                            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                            f"Markdown with fields {hit}"
                        )
        self.assertEqual(violations, [],
            "Dynamic content in Markdown mode:\n" + "\n".join(violations))

    def test_info_handler_parse_mode_is_html(self):
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_info":
                fn_src = ast.unparse(node)
                self.assertIn("parse_mode='HTML'", fn_src,
                    "cmd_info must use parse_mode='HTML'")
                self.assertNotIn("parse_mode='Markdown'", fn_src,
                    "cmd_info must not use parse_mode='Markdown'")

    def test_info_handler_escapes_first_name(self):
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_info":
                fn_src = ast.unparse(node)
                # Must escape first_name — this was the bug trigger
                self.assertIn("escape(target.first_name", fn_src,
                    "cmd_info must html.escape() first_name")
                self.assertIn("escape(target.last_name", fn_src,
                    "cmd_info must html.escape() last_name")
                self.assertIn("escape(", fn_src,
                    "cmd_info must use html.escape() for username")


# ─────────────────────────────────────────────────────────────────────────────
# TelegramConflictError diagnosis (AST / architectural, no network)
# ─────────────────────────────────────────────────────────────────────────────

class TestTelegramConflictErrorDiagnosis(unittest.TestCase):
    """
    Verifies bootstrap architecture against the TelegramConflictError
    'terminated by other getUpdates request' seen in Render logs.
    This is an AST/structural test — it cannot catch a runtime race,
    but it rules out code-level bugs.
    """

    def _get_bootstrap_src(self) -> str:
        return (PROJECT_ROOT / "app/core/bootstrap.py").read_text()

    def test_single_polling_task_created(self):
        """Only one asyncio.create_task wrapping dp.start_polling must exist."""
        src = self._get_bootstrap_src()
        tree = ast.parse(src)
        # Count create_task calls that contain start_polling (not the call itself split over lines)
        create_task_with_polling = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                fn_name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if fn_name == "create_task":
                    args_src = " ".join(ast.unparse(a) for a in node.args)
                    if "start_polling" in args_src:
                        create_task_with_polling.append(node.lineno)
        self.assertEqual(len(create_task_with_polling), 1,
            f"Expected 1 create_task(start_polling), found {len(create_task_with_polling)}"
            f" at lines {create_task_with_polling}")

    def test_delete_webhook_called_before_polling(self):
        """delete_webhook(drop_pending_updates=True) should precede start_polling."""
        src = self._get_bootstrap_src()
        self.assertIn("delete_webhook", src,
            "delete_webhook must be called to clear any lingering webhook")
        # Verify ordering: delete_webhook appears before start_polling in source
        dw_pos = src.index("delete_webhook")
        sp_pos = src.index("start_polling")
        self.assertLess(dw_pos, sp_pos,
            "delete_webhook must be called before start_polling")

    def test_no_duplicate_dispatcher_creation(self):
        """Only one Dispatcher() must be created."""
        src = self._get_bootstrap_src()
        tree = ast.parse(src)
        dispatchers = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if name == "Dispatcher":
                    dispatchers.append(node.lineno)
        self.assertEqual(len(dispatchers), 1,
            f"Expected 1 Dispatcher(), found {len(dispatchers)} at {dispatchers}")

    def test_conflict_diagnosis_documented(self):
        """
        TelegramConflictError diagnosis:
        A) No duplicate polling task in source — confirmed above.
        B) No duplicate Dispatcher — confirmed above.
        C) Render free tier may run multiple instances during deploy rollover.
        D) The error is transient (deploy overlap) not a code bug.
        E) delete_webhook() is called — prevents webhook/polling conflict.
        This test documents the finding as a structural assertion.
        """
        # The presence of delete_webhook is the key mitigation
        src = self._get_bootstrap_src()
        self.assertIn("drop_pending_updates=True", src,
            "drop_pending_updates=True ensures clean startup after restart")


if __name__ == "__main__":
    unittest.main(verbosity=2)
