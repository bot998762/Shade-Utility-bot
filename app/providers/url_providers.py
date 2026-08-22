"""
URL Shortener Providers
=======================
CleanURIProvider : primary  — cleanuri.com (JSON API)
VGdURLProvider   : fallback — v.gd      (plain-text response, already safe)

Both use text-first response reading to avoid aiohttp.ContentTypeError
when the provider returns HTML/plain-text error pages.
"""

import json
import aiohttp
from urllib.parse import quote

from app.core.config import settings
from app.core.exceptions import ProviderAPIError
from app.core.logger import setup_logger

logger = setup_logger()


class CleanURIProvider:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def create_short_url(self, target_url: str) -> str:
        api_url = "https://cleanuri.com/api/v1/shorten"
        timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT)

        async with self.session.post(
            api_url, data={"url": target_url}, timeout=timeout
        ) as resp:
            # Read as text first — never call resp.json() directly.
            # CleanURI returns text/html on rate-limit or error pages.
            raw = await resp.text(encoding="utf-8", errors="replace")

            if resp.status != 200:
                logger.warning({
                    "event": "cleanuri_http_error",
                    "status": resp.status,
                    "body_preview": raw[:150],
                })
                raise ProviderAPIError(f"CleanURI HTTP {resp.status}")

            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                logger.error({
                    "event": "cleanuri_non_json",
                    "body_preview": raw[:150],
                })
                raise ProviderAPIError("CleanURI returned non-JSON response")

            result = data.get("result_url", "")
            if result and result.startswith("http"):
                return result

            error_detail = data.get("error", raw[:100])
            raise ProviderAPIError(f"CleanURI: {error_detail}")


class VGdURLProvider:
    """v.gd returns plain text — already safe, no json() call."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def create_short_url(self, target_url: str) -> str:
        encoded_url = quote(target_url, safe="")
        api_url = f"https://v.gd/create.php?format=simple&url={encoded_url}"
        timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT)

        async with self.session.get(api_url, timeout=timeout) as resp:
            raw = await resp.text(encoding="utf-8", errors="replace")

            if resp.status != 200:
                logger.warning({
                    "event": "vgd_http_error",
                    "status": resp.status,
                    "body_preview": raw[:150],
                })
                raise ProviderAPIError(f"v.gd HTTP {resp.status}")

            stripped = raw.strip()
            if stripped.startswith("http"):
                return stripped

            logger.warning({"event": "vgd_unexpected_response", "body": raw[:150]})
            raise ProviderAPIError(f"v.gd unexpected response: {raw[:80]}")
