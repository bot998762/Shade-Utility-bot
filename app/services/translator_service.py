import asyncio
from deep_translator import GoogleTranslator

class TranslatorService:
    async def translate(self, text: str, target_lang: str = "en") -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, 
            lambda: GoogleTranslator(source='auto', target=target_lang).translate(text)
        )
