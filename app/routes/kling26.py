import os
import time
import json
import base64
import hmac
import hashlib
import logging
import asyncio
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_video
from ..db import spend_credits_by_user_id, add_credits_by_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

# ===== ENV =====
KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY", "").strip()
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY", "").strip()

# ΠΡΟΣΟΧΗ: αν το δικό σου Kling dashboard δίνει άλλο base, άλλαξέ το στο Railway env
KLING_BASE_URL = os.getenv("KLING_BASE_URL", "https://api.klingai.com").strip()

# Endpoints (όπως τα έχεις ήδη στήσει)
TEXT2VIDEO_PATH = os.getenv("KLING_TEXT2VIDEO_PATH", "/v1/videos/text2video").strip()
QUERY_PATH = os.getenv("KLING_QUERY_PATH", "/v1/video_tasks/query").strip()

# -------------------------
# JWT helpers (HS256)
# -------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def _jwt_hs256(payload: Dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}

    header_b64 = _b64url(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url(sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"

def kling_headers() -> Dict[str, str]:
    """
    Kling auth με Access Key + Secret Key => Bearer JWT.
    Αν λείπουν env vars, θα σου βγάλει καθαρό error και ΔΕΝ θα χρεώσει άδικα.
    """
    if not KLING_ACCESS_KEY or not KLING_SECRET_KEY:
        raise RuntimeError("Missing KLING_ACCESS_KEY / KLING_SECRET_KEY (Railway env)")

    now = int(time.time())
    token = _jwt_hs256(
        payload={
            "iss": KLING_ACCESS_KEY,
            "iat": now,
            "nbf": now - 5,
            "exp": now + 30 * 60,  # 30 λεπτά
        },
        secret=KLING_SECRET_KEY,
    )

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# -------------------------
# HTTP helpers
# -------------------------
async def _safe_json(r: httpx.Response) -> Dict[str, Any]:
    try:
        return r.json()
    except Exception:
        return {"raw": (r.text or "")[:4000]}

def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


# -------------------------
# CREATE TASK
# -------------------------
async def create_kling_task(payload: dict) -> str:
    url = _join(KLING_BASE_URL, TEXT2VIDEO_PATH)

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, json=payload, headers=kling_headers())
        data = await _safe_json(r)

    # Kling-style: code == 0 success
    if r.status_code != 200 or data.get("code") != 0:
        raise RuntimeError(f"Kling create error: {data}")

    task_id = (data.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"Kling create error: missing task_id: {data}")
    return task_id


# -------------------------
# POLL TASK
# -------------------------
async def poll_kling_task(task_id: str) -> str:
    url = _join(KLING_BASE_URL, QUERY_PATH)
    payload = {"task_ids": [task_id]}

    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(80):  # ~6-7 λεπτά
            r = await client.post(url, json=payload, headers=kling_headers())
            data = await _safe_json(r)

            if r.status_code != 200 or data.get("code") != 0:
                raise RuntimeError(f"Kling query error: {data}")

            items = (data.get("data") or [])
            if not items:
                await asyncio.sleep(5)
                continue

            item = items[0]
            status = item.get("task_status")

            if status == "success":
                videos = (item.get("task_result") or {}).get("videos") or []
                if videos and videos[0].get("url"):
                    return videos[0]["url"]
                raise RuntimeError(f"Kling success but no video url: {item}")

            if status in ("failed", "error"):
                raise RuntimeError(f"Kling task failed: {item}")

            await asyncio.sleep(5)

    raise RuntimeError("Kling task timeout")


# -------------------------
# BACKGROUND JOB
# -------------------------
async def run_kling_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    cost: float,
):
    try:
        # payload για Kling 2.6 (κρατάω τα δικά σου fields)
        payload = {
            "model_name": "kling-v2-6",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration": 5,
            "mode": "std",
        }

        task_id = await create_kling_task(payload)
        video_url = await poll_kling_task(task_id)

        await tg_send_video(
            chat_id=tg_chat_id,
            video_url=video_url,
            caption="🎬 Kling 2.6: Έτοιμο",
        )

    except Exception as e:
        logger.exception("Kling job failed")
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Kling fail", "system", None)
        except Exception:
            logger.exception("Refund failed")

        await tg_send_message(tg_chat_id, f"❌ Kling error:\n{str(e)[:350]}")


# -------------------------
# API ENDPOINT
# -------------------------
@router.post("/api/kling26/generate")
async def kling_generate(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    prompt = (payload.get("prompt") or "").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "16:9").strip()

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    # auth webapp -> db user
    try:
        dbu = db_user_from_webapp(payload.get("initData", ""))
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    COST = 11.0  # βάλε το κόστος που θες

    # ΠΡΙΝ χρεώσεις credits, κάνε γρήγορο check ότι έχεις keys
    try:
        _ = kling_headers()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=400)

    # Spend credits
    try:
        spend_credits_by_user_id(db_user_id, COST, "Kling 2.6 Video", "kling", "kling-v2-6")
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    await tg_send_message(tg_chat_id, "🎥 Kling 2.6: Δημιουργία video…")

    background_tasks.add_task(
        run_kling_job,
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
