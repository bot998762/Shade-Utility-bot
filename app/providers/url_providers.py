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
from app.utils.provider_diag import kind_for_status, safe_preview

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
                    "body_preview": safe_preview(raw),
                })
                raise ProviderAPIError(
                    f"CleanURI HTTP {resp.status}",
                    status=resp.status, kind=kind_for_status(resp.status),
                )

            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                logger.error({
                    "event": "cleanuri_non_json",
                    "body_preview": safe_preview(raw),
                })
                raise ProviderAPIError(
                    "CleanURI returned non-JSON response", status=resp.status, kind="bad_response",
                )

            result = data.get("result_url", "")
            if result and result.startswith("http"):
                return result

            # The provider's error text is not echoed into the exception (it may repeat
            # the submitted URL); a sanitised preview goes to the log instead.
            logger.warning({
                "event": "cleanuri_error_response",
                "body_preview": safe_preview(data.get("error", raw)),
            })
            raise ProviderAPIError(
                "CleanURI returned an error response", status=resp.status, kind="bad_response",
            )


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
                    "body_preview": safe_preview(raw),
                })
                raise ProviderAPIError(
                    f"v.gd HTTP {resp.status}",
                    status=resp.status, kind=kind_for_status(resp.status),
                )

            stripped = raw.strip()
            if stripped.startswith("http"):
                return stripped

            logger.warning({"event": "vgd_unexpected_response", "body_preview": safe_preview(raw)})
            raise ProviderAPIError(
                "v.gd unexpected response", status=resp.status, kind="bad_response",
            )
