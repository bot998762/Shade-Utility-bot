"""
Google Cloud Translation API v2 provider (REST / API key auth).

Uses the OFFICIAL Google Cloud Translation API — not web scraping.
Endpoint: https://translation.googleapis.com/language/translate/v2

Pool configuration via indexed environment variables:
  GOOGLE_TRANSLATE_API_KEY          → entry google_0
  GOOGLE_TRANSLATE_API_KEY_1        → entry google_1
  GOOGLE_TRANSLATE_API_KEY_2        → entry google_2
  ...

Each entry should represent an independent Google Cloud project.
Multiple keys in the same project do NOT multiply that project's quota.
This architecture is for redundancy and legitimate multi-project failover.

SECURITY: API keys are never logged, never included in error messages,
and never exposed in any user-facing response.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

# aiohttp is imported lazily inside translate() so that _parse_response
# and build_google_providers_from_env() remain importable without aiohttp.

from app.providers.translation_provider import (
    FailureKind,
    TranslationError,
    TranslationResult,
)

logger = logging.getLogger(__name__)

_GOOGLE_TRANSLATE_URL = (
    "https://translation.googleapis.com/language/translate/v2"
)
_REQUEST_TIMEOUT_SECS = 15.0

# Representative set of languages supported by Google Cloud Translation v2.
# Used for capability hints only — the provider will still attempt translation
# for codes not in this set (the API will return an error if truly unsupported).
_GOOGLE_SUPPORTED: frozenset[str] = frozenset([
    "af", "sq", "am", "ar", "hy", "az", "eu", "be", "bn", "bs", "bg",
    "ca", "ceb", "zh", "co", "hr", "cs", "da", "nl", "en", "eo", "et",
    "fi", "fr", "fy", "gl", "ka", "de", "el", "gu", "ht", "ha", "haw",
    "he", "hi", "hmn", "hu", "is", "ig", "id", "ga", "it", "ja", "jv",
    "kn", "kk", "km", "ko", "ku", "ky", "lo", "la", "lv", "lt", "lb",
    "mk", "mg", "ms", "ml", "mt", "mi", "mr", "mn", "my", "ne", "no",
    "ny", "or", "ps", "fa", "pl", "pt", "pa", "ro", "ru", "sm", "gd",
    "sr", "st", "sn", "sd", "si", "sk", "sl", "so", "es", "su", "sw",
    "sv", "tl", "tg", "ta", "tt", "te", "th", "tr", "tk", "uk", "ur",
    "ug", "uz", "vi", "cy", "xh", "yi", "yo", "zu",
])


class GoogleCloudTranslationProvider:
    """Single Google Cloud Translation API v2 entry."""

    def __init__(self, api_key: str, provider_id: str = "google_0") -> None:
        if not api_key:
            raise ValueError(
                f"GoogleCloudTranslationProvider '{provider_id}': api_key required"
            )
        self._api_key = api_key
        self.provider_id = provider_id

    def supported_languages(self) -> frozenset[str]:
        return _GOOGLE_SUPPORTED

    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> TranslationResult:
        params: dict[str, Any] = {
            "q": text,
            "target": target_lang,
            "format": "text",
            "key": self._api_key,
        }
        if source_lang and source_lang != "auto":
            params["source"] = source_lang

        import aiohttp  # lazy import: keeps module importable without aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _GOOGLE_TRANSLATE_URL,
                    json=params,
                    timeout=aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECS),
                ) as resp:
                    body = await resp.json(content_type=None)
                    return self._parse_response(body, resp.status, target_lang)
        except asyncio.TimeoutError:
            raise TranslationError(
                "Google Translate request timed out.",
                FailureKind.TIMEOUT,
                self.provider_id,
            )
        except aiohttp.ClientConnectionError as exc:  # noqa: F821 — imported lazily above
            logger.warning("[%s] connection error: %s", self.provider_id, type(exc).__name__)
            raise TranslationError(
                "Google Translate connection failed.",
                FailureKind.CONNECTION,
                self.provider_id,
            )
        except TranslationError:
            raise
        except Exception as exc:
            logger.warning("[%s] unexpected: %s", self.provider_id, type(exc).__name__)
            raise TranslationError(
                "Google Translate unexpected failure.",
                FailureKind.UNKNOWN,
                self.provider_id,
            )

    def _parse_response(
        self, body: Any, status: int, target_lang: str
    ) -> TranslationResult:
        if status in (401, 403):
            raise TranslationError(
                "Google Translate: authentication failed.",
                FailureKind.AUTH_ERROR,
                self.provider_id,
            )
        if status == 429:
            raise TranslationError(
                "Google Translate: rate limited.",
                FailureKind.RATE_LIMITED,
                self.provider_id,
            )
        if status >= 500:
            raise TranslationError(
                f"Google Translate: server error {status}.",
                FailureKind.SERVER_ERROR,
                self.provider_id,
            )
        if status >= 400:
            error_msg = ""
            if isinstance(body, dict):
                error_msg = (body.get("error") or {}).get("message", "")
            if "not support" in error_msg.lower():
                raise TranslationError(
                    f"Language '{target_lang}' not supported by Google Translate.",
                    FailureKind.UNSUPPORTED_LANGUAGE,
                    self.provider_id,
                )
            raise TranslationError(
                f"Google Translate: request error {status}.",
                FailureKind.SERVER_ERROR,
                self.provider_id,
            )
        try:
            translations = body["data"]["translations"]
            translated = translations[0]["translatedText"]
            detected = translations[0].get("detectedSourceLanguage", "")
        except (KeyError, IndexError, TypeError):
            raise TranslationError(
                "Google Translate: malformed response.",
                FailureKind.EMPTY_RESULT,
                self.provider_id,
            )
        if not translated:
            raise TranslationError(
                "Google Translate: empty result.",
                FailureKind.EMPTY_RESULT,
                self.provider_id,
            )
        return TranslationResult(
            translated_text=translated,
            provider_id=self.provider_id,
            source_lang_detected=detected,
        )


def build_google_providers_from_env() -> list[GoogleCloudTranslationProvider]:
    """
    Build provider pool from environment variables.

    GOOGLE_TRANSLATE_API_KEY    → google_0
    GOOGLE_TRANSLATE_API_KEY_1  → google_1
    GOOGLE_TRANSLATE_API_KEY_2  → google_2  (etc.)

    Each entry should represent an independent Google Cloud project.
    Returns empty list if no variables are set.

    Gap detection: a missing numbered entry (e.g. KEY_1 absent when KEY and
    KEY_2 are set) logs a warning so deployers can catch numbering mistakes.
    Duplicate provider IDs are skipped with an error log to prevent
    orchestrator state dict corruption.
    """
    providers: list[GoogleCloudTranslationProvider] = []
    seen_ids: set[str] = set()

    key_0 = os.environ.get("GOOGLE_TRANSLATE_API_KEY", "").strip()
    last_seen = -1
    if key_0:
        providers.append(GoogleCloudTranslationProvider(key_0, "google_0"))
        seen_ids.add("google_0")
        last_seen = 0

    for idx in range(1, 31):
        key_n = os.environ.get(f"GOOGLE_TRANSLATE_API_KEY_{idx}", "").strip()
        pid = f"google_{idx}"
        if key_n:
            if last_seen >= 0 and idx > last_seen + 1:
                logger.warning(
                    "Google Translate: gap in numbered entries — "
                    "indices %d..%d are missing (entry %d found). "
                    "Check GOOGLE_TRANSLATE_API_KEY_N numbering.",
                    last_seen + 1, idx - 1, idx,
                )
            if pid in seen_ids:
                logger.error(
                    "Google Translate: duplicate provider_id '%s' — "
                    "skipping duplicate.", pid,
                )
                last_seen = idx
                continue
            providers.append(GoogleCloudTranslationProvider(key_n, pid))
            seen_ids.add(pid)
            last_seen = idx
        elif last_seen >= 0 and idx <= last_seen + 20:
            continue
        elif last_seen < 0 and idx > 5:
            break

    return providers
