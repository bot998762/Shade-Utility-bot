"""
LibreTranslate provider — supports self-hosted instances.

Pool configuration via indexed environment variables:
  LIBRETRANSLATE_URL            → libretranslate_0
  LIBRETRANSLATE_API_KEY        (optional, for entry 0)
  LIBRETRANSLATE_URL_1          → libretranslate_1
  LIBRETRANSLATE_API_KEY_1      (optional, for entry 1)
  ...

Each entry is an independent LibreTranslate instance.

SECURITY (SSRF):
  Provider endpoints are server-side configuration only.
  Telegram users cannot supply URLs.
  Private/internal IP ranges are rejected by default.
  The guard uses stdlib ipaddress parsing (not regex) to catch:
    - Loopback (127.x.x.x, ::1)
    - RFC 1918 private ranges (10/8, 172.16/12, 192.168/16)
    - Link-local / cloud metadata (169.254.0.0/16, fe80::/10)
    - IPv4-mapped IPv6 (::ffff:192.168.x.x etc.)
    - CGNAT (100.64.0.0/10), multicast, reserved
    - Decimal-integer / octal / hex encoded IPs
    - Well-known internal hostnames
  Set LIBRETRANSLATE_ALLOW_PRIVATE_ENDPOINTS=1 only for
  intentional same-network self-hosted deployments.

SECURITY (secrets):
  API keys are never logged or included in error messages.

Configuration notes:
  Gaps in numbered entries (URL set, URL_2 set, URL_1 missing) are
  detected and logged as warnings. Duplicate provider IDs are rejected.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
from urllib.parse import urlparse

# aiohttp is imported lazily inside translate() so that this module's
# validation helpers (_is_endpoint_safe, _validate_endpoint) remain
# importable in test environments that do not have aiohttp installed.

from app.providers.translation_provider import (
    FailureKind,
    TranslationError,
    TranslationResult,
)
from app.utils.network import is_safe_host

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECS = 15.0

# Representative set for capability hints.
_LT_SUPPORTED: frozenset[str] = frozenset([
    "en", "ar", "az", "zh", "cs", "da", "nl", "eo", "fi", "fr", "de",
    "el", "he", "hi", "hu", "id", "ga", "it", "ja", "ko", "fa", "pl",
    "pt", "ru", "sk", "es", "sv", "th", "tr", "uk", "ur", "vi",
])


def _is_endpoint_safe(url: str) -> bool:
    """
    Return True only if the URL host is safe for an outbound connection.

    Covers:
      - Loopback (127.x.x.x, ::1)
      - RFC 1918 private (10/8, 172.16/12, 192.168/16)
      - Link-local / cloud metadata (169.254.0.0/16, fe80::/10)
      - IPv4-mapped IPv6 (::ffff:192.168.x.x → unwrap, then check IPv4)
      - CGNAT (100.64.0.0/10), multicast, reserved, unspecified
      - Decimal-integer / octal / hex encoded IPs
      - Well-known internal hostnames (localhost, metadata, 169.254.169.254, …)

    All range checks are delegated to is_safe_host() from app.utils.network,
    which uses ipaddress.is_private / _BLOCKED_NETWORKS for complete coverage.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname  # strips brackets from [::1], lowercases
    except Exception:
        return False

    if not host:
        return False

    # Unwrap IPv4-mapped IPv6 (::ffff:x.x.x.x) before the safety check.
    # Python's ipaddress.ip_address("::ffff:192.168.1.1").is_private may
    # vary by Python version; unwrapping to the plain IPv4 address and
    # delegating to is_safe_host() is the authoritative path.
    try:
        addr = ipaddress.ip_address(host)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            host = str(addr.ipv4_mapped)
    except ValueError:
        pass  # non-IP hostname — fall through to is_safe_host

    # Delegate all blocking decisions (including CGNAT, RFC 5737, …) to the
    # shared network utility which maintains _BLOCKED_NETWORKS.
    return is_safe_host(host)


def _validate_endpoint(url: str, provider_id: str, allow_private: bool) -> str:
    """Validate and normalise a LibreTranslate endpoint URL."""
    url = url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ValueError(
            f"LibreTranslate '{provider_id}': endpoint must start with "
            "http:// or https://"
        )
    if not allow_private and not _is_endpoint_safe(url):
        raise ValueError(
            f"LibreTranslate '{provider_id}': private/internal endpoints are "
            "blocked. Set LIBRETRANSLATE_ALLOW_PRIVATE_ENDPOINTS=1 to permit."
        )
    return url


def _get_allow_private() -> bool:
    """Read LIBRETRANSLATE_ALLOW_PRIVATE_ENDPOINTS from environment at call time."""
    return os.environ.get(
        "LIBRETRANSLATE_ALLOW_PRIVATE_ENDPOINTS", ""
    ).strip().lower() in ("1", "true", "yes")


class LibreTranslateProvider:
    """Single LibreTranslate instance."""

    def __init__(
        self,
        endpoint: str,
        provider_id: str = "libretranslate_0",
        api_key: str = "",
        *,
        allow_private: bool | None = None,
    ) -> None:
        # allow_private=None → read env at construction time (normal path)
        # allow_private=True/False → explicit override (useful in tests)
        _allow = _get_allow_private() if allow_private is None else allow_private
        self._endpoint = _validate_endpoint(endpoint, provider_id, _allow)
        self.provider_id = provider_id
        self._api_key = api_key

    def supported_languages(self) -> frozenset[str]:
        return _LT_SUPPORTED

    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> TranslationResult:
        payload: dict = {
            "q": text,
            "source": source_lang if source_lang != "auto" else "auto",
            "target": target_lang,
            "format": "text",
        }
        if self._api_key:
            payload["api_key"] = self._api_key

        url = f"{self._endpoint}/translate"

        import aiohttp  # lazy import: keeps module importable without aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECS),
                ) as resp:
                    body = await resp.json(content_type=None)
                    return self._parse_response(body, resp.status, target_lang)
        except asyncio.TimeoutError:
            raise TranslationError(
                "LibreTranslate request timed out.",
                FailureKind.TIMEOUT,
                self.provider_id,
            )
        except aiohttp.ClientConnectionError as exc:  # noqa: F821 — imported lazily above
            logger.warning("[%s] connection error: %s", self.provider_id, type(exc).__name__)
            raise TranslationError(
                "LibreTranslate connection failed.",
                FailureKind.CONNECTION,
                self.provider_id,
            )
        except TranslationError:
            raise
        except Exception as exc:
            logger.warning("[%s] unexpected: %s", self.provider_id, type(exc).__name__)
            raise TranslationError(
                "LibreTranslate unexpected failure.",
                FailureKind.UNKNOWN,
                self.provider_id,
            )

    def _parse_response(
        self, body: object, status: int, target_lang: str
    ) -> TranslationResult:
        if status in (401, 403):
            raise TranslationError(
                "LibreTranslate: authentication failed.",
                FailureKind.AUTH_ERROR,
                self.provider_id,
            )
        if status == 429:
            raise TranslationError(
                "LibreTranslate: rate limited.",
                FailureKind.RATE_LIMITED,
                self.provider_id,
            )
        if status == 400:
            error = ""
            if isinstance(body, dict):
                error = body.get("error", "")
            if "not supported" in error.lower() or "unsupported" in error.lower():
                raise TranslationError(
                    f"Language '{target_lang}' not supported by LibreTranslate.",
                    FailureKind.UNSUPPORTED_LANGUAGE,
                    self.provider_id,
                )
            raise TranslationError(
                "LibreTranslate: bad request.",
                FailureKind.SERVER_ERROR,
                self.provider_id,
            )
        if status >= 500:
            raise TranslationError(
                f"LibreTranslate: server error {status}.",
                FailureKind.SERVER_ERROR,
                self.provider_id,
            )
        try:
            translated = body["translatedText"]  # type: ignore[index]
        except (KeyError, TypeError):
            raise TranslationError(
                "LibreTranslate: malformed response.",
                FailureKind.EMPTY_RESULT,
                self.provider_id,
            )
        if not translated:
            raise TranslationError(
                "LibreTranslate: empty result.",
                FailureKind.EMPTY_RESULT,
                self.provider_id,
            )
        return TranslationResult(
            translated_text=translated,
            provider_id=self.provider_id,
        )


def build_libretranslate_providers_from_env() -> list[LibreTranslateProvider]:
    """
    Build LibreTranslate provider pool from environment variables.

    LIBRETRANSLATE_URL            → libretranslate_0
    LIBRETRANSLATE_API_KEY        (optional)
    LIBRETRANSLATE_URL_1          → libretranslate_1
    LIBRETRANSLATE_API_KEY_1      (optional)
    ...

    Returns empty list if no variables are set.
    Invalid endpoints are logged and skipped (bot continues without them).

    Gap detection: scans up to index 20 beyond the last seen entry.
    A missing entry (e.g. URL_2 absent when URL_1 and URL_3 are set) logs
    a warning so deployers can fix numbering mistakes. Duplicate provider
    IDs are rejected — they would corrupt the orchestrator's state dict.
    """
    providers: list[LibreTranslateProvider] = []
    seen_ids: set[str] = set()

    # Collect raw (url, api_key, pid) tuples including gap detection.
    # Index 0 uses the un-suffixed variable name; 1+ use _N suffixes.
    entries: list[tuple[str, str, str]] = []
    last_seen = -1

    url_0 = os.environ.get("LIBRETRANSLATE_URL", "").strip()
    if url_0:
        api_key_0 = os.environ.get("LIBRETRANSLATE_API_KEY", "").strip()
        entries.append((url_0, api_key_0, "libretranslate_0"))
        last_seen = 0

    # Scan up to 30 to detect gaps beyond reasonable deployment sizes
    for idx in range(1, 31):
        url_n = os.environ.get(f"LIBRETRANSLATE_URL_{idx}", "").strip()
        pid = f"libretranslate_{idx}"
        if url_n:
            api_key_n = os.environ.get(f"LIBRETRANSLATE_API_KEY_{idx}", "").strip()
            if last_seen >= 0 and idx > last_seen + 1:
                logger.warning(
                    "LibreTranslate: gap in numbered entries — "
                    "indices %d..%d are missing (entry %d found). "
                    "Check LIBRETRANSLATE_URL_N numbering.",
                    last_seen + 1, idx - 1, idx,
                )
            entries.append((url_n, api_key_n, pid))
            last_seen = idx
        elif last_seen >= 0 and idx <= last_seen + 20:
            # Keep scanning for gaps past the last seen entry
            continue
        elif last_seen < 0 and idx > 5:
            # No entries at all yet and no base URL; stop early
            break

    for url, api_key, pid in entries:
        if pid in seen_ids:
            logger.error(
                "LibreTranslate: duplicate provider_id '%s' — skipping duplicate.",
                pid,
            )
            continue
        try:
            providers.append(LibreTranslateProvider(url, pid, api_key))
            seen_ids.add(pid)
        except ValueError as exc:
            logger.warning("LibreTranslate entry '%s' skipped: %s", pid, exc)

    return providers
