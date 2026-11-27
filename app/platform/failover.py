import logging
import time
from typing import List, Tuple
from app.core.circuit_breaker import CircuitBreaker
from app.core.exceptions import (
    CircuitOpenError,
    NoProvidersAvailableError,
    ProvidersCoolingDownError,
)
from app.utils.provider_diag import classify_failure, safe_preview

logger = logging.getLogger("ShadePlatform")

class ProviderFailoverEngine:
    def __init__(self, domain: str):
        self.domain = domain
        self.providers: List[Tuple[any, CircuitBreaker]] = []

    def register_provider(self, provider, breaker: CircuitBreaker):
        self.providers.append((provider, breaker))

    async def execute(self, method_name: str, *args, **kwargs):
        failures: list[tuple[CircuitBreaker, Exception]] = []
        for provider, breaker in self.providers:
            started = time.monotonic()
            try:
                func = getattr(provider, method_name)
                result = await breaker.call(func, *args, **kwargs)
            except Exception as e:
                failures.append((breaker, e))
                kind, status = classify_failure(e)
                # CHG-030: structured and privacy-safe — no URL, query, body or secret.
                logger.warning({
                    "event": "provider_failover", "domain": self.domain,
                    "failed_provider": breaker.name, "kind": kind, "status": status,
                    "error_type": type(e).__name__, "error": safe_preview(e),
                    "breaker_state": breaker.state, "breaker_failures": breaker.failures,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                })
                continue
            logger.info({
                "event": "provider_success", "domain": self.domain, "provider": breaker.name,
                "breaker_state": breaker.state, "breaker_failures": breaker.failures,
                "duration_ms": int((time.monotonic() - started) * 1000),
            })
            return result

        cooling = bool(failures) and all(isinstance(e, CircuitOpenError) for _, e in failures)
        logger.warning({
            "event": "providers_exhausted", "domain": self.domain, "cooling_down": cooling,
            "outcomes": [{"provider": b.name, "kind": classify_failure(e)[0]} for b, e in failures],
        })
        if cooling:
            raise ProvidersCoolingDownError(
                f"All providers for {self.domain} are cooling down.",
                retry_after=min(b.retry_after() for b, _ in failures),
            )
        raise NoProvidersAvailableError(f"All providers for {self.domain} failed.")
