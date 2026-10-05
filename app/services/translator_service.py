"""
TranslatorService
=================
Wraps deep_translator.GoogleTranslator with:
- input validation (empty, whitespace, length)
- full provider exception normalization
- None/empty result guard
- async executor + timeout
"""

import asyncio
import html as _html

from deep_translator import GoogleTranslator
from deep_translator.exceptions import (
    LanguageNotSupportedException,
    RequestError,
    TooManyRequests,
    TranslationNotFound,
    ElementNotFoundInGetRequest,
    ServerException,
    NotValidPayload,
    NotValidLength,
)

from app.core.exceptions import ProviderAPIError

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
    "zh": "zh", "chinese": "zh",
    "pt": "pt", "portuguese": "pt",
    "it": "it", "italian": "it",
    "ko": "ko", "korean": "ko",
    "tr": "tr", "turkish": "tr",
}

_TRANSLATE_TIMEOUT_SECS = 15.0
_MAX_TEXT_LENGTH = 1000


class TranslatorService:
    async def translate(self, text: str, target_lang: str = "en") -> str:
        # --- Input validation ---
        if not text or not text.strip():
            raise ValueError("No text to translate.")
        if len(text) > _MAX_TEXT_LENGTH:
            raise ValueError(
                f"Text too long. Maximum {_MAX_TEXT_LENGTH} characters."
            )

        code = LANG_ALIASES.get(target_lang.lower(), target_lang.lower())
        loop = asyncio.get_running_loop()

        def _do_translate() -> str:
            return GoogleTranslator(source="auto", target=code).translate(text)

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _do_translate),
                timeout=_TRANSLATE_TIMEOUT_SECS,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Translation timed out after {int(_TRANSLATE_TIMEOUT_SECS)} seconds."
            )
        except LanguageNotSupportedException:
            raise ValueError(
                f"Language '{target_lang}' is not supported. "
                "Use a language code like 'en', 'fr', 'hi', or a name like 'french'."
            )
        except TooManyRequests:
            raise ProviderAPIError(
                "Translation service is busy. Please try again in a moment."
            )
        except (RequestError, ServerException):
            raise ProviderAPIError(
                "Translation service is temporarily unavailable."
            )
        except TranslationNotFound:
            raise ProviderAPIError(
                "Could not translate the provided text."
            )
        except ElementNotFoundInGetRequest:
            raise ProviderAPIError(
                "Translation service returned an unexpected response."
            )
        except NotValidPayload:
            raise ValueError("No text to translate.")
        except NotValidLength:
            raise ValueError(
                f"Text too long. Maximum {_MAX_TEXT_LENGTH} characters."
            )

        # --- Result guard ---
        if not result:
            raise ProviderAPIError(
                "Translation service returned no result."
            )

        return result
