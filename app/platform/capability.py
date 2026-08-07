from dataclasses import dataclass
from typing import Dict
from app.core.exceptions import FeatureDisabledError

@dataclass
class FeatureManifest:
    name: str
    version: str
    category: str
    is_premium: bool = False
    enabled: bool = True

class CapabilityRegistry:
    """Phase 1 & 2: Capability Registry and Runtime Feature Flags"""
    def __init__(self):
        self.features: Dict[str, FeatureManifest] = {}
        self.failed_loads: Dict[str, str] = {}

    def register(self, manifest: FeatureManifest):
        self.features[manifest.name] = manifest

    def record_failure(self, name: str, reason: str):
        self.failed_loads[name] = reason

    def is_enabled(self, name: str) -> bool:
        feat = self.features.get(name)
        return feat.enabled if feat else False

    def toggle(self, name: str, state: bool) -> bool:
        if name in self.features:
            self.features[name].enabled = state
            return True
        return False

    def require(self, name: str):
        if not self.is_enabled(name):
            raise FeatureDisabledError(f"Feature '{name}' is currently disabled for maintenance.")
