# app/routes/me.py
import time
from typing import Dict, Optional, Tuple

import httpx
from fastapi import APIRouter

from ..web_shared import packs_list, plans_list, SUBSCRIPTION_PLANS
from ..core.telegram_auth import db_user_from_webapp, verify_telegram_init_data
from ..config import BOT_TOKEN

router = APIRouter()

@router.post("/api/me")
async def me(payload: dict):
    init_data = payload.get("initData", "")
    dbu = db_user_from_webapp(init_data)

    total_credits = float(dbu.get("credits", 0) or 0)
    extra_credits = float(dbu.get("extra_credits", 0) or 0)
    plan_sku = dbu.get("plan_sku", "FREE") or "FREE"

    # Plan info
    plan = SUBSCRIPTION_PLANS.get(plan_sku, SUBSCRIPTION_PLANS["FREE"])
    plan_name = plan["name"]
    plan_total = plan["credits"]

    # Plan credits remaining (total minus extra)
    plan_credits_remaining = max(0.0, total_credits - extra_credits)

    return {
        "ok": True,
        "user": {
            "id": dbu["tg_user_id"],
            "username": dbu.get("tg_username") or "",
            "credits": total_credits,
            "extra_credits": extra_credits,
            "plan_sku": plan_sku,
            "plan_name": plan_name,
            "plan_total": plan_total,
            "plan_credits_remaining": plan_credits_remaining,
        },
        "packs": packs_list(),
        "plans": plans_list(),
    }

# ----------------------
# Telegram avatar
# ----------------------
_AVATAR_CACHE: Dict[int, Tuple[str, float]] = {}
_AVATAR_TTL_SECONDS = 60 * 30

async def _get_telegram_file_url(file_id: str) -> Optional[str]:
    if not file_id:
        return None
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{base}/getFile", params={"file_id": file_id})
        data = r.json()
        if not data.get("ok"):
            return None
        file_path = (data.get("result") or {}).get("file_path")
        if not file_path:
            return None
        return f"{base}/file/{file_path}"

async def _fetch_telegram_avatar_url(tg_user_id: int) -> Optional[str]:
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{base}/getUserProfilePhotos", params={"user_id": tg_user_id, "limit": 1})
        data = r.json()
        if not data.get("ok"):
            return None
        photos = (data.get("result") or {}).get("photos") or []
        if not photos or not photos[0]:
            return None
        best = photos[0][-1]
        file_id = best.get("file_id")
        if not file_id:
            return None
        return await _get_telegram_file_url(file_id)

@router.post("/api/avatar")
async def avatar(payload: dict):
    init_data = payload.get("initData", "")
    tg_user = verify_telegram_init_data(init_data)
    tg_id = int(tg_user["id"])

    now = time.time()
    cached = _AVATAR_CACHE.get(tg_id)
    if cached and cached[1] > now:
        return {"ok": True, "url": cached[0]}

    url = await _fetch_telegram_avatar_url(tg_id)
    if not url:
        _AVATAR_CACHE[tg_id] = ("", now + 60)
        return {"ok": True, "url": ""}

    _AVATAR_CACHE[tg_id] = (url, now + _AVATAR_TTL_SECONDS)
    return {"ok": True, "url": url}
