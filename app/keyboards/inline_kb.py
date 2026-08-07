from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_kb(bot_username: str = "ShadeUtilityBot"):
    add_to_group_url = f"https://t.me/{bot_username}?startgroup=true"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛠️ Developer Tools", callback_data="cat_dev"),
            InlineKeyboardButton(text="🔑 String Session", callback_data="cat_session")
        ],
        [
            InlineKeyboardButton(text="📸 Media & OCR", callback_data="cat_media"),
            InlineKeyboardButton(text="🌐 Web & Utilities", callback_data="cat_web")
        ],
        [
            InlineKeyboardButton(text="📘 Full Manual & Manuals (/help)", callback_data="menu_help")
        ],
        [
            InlineKeyboardButton(text="➕ Add Bot to Telegram Group 👥", url=add_to_group_url)
        ]
    ])

def category_dev_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Main Menu", callback_data="back_main")]
    ])
