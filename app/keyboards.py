# app/keyboards.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from .texts import BTN_PROFILE, BTN_VIDEO, BTN_IMAGES, BTN_AUDIO, BTN_PROMPTS, BTN_SUPPORT
from .config import WEBAPP_URL


def _webapp_url(path: str) -> str:
    base = (WEBAPP_URL or "").strip().rstrip("/")
    if not base.startswith("https://"):
        # Βάλε το web domain σου εδώ (αυτό που έκανες Generate Domain στο web service)
        base = "https://veolumibot-production.up.railway.app"
    return f"{base}{path}"


def start_inline_menu():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_PROFILE, web_app=WebAppInfo(url=_webapp_url("/profile")))],
            [InlineKeyboardButton(BTN_VIDEO, callback_data="menu:video")],
            [InlineKeyboardButton(BTN_IMAGES, callback_data="menu:images")],
            [InlineKeyboardButton(BTN_AUDIO, callback_data="menu:audio")],
            [InlineKeyboardButton(BTN_PROMPTS, url="https://t.me/veolumiprompts")],
            [InlineKeyboardButton(BTN_SUPPORT, url="https://t.me/veolumisupport")],
        ]
    )


def open_profile_webapp_kb():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("👤 Άνοιγμα Προφίλ / Αγορά Credits", web_app=WebAppInfo(url=_webapp_url("/profile")))]]
    )
