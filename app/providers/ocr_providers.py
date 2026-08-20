import aiohttp
from app.core.config import settings


class OCRSpaceProvider:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def parse_image(self, photo_bytes: bytes) -> str:
        data = aiohttp.FormData()
        data.add_field("file", photo_bytes, filename="img.jpg", content_type="image/jpeg")
        data.add_field("apikey", settings.OCR_API_KEY)

        timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT)
        async with self.session.post(
            "https://api.ocr.space/parse/image",
            data=data,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            res = await resp.json()
            if res.get("IsErroredOnProcessing"):
                raise Exception(res.get("ErrorMessage", ["OCR Error"])[0])
            parsed = res.get("ParsedResults", [])
            return parsed[0].get("ParsedText", "").strip() if parsed else ""


class DummyFallbackOCRProvider:
    """Last-resort fallback; returns a placeholder to avoid NoProviders error."""
    def __init__(self, session: aiohttp.ClientSession) -> None:
        pass  # session not used

    async def parse_image(self, photo_bytes: bytes) -> str:
        return "[OCR unavailable — primary provider unreachable]"
