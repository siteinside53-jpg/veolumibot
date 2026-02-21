# app/routes/seedance.py
import os
import uuid
import base64
import logging
import asyncio
from typing import Optional

import httpx
from fastapi import APIRouter, Request, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_video
from ..core.paths import VIDEOS_DIR
from ..web_shared import public_base_url
from ..db import spend_credits_by_user_id, add_credits_by_user_id, set_last_result
from ..texts import map_provider_error_to_gr, tool_error_message_gr

logger = logging.getLogger(__name__)
router = APIRouter()

SEEDANCE_API_KEY = os.getenv("SEEDANCE_API_KEY", "").strip()
SEEDANCE_API_URL = os.getenv("SEEDANCE_API_URL", "https://api.seedance.ai/v1").strip()


def _seedance_headers() -> dict:
    if not SEEDANCE_API_KEY:
        raise RuntimeError("SEEDANCE_API_KEY missing (set it in Railway env)")
    return {
        "Authorization": f"Bearer {SEEDANCE_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _compute_cost(quality: str, duration: int) -> float:
    """Cost: base 1, high quality *2, duration multiplier (1 per 3s chunk)."""
    base = 1.0
    if quality == "high":
        base *= 2
    multiplier = max(1, (duration + 2) // 3)  # 3s=1x, 5s=2x, 10s=3x
    return round(base * multiplier, 2)


async def _run_seedance_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    quality: str,
    duration: int,
    camera_lock: bool,
    cost: float,
) -> None:
    try:
        headers = _seedance_headers()

        body: dict = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "quality": quality,
            "duration": duration,
            "camera_lock": camera_lock,
        }

        # 1) Create generation
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{SEEDANCE_API_URL}/generations", json=body, headers=headers)

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            raise RuntimeError(f"Seedance create error {r.status_code}: {data}")

        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise RuntimeError(f"No task_id returned: {data}")

        # 2) Poll until done
        poll_url = f"{SEEDANCE_API_URL}/generations/{task_id}"
        for _ in range(180):  # ~6 min at 2s
            async with httpx.AsyncClient(timeout=30) as c:
                pr = await c.get(poll_url, headers=_seedance_headers())

            try:
                status_data = pr.json()
            except Exception:
                status_data = {}

            status = (status_data.get("status") or "").lower()
            if status in ("succeeded", "completed", "done"):
                break
            if status in ("failed", "cancelled", "error"):
                raise RuntimeError(f"Seedance generation failed: {status_data}")

            await asyncio.sleep(2)
        else:
            raise RuntimeError("Seedance generation timeout")

        # 3) Download video
        video_url = (
            status_data.get("video_url")
            or status_data.get("output_url")
            or (status_data.get("output") or [None])[0]
        )
        if not video_url:
            raise RuntimeError(f"No video URL in response: {status_data}")

        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            vr = await c.get(video_url)
            if vr.status_code >= 400:
                raise RuntimeError(f"Video download error {vr.status_code}")
            video_bytes = vr.content

        name = f"seedance_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "seedance", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "\ud83d\udd3d \u039a\u03b1\u03c4\u03ad\u03b2\u03b1\u03c3\u03b5", "url": public_url}],
                [{"text": "\u2190 \u03a0\u03af\u03c3\u03c9", "callback_data": "menu:video"}],
            ]
        }

        await tg_send_video(
            chat_id=tg_chat_id,
            video_bytes=video_bytes,
            caption="\u2705 Seedance: \u0388\u03c4\u03bf\u03b9\u03bc\u03bf",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Seedance job")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Seedance fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/seedance/generate")
async def seedance_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    prompt: str = Form(""),
    aspect_ratio: str = Form("16:9"),
    quality: str = Form("std"),
    duration: str = Form("5"),
    camera_lock: str = Form("false"),
):
    prompt = (prompt or "").strip()
    init_data = (tg_init_data or "").strip()
    aspect_ratio = (aspect_ratio or "16:9").strip()
    quality = "high" if (quality or "").strip().lower() == "high" else "std"

    try:
        dur = int(duration)
    except (ValueError, TypeError):
        dur = 5
    dur = max(3, min(10, dur))

    cam_lock = (camera_lock or "").strip().lower() in ("true", "1", "yes")

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    COST = _compute_cost(quality, dur)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(
            db_user_id, COST, f"Seedance ({quality},{dur}s)", "seedance", "seedance-v1"
        )
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "\ud83c\udfac Seedance: \u03a4\u03bf \u03b2\u03af\u03bd\u03c4\u03b5\u03bf \u03b5\u03c4\u03bf\u03b9\u03bc\u03ac\u03b6\u03b5\u03c4\u03b1\u03b9\u2026")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_seedance_job,
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        quality,
        dur,
        cam_lock,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
