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

FALLBACK_WEBAPP_BASE = "https://veolumibot-production.up.railway.app"


def _base_url() -> str:
    base = (WEBAPP_URL or "").strip().rstrip("/")
    return base if base else FALLBACK_WEBAPP_BASE


def _webapp_profile_url() -> str:
    return f"{_base_url()}/profile"


def _webapp_gpt_image_url() -> str:
    return f"{_base_url()}/gpt-image"


def _webapp_nanobanana_pro_url() -> str:
    return f"{_base_url()}/nanobanana-pro"


def start_inline_menu() -> InlineKeyboardMarkup:
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


def video_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🟢 Kling 2.6 (11–44 credits)", callback_data="menu:set:video:kling_26")],
            [InlineKeyboardButton("🌀 Wan 2.6 (14–56 credits)", callback_data="menu:set:video:wan_26")],
            [InlineKeyboardButton("🛰 Sora 2 PRO (18–80 credits)", callback_data="menu:set:video:sora2pro")],
            [InlineKeyboardButton("🎥 Veo 3.1 (12 credits)", callback_data="menu:set:video:veo31")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


def image_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧠 GPT Image 1.5", web_app=WebAppInfo(url=_webapp_gpt_image_url()))],
            [InlineKeyboardButton("🍌 Nano Banana PRO", web_app=WebAppInfo(url=_webapp_nanobanana_pro_url()))],
            [InlineKeyboardButton("🟣 Midjourney", callback_data="menu:set:image:midjourney")],
            [InlineKeyboardButton("🧪 Flux Kontext", callback_data="menu:set:image:flux_kontext")],
            [InlineKeyboardButton("⚪ Grok Imagine (0.8–4)", callback_data="menu:set:image:grok_imagine")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


def audio_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎵 Suno V5", callback_data="menu:set:audio:suno_v5")],
            [InlineKeyboardButton("🗣 ElevenLabs", callback_data="menu:set:audio:elevenlabs")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


def open_profile_webapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👤 Άνοιγμα Προφίλ / Αγορά Credits", web_app=WebAppInfo(url=_webapp_profile_url()))]
        ]
    )
