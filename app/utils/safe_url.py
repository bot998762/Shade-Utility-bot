"""
Safe outbound fetching of user-supplied URLs (CHG-024)
======================================================

Used by ``/short expand``. Pure stdlib at import time (aiohttp is imported
lazily inside ``create_guarded_session``) so every policy function is
importable and testable without aiohttp / aiogram installed.

Why this module exists
----------------------
Validating the *text* of a hostname (``network.is_safe_host``) cannot stop a
public-looking name such as ``127.0.0.1.nip.io`` from resolving to a private
address, and a check made *before* connecting can be raced by DNS rebinding.
The authoritative control is therefore enforced where aiohttp obtains the
addresses it will actually connect to:

  GuardedResolver  -- plugged into aiohttp's TCPConnector. Every name
                      resolution is validated; the SAME address list that was
                      validated is the one aiohttp connects to. If any answer
                      is prohibited, malformed or empty, the connection fails
                      closed. TLS is untouched (the URL still carries the real
                      hostname), so certificate verification and SNI keep
                      working.

Two things the resolver cannot see are handled here as well:

  * IP-literal URLs: aiohttp does not call the resolver for them, so they are
    validated by ``validate_public_http_url`` before every request.
  * Redirects: every ``Location`` is re-validated before it is followed.

``is_safe_host`` is still called as a cheap string-level defence in depth, but
it is no longer the security decision for hostnames.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from app.utils.network import _is_blocked_addr, is_safe_host

MAX_URL_LENGTH = 2048
MAX_REDIRECTS = 5
HOP_TIMEOUT_TOTAL = 10   # seconds, per request (set on the session)
HOP_TIMEOUT_CONNECT = 5  # seconds, per connection attempt
TOTAL_DEADLINE = 20      # seconds, whole redirect chain
DNS_TIMEOUT = 5          # seconds, per name resolution

_ALLOWED_SCHEMES = ("http", "https")
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_LABEL_RE = re.compile(r"^[a-z0-9_-]{1,63}$")
_USER_AGENT = "ShadeUtility/CHG024 URLExpander"


# ── Exceptions ──────────────────────────────────────────────────────────────

class UnsafeURLError(ValueError):
    """URL rejected by policy. ``code`` is a short machine-readable reason."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RedirectBlockedError(UnsafeURLError):
    """A redirect target was rejected by policy and was not followed."""


class RedirectLoopError(Exception):
    """A redirect chain revisited a URL it had already seen."""


class BlockedDestinationError(OSError):
    """Raised by GuardedResolver when an answer is a prohibited address."""


class DestinationResolutionError(OSError):
    """Raised by GuardedResolver when validation could not be completed."""


# ── Address policy ──────────────────────────────────────────────────────────

def _embedded_ipv4(addr: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """IPv4 addresses embedded in 6to4, Teredo and NAT64 (64:ff9b::/96)."""
    found: list[ipaddress.IPv4Address] = []
    if addr.sixtofour is not None:
        found.append(addr.sixtofour)
    if addr.teredo is not None:
        found.extend(addr.teredo)
    if (int(addr) >> 32) == (int(ipaddress.IPv6Address("64:ff9b::")) >> 32):
        found.append(ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF))
    return found


def is_prohibited_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if ``addr`` must never be contacted.

    Covers loopback, private, link-local, unspecified, multicast, reserved,
    CGNAT and the other ranges in ``network._BLOCKED_NETWORKS``, anything that
    is not globally routable, and IPv4 addresses hidden inside IPv4-mapped
    IPv6, 6to4, Teredo and NAT64 forms.
    """
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return is_prohibited_ip(addr.ipv4_mapped)
        if any(is_prohibited_ip(v4) for v4 in _embedded_ipv4(addr)):
            return True
    if _is_blocked_addr(addr):
        return True
    return not addr.is_global


# ── URL validation ──────────────────────────────────────────────────────────

def _ends_in_number(host: str) -> bool:
    last = host.rsplit(".", 1)[-1]
    return last.isdigit() or bool(re.fullmatch(r"0x[0-9a-f]*", last))


def normalize_host(raw_host: str):
    """Return ``(host, ip_or_None)`` or raise ``UnsafeURLError("host")``.

    Lowercases, strips one trailing dot, IDNA-encodes, validates labels, and
    rejects every non-canonical numeric host (decimal, octal, hex, short-form
    IPv4) instead of trying to interpret it. Canonical IPv4/IPv6 literals are
    returned as ``ipaddress`` objects (brackets already stripped by urlsplit).
    """
    if not raw_host or "%" in raw_host:
        raise UnsafeURLError("host")
    host = raw_host.lower()
    try:
        return host, ipaddress.ip_address(host)
    except ValueError:
        pass
    if host.endswith("."):
        host = host[:-1]
    if not host or host.endswith(".") or ".." in host:
        raise UnsafeURLError("host")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise UnsafeURLError("host") from None
    if len(host) > 253:
        raise UnsafeURLError("host")
    for label in host.split("."):
        if not _LABEL_RE.match(label) or label.startswith("-") or label.endswith("-"):
            raise UnsafeURLError("host")
    if _ends_in_number(host):
        raise UnsafeURLError("host")
    return host, None


@dataclass(frozen=True)
class SafeTarget:
    url: str          # canonical URL actually requested (no fragment)
    scheme: str
    host: str
    port: int
    is_ip_literal: bool = False


def validate_public_http_url(raw: str) -> SafeTarget:
    """Validate a user- or redirect-supplied URL; raise ``UnsafeURLError``.

    Codes: malformed, scheme, credentials, port, host, blocked.
    """
    if not isinstance(raw, str):
        raise UnsafeURLError("malformed")
    raw = raw.strip()
    if not raw or len(raw) > MAX_URL_LENGTH:
        raise UnsafeURLError("malformed")
    # Whitespace, control characters and backslashes are classic parser-
    # differential vectors; legitimate URLs never need them.
    if any(ord(c) <= 0x20 or ord(c) == 0x7F for c in raw) or "\\" in raw:
        raise UnsafeURLError("malformed")
    try:
        parts = urlsplit(raw)
    except ValueError:
        raise UnsafeURLError("malformed") from None

    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError("scheme")
    if not parts.netloc:
        raise UnsafeURLError("malformed")
    if "@" in parts.netloc:
        raise UnsafeURLError("credentials")
    try:
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise UnsafeURLError("port") from None
    if port is not None and not 1 <= port <= 65535:
        raise UnsafeURLError("port")

    host, ip = normalize_host(hostname or "")
    if ip is not None:
        if is_prohibited_ip(ip):
            raise UnsafeURLError("blocked")
    elif not is_safe_host(host):  # internal-name defence in depth only
        raise UnsafeURLError("blocked")

    netloc = f"[{host}]" if ip is not None and ip.version == 6 else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    url = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
    effective_port = port or (443 if scheme == "https" else 80)
    return SafeTarget(url, scheme, host, effective_port, ip is not None)


def _same_host_as_client_parser(target: SafeTarget) -> None:
    """Fail closed if aiohttp's URL parser (yarl) disagrees about the host."""
    try:
        from yarl import URL
    except ImportError:  # aiohttp (and thus any request) unavailable
        return
    try:
        client_host = URL(target.url).host
    except Exception:
        raise UnsafeURLError("malformed") from None
    if (client_host or "").lower().strip("[]") != target.host:
        raise UnsafeURLError("malformed")


# ── Connection-time enforcement ─────────────────────────────────────────────

class GuardedResolver:
    """aiohttp-compatible resolver that validates every answer.

    Duck-typed on aiohttp's ``AbstractResolver`` (``resolve`` / ``close``) so
    it can be unit-tested without aiohttp. ``base`` is the real resolver; it
    defaults to ``aiohttp.ThreadedResolver`` (stdlib ``getaddrinfo``).

    Policy: if ANY answer is prohibited, malformed, or the list is empty, the
    whole resolution fails closed. The unmodified, validated entries are
    returned, so aiohttp connects to exactly the addresses that were checked.
    """

    def __init__(self, base=None, *, timeout: float = DNS_TIMEOUT):
        self._base = base
        self._timeout = timeout

    def _get_base(self):
        if self._base is None:
            import aiohttp
            self._base = aiohttp.ThreadedResolver()
        return self._base

    async def resolve(self, host, port=0, family=socket.AF_INET):
        literal = None
        try:
            literal = ipaddress.ip_address(str(host).strip("[]"))
        except ValueError:
            pass
        if literal is not None:  # aiohttp normally skips the resolver for these
            if is_prohibited_ip(literal):
                raise BlockedDestinationError("prohibited destination")
            return [{
                "hostname": host, "host": str(literal), "port": port,
                "family": socket.AF_INET6 if literal.version == 6 else socket.AF_INET,
                "proto": 0, "flags": socket.AI_NUMERICHOST,
            }]

        try:
            entries = await asyncio.wait_for(
                self._get_base().resolve(host, port, family), self._timeout
            )
        except Exception as exc:  # incl. asyncio.TimeoutError: fail closed
            raise DestinationResolutionError("name resolution failed") from exc
        if not isinstance(entries, (list, tuple)) or not entries:
            raise DestinationResolutionError("no addresses")

        for entry in entries:
            try:
                addr = ipaddress.ip_address(str(entry["host"]).split("%", 1)[0])
            except (KeyError, TypeError, ValueError):
                raise DestinationResolutionError("malformed answer") from None
            if is_prohibited_ip(addr):
                raise BlockedDestinationError("prohibited destination")
        return list(entries)

    async def close(self) -> None:
        close = getattr(self._base, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


def create_guarded_session():
    """One long-lived session for user-supplied URLs (owned by bootstrap).

    * GuardedResolver on the connector, DNS cache off (every connection is
      re-validated, nothing stale is reused).
    * DummyCookieJar: cookies set by one user's redirect chain must never be
      replayed in another user's expansion.
    * trust_env=False: environment proxies are never consulted, so the
      resolver cannot be bypassed by a proxy that resolves names itself.
    * Bounded pool and per-request timeouts.
    """
    import aiohttp

    connector = aiohttp.TCPConnector(
        resolver=GuardedResolver(),
        use_dns_cache=False,
        limit=10,
        limit_per_host=3,
    )
    return aiohttp.ClientSession(
        connector=connector,
        cookie_jar=aiohttp.DummyCookieJar(),
        trust_env=False,
        timeout=aiohttp.ClientTimeout(total=HOP_TIMEOUT_TOTAL, connect=HOP_TIMEOUT_CONNECT),
    )


# ── Redirect tracing ────────────────────────────────────────────────────────

@dataclass
class TraceResult:
    hops: list = field(default_factory=list)
    truncated: bool = False  # stopped at the redirect limit, chain continues


def _loop_key(t: SafeTarget):
    return (t.scheme, t.host, t.port, urlsplit(t.url).path, urlsplit(t.url).query)


async def _trace(session, start: SafeTarget, max_redirects: int) -> TraceResult:
    hops = [start.url]
    seen = {_loop_key(start)}
    current = start
    for hop in range(max_redirects + 1):
        _same_host_as_client_parser(current)
        async with session.head(
            current.url,
            allow_redirects=False,
            headers={"User-Agent": _USER_AGENT},
        ) as resp:
            status = resp.status
            location = resp.headers.get("Location", "")
        if status not in _REDIRECT_STATUSES or not location:
            return TraceResult(hops, False)
        if hop == max_redirects:
            return TraceResult(hops, True)
        try:
            if len(location) > MAX_URL_LENGTH:
                raise UnsafeURLError("malformed")
            nxt = validate_public_http_url(urljoin(current.url, location))
        except UnsafeURLError as exc:
            raise RedirectBlockedError(exc.code) from None
        key = _loop_key(nxt)
        if key in seen:
            raise RedirectLoopError()
        seen.add(key)
        hops.append(nxt.url)
        current = nxt
    return TraceResult(hops, True)  # pragma: no cover (loop always returns)


async def trace_redirects(session, start: SafeTarget, *,
                          max_redirects: int = MAX_REDIRECTS,
                          total_timeout: float = TOTAL_DEADLINE) -> TraceResult:
    """Follow redirects manually with HEAD, validating every hop.

    Bounded by ``max_redirects`` and an overall ``total_timeout`` (raises
    ``asyncio.TimeoutError``). Response bodies are never read.
    """
    return await asyncio.wait_for(_trace(session, start, max_redirects), total_timeout)


def classify_network_error(exc: BaseException) -> str:
    """Return 'blocked', 'timeout' or 'network' without exposing details."""
    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack and len(seen) < 10:
        cur = stack.pop()
        if cur is None or id(cur) in seen:
            continue
        seen.add(id(cur))
        if isinstance(cur, BlockedDestinationError):
            return "blocked"
        stack.extend([getattr(cur, "os_error", None), cur.__cause__, cur.__context__])
    if isinstance(exc, asyncio.TimeoutError) or "Timeout" in type(exc).__name__:
        return "timeout"
    return "network"
