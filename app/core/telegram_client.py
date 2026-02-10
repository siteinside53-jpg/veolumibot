# tg_send_message, tg_send_photo, tg_send_video
# app/core/telegram_client.py
import json
import httpx
from typing import Optional, Dict, Any

from ..config import BOT_TOKEN

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

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, data=data, files=files)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendVideo failed: {j}")
        return j["result"]


async def tg_send_message_safe(chat_id: int, text: str) -> None:
    """Στέλνει μήνυμα στο Telegram χωρίς να σκάει η ροή σε περίπτωση σφάλματος."""
    try:
        await tg_send_message(chat_id, text)
    except Exception:
        return
