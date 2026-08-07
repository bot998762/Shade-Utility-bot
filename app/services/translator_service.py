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
    "de": "de", "german": "de"
}

class TranslatorService:
    async def translate(self, text: str, target_lang: str = "en") -> str:
        code = LANG_ALIASES.get(target_lang.lower(), target_lang.lower())
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, 
                lambda: GoogleTranslator(source='auto', target=code).translate(text)
            )
        except LanguageNotSupportedException:
            raise ValueError(f"Language code '{target_lang}' is not supported. Try using codes like: 'hi', 'en', 'es', 'ur', 'fr'.")
