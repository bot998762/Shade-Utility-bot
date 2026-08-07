import logging
from typing import List, Tuple
from app.core.circuit_breaker import CircuitBreaker
from app.core.exceptions import NoProvidersAvailableError

logger = logging.getLogger("ShadePlatform")

class ProviderFailoverEngine:
    def __init__(self, domain: str):
        self.domain = domain
        self.providers: List[Tuple[any, CircuitBreaker]] = []

    def register_provider(self, provider, breaker: CircuitBreaker):
        self.providers.append((provider, breaker))

    async def execute(self, method_name: str, *args, **kwargs):
        for provider, breaker in self.providers:
            try:
                func = getattr(provider, method_name)
                return await breaker.call(func, *args, **kwargs)
            except Exception as e:
                logger.warning({"event": "provider_failover", "domain": self.domain, "failed_provider": breaker.name, "error": str(e)})
                continue
        
        raise NoProvidersAvailableError(f"All providers for {self.domain} failed.")
