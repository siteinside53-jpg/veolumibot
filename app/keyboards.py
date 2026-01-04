from telegram import ReplyKeyboardMarkup

BTN_PROFILE = "👤 Το προφίλ μου"
BTN_VIDEO = "🎬 Δημιουργία βίντεο"
BTN_IMAGES = "🖼 Εικόνες"
BTN_AUDIO = "🎧 Ήχος"
BTN_PROMPTS = "💡 Κανάλι με prompts"
BTN_SUPPORT = "☁️ Υποστήριξη"

def main_menu():
    return ReplyKeyboardMarkup(
        [
            [BTN_PROFILE],
            [BTN_VIDEO, BTN_IMAGES],
            [BTN_AUDIO],
            [BTN_PROMPTS, BTN_SUPPORT],
        ],
        resize_keyboard=True,
    )
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
