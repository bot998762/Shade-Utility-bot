"""
CHG-028 — Telegram message-length safety.

Part 1 tests app/utils/telegram_text.py (pure stdlib).
Part 2 runs the real handler source of /ocr, /b64en, /b64de, /urlen and /jsonfmt
(extracted by AST from the routers, so aiogram is not required) against fake
messages. No network and no real Telegram traffic.

Telegram counts message length AFTER entity parsing, so sizes here are measured
by parsing the produced HTML (tags removed, character references resolved) in
UTF-16 units instead of trusting len() of the raw string.
"""

import ast
import html
import json
import random
import re
import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils import crypto
from app.utils import telegram_text as tt

TELEGRAM_LIMIT = 4096


# ───────────────────────────── Part 1: helper ─────────────────────────────

class TestUtf16AndVisibleLength(unittest.TestCase):

    def test_utf16_len(self):
        self.assertEqual(tt.utf16_len(""), 0)
        self.assertEqual(tt.utf16_len("abc"), 3)
        self.assertEqual(tt.utf16_len("é€中"), 3)            # BMP: 1 unit each
        self.assertEqual(tt.utf16_len("\U0001F600"), 2)       # astral: 2 units
        self.assertEqual(tt.utf16_len("a\U0001F680b"), 4)

    def test_html_visible_len_ignores_markup_and_resolves_entities(self):
        self.assertEqual(tt.html_visible_text("<b>Hi</b> <code>a&lt;b&gt;&amp;</code>"), "Hi a<b>&")
        self.assertEqual(tt.html_visible_len("<pre><code class=\"language-json\">&lt;&gt;</code></pre>"), 2)
        self.assertEqual(tt.html_visible_len("<i>\U0001F600</i>"), 2)

    def test_fits_boundaries(self):
        self.assertTrue(tt.fits("x" * tt.SINGLE_MESSAGE_BUDGET))
        self.assertFalse(tt.fits("x" * (tt.SINGLE_MESSAGE_BUDGET + 1)))
        # an astral character costs two units
        self.assertTrue(tt.fits("x" * (tt.SINGLE_MESSAGE_BUDGET - 2) + "\U0001F600"))
        self.assertFalse(tt.fits("x" * (tt.SINGLE_MESSAGE_BUDGET - 1) + "\U0001F600"))
        self.assertTrue(tt.fits("x" * 10, budget=10))
        self.assertFalse(tt.fits("x" * 11, budget=10))

    def test_budget_constants_are_ordered_and_safe(self):
        self.assertEqual(tt.TELEGRAM_MESSAGE_LIMIT, TELEGRAM_LIMIT)
        self.assertEqual(tt.CHUNK_BUDGET, 3500)
        self.assertLess(tt.CHUNK_BUDGET, tt.SINGLE_MESSAGE_BUDGET)
        self.assertLess(tt.SINGLE_MESSAGE_BUDGET, tt.TELEGRAM_MESSAGE_LIMIT)

    def test_chunk_room(self):
        self.assertEqual(tt.chunk_room("x" * 100), tt.CHUNK_BUDGET - 100)
        self.assertEqual(tt.chunk_room("\U0001F600" * 10, budget=1000), 980)
        with self.assertRaises(ValueError):
            tt.chunk_room("x" * (tt.CHUNK_BUDGET - 10))

    def test_too_long_notice_is_friendly_html(self):
        text = tt.too_long_notice("Base64")
        self.assertIn("Output too long", text)
        self.assertIn("Base64", text)
        self.assertIn("shorter input", text)


class TestSplitText(unittest.TestCase):

    def assert_valid(self, text, max_units):
        chunks = tt.split_text(text, max_units)
        self.assertEqual("".join(chunks), text, "split must be lossless")
        for chunk in chunks:
            self.assertGreater(len(chunk), 0)
            self.assertLessEqual(tt.utf16_len(chunk), max_units)
            chunk.encode("utf-8")  # never corrupt: no lone surrogates introduced
        return chunks

    def test_empty_and_short(self):
        self.assertEqual(tt.split_text("", 10), [])
        self.assertEqual(tt.split_text("abc", 10), ["abc"])
        self.assertEqual(tt.split_text("a" * 10, 10), ["a" * 10])

    def test_exact_and_off_by_one(self):
        self.assertEqual(len(tt.split_text("a" * 11, 10)), 2)
        self.assertEqual(tt.split_text("a" * 20, 10), ["a" * 10, "a" * 10])

    def test_invalid_max_units(self):
        for bad in (0, 1, -5):
            with self.assertRaises(ValueError):
                tt.split_text("abc", bad)

    def test_astral_characters_are_never_split_and_count_two_units(self):
        emoji = "\U0001F600"
        chunks = self.assert_valid(emoji * 7, 3)       # room for one emoji + one unit
        self.assertEqual(chunks, [emoji] * 7)
        chunks = self.assert_valid(emoji * 6, 4)       # two per chunk
        self.assertEqual(chunks, [emoji * 2] * 3)
        self.assert_valid("a" + emoji * 5 + "b", 2)    # minimum size, every emoji alone

    def test_prefers_newline_in_second_half_of_window(self):
        text = "aaaa\nbbbbbbbb\ncccc"
        chunks = self.assert_valid(text, 10)
        self.assertEqual(chunks[0], "aaaa\nbbbbbbbb\n"[:14][: len(chunks[0])])
        # window "aaaa\nbbbbb" -> last newline at index 4 is in the first half: fill window
        self.assertEqual(chunks[0], "aaaa\nbbbbb")
        text = "aaaaaaa\nbbbbbbbbbb"
        chunks = self.assert_valid(text, 10)
        self.assertEqual(chunks[0], "aaaaaaa\n")     # newline at index 7 (>= half): break after it

    def test_newline_break_keeps_text_lossless(self):
        text = "\n".join(f"line {i}" for i in range(200))
        chunks = self.assert_valid(text, 120)
        for chunk in chunks[:-1]:
            self.assertTrue(chunk.endswith("\n"), "chunks should end at line breaks here")

    def test_unicode_mix_property(self):
        rng = random.Random(28)
        alphabet = ["a", "Z", " ", "\n", "é", "€", "中", "\U0001F600", "\U0001F680", "&", "<", "`", "\\"]
        for _ in range(300):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 400)))
            self.assert_valid(text, rng.choice([2, 3, 5, 17, 64, 250]))


# ─────────────────────── Part 2: handlers via AST extraction ───────────────────────

def _strip_annotations(fn):
    for arg in fn.args.args + fn.args.kwonlyargs:
        arg.annotation = None
    fn.returns = None
    fn.decorator_list = []
    return fn


def _load(relpath, functions, assigns=(), extra=None):
    src = (PROJECT_ROOT / relpath).read_text()
    body = []
    found = set()
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions:
            body.append(_strip_annotations(node))
            found.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(getattr(t, "id", "") in assigns for t in targets):
                body.append(node)
                found.add(next(t.id for t in targets))
    missing = (set(functions) | set(assigns)) - found
    assert not missing, f"not found in {relpath}: {missing}"
    quiet = types.SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None)
    ns = {"_html": html, "_tt": tt, "crypto": crypto, "json": json, "logger": quiet}
    ns.update(extra or {})
    exec(compile(ast.Module(body=body, type_ignores=[]), relpath, "exec"), ns)  # noqa: S102
    return ns


MEDIA = "app/features/media/router.py"
CRYPTO = "app/features/crypto/router.py"
GENERAL = "app/features/general/router.py"
OCR_ASSIGNS = ("_OCR_MAX_MESSAGES", "_OCR_RULE", "_OCR_TITLE", "_OCR_FOOTER", "_OCR_CHUNK_OVERHEAD")


class SendFailure(Exception):
    """Stand-in for a Telegram send error (e.g. TelegramBadRequest)."""


class FakeStatus:
    def __init__(self, log, fail_on=()):
        self.edits = log
        self.fail_on = set(fail_on)
        self.calls = 0

    async def edit_text(self, text, **kw):
        self.calls += 1
        if self.calls in self.fail_on:
            raise SendFailure("edit failed")
        self.edits.append((text, kw))


class FakeMessage:
    def __init__(self, text="", *, photo=True, reply_fail_on=(), status_fail_on=()):
        self.text = text
        self.replies = []          # successful replies: (text, kwargs)
        self.reply_calls = 0
        self.reply_fail_on = set(reply_fail_on)
        self.status_edits = []
        self.status = FakeStatus(self.status_edits, status_fail_on)
        self.from_user = types.SimpleNamespace(id=1)
        self.reply_to_message = types.SimpleNamespace(photo=[types.SimpleNamespace(file_id="f")]) if photo else None

    async def reply(self, text, **kw):
        self.reply_calls += 1
        if self.reply_calls in self.reply_fail_on:
            raise SendFailure("reply failed")
        self.replies.append((text, kw))
        return self.status


class FakeBot:
    def __init__(self, fail=None):
        self.fail = fail

    async def get_file(self, file_id):
        if self.fail:
            raise self.fail
        return types.SimpleNamespace(file_path="p")

    async def download_file(self, path):
        import io
        return io.BytesIO(b"img")


class FakeOCR:
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error

    async def extract_text(self, data, user_id):
        if self.error:
            raise self.error
        return self.text


class FakeRegistry:
    def require(self, name):
        pass


def code_text(message_html):
    """Payload inside <code>...</code> (unescaped)."""
    match = re.search(r"<code>(.*?)</code>", message_html, re.DOTALL)
    return html.unescape(match.group(1))


class _Handlers(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = _load(MEDIA, ("cmd_ocr", "_ocr_messages", "_ocr_single_html"), OCR_ASSIGNS)
        cls.crypto_ns = _load(CRYPTO, ("cmd_b64en", "cmd_b64de"))
        cls.general = _load(GENERAL, ("cmd_urlen", "cmd_jsonfmt"))

    async def run_ocr(self, text=None, *, error=None, bot_error=None, msg=None):
        msg = msg or FakeMessage("/ocr")
        await self.media["cmd_ocr"](msg, FakeBot(bot_error), FakeOCR(text, error), FakeRegistry())
        return msg


# ───────────────────────────── /ocr ─────────────────────────────

class TestOcr(_Handlers):

    OLD_FORMAT = (
        "📝 <b>OCR Extracted Result:</b>\n"
        "───────────────────────────\n"
        "<code>{}</code>\n"
        "───────────────────────────\n"
        "<i>Tap text block to copy.</i>"
    )

    async def test_short_result_is_exactly_the_old_message(self):
        for text in ("hello world", "a<b>&\"' `x` _y_ *z*", "é€中 \U0001F600"):
            msg = await self.run_ocr(text)
            self.assertEqual(msg.status_edits, [(self.OLD_FORMAT.format(html.escape(text)), {"parse_mode": "HTML"})])
            self.assertEqual(msg.replies, [("📝 Processing Image OCR...", {})])  # only the status message

    async def test_empty_result_unchanged(self):
        for empty in ("", None):
            msg = await self.run_ocr(empty)
            self.assertEqual(msg.status_edits, [("❌ No optical text detected in image payload.", {})])

    async def test_missing_photo_unchanged(self):
        msg = FakeMessage("/ocr", photo=False)
        await self.run_ocr(msg=msg)
        self.assertEqual(msg.replies[0][0], "❌ Reply to an image message with <code>/ocr</code>.")
        self.assertEqual(msg.status_edits, [])

    async def test_single_message_boundary(self):
        base = f"{self.media['_OCR_TITLE']}\n{self.media['_OCR_RULE']}\n\n{self.media['_OCR_RULE']}\n{self.media['_OCR_FOOTER']}"
        room = tt.SINGLE_MESSAGE_BUDGET - tt.utf16_len(base) - 0
        fits = self.media["_ocr_messages"]("x" * room)
        self.assertEqual(len(fits), 1)
        over = self.media["_ocr_messages"]("x" * (room + 1))
        self.assertGreater(len(over), 1)

    async def test_long_result_is_chunked_within_budget(self):
        text = "\n".join(f"line {i:04d} " + "word " * 8 for i in range(220))   # ~ 11k chars
        msg = await self.run_ocr(text)
        sent = [m for m, _ in msg.status_edits] + [m for m, _ in msg.replies[1:]]
        self.assertGreater(len(sent), 1)
        self.assertLessEqual(len(sent), 4)
        for body in sent:
            self.assertLessEqual(tt.html_visible_len(body), tt.CHUNK_BUDGET, body[:80])
            self.assertLess(tt.html_visible_len(body), TELEGRAM_LIMIT)
        # first part replaces the status message, the rest are new replies, all HTML
        self.assertEqual(len(msg.status_edits), 1)
        self.assertEqual(msg.status_edits[0][1], {"parse_mode": "HTML"})
        for _, kw in msg.replies[1:]:
            self.assertEqual(kw, {"parse_mode": "HTML"})
        joined = "".join(code_text(m) for m in sent)
        if len(sent) < 4 or "Output truncated" not in sent[-1]:
            self.assertEqual(joined, text)
        for index, body in enumerate(sent, start=1):
            self.assertIn(f"part {index} of {len(sent)}", body)

    async def test_four_message_cap_and_truncation_notice(self):
        text = "".join(f"{i:06d}\n" for i in range(40000))      # 280k chars
        msg = await self.run_ocr(text)
        sent = [m for m, _ in msg.status_edits] + [m for m, _ in msg.replies[1:]]
        self.assertEqual(len(sent), 4)
        self.assertEqual(msg.reply_calls, 4)                      # status + 3 more replies
        shown = "".join(code_text(m) for m in sent)
        omitted = len(text) - len(shown)
        self.assertGreater(omitted, 0)
        self.assertTrue(text.startswith(shown))
        self.assertIn(f"Output truncated: {omitted} more characters not shown.", sent[-1])
        for body in sent[:-1]:
            self.assertNotIn("truncated", body)
        for body in sent:
            self.assertLessEqual(tt.html_visible_len(body), tt.CHUNK_BUDGET)

    async def test_exactly_four_full_chunks_has_no_truncation_notice(self):
        room = tt.chunk_room(self.media["_OCR_CHUNK_OVERHEAD"])
        text = "a" * (4 * room)
        sent = self.media["_ocr_messages"](text)
        self.assertEqual(len(sent), 4)
        self.assertNotIn("truncated", sent[-1])
        self.assertEqual("".join(code_text(m) for m in sent), text)
        over = self.media["_ocr_messages"](text + "b")
        self.assertEqual(len(over), 4)
        self.assertIn("1 more characters not shown", over[-1])

    async def test_special_and_unicode_text_is_escaped_and_never_split_badly(self):
        text = ("<tag> & \"q\" 'a' `code` _u_ *b* \\ é€中 \U0001F600\U0001F680\n") * 400
        sent = self.media["_ocr_messages"](text)
        self.assertGreater(len(sent), 1)
        for body in sent:
            self.assertLessEqual(tt.html_visible_len(body), tt.CHUNK_BUDGET)
            payload = re.search(r"<code>(.*?)</code>", body, re.DOTALL).group(1)
            self.assertNotIn("<tag>", payload)           # escaped
            self.assertNotRegex(payload, r"&(?!(?:amp|lt|gt|quot|#x27);)")
            code_text(body).encode("utf-8")
        shown = "".join(code_text(m) for m in sent)
        self.assertTrue(text.startswith(shown))

    async def test_emoji_heavy_text_respects_utf16_budget(self):
        text = "\U0001F600" * 5000                         # 10,000 UTF-16 units
        sent = self.media["_ocr_messages"](text)
        for body in sent:
            self.assertLessEqual(tt.html_visible_len(body), tt.CHUNK_BUDGET)

    async def test_failure_before_result_updates_status_and_reraises(self):
        for kwargs in ({"error": RuntimeError("provider down")}, {"bot_error": RuntimeError("download failed")}):
            msg = FakeMessage("/ocr")
            with self.assertRaises(RuntimeError):
                await self.run_ocr("text", msg=msg, **kwargs)
            self.assertEqual(msg.status_edits, [("❌ OCR failed. Please try again.", {})])

    async def test_failure_sending_result_still_reaches_middleware_and_clears_status(self):
        msg = FakeMessage("/ocr", status_fail_on={1})           # first edit (the result) fails
        with self.assertRaises(SendFailure):
            await self.run_ocr("hello", msg=msg)
        self.assertEqual(msg.status_edits, [("❌ OCR failed. Please try again.", {})])

    async def test_secondary_failure_while_clearing_status_is_swallowed_not_the_original(self):
        msg = FakeMessage("/ocr", status_fail_on={1, 2})        # result edit AND failure notice fail
        with self.assertRaises(SendFailure) as ctx:
            await self.run_ocr("hello", msg=msg)
        self.assertEqual(str(ctx.exception), "edit failed")
        self.assertEqual(msg.status_edits, [])

    async def test_failure_on_later_chunk_does_not_overwrite_delivered_result(self):
        text = "x" * 8000
        msg = FakeMessage("/ocr", reply_fail_on={2})            # status reply ok, first extra part fails
        with self.assertRaises(SendFailure):
            await self.run_ocr(text, msg=msg)
        self.assertEqual(len(msg.status_edits), 1)              # only the first part, no "OCR failed"
        self.assertIn("part 1 of", msg.status_edits[0][0])


# ───────────────────────── /b64en and /urlen ─────────────────────────

class TestEncoders(_Handlers):

    async def test_b64en_normal_output_is_byte_for_byte(self):
        msg = FakeMessage("/b64en hello")
        await self.crypto_ns["cmd_b64en"](msg)
        self.assertEqual(msg.replies, [("🔢 **Base64 Encoded:**\n`aGVsbG8=`", {"parse_mode": "Markdown"})])

    async def test_urlen_normal_output_is_byte_for_byte(self):
        msg = FakeMessage("/urlen a b&c/é")
        await self.general["cmd_urlen"](msg)
        expected = "🔗 **URL Encoded Payload:**\n`a%20b%26c/%C3%A9`"
        self.assertEqual(msg.replies, [(expected, {"parse_mode": "Markdown"})])

    async def test_usage_messages_unchanged(self):
        for ns_name, fn, usage in (("crypto_ns", "cmd_b64en", "❌ **Usage:** `/b64en <text>`"),
                                   ("general", "cmd_urlen", "❌ **Usage:** `/urlen <text>`")):
            msg = FakeMessage("/x")
            await getattr(self, ns_name)[fn](msg)
            self.assertEqual(msg.replies, [(usage, {"parse_mode": "Markdown"})])

    async def test_b64en_oversized_gets_friendly_message_never_truncated_output(self):
        msg = FakeMessage("/b64en " + "a" * 3100)               # 4,136 chars of Base64
        await self.crypto_ns["cmd_b64en"](msg)
        (text, kw), = msg.replies
        self.assertEqual(kw, {"parse_mode": "HTML"})
        self.assertIn("Output too long", text)
        self.assertNotIn("YWFh", text)                          # no encoded fragment leaked

    async def test_urlen_oversized_gets_friendly_message(self):
        msg = FakeMessage("/urlen " + "é" * 700)                # 4,200 chars encoded
        await self.general["cmd_urlen"](msg)
        (text, _kw), = msg.replies
        self.assertIn("Output too long", text)
        self.assertNotIn("%C3%A9", text)

    async def test_b64en_boundary_sends_full_untruncated_result_up_to_the_budget(self):
        title = "🔢 Base64 Encoded:\n"
        room = tt.SINGLE_MESSAGE_BUDGET - tt.utf16_len(title)   # Base64 chars allowed
        raw_len = (room // 4) * 3                               # largest input whose output fits
        text = "a" * raw_len
        encoded = crypto.b64_encode(text)
        self.assertLessEqual(len(encoded), room)
        msg = FakeMessage("/b64en " + text)
        await self.crypto_ns["cmd_b64en"](msg)
        self.assertEqual(msg.replies, [(f"🔢 **Base64 Encoded:**\n`{encoded}`", {"parse_mode": "Markdown"})])
        self.assertLessEqual(tt.utf16_len(title + encoded), tt.SINGLE_MESSAGE_BUDGET)
        over = FakeMessage("/b64en " + "a" * (raw_len + 3))
        await self.crypto_ns["cmd_b64en"](over)
        self.assertIn("Output too long", over.replies[0][0])

    async def test_urlen_boundary(self):
        title = "🔗 URL Encoded Payload:\n"
        room = tt.SINGLE_MESSAGE_BUDGET - tt.utf16_len(title)
        msg = FakeMessage("/urlen " + "a" * room)
        await self.general["cmd_urlen"](msg)
        self.assertEqual(msg.replies[0][1], {"parse_mode": "Markdown"})
        self.assertIn("a" * room, msg.replies[0][0])
        over = FakeMessage("/urlen " + "a" * (room + 1))
        await self.general["cmd_urlen"](over)
        self.assertIn("Output too long", over.replies[0][0])


# ─────────────────────────── /jsonfmt ───────────────────────────

class TestJsonFmt(_Handlers):

    async def run_json(self, payload, **kw):
        msg = FakeMessage("/jsonfmt " + payload, **kw)
        await self.general["cmd_jsonfmt"](msg)
        return msg

    async def test_normal_json_is_formatted_in_an_escaped_pre_block(self):
        msg = await self.run_json('{"a":1,"b":[true,null]}')
        formatted = json.dumps({"a": 1, "b": [True, None]}, indent=4)
        expected = ('📋 <b>Pretty JSON Output:</b>\n'
                    f'<pre><code class="language-json">{html.escape(formatted)}</code></pre>')
        self.assertEqual(msg.replies, [(expected, {"parse_mode": "HTML"})])

    async def test_json_with_backticks_backslashes_and_markup_formats_correctly(self):
        payload = json.dumps({"k": "a`b``c```d\\e", "html": "<b>&</b>", "u": "é€\U0001F600"})
        msg = await self.run_json(payload)
        (text, kw), = msg.replies
        self.assertEqual(kw, {"parse_mode": "HTML"})
        body = re.search(r"<code class=\"language-json\">(.*?)</code></pre>", text, re.DOTALL).group(1)
        self.assertEqual(html.unescape(body), json.dumps(json.loads(payload), indent=4))
        self.assertIn("`", body)                       # backticks pass through untouched
        self.assertNotIn("<b>", body)                  # user markup is escaped
        self.assertLess(tt.html_visible_len(text), TELEGRAM_LIMIT)

    async def test_invalid_json_keeps_its_message(self):
        msg = await self.run_json("{bad")
        try:
            json.loads("{bad")
        except json.JSONDecodeError as exc:
            expected = f"❌ **Invalid JSON:** `{exc}`"
        self.assertEqual(msg.replies, [(expected, {"parse_mode": "Markdown"})])

    async def test_pathologically_nested_json_is_reported_as_invalid_not_crashed(self):
        msg = await self.run_json("[" * 200000)
        (text, kw), = msg.replies
        self.assertTrue(text.startswith("❌ **Invalid JSON:**"))
        self.assertEqual(kw, {"parse_mode": "Markdown"})

    async def test_usage_unchanged(self):
        msg = FakeMessage("/jsonfmt")
        await self.general["cmd_jsonfmt"](msg)
        self.assertEqual(msg.replies, [("❌ **Usage:** `/jsonfmt <json_string>`", {"parse_mode": "Markdown"})])

    async def test_oversized_formatted_json_gets_friendly_message(self):
        payload = json.dumps(list(range(900)), separators=(",", ":"))
        self.assertLess(len(payload), 4096)                    # a legal Telegram message
        msg = await self.run_json(payload)
        (text, kw), = msg.replies
        self.assertIn("Output too long", text)
        self.assertEqual(kw, {"parse_mode": "HTML"})

    async def test_send_failure_is_not_mislabelled_as_invalid_json(self):
        msg = FakeMessage("/jsonfmt {\"a\":1}", reply_fail_on={1})
        with self.assertRaises(SendFailure):
            await self.general["cmd_jsonfmt"](msg)
        self.assertEqual(msg.replies, [])                      # no "Invalid JSON" fallback was sent

    async def test_boundary_just_inside_the_budget_is_sent(self):
        title = "📋 Pretty JSON Output:\n"
        # one string value sized so that the formatted JSON lands exactly on the budget
        overhead = len(json.dumps({"k": ""}, indent=4))
        size = tt.SINGLE_MESSAGE_BUDGET - tt.utf16_len(title) - overhead
        msg = await self.run_json(json.dumps({"k": "x" * size}))
        self.assertIn("<pre>", msg.replies[0][0])
        msg2 = await self.run_json(json.dumps({"k": "x" * (size + 1)}))
        self.assertIn("Output too long", msg2.replies[0][0])


# ─────────────────────────── /b64de ───────────────────────────

class TestB64Decode(_Handlers):

    async def test_valid_base64_output_unchanged(self):
        msg = FakeMessage("/b64de aGVsbG8gPGI+")
        await self.crypto_ns["cmd_b64de"](msg)
        self.assertEqual(msg.replies, [("🔡 <b>Base64 Decoded:</b>\n<code>hello &lt;b&gt;</code>", {"parse_mode": "HTML"})])

    async def test_invalid_base64_keeps_its_message(self):
        for bad in ("abc", "/w==", "a"):                       # bad padding, invalid UTF-8, bad length
            msg = FakeMessage(f"/b64de {bad}")
            await self.crypto_ns["cmd_b64de"](msg)
            self.assertEqual(msg.replies, [("❌ <b>Error:</b> Invalid Base64 string payload.", {"parse_mode": "HTML"})], bad)

    async def test_usage_unchanged(self):
        msg = FakeMessage("/b64de")
        await self.crypto_ns["cmd_b64de"](msg)
        self.assertEqual(msg.replies[0][0], "❌ <b>Usage:</b> <code>/b64de &lt;string&gt;</code>")

    async def test_send_failure_is_not_mislabelled_as_invalid_base64(self):
        msg = FakeMessage("/b64de aGVsbG8=", reply_fail_on={1})
        with self.assertRaises(SendFailure):
            await self.crypto_ns["cmd_b64de"](msg)
        self.assertEqual(msg.replies, [])

    async def test_oversized_decoded_text_gets_friendly_message(self):
        class LongDecoder:
            b64_decode = staticmethod(lambda text: "x" * 5000)
        ns = _load(CRYPTO, ("cmd_b64de",), extra={"crypto": LongDecoder})
        msg = FakeMessage("/b64de eA==")
        await ns["cmd_b64de"](msg)
        (text, kw), = msg.replies
        self.assertIn("Output too long", text)
        self.assertEqual(kw, {"parse_mode": "HTML"})

    async def test_unexpected_errors_are_not_swallowed(self):
        class Broken:
            @staticmethod
            def b64_decode(text):
                raise RuntimeError("bug")
        ns = _load(CRYPTO, ("cmd_b64de",), extra={"crypto": Broken})
        with self.assertRaises(RuntimeError):
            await ns["cmd_b64de"](FakeMessage("/b64de eA=="))


# ───────────────────────── wiring / scope checks ─────────────────────────

class TestScopeAndWiring(unittest.TestCase):

    def test_helper_is_stdlib_only(self):
        tree = ast.parse((PROJECT_ROOT / "app/utils/telegram_text.py").read_text())
        stdlib = {"__future__", "html"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], stdlib)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn((node.module or "").split(".")[0], stdlib)

    def test_handlers_use_the_helper(self):
        for path in (MEDIA, CRYPTO, GENERAL):
            self.assertIn("from app.utils import telegram_text as _tt", (PROJECT_ROOT / path).read_text())

    def test_no_broad_exception_handler_in_changed_decoding_handlers(self):
        for path, names in ((CRYPTO, {"cmd_b64en", "cmd_b64de"}), (GENERAL, {"cmd_jsonfmt", "cmd_urlen"})):
            tree = ast.parse((PROJECT_ROOT / path).read_text())
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)) and fn.name in names:
                    for handler in (h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers):
                        self.assertNotEqual(ast.unparse(handler.type), "Exception", fn.name)

    def test_ocr_reraises_original_error(self):
        tree = ast.parse((PROJECT_ROOT / MEDIA).read_text())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "cmd_ocr")
        outer = next(n for n in ast.walk(fn) if isinstance(n, ast.Try))
        self.assertTrue(any(isinstance(s, ast.Raise) and s.exc is None for s in outer.handlers[0].body))


if __name__ == "__main__":
    unittest.main()
