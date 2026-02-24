# app/routes/hailuo02.py
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

HAILUO_API_KEY = os.getenv("HAILUO_API_KEY", "").strip()
HAILUO_BASE_URL = os.getenv("HAILUO_BASE_URL", "https://api.minimaxi.chat/v1").strip()


def _hailuo_headers() -> dict:
    if not HAILUO_API_KEY:
        raise RuntimeError("HAILUO_API_KEY missing (set it in Railway env)")
    return {
        "Authorization": f"Bearer {HAILUO_API_KEY}",
        "Content-Type": "application/json",
    }


def _compute_cost(has_start_image: bool, has_end_image: bool) -> float:
    """Base 6, +3 per reference image."""
    base = 6.0
    if has_start_image:
        base += 3
    if has_end_image:
        base += 3
    return base


async def _run_hailuo_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    start_image_b64: Optional[str],
    end_image_b64: Optional[str],
    optimize_prompt: bool,
    cost: float,
) -> None:
    try:
        headers = _hailuo_headers()

        body: dict = {
            "model": "T2V-01",
            "prompt": prompt,
            "optimize_prompt": optimize_prompt,
        }
        if start_image_b64:
            body["first_frame_image"] = f"data:image/png;base64,{start_image_b64}"
        if end_image_b64:
            body["last_frame_image"] = f"data:image/png;base64,{end_image_b64}"

        # 1) Create task
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{HAILUO_BASE_URL}/video_generation",
                json=body,
                headers=headers,
            )

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            raise RuntimeError(f"Hailuo create error {r.status_code}: {data}")

        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise RuntimeError(f"No task_id returned: {data}")

        # 2) Poll until done
        poll_url = f"{HAILUO_BASE_URL}/video_generation/{task_id}"
        for _ in range(240):  # ~8 min at 2s
            async with httpx.AsyncClient(timeout=30) as c:
                pr = await c.get(poll_url, headers=_hailuo_headers())

            try:
                status_data = pr.json()
            except Exception:
                status_data = {}

            status = (status_data.get("status") or "").lower()
            if status in ("succeeded", "completed", "success", "done"):
                break
            if status in ("failed", "cancelled", "error"):
                raise RuntimeError(f"Hailuo generation failed: {status_data}")

            await asyncio.sleep(2)
        else:
            raise RuntimeError("Hailuo generation timeout")

        # 3) Download video
        video_url = (
            status_data.get("file_id")
            or status_data.get("video_url")
            or status_data.get("output_url")
            or (status_data.get("output") or [None])[0]
        )
        if not video_url:
            raise RuntimeError(f"No video URL in response: {status_data}")

        # If file_id returned, build download URL
        if not video_url.startswith("http"):
            video_url = f"{HAILUO_BASE_URL}/files/retrieve?file_id={video_url}"

        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            dl_headers = _hailuo_headers()
            vr = await c.get(video_url, headers=dl_headers)
            if vr.status_code >= 400:
                raise RuntimeError(f"Video download error {vr.status_code}")
            video_bytes = vr.content

        name = f"hailuo_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "hailuo02", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "\ud83d\udd3d \u039a\u03b1\u03c4\u03ad\u03b2\u03b1\u03c3\u03b5", "url": public_url}],
                [{"text": "\u2190 \u03a0\u03af\u03c3\u03c9", "callback_data": "menu:video"}],
            ]
        }

        await tg_send_document(
            chat_id=tg_chat_id,
            file_bytes=video_bytes,
            filename="video.mp4",
            mime_type="video/mp4",
            caption="\u2705 Hailuo AI: \u0388\u03c4\u03bf\u03b9\u03bc\u03bf",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Hailuo job")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Hailuo fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/hailuo02/generate")
async def hailuo02_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    prompt: str = Form(""),
    start_image: Optional[UploadFile] = File(None),
    end_image: Optional[UploadFile] = File(None),
    optimize_prompt: str = Form("true"),
):
    prompt = (prompt or "").strip()
    init_data = (tg_init_data or "").strip()
    opt_prompt = (optimize_prompt or "").strip().lower() in ("true", "1", "yes")

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    start_b64 = None
    if start_image:
        raw = await start_image.read()
        if raw:
            start_b64 = base64.b64encode(raw).decode("utf-8")

    end_b64 = None
    if end_image:
        raw = await end_image.read()
        if raw:
            end_b64 = base64.b64encode(raw).decode("utf-8")

    COST = _compute_cost(start_b64 is not None, end_b64 is not None)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(db_user_id, COST, "Hailuo AI Video", "hailuo", "T2V-01")
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "\ud83c\udfac Hailuo AI: \u03a4\u03bf \u03b2\u03af\u03bd\u03c4\u03b5\u03bf \u03b5\u03c4\u03bf\u03b9\u03bc\u03ac\u03b6\u03b5\u03c4\u03b1\u03b9\u2026")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_hailuo_job,
        tg_chat_id,
        db_user_id,
        prompt,
        start_b64,
        end_b64,
        opt_prompt,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
