# app/keyboards.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from .texts import BTN_PROFILE, BTN_VIDEO, BTN_IMAGES, BTN_AUDIO, BTN_PROMPTS, BTN_SUPPORT
from .config import WEBAPP_URL


def _base_url() -> str:
    return (WEBAPP_URL or "").rstrip("/")


def start_inline_menu():
    base = _base_url()
    profile_url = f"{base}/profile" if base else "https://veolumibot-production.up.railway.app/profile"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_PROFILE, web_app=WebAppInfo(url=profile_url))],
            [InlineKeyboardButton(BTN_VIDEO, callback_data="menu:video")],
            [InlineKeyboardButton(BTN_IMAGES, callback_data="menu:images")],
            [InlineKeyboardButton(BTN_AUDIO, callback_data="menu:audio")],
            [InlineKeyboardButton(BTN_PROMPTS, url="https://t.me/veolumiprompts")],
            [InlineKeyboardButton(BTN_SUPPORT, url="https://t.me/veolumisupport")],
        ]
    )


def open_profile_webapp_kb():
    base = _base_url()
    url = f"{base}/profile" if base else "https://veolumibot-production.up.railway.app/profile"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("👤 Άνοιγμα Προφίλ / Αγορά Credits", web_app=WebAppInfo(url=url))]]
    )
