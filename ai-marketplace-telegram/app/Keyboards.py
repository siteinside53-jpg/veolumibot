from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from .texts import *
from .config import WEBAPP_URL

def main_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_PROFILE)],
            [KeyboardButton(BTN_VIDEO), KeyboardButton(BTN_IMAGES)],
            [KeyboardButton(BTN_AUDIO)],
            [KeyboardButton(BTN_PROMPTS), KeyboardButton(BTN_SUPPORT)],
        ],
        resize_keyboard=True
    )

def open_profile_webapp_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Άνοιγμα Προφίλ / Αγορά Credits", web_app=WebAppInfo(url=f"{WEBAPP_URL}/profile"))]
    ])
