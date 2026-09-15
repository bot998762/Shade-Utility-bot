import html as _html
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.platform.capability import FeatureManifest
from app.utils import crypto

manifest = FeatureManifest(name="CryptoTools", version="1.0.0", category="Utility")
router = Router()

@router.message(Command("uuid"))
async def cmd_uuid(message: Message):
    await message.reply(f"🆔 **Generated UUIDv4:**\n`{crypto.gen_uuid()}`", parse_mode="Markdown")

@router.message(Command("password"))
async def cmd_password(message: Message):
    args = message.text.split()
    length = 16
    if len(args) > 1 and args[1].isdigit():
        length = max(8, min(64, int(args[1])))
    pwd = crypto.gen_password(length)
    await message.reply(f"🔑 **High-Entropy Password ({length} chars):**\n`{pwd}`", parse_mode="Markdown")

@router.message(Command("hash"))
async def cmd_hash(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ **Usage:** `/hash <text>`", parse_mode="Markdown")
        return
    md5_val, sha256_val, sha512_val, \
    sha3_224_val, sha3_256_val, sha3_384_val, sha3_512_val, \
    blake2b_val, blake2s_val = crypto.gen_hashes(args[1])
    await message.reply(
        f"🔐 **Cryptographic Hash Digest**\n"
        f"───────────────────────────\n"
        f"• **MD5:**\n`{md5_val}`\n\n"
        f"• **SHA-256:**\n`{sha256_val}`\n\n"
        f"• **SHA-512:**\n`{sha512_val}`\n\n"
        f"• **SHA3-256:**\n`{sha3_256_val}`\n\n"
        f"• **SHA3-512:**\n`{sha3_512_val}`\n\n"
        f"• **BLAKE2b:**\n`{blake2b_val}`\n\n"
        f"• **BLAKE2s:**\n`{blake2s_val}`\n"
        f"───────────────────────────",
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
        await message.reply("❌ <b>Usage:</b> <code>/b64de &lt;string&gt;</code>", parse_mode="HTML")
        return
    try:
        decoded = crypto.b64_decode(args[1])
        await message.reply(
            f"🔡 <b>Base64 Decoded:</b>\n<code>{_html.escape(decoded)}</code>",
            parse_mode="HTML",
        )
    except Exception:
        await message.reply("❌ <b>Error:</b> Invalid Base64 string payload.", parse_mode="HTML")

@router.message(Command("time"))
async def cmd_time(message: Message):
    await message.reply(f"⏰ **Current Unix Epoch:**\n`{crypto.current_time()}`", parse_mode="Markdown")
