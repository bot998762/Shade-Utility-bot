"""
Network utility functions — pure Python, no framework dependencies.
Importable in test environments without aiogram/aiohttp installed.
"""

import ipaddress as _ipaddress
import re as _re

# Additional ranges not covered by Python's ipaddress.is_private
_BLOCKED_NETWORKS = [
    _ipaddress.ip_network("100.64.0.0/10"),   # RFC 6598 CGNAT
    _ipaddress.ip_network("192.0.0.0/24"),     # RFC 6890 IETF Protocol
    _ipaddress.ip_network("198.18.0.0/15"),    # RFC 2544 Benchmarking
    _ipaddress.ip_network("198.51.100.0/24"),  # RFC 5737 TEST-NET-2
    _ipaddress.ip_network("203.0.113.0/24"),   # RFC 5737 TEST-NET-3
    _ipaddress.ip_network("240.0.0.0/4"),      # Reserved
]

_BLOCKED_HOSTNAMES = (
    "localhost", "internal", "local", "metadata", "169.254.169.254"
)


def _is_blocked_addr(addr: _ipaddress.IPv4Address | _ipaddress.IPv6Address) -> bool:
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return True
    for net in _BLOCKED_NETWORKS:
        if addr in net:
            return True
    return False


def is_safe_host(host: str) -> bool:
    """
    SSRF guard — rejects private, loopback, link-local, CGNAT, and
    alternate address representations (decimal-integer encoding, octal prefix).

    Returns True only for addresses safe to use in outbound lookups.
    """
    host = host.strip()
    lower = host.lower()

    # Block by well-known internal hostname / suffix
    if any(lower == h or lower.endswith(f".{h}") for h in _BLOCKED_HOSTNAMES):
        return False

    # Standard IP address notation (IPv4 dotted-decimal, IPv6)
    try:
        addr = _ipaddress.ip_address(host)
        return not _is_blocked_addr(addr)
    except ValueError:
        pass

    # Decimal-integer IPv4 encoding (e.g. 2130706433 → 127.0.0.1)
    try:
        as_int = int(host)
        if 0 <= as_int <= 0xFFFFFFFF:
            return not _is_blocked_addr(_ipaddress.ip_address(as_int))
    except (ValueError, OverflowError):
        pass

    # Block obviously encoded addresses: octal (0177.0.0.1), hex (0x7f000001)
    if _re.match(r"^0[0-9]", host) or _re.match(r"^0x", lower):
        return False

    # Regular hostname — allow (downstream API validates content)
    return True
