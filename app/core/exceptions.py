class BaseBotException(Exception): pass


class ProviderAPIError(BaseBotException):
    """A provider call failed.

    ``kind`` / ``status`` are optional, privacy-safe diagnostics (never a URL or
    response body). Existing ``ProviderAPIError("message")`` calls are unchanged.
    """

    def __init__(self, *args, status: int | None = None, kind: str | None = None):
        super().__init__(*args)
        self.status = status
        self.kind = kind


class CircuitOpenError(BaseBotException): pass
class FeatureDisabledError(BaseBotException): pass
class NoProvidersAvailableError(BaseBotException): pass


class ProvidersCoolingDownError(NoProvidersAvailableError):
    """Every provider was skipped because its circuit breaker is OPEN (no request was made).

    Subclasses NoProvidersAvailableError, so existing ``except NoProvidersAvailableError``
    handlers (including the frozen error middleware) keep working unchanged.
    """

    def __init__(self, *args, retry_after: float = 0.0):
        super().__init__(*args)
        self.retry_after = retry_after
