"""
OCR Providers
=============
OCRSpaceProvider     : primary  — api.ocr.space
DummyFallbackOCRProvider : last-resort fallback

Both use text-first response reading to avoid aiohttp.ContentTypeError
when the API returns HTML on 401/rate-limit/maintenance.
"""

import json
import aiohttp

from app.core.config import settings
from app.core.exceptions import ProviderAPIError
from app.core.logger import setup_logger

logger = setup_logger()


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
            # Read as text first — ocr.space returns text/html on 401/503
            raw = await resp.text(encoding="utf-8", errors="replace")

            if resp.status == 401:
                logger.error({"event": "ocr_api_key_rejected", "status": 401})
                raise ProviderAPIError("OCR API key is invalid or missing")

            if resp.status != 200:
                logger.warning({
                    "event": "ocr_http_error",
                    "status": resp.status,
                    "body_preview": raw[:150],
                })
                raise ProviderAPIError(f"OCR API HTTP {resp.status}")

            try:
                res = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                logger.error({
                    "event": "ocr_non_json",
                    "body_preview": raw[:150],
                })
                raise ProviderAPIError("OCR API returned non-JSON response")

            if res.get("IsErroredOnProcessing"):
                error_msgs = res.get("ErrorMessage", ["Unknown OCR error"])
                raise ProviderAPIError(error_msgs[0] if error_msgs else "OCR processing error")

            parsed = res.get("ParsedResults", [])
            return parsed[0].get("ParsedText", "").strip() if parsed else ""


class DummyFallbackOCRProvider:
    """
    Last-resort fallback: returns a placeholder instead of an exception.
    Prevents NoProvidersAvailableError when the primary provider is down.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        pass  # session not used

    async def parse_image(self, photo_bytes: bytes) -> str:
        logger.warning({"event": "ocr_fallback_used"})
        return ""  # Empty string signals "no text extracted" rather than a lie
