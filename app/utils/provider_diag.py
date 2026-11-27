"""Privacy-safe diagnostics for provider failures (CHG-030). Standard library only.

Nothing here returns or logs a full URL, query string, header, credential or raw
response body. ``classify_failure`` yields a coarse (kind, status) pair and
``safe_preview`` shortens provider text after stripping markup and URLs.
"""
import asyncio
import re
import socket
import ssl

_TLS_NAMES = {"ClientSSLError", "ClientConnectorSSLError", "ClientConnectorCertificateError",
              "SSLError", "SSLCertVerificationError", "CertificateError"}
_DNS_NAMES = {"ClientConnectorDNSError"}
_TIMEOUT_NAMES = {"TimeoutError", "ServerTimeoutError", "ConnectionTimeoutError",
                  "SocketTimeoutError"}
_CONNECT_NAMES = {"ClientConnectorError", "ClientOSError", "ServerDisconnectedError",
                  "ClientPayloadError"}


def _chain(exc: BaseException):
    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack and len(seen) < 8:
        cur = stack.pop()
        if cur is None or id(cur) in seen:
            continue
        seen.add(id(cur))
        yield cur
        stack.extend([getattr(cur, "os_error", None), cur.__cause__, cur.__context__])


def classify_failure(exc: BaseException) -> tuple[str, int | None]:
    """Return (kind, http_status). Kinds: circuit_open, rate_limited, server_error,
    http_error, bad_response, tls, dns, timeout, connect, other."""
    explicit_kind = getattr(exc, "kind", None)
    if explicit_kind:
        return explicit_kind, getattr(exc, "status", None)
    names = {c.__name__ for cur in _chain(exc) for c in type(cur).__mro__}
    if "CircuitOpenError" in names:
        return "circuit_open", None
    chain = list(_chain(exc))
    if any(isinstance(c, (ssl.SSLError, ssl.CertificateError)) for c in chain) or names & _TLS_NAMES:
        return "tls", None
    if any(isinstance(c, socket.gaierror) for c in chain) or names & _DNS_NAMES:
        return "dns", None
    if any(isinstance(c, (TimeoutError, asyncio.TimeoutError)) for c in chain) or names & _TIMEOUT_NAMES:
        return "timeout", None
    if names & _CONNECT_NAMES or any(isinstance(c, OSError) for c in chain):
        return "connect", None
    return "other", None


def kind_for_status(status: int) -> str:
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    return "http_error"


def safe_preview(text: object, limit: int = 80) -> str:
    """At most ``limit`` printable ASCII characters; markup removed, URLs -> '<url>'."""
    text = re.sub(r"<[^>]*>", " ", str(text))
    text = re.sub(r"(?i)\b(?:https?://|www\.)\S+", "<url>", text)
    text = re.sub(r"[^\x20-\x7e]", "", text)
    return " ".join(text.split())[:limit]
