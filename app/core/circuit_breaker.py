import time
import logging
from app.core.exceptions import CircuitOpenError

logger = logging.getLogger("ShadePlatform")

class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED"

    async def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitOpenError(f"Circuit {self.name} is OPEN.")

        try:
            result = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.failures = 0
                self.state = "CLOSED"
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = time.time()
            if self.failures >= self.failure_threshold:
                self.state = "OPEN"
                logger.error({"event": "circuit_open", "provider": self.name})
            raise
