"""
TranslatorService
=================
Wraps deep_translator.GoogleTranslator (uses unofficial API, sync HTTP).
The translation call runs in a thread executor to avoid blocking the
asyncio event loop. A hard timeout prevents indefinitely hanging workers.
"""

import asyncio
from deep_translator import GoogleTranslator
from deep_translator.exceptions import LanguageNotSupportedException

LANG_ALIASES = {
    "hin": "hi", "hindi": "hi",
    "eng": "en", "english": "en",
    "sp": "es", "spanish": "es",
    "ur": "ur", "urdu": "ur",
    "fr": "fr", "french": "fr",
    "ar": "ar", "arabic": "ar",
    "ru": "ru", "russian": "ru",
    "ja": "ja", "japanese": "ja",
    "de": "de", "german": "de",
}

# Maximum time to wait for the sync HTTP call in the thread pool.
_TRANSLATE_TIMEOUT_SECS = 15.0


class TranslatorService:
    async def translate(self, text: str, target_lang: str = "en") -> str:
        code = LANG_ALIASES.get(target_lang.lower(), target_lang.lower())
        loop = asyncio.get_running_loop()

        def _do_translate() -> str:
            return GoogleTranslator(source="auto", target=code).translate(text)

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _do_translate),
                timeout=_TRANSLATE_TIMEOUT_SECS,
            )
            return result
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Translation timed out after {_TRANSLATE_TIMEOUT_SECS}s. "
                "The translation service may be slow. Please try again."
            )
        except LanguageNotSupportedException:
            raise ValueError(
                f"Language code '{target_lang}' is not supported. "
                "Try codes like: 'hi', 'en', 'es', 'fr', 'ar', 'ru', 'ja', 'de'."
            )
