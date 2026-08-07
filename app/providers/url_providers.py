import aiohttp
from urllib.parse import quote
from app.core.config import settings

class IsGdURLProvider:
    """Fast Direct Link Shortener with 0s Delay"""
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def create_short_url(self, target_url: str) -> str:
        encoded_url = quote(target_url, safe='')
        api_url = f"https://is.gd/create.php?format=simple&url={encoded_url}"
        timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT)
        async with self.session.get(api_url, timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.text()
