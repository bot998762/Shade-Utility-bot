from app.platform.capability import CapabilityRegistry
from aiogram import Dispatcher
import importlib
import pkgutil
import logging

logger = logging.getLogger("ShadePlatform")

def load_features(dp: Dispatcher, registry: CapabilityRegistry):
    """Phase 1: Feature Isolation and Blast Radius Containment"""
    import app.features
    for _, module_name, _ in pkgutil.iter_modules(app.features.__path__):
        try:
            module = importlib.import_module(f"app.features.{module_name}.router")
            if hasattr(module, "manifest"):
                registry.register(module.manifest)
                if hasattr(module, "router"):
                    dp.include_router(module.router)
        except Exception as e:
            logger.error({"event": "plugin_load_failed", "module": module_name, "error": str(e)})
            registry.record_failure(module_name, str(e))
