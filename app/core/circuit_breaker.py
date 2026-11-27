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
        except Exception:
            self.failures += 1
            self.last_failure_time = time.time()
            if self.failures >= self.failure_threshold:
                self.state = "OPEN"
                logger.error({"event": "circuit_open", "provider": self.name})
            raise
        # CHG-030: failures are counted CONSECUTIVELY. A success while CLOSED (or the
        # HALF_OPEN probe) clears the counter, so isolated failures hours apart can no
        # longer add up to an OPEN breaker. A late success that arrives while the
        # breaker is OPEN (a call started before it opened) does not close it early.
        if self.state in ("CLOSED", "HALF_OPEN"):
            self.failures = 0
            self.state = "CLOSED"
        return result

    def retry_after(self) -> float:
        """Seconds until an OPEN breaker allows a probe again (0.0 when not OPEN)."""
        if self.state != "OPEN":
            return 0.0
        return max(0.0, self.recovery_timeout - (time.time() - self.last_failure_time))
