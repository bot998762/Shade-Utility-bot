from dataclasses import dataclass
from typing import Dict
from app.core.exceptions import FeatureDisabledError

@dataclass
class FeatureManifest:
    name: str
    version: str
    category: str
    description: str = ""
    is_premium: bool = False
    enabled: bool = True

class CapabilityRegistry:
    def __init__(self):
        self.features: Dict[str, FeatureManifest] = {}

    def register(self, manifest: FeatureManifest):
        self.features[manifest.name] = manifest

    def is_enabled(self, name: str) -> bool:
        feat = self.features.get(name)
        return feat.enabled if feat else True

    def toggle(self, name: str, state: bool) -> bool:
        if name in self.features:
            self.features[name].enabled = state
            return True
        return False

    def require(self, name: str):
        if not self.is_enabled(name):
            raise FeatureDisabledError(f"Feature '{name}' is currently disabled for maintenance.")
