import time
import psutil
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from app.platform.capability import FeatureManifest, CapabilityRegistry
from app.core.config import settings

manifest = FeatureManifest(name="AdminControl", version="1.0.0", category="System", is_premium=True)
router = Router()

def is_admin(message: Message):
    return settings.ADMIN_ID == 0 or message.from_user.id == settings.ADMIN_ID

@router.message(Command("diag"), F.func(is_admin))
async def cmd_diag(message: Message, registry: CapabilityRegistry, bootstrap_ref):
    uptime = time.time() - bootstrap_ref.start_time
    loaded = len(registry.features)
    disabled = sum(1 for f in registry.features.values() if not f.enabled)
    
    report = (
        f"🤖 **Shade Platform Control Plane**\n───────────────────────────\n"
        f"**Modules Engine**\n"
        f"• Loaded Features : `{loaded}`\n"
        f"• Disabled Features: `{disabled}`\n\n"
        f"**System Status**\n"
        f"• HTTP Pool Status: `{'OK' if bootstrap_ref.http_session else 'FAIL'}`\n"
        f"• Total Uptime    : `{uptime:.2f} sec`\n"
        f"───────────────────────────"
    )
    await message.reply(report, parse_mode="Markdown")

@router.message(Command("health"))
async def cmd_health(message: Message, bootstrap_ref):
    process = psutil.Process()
    mem_mb = process.memory_info().rss / (1024 * 1024)
    status = (
        f"🏥 **System Health Status**\n───────────────────────────\n"
        f"• **Platform Status:** Operational 🟢\n"
        f"• **RAM Memory RSS:** `{mem_mb:.2f} MB`\n"
        f"• **HTTP Client:** `{'Active' if bootstrap_ref.http_session else 'Closed'}`\n"
        f"───────────────────────────"
    )
    await message.reply(status, parse_mode="Markdown")
