from aiogram import Dispatcher
from app.platform.capability import CapabilityRegistry

from app.features.general.router import router as general_router, manifest as general_manifest
from app.features.crypto.router import router as crypto_router, manifest as crypto_manifest
from app.features.media.router import router as media_router, manifest as media_manifest
from app.features.admin.router import router as admin_router, manifest as admin_manifest

def load_features(dp: Dispatcher, registry: CapabilityRegistry):
    registry.register(general_manifest)
    registry.register(crypto_manifest)
    registry.register(media_manifest)
    registry.register(admin_manifest)
    
    dp.include_router(general_router)
    dp.include_router(crypto_router)
    dp.include_router(media_router)
    dp.include_router(admin_router)
