"""
Feature Loader — Isolated Dynamic Discovery
===========================================
Each feature module is imported independently inside a try/except block.
A broken optional feature (SyntaxError, missing dep, runtime error) is
logged and skipped; the remaining features continue loading and the bot
starts normally.

Critical infrastructure failures (bot token, HTTP session) still abort
startup via the bootstrap layer — this isolation only applies to features.

Each feature module MUST expose:
  router   : aiogram.Router
  manifest : app.platform.capability.FeatureManifest
"""

import importlib
import logging
from aiogram import Dispatcher
from app.platform.capability import CapabilityRegistry, FeatureManifest

logger = logging.getLogger("ShadePlatform")

# Ordered list of feature module paths. Add new features here.
FEATURE_MODULES = [
    "app.features.general.router",
    "app.features.crypto.router",
    "app.features.media.router",
    "app.features.session.router",
    "app.features.session_manager.router",
    "app.features.admin.router",
]


def load_features(
    dp: Dispatcher, registry: CapabilityRegistry
) -> tuple[list[str], list[str]]:
    """Load all feature modules in isolation.

    Returns:
        (loaded_names, failed_module_paths) — callers use this to populate
        degraded_features in the health readiness state.
    """
    loaded: list[str] = []
    failed: list[tuple[str, str]] = []

    for module_path in FEATURE_MODULES:
        try:
            mod = importlib.import_module(module_path)

            # Validate required exports
            if not hasattr(mod, "router"):
                raise AttributeError(f"Module '{module_path}' has no 'router' export")
            if not hasattr(mod, "manifest"):
                raise AttributeError(f"Module '{module_path}' has no 'manifest' export")

            manifest = mod.manifest
            # Normalise: accept FeatureManifest or duck-typed objects
            if not isinstance(manifest, FeatureManifest):
                logger.warning({
                    "event": "feature_manifest_type_mismatch",
                    "module": module_path,
                    "type": type(manifest).__name__,
                })

            registry.register(manifest)
            dp.include_router(mod.router)
            loaded.append(getattr(manifest, "name", module_path))

        except Exception as exc:
            failed.append((module_path, str(exc)))
            logger.error({
                "event": "feature_load_failed",
                "module": module_path,
                "error": type(exc).__name__,
                "detail": str(exc),
            })

    logger.info({
        "event": "features_summary",
        "loaded": loaded,
        "failed": [m for m, _ in failed],
        "loaded_count": len(loaded),
        "failed_count": len(failed),
    })

    if failed:
        logger.warning({
            "event": "degraded_startup",
            "message": f"{len(failed)} feature(s) failed to load; bot running in degraded mode",
        })

    return loaded, [m for m, _ in failed]
