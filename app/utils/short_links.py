"""Detection of links that are already shortened (CHG-030). Standard library only.

Deliberately NARROW: only the services this bot itself uses (v.gd, CleanURI) and
v.gd's sibling is.gd. It does not claim to recognise every URL shortener.
"""
from urllib.parse import urlsplit

KNOWN_SHORT_LINK_HOSTS = frozenset({"v.gd", "is.gd", "cleanuri.com"})


def known_short_link_host(raw: str) -> str | None:
    """Return the host if ``raw`` is a link on a known shortener (with a non-empty
    path, i.e. an actual short link rather than the site's home page), else None.

    Matching is on the exact host (an optional leading ``www.`` is ignored), so
    ``v.gd.example.com`` and ``https://v.gd@example.com/x`` are NOT matched.
    """
    candidate = raw.strip()
    if not candidate or " " in candidate:
        return None
    try:
        parts = urlsplit(candidate if "://" in candidate else "//" + candidate)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parts.scheme not in ("", "http", "https"):
        return None
    host = host.removeprefix("www.")
    if host in KNOWN_SHORT_LINK_HOSTS and parts.path.strip("/"):
        return host
    return None
