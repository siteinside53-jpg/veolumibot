from telegram import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from .texts import (
    BTN_PROFILE, BTN_VIDEO, BTN_IMAGES, BTN_AUDIO, BTN_PROMPTS, BTN_SUPPORT,
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

def image_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧠 GPT Image (WebApp)", web_app=WebAppInfo(url=_webapp_gpt_image_url()))],
            [InlineKeyboardButton("🍌 Nano Banana PRO", callback_data="menu:set:image:nano_banana_pro")],
            [InlineKeyboardButton("🟣 Midjourney", callback_data="menu:set:image:midjourney")],
            [InlineKeyboardButton("🧪 Flux Kontext", callback_data="menu:set:image:flux_kontext")],
            [InlineKeyboardButton("⚪ Grok Imagine (0.8–4)", callback_data="menu:set:image:grok_imagine")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )
