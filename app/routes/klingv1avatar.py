# app/routes/klingv1avatar.py
"""Kling V1 Avatar – face image to talking-head video"""
import os, uuid, base64, logging
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_document
from ..core.paths import VIDEOS_DIR
from ..web_shared import public_base_url
from ..db import spend_credits_by_user_id, add_credits_by_user_id, set_last_result
from ..texts import map_provider_error_to_gr, tool_error_message_gr
from ._kling_shared import create_kling_video_task, poll_kling_video_task, kling_headers

logger = logging.getLogger(__name__)
router = APIRouter()

MODEL = "kling-v1-avatar"
ENDPOINT = "/v1/videos/avatar"


def _calc_cost(duration: int) -> float:
    """5s = 16, 10s = 32"""
    return 32.0 if duration >= 10 else 16.0


def _guess_mime(filename: str) -> str:
    f = (filename or "").lower()
    if f.endswith(".jpg") or f.endswith(".jpeg"):
        return "image/jpeg"
    if f.endswith(".webp"):
        return "image/webp"
    return "image/png"


# -------------------------
# BACKGROUND JOB
# -------------------------
async def _run_klingv1avatar_job(
    tg_chat_id: int,
    db_user_id: int,
    payload: dict,
    cost: float,
):
    try:
        task_id = await create_kling_video_task(payload, ENDPOINT)
        video_url = await poll_kling_video_task(task_id, ENDPOINT)

        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            vd = await c.get(video_url)
            if vd.status_code >= 400:
                raise RuntimeError(f"Video download error {vd.status_code}")
            video_bytes = vd.content

        name = f"klingv1avatar_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "klingv1avatar", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "⚡ Πάρε αποτέλεσμα ξανά (δωρεάν)", "callback_data": "resend:klingv1avatar"}],

                [{"text": "← Πίσω", "callback_data": "menu:video"}],
            ]
        }

        await tg_send_document(
            chat_id=tg_chat_id,
            file_bytes=video_bytes,
            filename="video.mp4",
            mime_type="video/mp4",
            caption="✅ Kling V1 Avatar: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Kling V1 Avatar fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


# -------------------------
# API ENDPOINT (multipart/form-data for face image upload)
# -------------------------
@router.post("/api/klingv1avatar/generate")
async def klingv1avatar_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    prompt: str = Form(""),
    aspect_ratio: str = Form("16:9"),
    duration: int = Form(5),
    mode: str = Form("std"),
    face_image: Optional[UploadFile] = File(None),
):
    prompt = (prompt or "").strip()
    aspect_ratio = (aspect_ratio or "16:9").strip()
    mode = (mode or "std").strip()
    init_data = (tg_init_data or "").strip()

    if not face_image:
        return JSONResponse({"ok": False, "error": "missing_face_image"}, status_code=400)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    COST = _calc_cost(duration)

    try:
        _ = kling_headers()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=400)

    try:
        spend_credits_by_user_id(db_user_id, COST, f"Kling V1 Avatar ({duration}s)", "kling", MODEL)
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    face_bytes = await face_image.read()
    if not face_bytes:
        try:
            add_credits_by_user_id(db_user_id, COST, "Refund Kling Avatar empty image", "system", None)
        except Exception:
            logger.exception("Refund failed")
        return JSONResponse({"ok": False, "error": "empty_face_image"}, status_code=400)

    mime = _guess_mime(face_image.filename or "face.png")
    b64 = base64.b64encode(face_bytes).decode("utf-8")
    face_data_url = f"data:{mime};base64,{b64}"

    payload = {
        "model_name": MODEL,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "mode": mode,
        "face_image": face_data_url,
    }

    try:
        await tg_send_message(tg_chat_id, "🎬 Kling V1 Avatar: Δημιουργία video…")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_klingv1avatar_job,
        tg_chat_id,
        db_user_id,
        payload,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
