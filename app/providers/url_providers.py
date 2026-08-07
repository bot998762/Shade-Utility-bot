import aiohttp
from urllib.parse import quote
from app.core.config import settings

class CleanURIProvider:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def create_short_url(self, target_url: str) -> str:
        api_url = "https://cleanuri.com/api/v1/shorten"
        timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT)
        async with self.session.post(api_url, data={'url': target_url}, timeout=timeout) as resp:
            resp.raise_for_status()
            res_json = await resp.json()
            if 'result_url' in res_json:
                return res_json['result_url']
            raise Exception("CleanURI Failed")

class VGdURLProvider:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def create_short_url(self, target_url: str) -> str:
        encoded_url = quote(target_url, safe='')
        api_url = f"https://v.gd/create.php?format=simple&url={encoded_url}"
        timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT)
        async with self.session.get(api_url, timeout=timeout) as resp:
            resp.raise_for_status()
            res_text = await resp.text()
            if res_text.startswith("http"):
                return res_text.strip()
            raise Exception(f"v.gd Error: {res_text}")
