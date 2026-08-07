import time
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from app.platform.capability import FeatureManifest, CapabilityRegistry
from app.core.config import settings

manifest = FeatureManifest(name="AdminControl", version="1.0.0", category="System", is_premium=True)
router = Router()

def is_admin(message: Message):
    return message.from_user.id == settings.ADMIN_ID

@router.message(Command("diag"), F.func(is_admin))
async def cmd_diag(message: Message, registry: CapabilityRegistry, bootstrap_ref):
    """Phase 6: Self Diagnostics & Phase 4: Operational Control"""
    uptime = time.time() - bootstrap_ref.start_time
    loaded = len(registry.features)
    disabled = sum(1 for f in registry.features.values() if not f.enabled)
    failed = len(registry.failed_loads)
    
    report = (
        f"🤖 **Shade Utility V8 Control Plane**\n\n"
        f"**Features**\n"
        f"Loaded    : `{loaded}`\n"
        f"Disabled  : `{disabled}`\n"
        f"Failed    : `{failed}`\n\n"
        f"**Resources**\n"
        f"HTTP Pool : `{'OK' if bootstrap_ref.http_session else 'FAIL'}`\n"
        f"Uptime    : `{uptime:.2f} sec`"
    )
    await message.reply(report, parse_mode="Markdown")

@router.message(Command("disable"), F.func(is_admin))
async def cmd_disable(message: Message, registry: CapabilityRegistry):
    args = message.text.split()
    if len(args) > 1 and registry.toggle(args[1], False):
        await message.reply(f"✅ Feature '{args[1]}' disabled at runtime.")
    else:
        await message.reply("❌ Invalid feature name.")

@router.message(Command("enable"), F.func(is_admin))
async def cmd_enable(message: Message, registry: CapabilityRegistry):
    args = message.text.split()
    if len(args) > 1 and registry.toggle(args[1], True):
        await message.reply(f"✅ Feature '{args[1]}' enabled.")
    else:
        await message.reply("❌ Invalid feature name.")
