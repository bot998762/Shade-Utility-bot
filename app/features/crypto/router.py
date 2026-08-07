from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.platform.capability import FeatureManifest
from app.utils import crypto

manifest = FeatureManifest(name="CryptoTools", version="1.0.0", category="Utility")
router = Router()

@router.message(Command("uuid"))
async def cmd_uuid(message: Message):
    await message.reply(f"🆔 **Your UUIDv4:**\n`{crypto.gen_uuid()}`", parse_mode="Markdown")

@router.message(Command("password"))
async def cmd_password(message: Message):
    args = message.text.split()
    length = 16
    if len(args) > 1 and args[1].isdigit():
        length = max(8, min(64, int(args[1])))
    pwd = crypto.gen_password(length)
    await message.reply(f"🔑 **Generated Password ({length} chars):**\n`{pwd}`", parse_mode="Markdown")

@router.message(Command("hash"))
async def cmd_hash(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/hash <text>`", parse_mode="Markdown")
        return
    md5_val, sha256_val, sha512_val = crypto.gen_hashes(args[1])
    await message.reply(
        f"🔐 **Cryptographic Hashes:**\n"
        f"───────────────\n"
        f"• **MD5:**\n`{md5_val}`\n\n"
        f"• **SHA-256:**\n`{sha256_val}`\n\n"
        f"• **SHA-512:**\n`{sha512_val}`\n"
        f"───────────────",
        parse_mode="Markdown"
    )

@router.message(Command("b64en"))
async def cmd_b64en(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/b64en <text>`", parse_mode="Markdown")
        return
    await message.reply(f"🔢 **Base64 Encoded:**\n`{crypto.b64_encode(args[1])}`", parse_mode="Markdown")

@router.message(Command("b64de"))
async def cmd_b64de(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/b64de <string>`", parse_mode="Markdown")
        return
    try:
        await message.reply(f"🔡 **Base64 Decoded:**\n`{crypto.b64_decode(args[1])}`", parse_mode="Markdown")
    except Exception:
        await message.reply("❌ **Error:** Invalid Base64 string.")

@router.message(Command("time"))
async def cmd_time(message: Message):
    await message.reply(f"⏰ **Current Unix Timestamp:**\n`{crypto.current_time()}`", parse_mode="Markdown")
