# app/keyboards.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from .texts import (
    BTN_TOPUP,
    BTN_PROFILE,
    BTN_VIDEO,
    BTN_IMAGES,
    BTN_AUDIO,
    BTN_TEXT_AI,
    BTN_JOBS,
    BTN_PROMPTS,
    BTN_SUPPORT,
)
from .config import WEBAPP_URL

FALLBACK_WEBAPP_BASE = "https://veolumibot-production.up.railway.app"


def _base_url() -> str:
    base = (WEBAPP_URL or "").strip().rstrip("/")
    return base if base else FALLBACK_WEBAPP_BASE


# ========================
# URL helpers
# ========================
def _webapp_profile_url() -> str:
    return f"{_base_url()}/profile"

# --- Video ---
def _webapp_kling_o1_url() -> str:
    return f"{_base_url()}/kling-o1"

def _webapp_kling21_url() -> str:
    return f"{_base_url()}/kling21"

def _webapp_kling25turbo_url() -> str:
    return f"{_base_url()}/kling25turbo"

def _webapp_kling26_url() -> str:
    return f"{_base_url()}/kling26"

def _webapp_kling26motion_url() -> str:
    return f"{_base_url()}/kling26motion"

def _webapp_kling26motion2_url() -> str:
    return f"{_base_url()}/kling26motion2"

def _webapp_kling30_url() -> str:
    return f"{_base_url()}/kling30"

def _webapp_kling30_2_url() -> str:
    return f"{_base_url()}/kling30-2"

def _webapp_klingv1avatar_url() -> str:
    return f"{_base_url()}/klingv1avatar"

def _webapp_runway_url() -> str:
    return f"{_base_url()}/runway"

def _webapp_runway_aleph_url() -> str:
    return f"{_base_url()}/runway-aleph"

def _webapp_seedance_url() -> str:
    return f"{_base_url()}/seedance"

def _webapp_sora2_url() -> str:
    return f"{_base_url()}/sora2"

def _webapp_sora2pro_url() -> str:
    return f"{_base_url()}/sora2pro"

def _webapp_veo31_url() -> str:
    return f"{_base_url()}/veo31"

def _webapp_veo3fast_url() -> str:
    return f"{_base_url()}/veo3fast"

def _webapp_wan25_url() -> str:
    return f"{_base_url()}/wan25"

def _webapp_wan26_url() -> str:
    return f"{_base_url()}/wan26"

def _webapp_hailuo02_url() -> str:
    return f"{_base_url()}/hailuo02"

def _webapp_topaz_url() -> str:
    return f"{_base_url()}/topaz-upscale"

def _webapp_modjourney_video_url() -> str:
    return f"{_base_url()}/modjourney-video"

# --- Image ---
def _webapp_gpt_image_url() -> str:
    return f"{_base_url()}/gpt-image"

def _webapp_seedream_url() -> str:
    return f"{_base_url()}/seedream"

def _webapp_seedream45_url() -> str:
    return f"{_base_url()}/seedream45"

def _webapp_nanobanana_pro_url() -> str:
    return f"{_base_url()}/nanobanana-pro"

def _webapp_nanobanana_url() -> str:
    return f"{_base_url()}/nanobanana"

def _webapp_midjourney_url() -> str:
    return f"{_base_url()}/midjourney"

def _webapp_grok_url() -> str:
    return f"{_base_url()}/grok"

# --- Audio ---
def _webapp_sunov5_url() -> str:
    return f"{_base_url()}/sunov5"

def _webapp_elevenlabs_url() -> str:
    return f"{_base_url()}/elevenlabs"

# --- Jobs ---
def _webapp_jobs_post_url() -> str:
    return f"{_base_url()}/jobs-post"

def _webapp_jobs_browse_url() -> str:
    return f"{_base_url()}/jobs-browse"


# ========================
# Main menu
# ========================
def start_inline_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_TOPUP, web_app=WebAppInfo(url=_webapp_profile_url()))],
            [InlineKeyboardButton(BTN_VIDEO, callback_data="menu:video")],
            [InlineKeyboardButton(BTN_IMAGES, callback_data="menu:images")],
            [InlineKeyboardButton(BTN_AUDIO, callback_data="menu:audio")],
            [InlineKeyboardButton(BTN_TEXT_AI, callback_data="menu:text")],
            [InlineKeyboardButton(BTN_JOBS, callback_data="menu:jobs")],
            [InlineKeyboardButton(BTN_PROMPTS, url="https://t.me/veolumiprompts")],
            [InlineKeyboardButton(BTN_SUPPORT, url="https://t.me/veolumisupport")],
        ]
    )


# ========================
# Video — category menu
# ========================
def video_models_menu() -> InlineKeyboardMarkup:
    return video_categories_menu()


def video_categories_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🟢 Kling (9 μοντέλα)", callback_data="menu:video:kling")],
            [InlineKeyboardButton("🎬 Runway (2 μοντέλα)", callback_data="menu:video:runway")],
            [InlineKeyboardButton("🛰 Sora (2 μοντέλα)", callback_data="menu:video:sora")],
            [InlineKeyboardButton("🎬 Google Veo (2 μοντέλα)", callback_data="menu:video:veo")],
            [InlineKeyboardButton("🌀 Wan (2 μοντέλα)", callback_data="menu:video:wan")],
            [InlineKeyboardButton("💃 Seedance 1.0 Lite (1–20 credits)", web_app=WebAppInfo(url=_webapp_seedance_url()))],
            [InlineKeyboardButton("🌊 Hailuo 02 (6–12 credits)", web_app=WebAppInfo(url=_webapp_hailuo02_url()))],
            [InlineKeyboardButton("✨ Topaz Upscale (14 credits)", web_app=WebAppInfo(url=_webapp_topaz_url()))],
            [InlineKeyboardButton("⚪ Grok Imagine Video", web_app=WebAppInfo(url=_webapp_grok_url()))],
            [InlineKeyboardButton("🟣 Modjourney Video (2–13 credits)", web_app=WebAppInfo(url=_webapp_modjourney_video_url()))],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


# --- Video submenus ---
def kling_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🟢 Kling O1 (15–25 credits)", web_app=WebAppInfo(url=_webapp_kling_o1_url()))],
            [InlineKeyboardButton("🟢 Kling 2.1 (5–64 credits)", web_app=WebAppInfo(url=_webapp_kling21_url()))],
            [InlineKeyboardButton("⚡ Kling 2.5 Turbo (8–17 credits)", web_app=WebAppInfo(url=_webapp_kling25turbo_url()))],
            [InlineKeyboardButton("🟢 Kling 2.6 (11–44 credits)", web_app=WebAppInfo(url=_webapp_kling26_url()))],
            [InlineKeyboardButton("🎯 Kling 2.6 Motion (20–75 credits)", web_app=WebAppInfo(url=_webapp_kling26motion_url()))],
            [InlineKeyboardButton("🎯 Kling 2.6 Motion 2", web_app=WebAppInfo(url=_webapp_kling26motion2_url()))],
            [InlineKeyboardButton("🔥 Kling 3.0 (18 credits)", web_app=WebAppInfo(url=_webapp_kling30_url()))],
            [InlineKeyboardButton("🔥 Kling 3.0 v2 (18 credits)", web_app=WebAppInfo(url=_webapp_kling30_2_url()))],
            [InlineKeyboardButton("👤 Kling V1 Avatar (16–32 credits)", web_app=WebAppInfo(url=_webapp_klingv1avatar_url()))],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:video")],
        ]
    )


def runway_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎬 Runway (6 credits)", web_app=WebAppInfo(url=_webapp_runway_url()))],
            [InlineKeyboardButton("🎬 Runway Aleph (22 credits)", web_app=WebAppInfo(url=_webapp_runway_aleph_url()))],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:video")],
        ]
    )


def sora_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛰 Sora 2 (6 credits)", web_app=WebAppInfo(url=_webapp_sora2_url()))],
            [InlineKeyboardButton("🛰 Sora 2 PRO (18–80 credits)", web_app=WebAppInfo(url=_webapp_sora2pro_url()))],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:video")],
        ]
    )


def veo_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎬 Google Veo 3.1 (10–60 credits)", web_app=WebAppInfo(url=_webapp_veo31_url()))],
            [InlineKeyboardButton("⚡ Google Veo 3 Fast (7–30 credits)", web_app=WebAppInfo(url=_webapp_veo3fast_url()))],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:video")],
        ]
    )


def wan_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🌀 Wan 2.5 (12–30 credits)", web_app=WebAppInfo(url=_webapp_wan25_url()))],
            [InlineKeyboardButton("🌀 Wan 2.6 (14–56 credits)", web_app=WebAppInfo(url=_webapp_wan26_url()))],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:video")],
        ]
    )


# ========================
# Image — category menu
# ========================
def image_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧠 GPT Image 1.5 (1–5 credits)", web_app=WebAppInfo(url=_webapp_gpt_image_url()))],
            [InlineKeyboardButton("🌱 Seedream (2 μοντέλα)", callback_data="menu:images:seedream")],
            [InlineKeyboardButton("🍌 Nano Banana (2 μοντέλα)", callback_data="menu:images:nanobanana")],
            [InlineKeyboardButton("🤖 Qwen AI (1 credit)", callback_data="menu:set:image:qwen_ai")],
            [InlineKeyboardButton("🟣 Midjourney (2 credits)", web_app=WebAppInfo(url=_webapp_midjourney_url()))],
            [InlineKeyboardButton("⚪ Grok Imagine (0.8–4 credits)", web_app=WebAppInfo(url=_webapp_grok_url()))],
            [InlineKeyboardButton("🧪 Flux Kontext (1 credit)", callback_data="menu:set:image:flux_kontext")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


# --- Image submenus ---
def seedream_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🌱 Seedream (1–4 credits)", web_app=WebAppInfo(url=_webapp_seedream_url()))],
            [InlineKeyboardButton("🌱 Seedream 4.5 (1.3 credits)", web_app=WebAppInfo(url=_webapp_seedream45_url()))],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:images")],
        ]
    )


def nanobanana_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🍌 Nano Banana PRO (4 credits)", web_app=WebAppInfo(url=_webapp_nanobanana_pro_url()))],
            [InlineKeyboardButton("🍌 Nano Banana AI (0.5 credits)", web_app=WebAppInfo(url=_webapp_nanobanana_url()))],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:images")],
        ]
    )


# ========================
# Audio models
# ========================
def audio_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎵 Suno V5 (2.4 credits)", web_app=WebAppInfo(url=_webapp_sunov5_url()))],
            [InlineKeyboardButton("🗣 ElevenLabs (1–30 credits)", web_app=WebAppInfo(url=_webapp_elevenlabs_url()))],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


# ========================
# Text AI models
# ========================
def text_models_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💬 Gemini 3 Flash (0.5 credits)", callback_data="menu:set:text:gemini3flash")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


# ========================
# Profile WebApp
# ========================
def open_profile_webapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👤 Άνοιγμα Προφίλ / Αγορά Credits", web_app=WebAppInfo(url=_webapp_profile_url()))]
        ]
    )


# ========================
# Jobs (WebApp)
# ========================
def jobs_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 Δημοσίευσε Αγγελία", web_app=WebAppInfo(url=_webapp_jobs_post_url()))],
            [InlineKeyboardButton("👀 Δες Εργασίες", web_app=WebAppInfo(url=_webapp_jobs_browse_url()))],
            [
                InlineKeyboardButton("ℹ️ Τι να γράψω;", callback_data="jobs:help:client"),
                InlineKeyboardButton("ℹ️ Πώς δουλεύει", callback_data="jobs:help:freelancer"),
            ],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )
