# app/routes/_shared.py
import os
import hmac
import json
import time
import hashlib
import base64
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl

import httpx
from fastapi import HTTPException

from ..config import BOT_TOKEN, WEBAPP_URL
from ..db import ensure_user, get_user

# ======================
# Env / Keys
# ======================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ======================
# Paths / Static
# ======================
BASE_DIR = Path(__file__).resolve().parents[1]            # .../app
TEMPLATES_DIR = BASE_DIR / "web_templates"
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
VIDEOS_DIR = STATIC_DIR / "videos"


def ensure_dirs() -> None:
    """
    Φτιάχνει directories.
    Αν υπάρχει FILE με ίδιο όνομα, το σβήνει και το ξαναφτιάχνει ως directory.
    """
    for p in (STATIC_DIR, IMAGES_DIR, VIDEOS_DIR):
        if p.exists() and p.is_file():
            p.unlink()
        p.mkdir(parents=True, exist_ok=True)


def public_base_url() -> str:
    base = (WEBAPP_URL or "").strip().rstrip("/")
    return base or "https://veolumibot-production.up.railway.app"


# ======================
# Telegram WebApp initData verification
# ======================
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


def db_user_from_webapp(init_data: str) -> dict:
    tg_user = verify_telegram_init_data(init_data)
    tg_id = int(tg_user["id"])

    ensure_user(tg_id, tg_user.get("username"), tg_user.get("first_name"))

    dbu = get_user(tg_id)
    if not dbu:
        raise HTTPException(500, "User not found after ensure_user")
    return dbu


# ======================
# Telegram helpers
# ======================
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


# ======================
# Misc helpers
# ======================
def guess_image_mime(filename: str) -> str:
    f = (filename or "").lower().strip()
    if f.endswith(".jpg") or f.endswith(".jpeg"):
        return "image/jpeg"
    if f.endswith(".webp"):
        return "image/webp"
    return "image/png"


def now_ts() -> float:
    return time.time()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")
