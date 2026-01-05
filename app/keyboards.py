# app/keyboards.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from .texts import (
    BTN_PROFILE,
    BTN_VIDEO,
    BTN_IMAGES,
    BTN_AUDIO,
    BTN_PROMPTS,
    BTN_SUPPORT,
)
from .config import WEBAPP_URL

# Σταθερό fallback domain show
FALLBACK_WEBAPP_BASE = "https://veolumibot-production.up.railway.app"


def _webapp_profile_url() -> str:
    """
    Βγάζει το σωστό URL για το Telegram WebApp.
    - Αν έχεις WEBAPP_URL στο env, το χρησιμοποιεί.
    - Αλλιώς χρησιμοποιεί fallback.
    """
    base = (WEBAPP_URL or "").strip().rstrip("/")
    if not base:
        base = FALLBACK_WEBAPP_BASE
    return f"{base}/profile"


# -----------------------
# MAIN MENU (Start card)
# -----------------------
def start_inline_menu() -> InlineKeyboardMarkup:
    """
    Κεντρικό inline menu κάτω από το START card.
    ΣΗΜΑΝΤΙΚΟ:
    - Το κουμπί Profile εδώ ανοίγει WebApp (όχι callback_data),
      άρα ΔΕΝ θα περνάει από on_menu_click.
    """
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_PROFILE, web_app=WebAppInfo(url=_webapp_profile_url()))],
            [InlineKeyboardButton(BTN_VIDEO, callback_data="menu:video")],
            [InlineKeyboardButton(BTN_IMAGES, callback_data="menu:images")],
            [InlineKeyboardButton(BTN_AUDIO, callback_data="menu:audio")],
            [InlineKeyboardButton(BTN_PROMPTS, url="https://t.me/veolumiprompts")],
            [InlineKeyboardButton(BTN_SUPPORT, url="https://t.me/veolumisupport")],
        ]
    )


# -----------------------
# SUB MENUS
# -----------------------
def video_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🟢 Kling 2.6 (11–44 credits)  □", callback_data="menu:set:video:kling_26")],
            [InlineKeyboardButton("🌀 Wan 2.6 (14–56 credits)    □", callback_data="menu:set:video:wan_26")],
            [InlineKeyboardButton("🛰 Sora 2 PRO (18–80 credits) □", callback_data="menu:set:video:sora2pro")],
            [InlineKeyboardButton("🎥 Veo 3.1 (12 credits)       □", callback_data="menu:set:video:veo31")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


def image_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🍌 Nano Banana PRO           □", callback_data="menu:set:image:nano_banana_pro")],
            [InlineKeyboardButton("🟣 Midjourney                □", callback_data="menu:set:image:midjourney")],
            [InlineKeyboardButton("🧪 Flux Kontext              □", callback_data="menu:set:image:flux_kontext")],
            [InlineKeyboardButton("⚪ Grok Imagine (0.8–4)      □", callback_data="menu:set:image:grok_imagine")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


def audio_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎵 Suno V5                    □", callback_data="menu:set:audio:suno_v5")],
            [InlineKeyboardButton("🗣 ElevenLabs                 □", callback_data="menu:set:audio:elevenlabs")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


# -----------------------
# EXTRA: button κάτω από Profile text (αν το κρατάς)
# -----------------------
def open_profile_webapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👤 Άνοιγμα Προφίλ / Αγορά Credits", web_app=WebAppInfo(url=_webapp_profile_url()))]
        ]
            )
