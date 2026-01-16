# app/routes/_shared.py
import os
import hmac
import json
import time
import base64
import hashlib
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, List
from urllib.parse import parse_qsl

import httpx
from fastapi import HTTPException
from fastapi.templating import Jinja2Templates

from ..config import BOT_TOKEN, WEBAPP_URL
from ..db import ensure_user, get_user

# ----------------------
# Paths / Templates
# ----------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # /app/app
TEMPLATES_DIR = BASE_DIR / "web_templates"
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
VIDEOS_DIR = STATIC_DIR / "videos"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def _ensure_dir(path: Path):
    if path.exists() and path.is_file():
        path.unlink()
    path.mkdir(parents=True, exist_ok=True)

_ensure_dir(STATIC_DIR)
_ensure_dir(IMAGES_DIR)
_ensure_dir(VIDEOS_DIR)

# ----------------------
# Packs / Catalog
# ----------------------
CREDITS_PACKS = {
    "CREDITS_100": {"credits": 100, "amount_eur": 7.00, "title": "Start", "desc": "100 credits"},
    "CREDITS_250": {"credits": 250, "amount_eur": 12.00, "title": "Middle", "desc": "250 credits"},
    "CREDITS_500": {"credits": 500, "amount_eur": 22.00, "title": "Pro", "desc": "500 credits"},
    "CREDITS_1000": {"credits": 1000, "amount_eur": 40.00, "title": "Creator", "desc": "1000 credits"},
}

def packs_list():
    return [{"sku": k, **v} for k, v in CREDITS_PACKS.items()]

TOOLS_CATALOG = {
    "video": [
        {"name": "Kling 2.6 Motion", "credits": "20–75"},
        {"name": "Kling 01", "credits": "15–25"},
        {"name": "Kling V1 Avatar", "credits": "16–32"},
        {"name": "Kling 2.6", "credits": "11–44"},
        {"name": "Kling 2.1", "credits": "5–64"},
        {"name": "Sora 2 PRO", "credits": "18–60"},
        {"name": "Veo 3.1", "credits": "12"},
        {"name": "Sora 2", "credits": "6"},
        {"name": "Veo 3", "credits": "10"},
        {"name": "Midjourney", "credits": "2–13"},
        {"name": "Runway Aleph", "credits": "22"},
        {"name": "Runway", "credits": "6"},
        {"name": "Seedance", "credits": "1–20"},
        {"name": "Kling 2.5 Turbo", "credits": "8–17"},
        {"name": "Wan 2.5", "credits": "12–30"},
        {"name": "Hailuo 02", "credits": "6–12"},
    ],
    "photo": [
        {"name": "GPT image", "credits": "2"},
        {"name": "Seedream 4.5", "credits": "1.3"},
        {"name": "Nano Banana Pro", "credits": "4"},
        {"name": "Nano Banana", "credits": "0.5"},
        {"name": "Qwen", "credits": "1"},
        {"name": "Seedream", "credits": "1–4"},
        {"name": "Midjourney", "credits": "2"},
    ],
    "audio": [
        {"name": "Suno V5", "credits": "2.4"},
        {"name": "Eleven Labs", "credits": "1–30"},
    ],
}

# ----------------------
# Telegram WebApp initData verification
# ----------------------
def verify_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(401, "Missing initData (open inside Telegram)")

    data = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_received = data.pop("hash", None)
    if not hash_received:
        raise HTTPException(401, "No hash")

    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(h, hash_received):
        raise HTTPException(401, "Invalid initData signature")

    user_json = data.get("user")
    if not user_json:
        raise HTTPException(401, "No user")

    try:
        return json.loads(user_json)
    except Exception:
        raise HTTPException(401, "Bad user json")

def db_user_from_webapp(init_data: str):
    tg_user = verify_telegram_init_data(init_data)
    tg_id = int(tg_user["id"])

    ensure_user(tg_id, tg_user.get("username"), tg_user.get("first_name"))
    dbu = get_user(tg_id)
    if not dbu:
        raise HTTPException(500, "User not found after ensure_user")
    return dbu

# ----------------------
# Telegram helpers
# ----------------------
async def tg_send_message(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json={"chat_id": chat_id, "text": text})
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {j}")

async def tg_send_photo(
    chat_id: int,
    img_bytes: bytes,
    caption: str = "",
    reply_markup: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {"chat_id": str(chat_id), "caption": caption}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    files = {"photo": ("photo.png", img_bytes, "image/png")}
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(url, data=data, files=files)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendPhoto failed: {j}")
        return j["result"]

async def tg_send_video(
    chat_id: int,
    video_bytes: bytes,
    caption: str = "",
    reply_markup: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
    data = {"chat_id": str(chat_id), "caption": caption}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    files = {"video": ("video.mp4", video_bytes, "video/mp4")}
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, data=data, files=files)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendVideo failed: {j}")
        return j["result"]

def public_base_url() -> str:
    base = (WEBAPP_URL or "").strip().rstrip("/")
    return base or "https://veolumibot-production.up.railway.app"
