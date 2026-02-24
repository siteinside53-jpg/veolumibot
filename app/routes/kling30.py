# app/routes/kling30.py
"""Kling V3-0 – text-to-video with segments control & audio generation"""
import os, uuid, json, logging

import httpx
from fastapi import APIRouter, Request, BackgroundTasks
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

MODEL = "kling-v3-0"
ENDPOINT = "/v1/videos/text2video"
BASE_COST = 18.0


# -------------------------
# BACKGROUND JOB
# -------------------------
async def _run_kling30_job(
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

        name = f"kling30_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "kling30", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "🔽 Κατέβασε", "url": public_url}],
                [{"text": "← Πίσω", "callback_data": "menu:video"}],
            ]
        }

        await tg_send_document(
            chat_id=tg_chat_id,
            file_bytes=video_bytes,
            filename="video.mp4",
            mime_type="video/mp4",
            caption="✅ Kling 3.0: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Kling 3.0 fail", "system", None)
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
# API ENDPOINT
# -------------------------
@router.post("/api/kling30/generate")
async def kling30_generate(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    prompt = (data.get("prompt") or "").strip()
    aspect_ratio = (data.get("aspect_ratio") or "16:9").strip()
    duration = int(data.get("duration") or 5)
    generate_audio = bool(data.get("generate_audio", False))
    segments_json = (data.get("segments_json") or "").strip()

    if duration < 3:
        duration = 3
    if duration > 15:
        duration = 15

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    try:
        dbu = db_user_from_webapp(data.get("initData", ""))
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    COST = BASE_COST

    try:
        _ = kling_headers()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=400)

    try:
        spend_credits_by_user_id(db_user_id, COST, f"Kling 3.0 ({duration}s)", "kling", MODEL)
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    payload = {
        "model_name": MODEL,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
    }

    if generate_audio:
        payload["generate_audio"] = True

    # Parse segments JSON if provided
    if segments_json:
        try:
            segments = json.loads(segments_json)
            if isinstance(segments, list) and len(segments) > 0:
                payload["segments"] = segments
        except json.JSONDecodeError:
            logger.warning("Invalid segments_json, ignoring")

    try:
        await tg_send_message(tg_chat_id, "🎬 Kling 3.0: Δημιουργία video…")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_kling30_job,
        tg_chat_id,
        db_user_id,
        payload,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
