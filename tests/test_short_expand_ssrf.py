"""
CHG-024 — /short expand SSRF hardening tests.

All DNS and HTTP behaviour is faked and deterministic: no real network
traffic, no real internal services, no port scanning.

Layers covered
--------------
1. validate_public_http_url  -- URL policy (schemes, credentials, ports, hosts)
2. is_prohibited_ip          -- destination-address policy (IPv4/IPv6/mapped)
3. GuardedResolver           -- the connection-time enforcement point that is
                                plugged into aiohttp's TCPConnector
4. trace_redirects           -- per-hop validation, limits, loops, timeouts
5. Wiring                    -- the guarded session really is what the
                                handler/bootstrap use (AST/source checks)
6. aiohttp integration       -- real TCPConnector + GuardedResolver; SKIPPED
                                when aiohttp is not installed

Layers 1-5 need only the standard library and run everywhere.
"""

import asyncio
import ast
import ipaddress
import socket
import unittest
from pathlib import Path

from app.utils import safe_url as su

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _entry(host: str, family=None):
    ip = ipaddress.ip_address(host)
    return {
        "hostname": "x", "host": host, "port": 443,
        "family": family or (socket.AF_INET6 if ip.version == 6 else socket.AF_INET),
        "proto": 0, "flags": 0,
    }


class FakeBaseResolver:
    """Scripted resolver. answers[host] is a list of results, one per call
    (the last is repeated), so DNS rebinding can be simulated."""

    def __init__(self, answers):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.calls = []

    async def resolve(self, host, port=0, family=socket.AF_INET):
        self.calls.append(host)
        seq = self.answers.get(host)
        if seq is None:
            raise OSError("NXDOMAIN")
        result = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(result, Exception):
            raise result
        return result


def run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# 1. URL validation
# ─────────────────────────────────────────────────────────────────────────────

class TestUrlValidation(unittest.TestCase):

    def _code(self, url):
        with self.assertRaises(su.UnsafeURLError) as cm:
            su.validate_public_http_url(url)
        return cm.exception.code

    def test_valid_public_urls_accepted(self):
        for url in (
            "http://8.8.8.8/",
            "https://example.com/a?b=1",
            "http://[2606:4700:4700::1111]/x",
            "https://example.com:8443/path",
            "http://xn--bcher-kva.example/",
        ):
            with self.subTest(url=url):
                self.assertTrue(su.validate_public_http_url(url).url)

    def test_fragment_dropped_and_host_normalised(self):
        t = su.validate_public_http_url("HTTPS://EXAMPLE.com./p#frag")
        self.assertEqual(t.host, "example.com")
        self.assertEqual(t.url, "https://example.com/p")
        self.assertEqual(t.port, 443)

    def test_unicode_host_idna_encoded(self):
        t = su.validate_public_http_url("http://bücher.example/")
        self.assertEqual(t.host, "xn--bcher-kva.example")

    def test_unsupported_schemes(self):
        for url in ("ftp://example.com/", "file:///etc/passwd", "gopher://example.com/",
                    "javascript:alert(1)", "data:text/plain,hi"):
            with self.subTest(url=url):
                self.assertEqual(self._code(url), "scheme")

    def test_embedded_credentials_rejected(self):
        for url in ("http://user:pw@example.com/", "http://user@example.com/",
                    "http://@example.com/", "http://example.com@evil.example/"):
            with self.subTest(url=url):
                self.assertEqual(self._code(url), "credentials")

    def test_invalid_ports_rejected(self):
        for url in ("http://example.com:0/", "http://example.com:65536/",
                    "http://example.com:99999/", "http://example.com:abc/",
                    "http://example.com:-1/"):
            with self.subTest(url=url):
                self.assertEqual(self._code(url), "port")

    def test_malformed_urls_rejected(self):
        for url in ("", "   ", "http://", "http:///x", "http://exa mple.com/",
                    "http://example.com/a\nb", "http://example.com\\@evil.example/",
                    "http://[::1/", "http://" + "a" * 3000 + ".com/"):
            with self.subTest(url=url[:40]):
                self.assertIn(self._code(url), ("malformed", "host", "port"))
        with self.assertRaises(su.UnsafeURLError):
            su.validate_public_http_url(None)

    def test_ip_literal_forms_rejected(self):
        """Non-canonical numeric hosts are rejected, never interpreted."""
        for url in ("http://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/",
                    "http://127.1/", "http://127.0.0.1./", "http://1.2.3/"):
            with self.subTest(url=url):
                self.assertEqual(self._code(url), "host")

    def test_prohibited_ip_literals_rejected(self):
        for url in ("http://127.0.0.1/", "http://10.0.0.1/", "http://172.16.0.1/",
                    "http://192.168.1.1/", "http://169.254.169.254/", "http://0.0.0.0/",
                    "http://100.64.0.1/", "http://224.0.0.1/", "http://240.0.0.1/",
                    "http://255.255.255.255/"):
            with self.subTest(url=url):
                self.assertEqual(self._code(url), "blocked")

    def test_bracketed_ipv6_edge_cases(self):
        for url in ("http://[::1]/", "http://[::]/", "http://[fe80::1]/",
                    "http://[fc00::1]/", "http://[ff02::1]/", "http://[2001:db8::1]/",
                    "http://[::ffff:127.0.0.1]/", "http://[::ffff:10.0.0.1]/",
                    "http://[::ffff:169.254.169.254]/", "http://[2002:7f00:1::]/",
                    "http://[64:ff9b::7f00:1]/"):
            with self.subTest(url=url):
                self.assertEqual(self._code(url), "blocked")

    def test_ipv6_zone_id_rejected(self):
        self.assertIn(self._code("http://[fe80::1%25eth0]/"), ("host", "malformed", "port"))

    def test_internal_names_rejected(self):
        for url in ("http://localhost/", "http://localhost./", "http://LOCALHOST/",
                    "http://metadata.google.internal/", "http://printer.local/"):
            with self.subTest(url=url):
                self.assertEqual(self._code(url), "blocked")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Destination-address policy
# ─────────────────────────────────────────────────────────────────────────────

class TestAddressPolicy(unittest.TestCase):

    def _p(self, s):
        return su.is_prohibited_ip(ipaddress.ip_address(s))

    def test_public_addresses_allowed(self):
        for s in ("8.8.8.8", "1.1.1.1", "93.184.216.34",
                  "2606:4700:4700::1111", "2001:4860:4860::8888"):
            with self.subTest(addr=s):
                self.assertFalse(self._p(s))

    def test_prohibited_ipv4(self):
        for s in ("127.0.0.1", "127.255.255.254", "10.1.2.3", "172.16.0.1", "172.31.255.255",
                  "192.168.0.1", "169.254.169.254", "0.0.0.0", "100.64.0.1", "198.18.0.1",
                  "192.0.2.1", "198.51.100.1", "203.0.113.1", "224.0.0.1", "239.255.255.255",
                  "240.0.0.1", "255.255.255.255"):
            with self.subTest(addr=s):
                self.assertTrue(self._p(s))

    def test_prohibited_ipv6(self):
        for s in ("::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1", "2001:db8::1"):
            with self.subTest(addr=s):
                self.assertTrue(self._p(s))

    def test_ipv4_mapped_ipv6_unwrapped(self):
        for s in ("::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:192.168.1.1",
                  "::ffff:169.254.169.254", "::ffff:100.64.0.1", "::ffff:0.0.0.0"):
            with self.subTest(addr=s):
                self.assertTrue(self._p(s))

    def test_ipv4_mapped_public_is_allowed(self):
        self.assertFalse(self._p("::ffff:8.8.8.8"))

    def test_embedded_ipv4_forms(self):
        self.assertTrue(self._p("2002:7f00:1::"))        # 6to4 -> 127.0.0.1
        self.assertTrue(self._p("2002:0a00:0001::"))     # 6to4 -> 10.0.0.1
        self.assertTrue(self._p("64:ff9b::7f00:1"))      # NAT64 -> 127.0.0.1
        self.assertTrue(self._p("64:ff9b::a00:1"))       # NAT64 -> 10.0.0.1


# ─────────────────────────────────────────────────────────────────────────────
# 3. GuardedResolver -- the connection-time enforcement point
# ─────────────────────────────────────────────────────────────────────────────

class TestGuardedResolver(unittest.TestCase):

    def _resolver(self, answers):
        base = FakeBaseResolver(answers)
        return su.GuardedResolver(base), base

    def test_public_answer_returned_unchanged(self):
        r, _ = self._resolver({"example.com": [[_entry("93.184.216.34")]]})
        entries = run(r.resolve("example.com", 443))
        self.assertEqual([e["host"] for e in entries], ["93.184.216.34"])

    def test_public_ipv6_answer_allowed(self):
        r, _ = self._resolver({"example.com": [[_entry("2606:4700:4700::1111")]]})
        self.assertEqual(len(run(r.resolve("example.com", 443))), 1)

    def test_nip_io_style_name_resolving_to_loopback_blocked(self):
        r, _ = self._resolver({"127.0.0.1.nip.io": [[_entry("127.0.0.1")]]})
        with self.assertRaises(su.BlockedDestinationError):
            run(r.resolve("127.0.0.1.nip.io", 80))

    def test_localtest_me_resolving_to_loopback_blocked(self):
        r, _ = self._resolver({"localtest.me": [[_entry("127.0.0.1"), _entry("::1")]]})
        with self.assertRaises(su.BlockedDestinationError):
            run(r.resolve("localtest.me", 80))

    def test_each_prohibited_class_blocked_via_dns(self):
        for ip in ("10.0.0.5", "172.16.4.4", "192.168.1.10", "169.254.169.254", "0.0.0.0",
                   "100.64.1.1", "224.0.0.5", "240.0.0.9", "::1", "fe80::1", "fc00::5",
                   "::ffff:10.0.0.1", "::ffff:127.0.0.1", "2002:7f00:1::"):
            with self.subTest(ip=ip):
                r, _ = self._resolver({"evil.example": [[_entry(ip)]]})
                with self.assertRaises(su.BlockedDestinationError):
                    run(r.resolve("evil.example", 80))

    def test_mixed_public_and_prohibited_answers_fail_closed(self):
        for order in (("93.184.216.34", "10.0.0.1"), ("10.0.0.1", "93.184.216.34")):
            with self.subTest(order=order):
                r, _ = self._resolver({"mixed.example": [[_entry(a) for a in order]]})
                with self.assertRaises(su.BlockedDestinationError):
                    run(r.resolve("mixed.example", 80))

    def test_dns_failure_fails_closed(self):
        r, _ = self._resolver({})  # NXDOMAIN -> OSError from base
        with self.assertRaises(su.DestinationResolutionError):
            run(r.resolve("nope.example", 80))

    def test_resolver_timeout_fails_closed(self):
        class Slow:
            async def resolve(self, *a, **k):
                await asyncio.sleep(5)
        r = su.GuardedResolver(Slow(), timeout=0.05)
        with self.assertRaises(su.DestinationResolutionError):
            run(r.resolve("slow.example", 80))

    def test_malformed_resolver_results_fail_closed(self):
        bad_answers = {
            "empty.example": [[]],
            "none.example": [None],
            "notlist.example": ["93.184.216.34"],
            "nohost.example": [[{"hostname": "x", "port": 80}]],
            "garbage.example": [[{"host": "not-an-ip"}]],
            "notdict.example": [[42]],
            "mixedbad.example": [[_entry("93.184.216.34"), {"host": None}]],
        }
        for name, ans in bad_answers.items():
            with self.subTest(name=name):
                r, _ = self._resolver({name: [ans[0] if name != "empty.example" else []]})
                with self.assertRaises(su.DestinationResolutionError):
                    run(r.resolve(name, 80))

    def test_dns_rebinding_each_resolution_is_validated(self):
        """First answer public, second private: the second is blocked."""
        r, base = self._resolver({
            "rebind.example": [[_entry("93.184.216.34")], [_entry("127.0.0.1")]],
        })
        self.assertEqual(run(r.resolve("rebind.example", 80))[0]["host"], "93.184.216.34")
        with self.assertRaises(su.BlockedDestinationError):
            run(r.resolve("rebind.example", 80))
        self.assertEqual(len(base.calls), 2, "resolver must not cache between connections")

    def test_dns_rebinding_private_then_public_still_blocked_first(self):
        r, _ = self._resolver({
            "rebind2.example": [[_entry("10.0.0.1")], [_entry("93.184.216.34")]],
        })
        with self.assertRaises(su.BlockedDestinationError):
            run(r.resolve("rebind2.example", 80))
        self.assertEqual(run(r.resolve("rebind2.example", 80))[0]["host"], "93.184.216.34")

    def test_ip_literal_passed_directly_is_validated(self):
        r, base = self._resolver({})
        with self.assertRaises(su.BlockedDestinationError):
            run(r.resolve("127.0.0.1", 80))
        with self.assertRaises(su.BlockedDestinationError):
            run(r.resolve("[::ffff:10.0.0.1]", 80))
        self.assertEqual(base.calls, [], "literals must not reach the base resolver")
        self.assertEqual(run(r.resolve("8.8.8.8", 53))[0]["host"], "8.8.8.8")

    def test_scoped_ipv6_answer_checked_without_zone(self):
        r, _ = self._resolver({"z.example": [[{"host": "fe80::1%eth0", "port": 80}]]})
        with self.assertRaises(su.BlockedDestinationError):
            run(r.resolve("z.example", 80))

    def test_blocked_error_is_oserror_so_aiohttp_wraps_it(self):
        self.assertTrue(issubclass(su.BlockedDestinationError, OSError))
        self.assertTrue(issubclass(su.DestinationResolutionError, OSError))
        self.assertFalse(issubclass(su.BlockedDestinationError, TimeoutError))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Redirect tracing
# ─────────────────────────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status, location=None):
        self.status = status
        self.headers = {"Location": location} if location is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Maps URL -> FakeResponse | Exception. Records every requested URL."""

    def __init__(self, routes):
        self.routes = routes
        self.requested = []
        self.kwargs = []

    def head(self, url, **kwargs):
        self.requested.append(url)
        self.kwargs.append(kwargs)
        r = self.routes[url]
        if isinstance(r, BaseException):
            raise r
        return r


class TestRedirectTracing(unittest.TestCase):

    def _trace(self, routes, start="https://short.example/a", **kw):
        s = FakeSession(routes)
        target = su.validate_public_http_url(start)
        return s, run(su.trace_redirects(s, target, **kw))

    def test_no_redirect(self):
        s, res = self._trace({"https://short.example/a": FakeResponse(200)})
        self.assertEqual(res.hops, ["https://short.example/a"])
        self.assertFalse(res.truncated)

    def test_legitimate_http_and_https_expansion(self):
        s, res = self._trace({
            "http://short.example/a": FakeResponse(301, "https://www.example.com/landing"),
            "https://www.example.com/landing": FakeResponse(200),
        }, start="http://short.example/a")
        self.assertEqual(res.hops, ["http://short.example/a", "https://www.example.com/landing"])

    def test_relative_and_protocol_relative_redirects_resolved(self):
        s, res = self._trace({
            "https://short.example/a": FakeResponse(302, "/b"),
            "https://short.example/b": FakeResponse(302, "//cdn.example/c"),
            "https://cdn.example/c": FakeResponse(200),
        })
        self.assertEqual(res.hops[-1], "https://cdn.example/c")

    def test_head_only_redirects_never_auto_followed_and_no_body_read(self):
        s, _ = self._trace({"https://short.example/a": FakeResponse(200)})
        self.assertFalse(s.kwargs[0]["allow_redirects"])

    def test_redirect_to_loopback_blocked_and_not_requested(self):
        for loc in ("http://127.0.0.1/admin", "http://[::1]/", "http://localhost/",
                    "http://[::ffff:127.0.0.1]/", "http://2130706433/", "http://0x7f.1/"):
            with self.subTest(location=loc):
                s = FakeSession({"https://short.example/a": FakeResponse(302, loc)})
                with self.assertRaises(su.RedirectBlockedError):
                    run(su.trace_redirects(s, su.validate_public_http_url("https://short.example/a")))
                self.assertEqual(s.requested, ["https://short.example/a"],
                                 "the prohibited target must never be requested")

    def test_redirect_to_private_ranges_blocked(self):
        for loc in ("http://10.0.0.1/", "http://192.168.1.1/", "http://172.16.0.9/",
                    "http://169.254.169.254/latest/meta-data/", "http://100.64.0.1/",
                    "http://0.0.0.0/", "http://224.0.0.1/", "http://metadata.google.internal/"):
            with self.subTest(location=loc):
                s = FakeSession({"https://short.example/a": FakeResponse(301, loc)})
                with self.assertRaises(su.RedirectBlockedError):
                    run(su.trace_redirects(s, su.validate_public_http_url("https://short.example/a")))

    def test_redirect_with_bad_scheme_credentials_or_port_blocked(self):
        cases = {"ftp://example.com/": "scheme", "file:///etc/passwd": "scheme",
                 "http://u:p@example.com/": "credentials", "http://example.com:99999/": "port"}
        for loc, code in cases.items():
            with self.subTest(location=loc):
                s = FakeSession({"https://short.example/a": FakeResponse(302, loc)})
                with self.assertRaises(su.RedirectBlockedError) as cm:
                    run(su.trace_redirects(s, su.validate_public_http_url("https://short.example/a")))
                self.assertEqual(cm.exception.code, code)

    def test_oversized_location_header_blocked(self):
        s = FakeSession({"https://short.example/a": FakeResponse(302, "https://x.example/" + "a" * 5000)})
        with self.assertRaises(su.RedirectBlockedError):
            run(su.trace_redirects(s, su.validate_public_http_url("https://short.example/a")))

    def test_multi_hop_chain_followed(self):
        routes = {f"https://h{i}.example/": FakeResponse(302, f"https://h{i+1}.example/") for i in range(3)}
        routes["https://h3.example/"] = FakeResponse(200)
        s, res = self._trace(routes, start="https://h0.example/")
        self.assertEqual(len(res.hops), 4)
        self.assertFalse(res.truncated)

    def test_redirect_limit_enforced_and_reported(self):
        routes = {f"https://h{i}.example/": FakeResponse(302, f"https://h{i+1}.example/") for i in range(50)}
        s, res = self._trace(routes, start="https://h0.example/")
        self.assertTrue(res.truncated)
        self.assertEqual(len(res.hops), su.MAX_REDIRECTS + 1)
        self.assertEqual(len(s.requested), su.MAX_REDIRECTS + 1, "bounded number of requests")

    def test_redirect_loop_detected(self):
        routes = {"https://a.example/": FakeResponse(302, "https://b.example/"),
                  "https://b.example/": FakeResponse(302, "https://a.example/")}
        s = FakeSession(routes)
        with self.assertRaises(su.RedirectLoopError):
            run(su.trace_redirects(s, su.validate_public_http_url("https://a.example/")))
        self.assertLessEqual(len(s.requested), 3)

    def test_self_redirect_loop_detected_despite_case_and_fragment(self):
        routes = {"https://a.example/x": FakeResponse(302, "HTTPS://A.EXAMPLE./x#f")}
        with self.assertRaises(su.RedirectLoopError):
            run(su.trace_redirects(FakeSession(routes), su.validate_public_http_url("https://a.example/x")))

    def test_redirect_without_location_is_final(self):
        s, res = self._trace({"https://short.example/a": FakeResponse(302)})
        self.assertEqual(res.hops, ["https://short.example/a"])

    def test_overall_deadline_enforced(self):
        class Hang:
            def head(self, url, **kw):
                class _R:
                    async def __aenter__(self):
                        await asyncio.sleep(5)
                    async def __aexit__(self, *e):
                        return False
                return _R()
        with self.assertRaises(asyncio.TimeoutError):
            run(su.trace_redirects(Hang(), su.validate_public_http_url("https://a.example/"),
                                   total_timeout=0.05))

    def test_network_errors_propagate_for_classification(self):
        s = FakeSession({"https://short.example/a": ConnectionResetError("boom 10.1.2.3")})
        with self.assertRaises(ConnectionResetError):
            run(su.trace_redirects(s, su.validate_public_http_url("https://short.example/a")))


class TestErrorClassification(unittest.TestCase):

    def test_blocked_found_through_os_error_and_cause_chain(self):
        class Wrapper(Exception):  # stands in for aiohttp.ClientConnectorError
            def __init__(self, inner):
                super().__init__("wrapped")
                self.os_error = inner
        blocked = su.BlockedDestinationError("x")
        self.assertEqual(su.classify_network_error(Wrapper(blocked)), "blocked")
        try:
            try:
                raise blocked
            except OSError as e:
                raise RuntimeError("outer") from e
        except RuntimeError as outer:
            self.assertEqual(su.classify_network_error(outer), "blocked")

    def test_timeout_and_generic_network(self):
        self.assertEqual(su.classify_network_error(asyncio.TimeoutError()), "timeout")
        self.assertEqual(su.classify_network_error(ConnectionRefusedError()), "network")
        self.assertEqual(su.classify_network_error(su.DestinationResolutionError("dns")), "network")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Wiring and error-message hygiene (source/AST; no aiogram needed)
# ─────────────────────────────────────────────────────────────────────────────

class TestWiringAndMessages(unittest.TestCase):

    def setUp(self):
        self.router = (PROJECT_ROOT / "app/features/media/router.py").read_text()
        self.boot = (PROJECT_ROOT / "app/core/bootstrap.py").read_text()
        self.mod = (PROJECT_ROOT / "app/utils/safe_url.py").read_text()

    def _fn(self, src, name):
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
                return ast.unparse(n)
        self.fail(f"{name} not found")

    def test_handler_uses_guarded_session_not_a_new_one(self):
        body = self._fn(self.router, "_cmd_short_expand")
        self.assertIn("expand_session", body)
        self.assertNotIn("ClientSession", body, "no per-request session")
        self.assertNotIn("http_session", body, "must not fall back to the unguarded shared session")

    def test_handler_fails_closed_without_guarded_session(self):
        body = self._fn(self.router, "_cmd_short_expand")
        self.assertIn("temporarily unavailable", body)

    def test_handler_validates_url_and_traces_via_safe_url(self):
        body = self._fn(self.router, "_cmd_short_expand")
        self.assertIn("validate_public_http_url", body)
        self.assertIn("trace_redirects", body)

    def test_logger_defined_in_media_router(self):
        """Regression: the old helper logged through an undefined name."""
        self.assertIn("logger = setup_logger()", self.router)

    def test_user_messages_do_not_echo_hosts_or_exception_text(self):
        body = self._fn(self.router, "_cmd_short_expand")
        for leaked in ("redir_host", "str(exc)", "{exc}", "exc.args", "repr(exc)"):
            self.assertNotIn(leaked, body)
        # exception class names go to logs only, never into reply text
        self.assertNotIn("type(exc).__name__)}", body)

    def test_bootstrap_owns_and_closes_guarded_session(self):
        self.assertIn("self.expand_session = create_guarded_session()", self.boot)
        self.assertIn("self.expand_session.close()", self.boot)

    def test_bootstrap_shutdown_order_still_ends_with_http_resources(self):
        body = self._fn(self.boot, "on_shutdown")
        self.assertTrue(body.rstrip().rstrip("'").endswith("logger.info({'event': 'shutdown_complete'})"))
        self.assertIn("_close_http_resources", body)

    def test_guarded_session_configuration(self):
        body = self._fn(self.mod, "create_guarded_session")
        for needle in ("GuardedResolver()", "use_dns_cache=False", "DummyCookieJar",
                       "trust_env=False", "ClientTimeout"):
            self.assertIn(needle, body)

    def test_policy_constants_are_bounded(self):
        self.assertLessEqual(su.MAX_REDIRECTS, 10)
        self.assertLessEqual(su.TOTAL_DEADLINE, 30)
        self.assertLessEqual(su.MAX_URL_LENGTH, 4096)

    def test_frozen_session_router_untouched(self):
        import hashlib
        digest = hashlib.md5((PROJECT_ROOT / "app/features/session/router.py").read_bytes()).hexdigest()
        self.assertEqual(digest, "c61dcc219b29736e228bdc1d0915d82d")

    def test_existing_is_safe_host_guard_not_weakened(self):
        from app.utils.network import is_safe_host
        for h in ("127.0.0.1", "localhost", "10.0.0.1", "169.254.169.254", "100.64.0.1",
                  "2130706433", "0x7f000001", "0177.0.0.1", "metadata.google.internal"):
            self.assertFalse(is_safe_host(h), h)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Real aiohttp integration (skipped when aiohttp is not installed)
# ─────────────────────────────────────────────────────────────────────────────

def _have_aiohttp():
    try:
        import aiohttp  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_have_aiohttp(), "aiohttp not installed")
class TestAiohttpConnectionPathEnforcement(unittest.IsolatedAsyncioTestCase):
    """Proves aiohttp's real connector routes name resolution through the guard.

    The fake base resolver maps public-looking names to prohibited addresses.
    If enforcement were bypassed aiohttp would try to connect to 127.0.0.1:9
    (discard port; nothing listens) -- a refused connection, not a block.
    """

    async def _session(self, answers):
        import aiohttp
        base = FakeBaseResolver(answers)
        connector = aiohttp.TCPConnector(resolver=su.GuardedResolver(base), use_dns_cache=False)
        return aiohttp.ClientSession(connector=connector, trust_env=False), base

    async def test_hostname_resolving_to_loopback_blocked_by_connector(self):
        session, base = await self._session({"127.0.0.1.nip.io": [[_entry("127.0.0.1")]]})
        async with session:
            with self.assertRaises(Exception) as cm:
                async with session.head("http://127.0.0.1.nip.io:9/", allow_redirects=False):
                    pass
        self.assertEqual(su.classify_network_error(cm.exception), "blocked")
        self.assertEqual(base.calls, ["127.0.0.1.nip.io"])

    async def test_rebinding_second_connection_blocked_by_connector(self):
        session, _ = await self._session(
            {"rebind.example": [[_entry("10.0.0.1")], [_entry("127.0.0.1")]]})
        async with session:
            for _ in range(2):
                with self.assertRaises(Exception) as cm:
                    async with session.head("http://rebind.example:9/", allow_redirects=False):
                        pass
                self.assertEqual(su.classify_network_error(cm.exception), "blocked")

    async def test_mixed_answers_blocked_by_connector(self):
        session, _ = await self._session(
            {"mixed.example": [[_entry("93.184.216.34"), _entry("10.0.0.1")]]})
        async with session:
            with self.assertRaises(Exception) as cm:
                async with session.head("http://mixed.example:9/", allow_redirects=False):
                    pass
        self.assertEqual(su.classify_network_error(cm.exception), "blocked")

    async def test_dns_failure_is_not_reported_as_blocked(self):
        session, _ = await self._session({})
        async with session:
            with self.assertRaises(Exception) as cm:
                async with session.head("http://nxdomain.example:9/", allow_redirects=False):
                    pass
        self.assertEqual(su.classify_network_error(cm.exception), "network")

    async def test_ip_literal_urls_never_reach_connector(self):
        """aiohttp skips the resolver for literals; policy must stop them earlier."""
        for url in ("http://127.0.0.1:9/", "http://[::1]:9/"):
            with self.assertRaises(su.UnsafeURLError):
                su.validate_public_http_url(url)

    async def test_client_parser_agrees_with_validator_host(self):
        t = su.validate_public_http_url("https://EXAMPLE.com./a")
        su._same_host_as_client_parser(t)  # must not raise

    async def test_create_guarded_session_is_configured(self):
        session = su.create_guarded_session()
        try:
            self.assertIsInstance(session.connector._resolver, su.GuardedResolver)
            self.assertFalse(session.trust_env)
            self.assertEqual(type(session.cookie_jar).__name__, "DummyCookieJar")
        finally:
            await session.close()


class TestExpandResultMessages(unittest.IsolatedAsyncioTestCase):
    """CHG-025 — user-facing text of _cmd_short_expand for each outcome.

    The handler's source is extracted from media/router.py (aiogram is not
    needed) and run against a fake message and a fake trace_redirects, so no
    network is used. Only message text is under test; SSRF logic is in
    safe_url and covered elsewhere in this file.
    """

    URL = "https://v.gd/UUSMmS"

    def _handler(self, trace):
        import types
        src = (PROJECT_ROOT / "app/features/media/router.py").read_text()
        tree = ast.parse(src)
        wanted = []
        for n in tree.body:
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_cmd_short_expand":
                wanted.append(n)
            elif isinstance(n, ast.Assign) and any(
                getattr(t, "id", "") in ("_EXPAND_URL_ERRORS", "_MAX_REDIRECTS") for t in n.targets
            ):
                wanted.append(n)
        self.assertEqual(len(wanted), 3)
        fake_su = types.SimpleNamespace(**{k: getattr(su, k) for k in dir(su) if not k.startswith("__")})
        fake_su.trace_redirects = trace
        quiet = types.SimpleNamespace(warning=lambda *a, **k: None)
        ns = {"_su": fake_su, "logger": quiet}
        exec(compile(ast.Module(body=wanted, type_ignores=[]), "router_extract", "exec"), ns)
        return ns["_cmd_short_expand"]

    async def _run(self, trace, url=None):
        edits = []

        class Status:
            async def edit_text(self_, text, **kw):
                edits.append(text)

        class Msg:
            async def reply(self_, text, **kw):
                return Status()

        class Boot:
            expand_session = type("S", (), {"closed": False})()

        await self._handler(trace)(Msg(), url or self.URL, Boot())
        self.assertEqual(len(edits), 1)
        return edits[0]

    async def test_no_redirect_message_is_clarified(self):
        async def trace(session, target):
            return su.TraceResult([target.url], False)
        text = await self._run(trace)
        self.assertIn("No HTTP redirect was detected", text)
        self.assertIn("landing or preview page", text)
        self.assertIn("actual destination may differ", text)
        self.assertIn(f"<code>{self.URL}</code>", text, "original URL must stay visible")
        self.assertNotIn("No redirects found", text)
        self.assertNotIn("already points directly", text)

    async def test_no_redirect_message_escapes_html(self):
        async def trace(session, target):
            return su.TraceResult([target.url], False)
        text = await self._run(trace, "https://example.com/?a=<b>&c=1")
        self.assertNotIn("<b>&c", text)
        self.assertIn("&lt;b&gt;", text)

    async def test_actual_redirect_result_unchanged(self):
        async def trace(session, target):
            return su.TraceResult([target.url, "https://example.org/final"], False)
        text = await self._run(trace)
        self.assertIn("URL Expansion (1 redirect):", text)
        self.assertIn("1. <code>https://v.gd/UUSMmS</code>", text)
        self.assertIn("2. <code>https://example.org/final</code>", text)
        self.assertIn("✅ <b>Final destination:</b> <code>https://example.org/final</code>", text)
        self.assertNotIn("preview page", text)

    async def test_multi_hop_plural(self):
        async def trace(session, target):
            return su.TraceResult([target.url, "https://a.example/", "https://b.example/"], False)
        text = await self._run(trace)
        self.assertIn("URL Expansion (2 redirects):", text)

    async def test_truncated_chain_unchanged(self):
        async def trace(session, target):
            return su.TraceResult([target.url, "https://a.example/"], True)
        text = await self._run(trace)
        self.assertIn("Stopped after 5 redirects — the chain continues.", text)
        self.assertIn("<b>Last URL reached:</b> <code>https://a.example/</code>", text)
        self.assertNotIn("preview page", text)

    async def test_error_outcomes_unchanged_and_distinct(self):
        cases = [
            (su.RedirectBlockedError("blocked"), "⛔ Redirect to a private, internal or invalid destination blocked."),
            (su.RedirectBlockedError("scheme"), "⛔ Redirect to non-HTTP scheme blocked."),
            (su.RedirectLoopError(), "⛔ Redirect loop detected — expansion stopped."),
            (asyncio.TimeoutError(), "⏱️ The request timed out while tracing."),
            (su.BlockedDestinationError("x"), "⛔ Destination is not allowed — cannot expand."),
            (ConnectionResetError("x"), "⏱️ Network error while tracing the URL."),
        ]
        for exc, expected in cases:
            async def trace(session, target, _e=exc):
                raise _e
            text = await self._run(trace)
            self.assertEqual(text, expected, type(exc).__name__)
            self.assertNotIn("No HTTP redirect", text)

    async def test_invalid_url_rejected_before_tracing(self):
        calls = []

        async def trace(session, target):
            calls.append(target)
            return su.TraceResult([target.url], False)
        replies = []

        class Msg:
            async def reply(self_, text, **kw):
                replies.append(text)

        class Boot:
            expand_session = object()

        await self._handler(trace)(Msg(), "http://127.0.0.1/", Boot())
        self.assertEqual(calls, [])
        self.assertEqual(replies, ["❌ Private/reserved host in URL — cannot expand."])


if __name__ == "__main__":
    unittest.main()
