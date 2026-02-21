# app/routes/runway_aleph.py
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

RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "").strip()
RUNWAY_BASE_URL = os.getenv("RUNWAY_BASE_URL", "https://api.runwayml.com/v1").strip()

COST = 22


def _runway_headers() -> dict:
    if not RUNWAY_API_KEY:
        raise RuntimeError("RUNWAY_API_KEY missing (set it in Railway env)")
    return {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _run_runway_aleph_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    video_b64: str,
    cost: float,
) -> None:
    try:
        headers = _runway_headers()

        body: dict = {
            "model": "gen3a_turbo_aleph",
            "prompt": prompt,
            "video": f"data:video/mp4;base64,{video_b64}",
        }

        # 1) Create generation
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{RUNWAY_BASE_URL}/generations", json=body, headers=headers)

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            raise RuntimeError(f"Runway Aleph create error {r.status_code}: {data}")

        gen_id = data.get("id")
        if not gen_id:
            raise RuntimeError(f"No generation id returned: {data}")

        # 2) Poll until done
        poll_url = f"{RUNWAY_BASE_URL}/generations/{gen_id}"
        for _ in range(240):  # ~8 min at 2s
            async with httpx.AsyncClient(timeout=30) as c:
                pr = await c.get(poll_url, headers=_runway_headers())

            try:
                status_data = pr.json()
            except Exception:
                status_data = {}

            status = status_data.get("status", "")
            if status == "succeeded":
                break
            if status in ("failed", "cancelled"):
                raise RuntimeError(f"Runway Aleph generation failed: {status_data}")

            await asyncio.sleep(2)
        else:
            raise RuntimeError("Runway Aleph generation timeout")

        # 3) Download video
        video_url = status_data.get("output", [None])[0]
        if not video_url:
            video_url = status_data.get("video_url") or status_data.get("url")
        if not video_url:
            raise RuntimeError(f"No video URL in response: {status_data}")

        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            vr = await c.get(video_url)
            if vr.status_code >= 400:
                raise RuntimeError(f"Video download error {vr.status_code}")
            video_bytes = vr.content

        name = f"runway_aleph_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "runway_aleph", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "\ud83d\udd3d \u039a\u03b1\u03c4\u03ad\u03b2\u03b1\u03c3\u03b5", "url": public_url}],
                [{"text": "\u2190 \u03a0\u03af\u03c3\u03c9", "callback_data": "menu:video"}],
            ]
        }

        await tg_send_video(
            chat_id=tg_chat_id,
            video_bytes=video_bytes,
            caption="\u2705 Runway Aleph: \u0388\u03c4\u03bf\u03b9\u03bc\u03bf",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Runway Aleph job")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Runway Aleph fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/runway-aleph/generate")
async def runway_aleph_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    prompt: str = Form(""),
    video: Optional[UploadFile] = File(None),
):
    prompt = (prompt or "").strip()
    init_data = (tg_init_data or "").strip()

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    if not video:
        return JSONResponse({"ok": False, "error": "missing_video"}, status_code=400)

    video_raw = await video.read()
    if not video_raw:
        return JSONResponse({"ok": False, "error": "empty_video"}, status_code=400)

    video_b64 = base64.b64encode(video_raw).decode("utf-8")

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(db_user_id, COST, "Runway Aleph", "runway", "gen3a_turbo_aleph")
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "\ud83c\udfac Runway Aleph: \u03a4\u03bf \u03b2\u03af\u03bd\u03c4\u03b5\u03bf \u03b5\u03c4\u03bf\u03b9\u03bc\u03ac\u03b6\u03b5\u03c4\u03b1\u03b9\u2026")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_runway_aleph_job,
        tg_chat_id,
        db_user_id,
        prompt,
        video_b64,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
