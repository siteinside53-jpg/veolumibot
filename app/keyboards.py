# app/keyboards.py
from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)

from .texts import (
    BTN_PROFILE,
    BTN_VIDEO,
    BTN_IMAGES,
    BTN_AUDIO,
    BTN_PROMPTS,
    BTN_SUPPORT,
)
from .config import WEBAPP_URL


def start_inline_menu():
    """Inline menu κάτω από το START card (σαν το άλλο bot)."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_PROFILE, callback_data="menu:profile")],
            [InlineKeyboardButton(BTN_VIDEO, callback_data="menu:video")],
            [InlineKeyboardButton(BTN_IMAGES, callback_data="menu:images")],
            [InlineKeyboardButton(BTN_AUDIO, callback_data="menu:audio")],
            [
                InlineKeyboardButton(BTN_PROMPTS, url="https://t.me/YOUR_PROMPTS_CHANNEL"),
            ],
            [
                InlineKeyboardButton(BTN_SUPPORT, callback_data="menu:support"),
            ],
            [
                InlineKeyboardButton(BTN_MENU, callback_data="menu:home"),
            ],
        ]
    )


def open_profile_webapp_kb():
    url = f"{WEBAPP_URL}/profile" if WEBAPP_URL else "/profile"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("👤 Άνοιγμα Προφίλ / Αγορά Credits", web_app=WebAppInfo(url=url))]]
    )
