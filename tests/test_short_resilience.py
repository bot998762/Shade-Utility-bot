"""CHG-030 — /short resilience: consecutive-failure circuit breaker, cooldown vs outage
reporting, already-shortened input, privacy-safe provider diagnostics, OCR regression.

The REAL url_providers / failover / circuit-breaker / short_links code is exercised with
mocked HTTP sessions (no network). aiohttp, pydantic_settings and python-json-logger are
stubbed only where missing, so every test runs in any environment.

Not covered (by design): live CleanURI / v.gd behaviour. Verified-URL-rejection
classification (CHG-030 item B) is NOT implemented because the providers' error formats
could not be verified; test_http_400_is_still_a_provider_failure documents that.
"""
import ast
import asyncio
import importlib.util
import json
import logging
import socket
import ssl
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.circuit_breaker import CircuitBreaker
from app.core.exceptions import (
    CircuitOpenError,
    NoProvidersAvailableError,
    ProviderAPIError,
    ProvidersCoolingDownError,
)
from app.platform.failover import ProviderFailoverEngine
from app.utils import provider_diag
from app.utils import short_links as sl

PIN = "https://in.pinterest.com/search/pins/?rs=typed&q=Kai+hiwatari"
GH = "https://github.com/WEB-BUILDER-OFC/Fylo/actions/runs/43779958021"
EX = "https://example.com/"
VG = "https://v.gd/Nlkqlc"


# ───────────────────────────── helpers ─────────────────────────────

def _load(relpath: str, name: str, extra_stubs: dict | None = None):
    """Import a real project module with only the missing third-party deps stubbed."""
    stubs = {}
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        aio = types.ModuleType("aiohttp")
        aio.ClientTimeout = lambda total=None: types.SimpleNamespace(total=total)
        aio.ClientSession = object
        aio.FormData = object
        stubs["aiohttp"] = aio
    cfg = types.ModuleType("app.core.config")
    cfg.settings = types.SimpleNamespace(REQUEST_TIMEOUT=15, OCR_API_KEY="test-placeholder")
    lg = types.ModuleType("app.core.logger")
    lg.setup_logger = lambda *a, **k: logging.getLogger("ShadePlatform")
    stubs.update({"app.core.config": cfg, "app.core.logger": lg})
    stubs.update(extra_stubs or {})
    with mock.patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relpath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


PROVIDERS = _load("app/providers/url_providers.py", "url_providers_under_test")


def _ocr_service_cls():
    """The real OCRService; only its (unused here) EventBus import is stubbed."""
    bus_mod = types.ModuleType("app.platform.event_bus")
    bus_mod.EventBus = object
    return _load("app/services/ocr_service.py", "ocr_service_under_test",
                 {"app.platform.event_bus": bus_mod}).OCRService


class Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def text(self, **kw):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    """Fake aiohttp session. fn(sent_url, call_no) -> Resp | exception instance."""

    def __init__(self, fn):
        self.fn, self.calls, self.sent = fn, 0, []

    def _do(self, kind, url, **kw):
        self.calls += 1
        sent = kw["data"]["url"] if kind == "POST" else parse_qs(urlsplit(url).query)["url"][0]
        self.sent.append(sent)
        r = self.fn(sent, self.calls)
        if isinstance(r, BaseException):
            raise r
        return r

    def post(self, url, **kw):
        return self._do("POST", url, **kw)

    def get(self, url, **kw):
        return self._do("GET", url, **kw)


class ClientConnectorDNSError(OSError):
    """Name-compatible stand-in for aiohttp's DNS error."""


class ClientConnectorError(OSError):
    pass


def cleanuri_ok(u, n):
    return Resp(200, json.dumps({"result_url": "https://cleanuri.com/abc123"}))


def vgd_ok(u, n):
    return Resp(200, "https://v.gd/Nlkqlc")


def boom(exc):
    return lambda u, n: exc


def make_engine(cfn, vfn):
    c, v = FakeSession(cfn), FakeSession(vfn)
    engine = ProviderFailoverEngine("URLShortener")
    engine.register_provider(PROVIDERS.CleanURIProvider(c), CircuitBreaker("CleanURI", failure_threshold=2))
    engine.register_provider(PROVIDERS.VGdURLProvider(v), CircuitBreaker("VGdURL", failure_threshold=2))
    return engine, c, v


async def ok_call():
    return "ok"


async def bad_call():
    raise RuntimeError("boom")


# ───────────────────────── A: circuit breaker ─────────────────────────

class TestBreakerConsecutiveFailures(unittest.IsolatedAsyncioTestCase):
    async def _call(self, cb, fn):
        try:
            return await cb.call(fn)
        except Exception:  # noqa: BLE001
            return None

    async def test_failure_success_failure_does_not_open(self):
        cb = CircuitBreaker("t", failure_threshold=2)
        await self._call(cb, bad_call)
        self.assertEqual(cb.failures, 1)
        await self._call(cb, ok_call)
        self.assertEqual((cb.failures, cb.state), (0, "CLOSED"))
        await self._call(cb, bad_call)
        self.assertEqual((cb.failures, cb.state), (1, "CLOSED"))

    async def test_many_isolated_failures_never_open(self):
        cb = CircuitBreaker("t", failure_threshold=2)
        for _ in range(25):
            await self._call(cb, bad_call)
            await self._call(cb, ok_call)
        self.assertEqual(cb.state, "CLOSED")

    async def test_consecutive_failures_still_open(self):
        cb = CircuitBreaker("t", failure_threshold=2)
        await self._call(cb, bad_call)
        await self._call(cb, bad_call)
        self.assertEqual(cb.state, "OPEN")
        with self.assertRaises(CircuitOpenError):
            await cb.call(ok_call)

    async def test_half_open_recovery_closes_and_clears(self):
        cb = CircuitBreaker("t", failure_threshold=2, recovery_timeout=60)
        await self._call(cb, bad_call)
        await self._call(cb, bad_call)
        cb.last_failure_time -= 61
        self.assertEqual(await cb.call(ok_call), "ok")
        self.assertEqual((cb.state, cb.failures), ("CLOSED", 0))

    async def test_half_open_failure_reopens_immediately(self):
        cb = CircuitBreaker("t", failure_threshold=2, recovery_timeout=60)
        await self._call(cb, bad_call)
        await self._call(cb, bad_call)
        cb.last_failure_time -= 61
        await self._call(cb, bad_call)
        self.assertEqual(cb.state, "OPEN")
        with self.assertRaises(CircuitOpenError):
            await cb.call(ok_call)

    async def test_open_blocks_without_calling(self):
        cb = CircuitBreaker("t", failure_threshold=1)
        await self._call(cb, bad_call)
        called = []

        async def probe():
            called.append(1)

        with self.assertRaises(CircuitOpenError):
            await cb.call(probe)
        self.assertEqual(called, [])

    async def test_retry_after(self):
        cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout=60)
        self.assertEqual(cb.retry_after(), 0.0)
        await self._call(cb, bad_call)
        self.assertTrue(0 < cb.retry_after() <= 60)
        cb.last_failure_time -= 100
        self.assertEqual(cb.retry_after(), 0.0)

    async def test_late_success_while_open_does_not_close_or_reset(self):
        cb = CircuitBreaker("t", failure_threshold=2)
        gate = asyncio.Event()

        async def slow_ok():
            await gate.wait()
            return "late"

        slow = asyncio.ensure_future(cb.call(slow_ok))   # started while CLOSED
        await asyncio.sleep(0)
        await self._call(cb, bad_call)
        await self._call(cb, bad_call)
        self.assertEqual(cb.state, "OPEN")
        gate.set()
        self.assertEqual(await slow, "late")
        self.assertEqual(cb.state, "OPEN")
        self.assertGreaterEqual(cb.failures, 2)

    async def test_concurrent_successes_keep_state_clean(self):
        cb = CircuitBreaker("t", failure_threshold=2)

        async def work(i):
            await asyncio.sleep(0)
            return i

        res = await asyncio.gather(*[cb.call(work, i) for i in range(200)])
        self.assertEqual(res, list(range(200)))
        self.assertEqual((cb.state, cb.failures), ("CLOSED", 0))

    async def test_concurrent_mixed_calls_keep_invariants(self):
        cb = CircuitBreaker("t", failure_threshold=3, recovery_timeout=0)

        async def work(i):
            await asyncio.sleep(0)
            if i % 3 == 0:
                raise RuntimeError("x")
            return i

        await asyncio.gather(*[cb.call(work, i) for i in range(300)], return_exceptions=True)
        self.assertIn(cb.state, ("CLOSED", "OPEN", "HALF_OPEN"))
        self.assertGreaterEqual(cb.failures, 0)
        if cb.state == "CLOSED":
            self.assertLess(cb.failures, cb.failure_threshold)

    async def test_concurrent_failures_open_exactly_once_logic(self):
        cb = CircuitBreaker("t", failure_threshold=2)

        async def failing():
            await asyncio.sleep(0)
            raise RuntimeError("x")

        await asyncio.gather(*[cb.call(failing) for _ in range(5)], return_exceptions=True)
        self.assertEqual(cb.state, "OPEN")
        self.assertGreaterEqual(cb.failures, 2)


# ───────────────────── failover engine and diagnostics ─────────────────────

class _Provider:
    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    async def do(self, *a):
        self.calls += 1
        r = self.fn(self.calls)
        if isinstance(r, BaseException):
            raise r
        return r


class TestFailoverEngine(unittest.IsolatedAsyncioTestCase):
    def _engine(self, *fns, threshold=2):
        e = ProviderFailoverEngine("T")
        provs = []
        for i, fn in enumerate(fns):
            p = _Provider(fn)
            provs.append(p)
            e.register_provider(p, CircuitBreaker(f"P{i}", failure_threshold=threshold))
        return e, provs

    async def test_all_cooling_down_raises_subclass_with_retry_after(self):
        e, _ = self._engine(lambda n: RuntimeError("x"), lambda n: RuntimeError("x"), threshold=1)
        with self.assertRaises(NoProvidersAvailableError):
            await e.execute("do")
        with self.assertRaises(ProvidersCoolingDownError) as ctx:
            await e.execute("do")
        self.assertTrue(0 < ctx.exception.retry_after <= 60)
        self.assertIsInstance(ctx.exception, NoProvidersAvailableError)

    async def test_first_failure_round_is_plain_unavailable_not_cooldown(self):
        e, _ = self._engine(lambda n: RuntimeError("x"), lambda n: RuntimeError("x"))
        with self.assertRaises(NoProvidersAvailableError) as ctx:
            await e.execute("do")
        self.assertNotIsInstance(ctx.exception, ProvidersCoolingDownError)

    async def test_mixed_open_and_real_failure_is_unavailable(self):
        e = ProviderFailoverEngine("T")
        e.register_provider(_Provider(lambda n: RuntimeError("x")), CircuitBreaker("P0", failure_threshold=1))
        e.register_provider(_Provider(lambda n: RuntimeError("y")), CircuitBreaker("P1", failure_threshold=5))
        with self.assertRaises(NoProvidersAvailableError):
            await e.execute("do")                      # P0 opens, P1 fails genuinely
        with self.assertRaises(NoProvidersAvailableError) as ctx:
            await e.execute("do")                      # P0 skipped (open), P1 fails genuinely
        self.assertNotIsInstance(ctx.exception, ProvidersCoolingDownError)

    async def test_no_providers_is_plain_unavailable(self):
        with self.assertRaises(NoProvidersAvailableError) as ctx:
            await ProviderFailoverEngine("T").execute("do")
        self.assertNotIsInstance(ctx.exception, ProvidersCoolingDownError)

    async def test_failover_and_success_still_work(self):
        e, provs = self._engine(lambda n: RuntimeError("x"), lambda n: "second")
        self.assertEqual(await e.execute("do"), "second")
        self.assertEqual([p.calls for p in provs], [1, 1])

    async def test_genuine_failures_count_against_the_breaker(self):
        errors = {
            "429": ProviderAPIError("HTTP 429", status=429, kind="rate_limited"),
            "500": ProviderAPIError("HTTP 500", status=500, kind="server_error"),
            "dns": ClientConnectorDNSError("dns"),
            "gaierror": socket.gaierror(-2, "x"),
            "tls": ssl.SSLError("tls"),
            "timeout": asyncio.TimeoutError(),
            "refused": ConnectionRefusedError("refused"),
        }
        for name, exc in errors.items():
            with self.subTest(name):
                e, _ = self._engine(lambda n, _e=exc: _e, lambda n: "ok")
                self.assertEqual(await e.execute("do"), "ok")
                self.assertEqual(e.providers[0][1].failures, 1)

    async def test_classification_kinds(self):
        cases = {
            "rate_limited": ProviderAPIError("x", status=429, kind="rate_limited"),
            "server_error": ProviderAPIError("x", status=503, kind="server_error"),
            "dns": ClientConnectorDNSError("x"),
            "tls": ssl.SSLError("x"),
            "timeout": asyncio.TimeoutError(),
            "connect": ConnectionRefusedError("x"),
            "circuit_open": CircuitOpenError("x"),
            "other": ValueError("x"),
        }
        for kind, exc in cases.items():
            with self.subTest(kind):
                self.assertEqual(provider_diag.classify_failure(exc)[0], kind)
        self.assertEqual(provider_diag.classify_failure(cases["rate_limited"]), ("rate_limited", 429))

    async def test_logs_are_structured_and_contain_no_url(self):
        secret_url = "https://in.pinterest.com/search/pins/?rs=typed&q=Kai+hiwatari"
        e, _ = self._engine(lambda n: RuntimeError(f"failed for {secret_url} token=abc"), lambda n: "ok")
        with self.assertLogs("ShadePlatform", level="INFO") as cm:
            await e.execute("do")
        joined = "\n".join(str(r.msg) for r in cm.records)
        for needle in ("pinterest", "Kai", "https://", "rs=typed"):
            self.assertNotIn(needle, joined)
        fail = next(r.msg for r in cm.records if isinstance(r.msg, dict) and r.msg["event"] == "provider_failover")
        self.assertEqual(fail["failed_provider"], "P0")
        self.assertEqual(fail["kind"], "other")
        self.assertIn("breaker_state", fail)
        self.assertTrue(any(isinstance(r.msg, dict) and r.msg["event"] == "provider_success" for r in cm.records))

    def test_safe_preview(self):
        out = provider_diag.safe_preview("<b>Error</b> see https://x.test/a?b=c and www.y.test now\u0000" + "z" * 200)
        self.assertNotIn("x.test", out)
        self.assertNotIn("www.y", out)
        self.assertNotIn("<b>", out)
        self.assertLessEqual(len(out), 80)


# ───────────────── real providers, mocked HTTP responses ─────────────────

class TestProvidersMocked(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_urls_succeed_and_arrive_intact(self):
        for url in (PIN, GH, EX):
            with self.subTest(url=url):
                e, c, v = make_engine(cleanuri_ok, vgd_ok)
                self.assertEqual(await e.execute("create_short_url", url), "https://cleanuri.com/abc123")
                self.assertEqual(c.sent, [url])
                self.assertEqual(v.calls, 0)

    async def test_pinterest_query_intact_for_both_providers(self):
        e, c, v = make_engine(boom(ClientConnectorError("down")), vgd_ok)
        self.assertEqual(await e.execute("create_short_url", PIN), "https://v.gd/Nlkqlc")
        self.assertEqual(c.sent, [PIN])
        self.assertEqual(v.sent, [PIN])           # '?', '&', '=' and '+' survive the round trip

    async def test_vgd_request_format_matches_documented_endpoint(self):
        seen = {}

        class S(FakeSession):
            def get(self, url, **kw):
                seen["url"] = url
                return super().get(url, **kw)

        s = S(vgd_ok)
        await PROVIDERS.VGdURLProvider(s).create_short_url(PIN)
        self.assertTrue(seen["url"].startswith("https://v.gd/create.php?format=simple&url=https%3A%2F%2F"))
        self.assertIn("q%3DKai%2Bhiwatari", seen["url"])

    async def test_same_url_repeatedly_no_artificial_lockout(self):
        # CleanURI genuinely dead, v.gd healthy: v.gd must never be locked out.
        e, _c, v = make_engine(boom(ClientConnectorError("down")), vgd_ok)
        for _ in range(12):
            self.assertEqual(await e.execute("create_short_url", PIN), "https://v.gd/Nlkqlc")
        vb = e.providers[1][1]
        self.assertEqual((vb.state, vb.failures), ("CLOSED", 0))
        self.assertEqual(v.calls, 12)

    async def test_different_urls_consecutively(self):
        e, _c, v = make_engine(boom(ClientConnectorError("down")), vgd_ok)
        for url in (PIN, GH, EX, PIN, GH):
            self.assertEqual(await e.execute("create_short_url", url), "https://v.gd/Nlkqlc")
        self.assertEqual(v.sent, [PIN, GH, EX, PIN, GH])

    async def test_observed_sequence_no_longer_locks_out(self):
        # Live sequence: Pinterest ok, v.gd link, Pinterest, Pinterest. v.gd refuses its own
        # links (HYPOTHETICAL provider behaviour) and carries one older failure.
        def vgd(u, n):
            return Resp(400, "Error: nope") if "v.gd/" in u else Resp(200, "https://v.gd/Nlkqlc")

        e, _c, _v = make_engine(boom(ClientConnectorError("down")), vgd)
        e.providers[1][1].failures = 1            # stale count from an earlier incident
        await e.execute("create_short_url", PIN)  # success clears it
        self.assertEqual(e.providers[1][1].failures, 0)
        with self.assertRaises(NoProvidersAvailableError):
            await e.execute("create_short_url", VG)
        for _ in range(2):
            self.assertEqual(await e.execute("create_short_url", PIN), "https://v.gd/Nlkqlc")

    async def test_cleanuri_failures_open_only_when_consecutive(self):
        flip = {"n": 0}

        def cleanuri(u, n):
            flip["n"] += 1
            return ClientConnectorError("x") if flip["n"] % 2 else cleanuri_ok(u, n)

        e, _c, _v = make_engine(cleanuri, vgd_ok)
        for _ in range(10):
            await e.execute("create_short_url", EX)
        self.assertEqual(e.providers[0][1].state, "CLOSED")

    async def test_cleanuri_failure_modes_counted_and_sanitised(self):
        cases = [
            (Resp(429, "<html>slow down</html>"), "rate_limited", 429),
            (Resp(500, "oops"), "server_error", 500),
            (Resp(200, "<html>not json</html>"), "bad_response", 200),
            (Resp(200, json.dumps({"error": f"bad url {PIN}"})), "bad_response", 200),
            (Resp(200, json.dumps({"result_url": ""})), "bad_response", 200),
        ]
        for resp, kind, status in cases:
            with self.subTest(kind=kind, status=status):
                prov = PROVIDERS.CleanURIProvider(FakeSession(lambda u, n, _r=resp: _r))
                with self.assertRaises(ProviderAPIError) as ctx:
                    await prov.create_short_url(PIN)
                self.assertEqual((ctx.exception.kind, ctx.exception.status), (kind, status))
                self.assertNotIn("pinterest", str(ctx.exception))

    async def test_vgd_failure_modes_counted_and_sanitised(self):
        cases = [
            (Resp(429, "Error: rate limit"), "rate_limited", 429),
            (Resp(503, "x"), "server_error", 503),
            (Resp(200, f"Error: cannot shorten {PIN}"), "bad_response", 200),
        ]
        for resp, kind, status in cases:
            with self.subTest(kind=kind):
                prov = PROVIDERS.VGdURLProvider(FakeSession(lambda u, n, _r=resp: _r))
                with self.assertLogs("ShadePlatform", level="WARNING") as cm, \
                        self.assertRaises(ProviderAPIError) as ctx:
                    await prov.create_short_url(PIN)
                self.assertEqual((ctx.exception.kind, ctx.exception.status), (kind, status))
                self.assertNotIn("pinterest", str(ctx.exception))
                self.assertNotIn("pinterest", "\n".join(str(r.msg) for r in cm.records))

    async def test_transport_failures_count_as_provider_failures(self):
        for name, exc in {
            "dns": ClientConnectorDNSError("x"),
            "tls": ssl.SSLError("x"),
            "timeout": asyncio.TimeoutError(),
            "connect": ClientConnectorError("x"),
        }.items():
            with self.subTest(name):
                e, _c, _v = make_engine(boom(exc), boom(exc))
                with self.assertRaises(NoProvidersAvailableError):
                    await e.execute("create_short_url", EX)
                self.assertEqual([b.failures for _, b in e.providers], [1, 1])

    async def test_http_400_is_still_a_provider_failure(self):
        # CHG-030 item B (verified URL rejection) is intentionally NOT implemented: the
        # providers' real rejection formats were not verified. A 400 therefore counts as
        # an ordinary failure; only 429/5xx/transport errors were required to do so.
        e, _c, _v = make_engine(lambda u, n: Resp(400, "x"), lambda u, n: Resp(400, "Error: x"))
        with self.assertRaises(NoProvidersAvailableError):
            await e.execute("create_short_url", EX)
        self.assertEqual([b.failures for _, b in e.providers], [1, 1])
        self.assertFalse(hasattr(provider_diag, "url_rejected"))

    async def test_cooldown_then_recovery_end_to_end(self):
        down = {"on": True}

        def vgd(u, n):
            return ClientConnectorError("x") if down["on"] else vgd_ok(u, n)

        e, c, v = make_engine(boom(ClientConnectorError("x")), vgd)
        for _ in range(2):
            with self.assertRaises(NoProvidersAvailableError):
                await e.execute("create_short_url", EX)
        calls = (c.calls, v.calls)
        with self.assertRaises(ProvidersCoolingDownError):
            await e.execute("create_short_url", EX)
        self.assertEqual((c.calls, v.calls), calls)           # no network while cooling down
        down["on"] = False
        for _, b in e.providers:
            b.last_failure_time -= 61
        self.assertEqual(await e.execute("create_short_url", EX), "https://v.gd/Nlkqlc")


# ───────────────────────── C: already-shortened links ─────────────────────────

class TestKnownShortLink(unittest.TestCase):
    def test_detected(self):
        for raw, host in [
            (VG, "v.gd"), ("http://V.GD/abc", "v.gd"), ("v.gd/abc", "v.gd"),
            ("https://www.is.gd/x", "is.gd"), ("https://cleanuri.com/abc", "cleanuri.com"),
            ("https://v.gd./abc", "v.gd"), ("https://evil.example@v.gd/abc", "v.gd"),
        ]:
            with self.subTest(raw):
                self.assertEqual(sl.known_short_link_host(raw), host)

    def test_not_detected(self):
        for raw in [
            PIN, GH, EX, "https://v.gd/", "https://v.gd", "https://v.gd.evil.com/x",
            "https://evil.com/v.gd/abc", "https://v.gd@evil.com/x", "https://bit.ly/abc",
            "hello", "", "ftp://v.gd/abc", "https://v.gd/a b", "https://[::1/x",
        ]:
            with self.subTest(raw):
                self.assertIsNone(sl.known_short_link_host(raw))

    def test_scope_is_narrow(self):
        self.assertEqual(sl.KNOWN_SHORT_LINK_HOSTS, frozenset({"v.gd", "is.gd", "cleanuri.com"}))


# ───────────────────────── D: /short handler messages ─────────────────────────

class TestCmdShortHandler(unittest.IsolatedAsyncioTestCase):
    def _handler(self, expand_calls):
        src = (PROJECT_ROOT / "app/features/media/router.py").read_text()
        node = next(n for n in ast.parse(src).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "cmd_short")
        node.decorator_list = []
        import html as _html
        logged = []
        ns = {
            "_html": _html, "_sl": sl, "Message": object, "ShortenerService": object,
            "NoProvidersAvailableError": NoProvidersAvailableError,
            "ProvidersCoolingDownError": ProvidersCoolingDownError,
            "logger": types.SimpleNamespace(info=lambda e: logged.append(e), warning=lambda e: None),
        }

        async def fake_expand(message, raw_url, bootstrap_ref=None):
            expand_calls.append(raw_url)

        ns["_cmd_short_expand"] = fake_expand
        exec(compile(ast.Module(body=[node], type_ignores=[]), "router_extract", "exec"), ns)  # noqa: S102
        self.logged = logged
        return ns["cmd_short"]

    async def _run(self, text, service):
        replies = []

        class Msg:
            def __init__(self, t):
                self.text = t

            async def reply(self_, t, **kw):
                replies.append((t, kw))

        expand = []
        await self._handler(expand)(Msg(text), service, object())
        return replies, expand

    class Service:
        def __init__(self, result=None, exc=None):
            self.result, self.exc, self.calls = result, exc, []

        async def shorten_url(self, url):
            self.calls.append(url)
            if self.exc:
                raise self.exc
            return self.result

    async def test_success_message_unchanged_and_url_intact(self):
        svc = self.Service("https://v.gd/Nlkqlc")
        replies, _ = await self._run(f"/short {PIN}", svc)
        self.assertEqual(svc.calls, [PIN])
        self.assertEqual(replies, [("🌐 <b>Shortened Direct Link:</b>\nhttps://v.gd/Nlkqlc", {"parse_mode": "HTML"})])

    async def test_github_and_example_pass_through(self):
        for u in (GH, EX):
            svc = self.Service("https://v.gd/x")
            await self._run(f"/short {u}", svc)
            self.assertEqual(svc.calls, [u])

    async def test_already_shortened_makes_no_provider_call(self):
        svc = self.Service("never")
        replies, _ = await self._run(f"/short {VG}", svc)
        self.assertEqual(svc.calls, [])
        self.assertEqual(len(replies), 1)
        text = replies[0][0]
        self.assertIn("already shortened (v.gd)", text)
        self.assertIn("/short expand", text)
        self.assertEqual(self.logged, [{"event": "short_already_shortened", "host": "v.gd"}])
        self.assertNotIn("Nlkqlc", str(self.logged))

    async def test_cooldown_message(self):
        exc = ProvidersCoolingDownError("x", retry_after=41.2)
        replies, _ = await self._run(f"/short {EX}", self.Service(exc=exc))
        self.assertIn("cooling down", replies[0][0])
        self.assertIn("about 42 seconds", replies[0][0])

    async def test_cooldown_seconds_are_clamped(self):
        for ra, expected in ((0, 1), (0.2, 1), (500, 60)):
            replies, _ = await self._run(f"/short {EX}", self.Service(exc=ProvidersCoolingDownError("x", retry_after=ra)))
            self.assertIn(f"about {expected} seconds", replies[0][0])

    async def test_all_providers_unavailable_message(self):
        replies, _ = await self._run(f"/short {EX}", self.Service(exc=NoProvidersAvailableError("x")))
        self.assertIn("every provider failed", replies[0][0])

    async def test_messages_are_distinct(self):
        texts = set()
        for svc in (self.Service("https://v.gd/a"), self.Service(exc=ProvidersCoolingDownError("x", retry_after=5)),
                    self.Service(exc=NoProvidersAvailableError("x"))):
            replies, _ = await self._run(f"/short {EX}", svc)
            texts.add(replies[0][0])
        replies, _ = await self._run(f"/short {VG}", self.Service("n"))
        texts.add(replies[0][0])
        self.assertEqual(len(texts), 4)
        self.assertNotIn("Service is temporarily unavailable", " ".join(texts))

    async def test_other_errors_propagate_to_middleware(self):
        with self.assertRaises(RuntimeError):
            await self._run(f"/short {EX}", self.Service(exc=RuntimeError("boom")))

    async def test_usage_and_expand_routing_unchanged(self):
        svc = self.Service("n")
        replies, expand = await self._run("/short", svc)
        self.assertIn("Usage", replies[0][0])
        replies, expand = await self._run(f"/short expand {VG}", svc)
        self.assertEqual((replies, expand, svc.calls), ([], [VG], []))     # v.gd link still expandable

    async def test_extra_words_after_url_ignored_like_before(self):
        svc = self.Service("https://v.gd/x")
        await self._run(f"/short {EX} trailing words", svc)
        self.assertEqual(svc.calls, [EX])


# ───────────────────────── OCR shares the breaker/engine ─────────────────────────

class TestOcrRegression(unittest.IsolatedAsyncioTestCase):
    def _service(self, primary_fn, fallback_text=""):
        OCRService = _ocr_service_cls()

        class Prov:
            def __init__(self, fn):
                self.fn, self.calls = fn, 0

            async def parse_image(self, data):
                self.calls += 1
                r = self.fn(self.calls)
                if isinstance(r, BaseException):
                    raise r
                return r

        primary, fallback = Prov(primary_fn), Prov(lambda n: fallback_text)
        engine = ProviderFailoverEngine("OCR")
        engine.register_provider(primary, CircuitBreaker("OCRSpace", failure_threshold=2))
        engine.register_provider(fallback, CircuitBreaker("FallbackOCR"))

        class Bus:
            def __init__(self):
                self.events = []

            def publish(self, name, payload):
                self.events.append((name, payload))

        bus = Bus()
        return OCRService(engine, bus), engine, primary, fallback, bus

    async def test_primary_success(self):
        svc, _e, _p, f, bus = self._service(lambda n: "hello")
        self.assertEqual(await svc.extract_text(b"x", 1), "hello")
        self.assertEqual(f.calls, 0)
        self.assertEqual(bus.events, [("ocr_processed", {"user_id": 1, "length": 5})])

    async def test_primary_failure_falls_back(self):
        svc, _e, p, f, _bus = self._service(lambda n: ProviderAPIError("OCR API HTTP 500", status=500, kind="server_error"))
        self.assertEqual(await svc.extract_text(b"x", 1), "")
        self.assertEqual((p.calls, f.calls), (1, 1))

    async def test_isolated_ocr_failures_no_longer_accumulate(self):
        svc, e, _p, _f, _bus = self._service(lambda n: RuntimeError("x") if n % 2 else "text")
        for _ in range(10):
            await svc.extract_text(b"x", 1)
        self.assertEqual(e.providers[0][1].state, "CLOSED")

    async def test_consecutive_ocr_failures_still_open_primary_and_fallback_serves(self):
        svc, e, p, f, _bus = self._service(lambda n: RuntimeError("x"))
        for _ in range(4):
            self.assertEqual(await svc.extract_text(b"x", 1), "")
        self.assertEqual(e.providers[0][1].state, "OPEN")
        self.assertEqual(p.calls, 2)              # not called again while OPEN
        self.assertEqual(f.calls, 4)

    async def test_ocr_primary_recovers_after_cooldown(self):
        mode = {"fail": True}
        svc, e, _p, _f, _bus = self._service(lambda n: RuntimeError("x") if mode["fail"] else "back")
        for _ in range(2):
            await svc.extract_text(b"x", 1)
        mode["fail"] = False
        e.providers[0][1].last_failure_time -= 61
        self.assertEqual(await svc.extract_text(b"x", 1), "back")
        self.assertEqual((e.providers[0][1].state, e.providers[0][1].failures), ("CLOSED", 0))

    async def test_all_ocr_providers_failing_still_raises_for_the_middleware(self):
        OCRService = _ocr_service_cls()
        e = ProviderFailoverEngine("OCR")

        class Bad:
            async def parse_image(self, d):
                raise RuntimeError("x")

        e.register_provider(Bad(), CircuitBreaker("a", failure_threshold=1))
        svc = OCRService(e, types.SimpleNamespace(publish=lambda *a: None))
        with self.assertRaises(NoProvidersAvailableError):
            await svc.extract_text(b"x", 1)
        with self.assertRaises(NoProvidersAvailableError) as ctx:      # now cooling down
            await svc.extract_text(b"x", 1)
        # the frozen middleware catches NoProvidersAvailableError, so the subclass is handled identically
        self.assertIsInstance(ctx.exception, ProvidersCoolingDownError)
        self.assertTrue(issubclass(ProvidersCoolingDownError, NoProvidersAvailableError))

    async def test_real_dummy_ocr_fallback_unchanged(self):
        ocr = _load("app/providers/ocr_providers.py", "ocr_providers_under_test")
        self.assertEqual(await ocr.DummyFallbackOCRProvider(object()).parse_image(b"x"), "")

    def test_provider_api_error_backward_compatible(self):
        e = ProviderAPIError("plain message")
        self.assertEqual((str(e), e.status, e.kind), ("plain message", None, None))


class TestScope(unittest.TestCase):
    def test_frozen_error_middleware_text_unchanged(self):
        src = (PROJECT_ROOT / "app/middlewares/error.py").read_text()
        self.assertIn("⚠️ Service is temporarily unavailable. Please try again later.", src)
        self.assertNotIn("ProvidersCoolingDownError", src)

    def test_expand_path_untouched_by_short_changes(self):
        src = (PROJECT_ROOT / "app/features/media/router.py").read_text()
        self.assertIn("await _cmd_short_expand(message, args[2].strip(), bootstrap_ref)", src)
        self.assertIn("_expansion_text(result.hops, result.truncated)", src)   # CHG-029 intact


if __name__ == "__main__":
    unittest.main()
