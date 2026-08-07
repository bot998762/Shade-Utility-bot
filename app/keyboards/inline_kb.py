from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_kb(bot_username: str = "ShadeUtilityBot"):
    add_to_group_url = f"https://t.me/{bot_username}?startgroup=true"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🖼️ Image Tools", callback_data="coming_soon_image"),
            InlineKeyboardButton(text="📄 PDF Tools", callback_data="coming_soon_pdf")
        ],
        [
            InlineKeyboardButton(text="🎥 Media Tools", callback_data="coming_soon_media"),
            InlineKeyboardButton(text="⚙️ All Utilities", callback_data="menu_utils")
        ],
        [
            InlineKeyboardButton(text="➕ Add Me To Your Group 👥", url=add_to_group_url)
        ]
    ])

def utils_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Main Menu", callback_data="back_main")]
    ])
