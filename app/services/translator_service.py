"""
TranslatorService
=================

Application-facing translation service. The Telegram handler remains
unaware of provider details — it calls translate() and receives either
a result string or a normalized ValueError / ProviderAPIError.

Responsibilities:
  - input validation (empty, whitespace, length) — Phase 2L preserved
  - language alias resolution
  - delegation to TranslationOrchestrator
"""
from __future__ import annotations

import logging

from app.core.exceptions import ProviderAPIError  # noqa: F401 (re-exported for handler)
from app.services.translation_orchestrator import TranslationOrchestrator

logger = logging.getLogger(__name__)

LANG_ALIASES: dict[str, str] = {
    "hin": "hi",  "hindi": "hi",
    "eng": "en",  "english": "en",
    "sp":  "es",  "spanish": "es",
    "ur":  "ur",  "urdu": "ur",
    "fr":  "fr",  "french": "fr",
    "ar":  "ar",  "arabic": "ar",
    "ru":  "ru",  "russian": "ru",
    "ja":  "ja",  "japanese": "ja",
    "de":  "de",  "german": "de",
    "zh":  "zh",  "chinese": "zh",
    "pt":  "pt",  "portuguese": "pt",
    "it":  "it",  "italian": "it",
    "ko":  "ko",  "korean": "ko",
    "tr":  "tr",  "turkish": "tr",
}

_MAX_TEXT_LENGTH = 1000


class TranslatorService:
    def __init__(self, orchestrator: TranslationOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def translate(self, text: str, target_lang: str = "en") -> str:
        # --- Input validation (Phase 2L, preserved) ---
        if not text or not text.strip():
            raise ValueError("No text to translate.")
        if len(text) > _MAX_TEXT_LENGTH:
            raise ValueError(
                f"Text too long. Maximum {_MAX_TEXT_LENGTH} characters."
            )

        code = LANG_ALIASES.get(target_lang.lower(), target_lang.lower())
        return await self._orchestrator.translate(text, target_lang=code)
