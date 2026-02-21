# app/routes/modjourney_video.py
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

MODJOURNEY_API_KEY = os.getenv("MODJOURNEY_API_KEY", "").strip()
MODJOURNEY_API_URL = os.getenv(
    "MODJOURNEY_API_URL", "https://api.modjourney.ai/v1"
).strip()


def _modjourney_headers() -> dict:
    if not MODJOURNEY_API_KEY:
        raise RuntimeError("MODJOURNEY_API_KEY missing (set it in Railway env)")
    return {
        "Authorization": f"Bearer {MODJOURNEY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _compute_cost(aspect_ratio: str) -> float:
    """Base 2, wider/taller ratios cost more."""
    ratio = (aspect_ratio or "16:9").strip()
    cost_map = {
        "1:1": 2.0,
        "16:9": 5.0,
        "9:16": 5.0,
        "4:3": 4.0,
        "3:4": 4.0,
        "21:9": 8.0,
    }
    return cost_map.get(ratio, 5.0)


async def _run_modjourney_video_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    cost: float,
) -> None:
    try:
        headers = _modjourney_headers()

        body: dict = {
            "type": "video",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
        }

        # 1) Create generation
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{MODJOURNEY_API_URL}/generations",
                json=body,
                headers=headers,
            )

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            raise RuntimeError(f"Modjourney Video create error {r.status_code}: {data}")

        task_id = data.get("task_id") or data.get("id") or data.get("job_id")
        if not task_id:
            raise RuntimeError(f"No task_id returned: {data}")

        # 2) Poll until done
        poll_url = f"{MODJOURNEY_API_URL}/generations/{task_id}"
        for _ in range(180):  # ~6 min at 2s
            async with httpx.AsyncClient(timeout=30) as c:
                pr = await c.get(poll_url, headers=_modjourney_headers())

            try:
                status_data = pr.json()
            except Exception:
                status_data = {}

            status = (status_data.get("status") or "").lower()
            if status in ("succeeded", "completed", "done"):
                break
            if status in ("failed", "cancelled", "error"):
                raise RuntimeError(f"Modjourney Video generation failed: {status_data}")

            await asyncio.sleep(2)
        else:
            raise RuntimeError("Modjourney Video generation timeout")

        # 3) Download video
        video_url = (
            status_data.get("video_url")
            or status_data.get("output_url")
            or (status_data.get("output") or [None])[0]
            or (status_data.get("result_urls") or [None])[0]
        )
        if not video_url:
            raise RuntimeError(f"No video URL in response: {status_data}")

        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            vr = await c.get(video_url)
            if vr.status_code >= 400:
                raise RuntimeError(f"Video download error {vr.status_code}")
            video_bytes = vr.content

        name = f"modjourney_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "modjourney_video", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "\ud83d\udd3d \u039a\u03b1\u03c4\u03ad\u03b2\u03b1\u03c3\u03b5", "url": public_url}],
                [{"text": "\u2190 \u03a0\u03af\u03c3\u03c9", "callback_data": "menu:video"}],
            ]
        }

        await tg_send_video(
            chat_id=tg_chat_id,
            video_bytes=video_bytes,
            caption="\u2705 Modjourney Video: \u0388\u03c4\u03bf\u03b9\u03bc\u03bf",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Modjourney Video job")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Modjourney Video fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/modjourney-video/generate")
async def modjourney_video_generate(
    request: Request,
    background_tasks: BackgroundTasks,
):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    prompt = (payload.get("prompt") or "").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "16:9").strip()

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    COST = _compute_cost(aspect_ratio)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(
            db_user_id, COST, f"Modjourney Video ({aspect_ratio})", "modjourney", "modjourney-video"
        )
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "\ud83c\udfac Modjourney Video: \u03a4\u03bf \u03b2\u03af\u03bd\u03c4\u03b5\u03bf \u03b5\u03c4\u03bf\u03b9\u03bc\u03ac\u03b6\u03b5\u03c4\u03b1\u03b9\u2026")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_modjourney_video_job,
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
