from app.platform.failover import ProviderFailoverEngine

class ShortenerService:
    def __init__(self, failover_engine: ProviderFailoverEngine):
        self.engine = failover_engine

    async def shorten_url(self, target_url: str) -> str:
        return await self.engine.execute("create_short_url", target_url)
