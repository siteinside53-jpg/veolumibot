import os
import time
import uuid
import hmac
import base64
import hashlib
import logging
import httpx

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_video
from ..db import spend_credits_by_user_id, add_credits_by_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY", "").strip()
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY", "").strip()
KLING_BASE_URL = os.getenv("KLING_BASE_URL", "https://api.klingai.com").strip()


# -------------------------
# AUTH HEADERS (HMAC)
# -------------------------
def _kling_headers() -> dict:
    if not KLING_ACCESS_KEY or not KLING_SECRET_KEY:
        raise RuntimeError("Missing KLING_ACCESS_KEY / KLING_SECRET_KEY")

    return {
        "Authorization": f"Bearer {KLING_ACCESS_KEY}",
        "X-Kling-Secret": KLING_SECRET_KEY,
        "Content-Type": "application/json",
    }


# -------------------------
# CREATE TASK
# -------------------------
async def create_kling_task(payload: dict) -> str:
    url = f"{KLING_BASE_URL}/v1/videos/text2video"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, json=payload, headers=kling_headers())
        data = r.json()

    if r.status_code != 200 or data.get("code") != 0:
        raise RuntimeError(f"Kling create error: {data}")

    return data["data"]["task_id"]


# -------------------------
# POLL TASK
# -------------------------
async def poll_kling_task(task_id: str) -> str:
    url = f"{KLING_BASE_URL}/v1/videos/query"
    payload = {"task_id": task_id}

    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(60):  # ~5 λεπτά max
            r = await client.post(url, json=payload, headers=kling_headers())
            data = r.json()

            if data.get("data", {}).get("task_status") == "success":
                videos = data["data"]["task_result"]["videos"]
                return videos[0]["url"]

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
    cost: float
):
    try:
        payload = {
            "model_name": "kling-v2-6",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration": 5,
            "mode": "std"
        }

        task_id = await create_kling_task(payload)
        video_url = await poll_kling_task(task_id)

        await tg_send_video(
            chat_id=tg_chat_id,
            video_url=video_url,
            caption="🎬 Kling Video: Έτοιμο"
        )

    except Exception as e:
        logger.exception("Kling job failed")
        add_credits_by_user_id(db_user_id, cost, "Refund Kling", "system", None)
        await tg_send_message(tg_chat_id, f"❌ Kling error:\n{str(e)[:300]}")


# -------------------------
# API ENDPOINT
# -------------------------
@router.post("/api/kling26/generate")
async def kling_generate(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()

    prompt = (payload.get("prompt") or "").strip()
    aspect_ratio = payload.get("aspect_ratio", "16:9")

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    dbu = db_user_from_webapp(payload.get("initData", ""))
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    COST = 3.0
    spend_credits_by_user_id(db_user_id, COST, "Kling Video", "kling", "kling-v2-6")

    await tg_send_message(tg_chat_id, "🎥 Kling: Δημιουργία video…")

    background_tasks.add_task(
        run_kling_job,
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        COST
    )

    return {"ok": True}
