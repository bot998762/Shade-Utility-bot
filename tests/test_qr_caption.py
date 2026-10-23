"""
CHG-026 — /qr photo caption must respect Telegram's 1024-character limit.

Telegram counts caption length AFTER entity parsing (tags removed, character
references such as &lt; counted once) in UTF-16 code units. These tests parse
the produced HTML the same way instead of trusting Python's len() of the raw
string.

cmd_qr and _build_qr_caption are extracted from media/router.py by AST and run
against a fake message and a fake QR module, so aiogram is not required and no
network is used. Two tests use the real qrcode library and skip without it.
"""

import ast
import html
import io
import types
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TELEGRAM_CAPTION_LIMIT = 1024


class _FakeOverflow(Exception):
    """Stand-in for qrcode.exceptions.DataOverflowError."""


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(("start", tag))

    def handle_endtag(self, tag):
        self.tags.append(("end", tag))

    def handle_data(self, data):
        self.parts.append(data)


def parsed_text(caption_html: str) -> str:
    p = _TextOnly()
    p.feed(caption_html)
    p.close()
    return "".join(p.parts)


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _load_router_pieces(fake_qr):
    src = (PROJECT_ROOT / "app/features/media/router.py").read_text()
    names = {"_utf16_len", "_build_qr_caption", "cmd_qr"}
    assigns = {"_QR_CAPTION_LIMIT", "_QR_CAPTION_PREVIEW_CHARS", "_QR_CAPTION_TITLE"}
    body = []
    for n in ast.parse(src).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names:
            n.decorator_list = []  # drop @router.message
            body.append(n)
        elif isinstance(n, ast.Assign) and any(getattr(t, "id", "") in assigns for t in n.targets):
            body.append(n)
    ns = {
        "_html": html,
        "qr": fake_qr,
        "QRDataOverflowError": _FakeOverflow,
        "BufferedInputFile": lambda data, filename=None: ("file", len(data), filename),
        "Message": object,
    }
    # Intentional: executes only function/constant definitions AST-extracted
    # from this project's own router source (aiogram is not importable here).
    exec(compile(ast.Module(body=body, type_ignores=[]), "router_extract", "exec"), ns)  # noqa: S102
    return ns


class _Msg:
    def __init__(self, text):
        self.text = text
        self.replies = []
        self.photos = []

    async def reply(self, text, **kw):
        self.replies.append((text, kw))

    async def reply_photo(self, photo, caption, parse_mode):
        self.photos.append((photo, caption, parse_mode))


def _fake_qr(generate):
    return types.SimpleNamespace(generate_qr_buffer=generate)


def _png_ok(data):
    return io.BytesIO(b"\x89PNG-fake-" + data.encode()[:10])


class TestQrCaption(unittest.IsolatedAsyncioTestCase):

    async def _send(self, content, generate=_png_ok):
        ns = _load_router_pieces(_fake_qr(generate))
        msg = _Msg(f"/qr {content}")
        await ns["cmd_qr"](msg)
        return msg, ns

    def _caption_ok(self, caption):
        visible = parsed_text(caption)
        self.assertLessEqual(utf16_len(visible), TELEGRAM_CAPTION_LIMIT)
        self.assertLessEqual(utf16_len(visible), 900)
        # tags must be balanced (no half-cut markup)
        starts = [t for k, t in _TextOnly_tags(caption) if k == "start"]
        ends = [t for k, t in _TextOnly_tags(caption) if k == "end"]
        self.assertEqual(sorted(starts), sorted(ends))
        return visible

    async def test_short_text_caption_unchanged(self):
        msg, _ = await self._send("hello world")
        (_, caption, mode), = msg.photos
        self.assertEqual(caption, "🔳 <b>Generated QR Code Matrix:</b>\n<code>hello world</code>")
        self.assertEqual(mode, "HTML")

    async def test_short_text_with_specials_matches_original_escaping(self):
        content = 'a<b>&"c\' é'
        msg, _ = await self._send(content)
        (_, caption, _), = msg.photos
        self.assertEqual(
            caption,
            f"🔳 <b>Generated QR Code Matrix:</b>\n<code>{html.escape(content)}</code>",
        )

    async def test_text_at_budget_boundary_is_not_truncated(self):
        ns = _load_router_pieces(_fake_qr(_png_ok))
        room = ns["_QR_CAPTION_LIMIT"] - utf16_len(ns["_QR_CAPTION_TITLE"])
        full = ns["_build_qr_caption"]("x" * room)
        self.assertNotIn("truncated", full)
        over = ns["_build_qr_caption"]("x" * (room + 1))
        self.assertIn("truncated", over)

    async def test_long_input_sends_png_with_short_truncated_caption(self):
        for n in (1200, 1500, 2000):
            content = "abc " * (n // 4)
            msg, _ = await self._send(content)
            self.assertEqual(len(msg.photos), 1, n)
            (_photo, caption, _), = msg.photos
            visible = self._caption_ok(caption)
            self.assertIn("truncated", visible)
            self.assertIn(f"of {len(content)} characters", visible)
            self.assertIn("QR code contains the full text", visible)
            self.assertNotIn(content[:300], visible, "full input must not be repeated")
            self.assertEqual(msg.replies, [])

    async def test_qr_receives_the_full_untruncated_input(self):
        seen = []

        def gen(data):
            seen.append(data)
            return _png_ok(data)
        content = "z" * 1800
        await self._send(content, gen)
        self.assertEqual(seen, [content])

    async def test_special_and_multibyte_input_escaped_and_truncated_safely(self):
        tricky = ('<>&"\' ' + "€é中文 " + "\U0001F600\U0001F680 ") * 120
        self.assertGreater(len(tricky), 1000)
        msg, _ = await self._send(tricky)
        (_, caption, _), = msg.photos
        visible = self._caption_ok(caption)
        # raw '<' only appears as markup we wrote; user '<' is always escaped
        self.assertNotIn("<>", caption)
        self.assertNotIn("&<", caption)
        # the preview in the caption is a prefix of the original input
        shown = visible.split("\n", 1)[1].split("…")[0]
        self.assertTrue(tricky.startswith(shown))
        # no entity cut in half and no lone surrogate / replacement damage
        shown.encode("utf-8")
        self.assertNotRegex(caption, r"&[a-z#0-9]*(?=[<…\s]|$)(?<!;)")

    async def test_cut_point_never_splits_an_entity_or_astral_character(self):
        ns = _load_router_pieces(_fake_qr(_png_ok))
        preview = ns["_QR_CAPTION_PREVIEW_CHARS"]
        for ch in ("&", "<", "\U0001F600"):
            content = "a" * (preview - 1) + ch * 900  # cut lands right at the special char
            cap = ns["_build_qr_caption"](content)
            visible = parsed_text(cap)
            self.assertLessEqual(utf16_len(visible), 900)
            shown = visible.split("\n", 1)[1].split("…")[0]
            self.assertTrue(content.startswith(shown))
            self.assertEqual(len(shown), preview)

    async def test_worst_case_input_stays_within_limit(self):
        # 4096 is Telegram's maximum message length; emoji are 2 UTF-16 units each
        for content in ("\U0001F600" * 2000, "&" * 4000, "<" * 4000, "a" * 4000):
            msg, _ = await self._send(content)
            (_, caption, _), = msg.photos
            self._caption_ok(caption)

    async def test_over_capacity_input_gets_friendly_message_and_no_photo(self):
        def gen(data):
            raise _FakeOverflow()
        msg, _ = await self._send("x" * 4000, gen)
        self.assertEqual(msg.photos, [])
        (text, kw), = msg.replies
        self.assertIn("Data too large for QR code", text)
        self.assertEqual(kw.get("parse_mode"), "HTML")

    async def test_unrelated_value_error_propagates_unchanged(self):
        def gen(data):
            raise ValueError("boom")
        ns = _load_router_pieces(_fake_qr(gen))
        msg = _Msg("/qr hello")
        with self.assertRaises(ValueError) as ctx:
            await ns["cmd_qr"](msg)
        self.assertEqual(str(ctx.exception), "boom")
        self.assertEqual(msg.photos, [])
        self.assertEqual(msg.replies, [])

    async def test_upload_errors_are_not_swallowed(self):
        """A failing reply_photo (e.g. Telegram rejecting the upload) must reach
        the error middleware instead of being hidden by cmd_qr."""
        ns = _load_router_pieces(_fake_qr(_png_ok))
        msg = _Msg("/qr hello")

        async def failing_reply_photo(photo, caption, parse_mode):
            raise RuntimeError("telegram said no")
        msg.reply_photo = failing_reply_photo
        with self.assertRaises(RuntimeError):
            await ns["cmd_qr"](msg)
        self.assertEqual(msg.replies, [])

    def test_cmd_qr_has_no_broad_exception_handler(self):
        src = (PROJECT_ROOT / "app/features/media/router.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "cmd_qr")
        handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
        self.assertEqual([ast.unparse(h.type) for h in handlers], ["QRDataOverflowError"])

    async def test_usage_message_without_argument_unchanged(self):
        ns = _load_router_pieces(_fake_qr(_png_ok))
        msg = _Msg("/qr")
        await ns["cmd_qr"](msg)
        self.assertEqual(msg.photos, [])
        self.assertIn("Usage:", msg.replies[0][0])


def _TextOnly_tags(caption_html):
    p = _TextOnly()
    p.feed(caption_html)
    p.close()
    return p.tags


try:
    import qrcode  # noqa: F401
    _HAVE_QRCODE = True
except ImportError:
    _HAVE_QRCODE = False


@unittest.skipUnless(_HAVE_QRCODE, "qrcode not installed")
class TestQrCaptionWithRealQrLibrary(unittest.IsolatedAsyncioTestCase):
    """Real qrcode encoding: input longer than a caption still yields a PNG."""

    def _real_generate(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            from app.utils.qr import generate_qr_buffer
        except ImportError as exc:  # e.g. pyzbar/libzbar missing
            self.skipTest(f"app.utils.qr not importable: {exc}")
        return generate_qr_buffer

    async def test_1500_char_input_encodes_and_caption_fits(self):
        gen = self._real_generate()
        content = "https://example.com/?q=" + "a1" * 700
        ns = _load_router_pieces(_fake_qr(gen))
        msg = _Msg(f"/qr {content}")
        await ns["cmd_qr"](msg)
        (photo, caption, _), = msg.photos
        self.assertEqual(photo[2], "qrcode.png")
        self.assertGreater(photo[1], 1000)
        self.assertLessEqual(utf16_len(parsed_text(caption)), 900)

    async def test_over_capacity_still_raises_overflow_from_real_library(self):
        from qrcode.exceptions import DataOverflowError
        gen = self._real_generate()
        with self.assertRaises(DataOverflowError):
            gen("A" * 10000)
        with patch("qrcode.make", side_effect=ValueError("boom")), self.assertRaises(ValueError):
            gen("hi")


if __name__ == "__main__":
    unittest.main()
