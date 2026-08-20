import time
import psutil
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from app.platform.capability import FeatureManifest, CapabilityRegistry
from app.core.config import settings
from app.core.logger import setup_logger

manifest = FeatureManifest(name="AdminControl", version="1.0.0", category="System", is_premium=True)
router = Router()
logger = setup_logger()


def _is_admin(message: Message) -> bool:
    """
    Returns True only if ADMIN_ID is configured AND the sender matches.
    If ADMIN_ID == 0 (unconfigured default) access is DENIED to everyone.
    """
    if settings.ADMIN_ID == 0:
        return False  # Fail-closed: unconfigured == locked down
    return message.from_user.id == settings.ADMIN_ID


@router.message(Command("diag"), F.func(_is_admin))
async def cmd_diag(message: Message, registry: CapabilityRegistry, bootstrap_ref) -> None:
    uptime = time.time() - bootstrap_ref.start_time
    loaded = len(registry.features)
    disabled = sum(1 for f in registry.features.values() if not f.enabled)

    process = psutil.Process()
    mem_mb = process.memory_info().rss / (1024 * 1024)
    cpu_pct = process.cpu_percent(interval=None)

    report = (
        f"🤖 **Shade Platform Control Plane**\n───────────────────────────\n"
        f"**Module Engine**\n"
        f"• Loaded Features : `{loaded}`\n"
        f"• Disabled Features: `{disabled}`\n\n"
        f"**System Status**\n"
        f"• HTTP Pool       : `{'OK' if bootstrap_ref.http_session and not bootstrap_ref.http_session.closed else 'FAIL'}`\n"
        f"• RAM (RSS)       : `{mem_mb:.1f} MB`\n"
        f"• CPU             : `{cpu_pct:.1f}%`\n"
        f"• Uptime          : `{uptime:.1f}s`\n"
        f"───────────────────────────"
    )
    await message.reply(report, parse_mode="Markdown")
    logger.info({"event": "admin_diag", "user_id": message.from_user.id})


@router.message(Command("health"), F.func(_is_admin))
async def cmd_health(message: Message, bootstrap_ref) -> None:
    process = psutil.Process()
    mem_mb = process.memory_info().rss / (1024 * 1024)
    http_ok = bootstrap_ref.http_session and not bootstrap_ref.http_session.closed
    status = (
        f"🏥 **System Health**\n───────────────────────────\n"
        f"• Platform   : {'Operational 🟢' if http_ok else 'Degraded 🔴'}\n"
        f"• RAM (RSS)  : `{mem_mb:.1f} MB`\n"
        f"• HTTP Client: `{'Active' if http_ok else 'Closed'}`\n"
        f"───────────────────────────"
    )
    await message.reply(status, parse_mode="Markdown")
