class BaseBotException(Exception): pass
class ProviderAPIError(BaseBotException): pass
class CircuitOpenError(BaseBotException): pass
class FeatureDisabledError(BaseBotException): pass
class NoProvidersAvailableError(BaseBotException): pass
