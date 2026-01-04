# app/keyboards.py
from telegram import (
    ReplyKeyboardMarkup,
    KeyboardButton,
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


def main_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_PROFILE)],
            [KeyboardButton(BTN_VIDEO), KeyboardButton(BTN_IMAGES)],
            [KeyboardButton(BTN_AUDIO)],
            [KeyboardButton(BTN_PROMPTS), KeyboardButton(BTN_SUPPORT)],
        ],
        resize_keyboard=True,
    )


def open_profile_webapp_kb():
    url = f"{WEBAPP_URL}/profile" if WEBAPP_URL else "/profile"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👤 Άνοιγμα Προφίλ / Αγορά Credits",
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )
