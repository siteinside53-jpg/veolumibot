# app/routes/topaz_upscale.py
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
from ..core.telegram_client import tg_send_message, tg_send_document
from ..core.paths import VIDEOS_DIR
from ..web_shared import public_base_url
from ..db import spend_credits_by_user_id, add_credits_by_user_id, set_last_result
from ..texts import map_provider_error_to_gr, tool_error_message_gr

logger = logging.getLogger(__name__)
router = APIRouter()

TOPAZ_API_KEY = os.getenv("TOPAZ_API_KEY", "").strip()
TOPAZ_API_URL = os.getenv("TOPAZ_API_URL", "https://api.topazlabs.com/v1").strip()

COST = 14


def _topaz_headers() -> dict:
    if not TOPAZ_API_KEY:
        raise RuntimeError("TOPAZ_API_KEY missing (set it in Railway env)")
    return {
        "Authorization": f"Bearer {TOPAZ_API_KEY}",
        "Accept": "application/json",
    }


async def _run_topaz_upscale_job(
    tg_chat_id: int,
    db_user_id: int,
    video_raw: bytes,
    video_filename: str,
    quality: str,
    cost: float,
) -> None:
    try:
        headers = _topaz_headers()
        # Remove Content-Type for multipart
        headers.pop("Content-Type", None)

        # 1) Upload video + start upscale
        files = {
            "video": (video_filename, video_raw, "video/mp4"),
        }
        form_data = {
            "quality": quality,
            "scale": "2",  # 2x upscale default
            "model": "auto",
        }

        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{TOPAZ_API_URL}/enhance",
                headers=headers,
                data=form_data,
                files=files,
            )

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            raise RuntimeError(f"Topaz create error {r.status_code}: {data}")

        task_id = data.get("task_id") or data.get("id") or data.get("job_id")
        if not task_id:
            raise RuntimeError(f"No task_id returned: {data}")

        # 2) Poll until done
        poll_url = f"{TOPAZ_API_URL}/enhance/{task_id}"
        for _ in range(360):  # ~12 min at 2s (upscaling can be slow)
            async with httpx.AsyncClient(timeout=30) as c:
                pr = await c.get(poll_url, headers=_topaz_headers())

            try:
                status_data = pr.json()
            except Exception:
                status_data = {}

            status = (status_data.get("status") or "").lower()
            if status in ("succeeded", "completed", "done", "ready"):
                break
            if status in ("failed", "cancelled", "error"):
                raise RuntimeError(f"Topaz upscale failed: {status_data}")

            await asyncio.sleep(2)
        else:
            raise RuntimeError("Topaz upscale timeout")

        # 3) Download upscaled video
        download_url = (
            status_data.get("download_url")
            or status_data.get("output_url")
            or status_data.get("video_url")
            or (status_data.get("output") or [None])[0]
        )
        if not download_url:
            raise RuntimeError(f"No download URL in response: {status_data}")

        async with httpx.AsyncClient(timeout=600, follow_redirects=True) as c:
            vr = await c.get(download_url, headers=_topaz_headers())
            if vr.status_code >= 400:
                raise RuntimeError(f"Video download error {vr.status_code}")
            video_bytes = vr.content

        name = f"topaz_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "topaz_upscale", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "\u2190 \u03a0\u03af\u03c3\u03c9", "callback_data": "menu:video"}],
            ]
        }

        await tg_send_document(
            chat_id=tg_chat_id,
            file_bytes=video_bytes,
            filename="video.mp4",
            mime_type="video/mp4",
            caption="\u2705 Topaz Upscale: \u0388\u03c4\u03bf\u03b9\u03bc\u03bf",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Topaz Upscale job")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Topaz Upscale fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/topaz-upscale/generate")
async def topaz_upscale_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    quality: str = Form("high"),
    video: Optional[UploadFile] = File(None),
):
    init_data = (tg_init_data or "").strip()
    quality = (quality or "high").strip().lower()
    if quality not in ("low", "medium", "high"):
        quality = "high"

    if not video:
        return JSONResponse({"ok": False, "error": "missing_video"}, status_code=400)

    video_raw = await video.read()
    if not video_raw:
        return JSONResponse({"ok": False, "error": "empty_video"}, status_code=400)

    video_filename = video.filename or "input.mp4"

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(
            db_user_id, COST, f"Topaz Upscale ({quality})", "topaz", "topaz-video-ai"
        )
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "\ud83d\udcf9 Topaz Upscale: \u03a4\u03bf \u03b2\u03af\u03bd\u03c4\u03b5\u03bf \u03b1\u03bd\u03b1\u03b2\u03b1\u03b8\u03bc\u03af\u03b6\u03b5\u03c4\u03b1\u03b9\u2026")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_topaz_upscale_job,
        tg_chat_id,
        db_user_id,
        video_raw,
        video_filename,
        quality,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
