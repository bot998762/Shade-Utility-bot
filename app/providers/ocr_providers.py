import aiohttp
from app.core.config import settings
from app.providers.interfaces import IOCRProvider

class OCRSpaceProvider(IOCRProvider):
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        
    async def parse_image(self, photo_bytes: bytes) -> str:
        data = aiohttp.FormData()
        data.add_field('file', photo_bytes, filename='img.jpg', content_type='image/jpeg')
        data.add_field('apikey', settings.OCR_API_KEY)
        
        async with self.session.post("https://api.ocr.space/parse/image", data=data, timeout=settings.REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            res = await resp.json()
            if res.get("IsErroredOnProcessing"): raise Exception(res.get("ErrorMessage", ["Error"])[0])
            parsed = res.get("ParsedResults", [])
            return parsed[0].get("ParsedText", "").strip() if parsed else ""

class DummyFallbackOCRProvider(IOCRProvider):
    """Fallback provider to demonstrate Phase 3 Engine"""
    def __init__(self, session: aiohttp.ClientSession):
        pass
    async def parse_image(self, photo_bytes: bytes) -> str:
        return "[Fallback OCR] Extracted text simulated due to Primary API failure."
