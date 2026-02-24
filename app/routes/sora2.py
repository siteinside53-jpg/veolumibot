# app/routes/sora2.py
import os
import uuid
import base64
import logging
import asyncio
import random
from typing import Optional, Dict, Any

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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}

COST = 6


def _size_from_aspect(aspect: str) -> str:
    a = (aspect or "").lower().strip()
    return "720x1280" if a in ("portrait", "9:16", "vertical") else "1280x720"


def _seconds_from_ui(seconds: str) -> str:
    s = str(seconds or "").strip()
    return s if s in ("4", "8") else "8"


async def _request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    json_body: Dict[str, Any] | None = None,
    data: Dict[str, Any] | None = None,
    files: Any = None,
    max_attempts: int = 8,
    base_sleep: float = 1.5,
) -> httpx.Response:
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            r = await client.request(
                method, url, headers=headers, json=json_body, data=data, files=files,
            )
            if r.status_code in _TRANSIENT_STATUSES:
                sleep_s = min(20.0, base_sleep * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
                await asyncio.sleep(sleep_s)
                continue
            return r
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            sleep_s = min(20.0, base_sleep * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
            await asyncio.sleep(sleep_s)

    raise RuntimeError(f"Network/transient failure after retries: {last_exc or 'Unknown error'}")


async def _run_sora2_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    size: str,
    seconds: str,
    cost: float,
) -> None:
    video_id: Optional[str] = None

    try:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY missing (set it in Railway env)")

        await tg_send_message(tg_chat_id, "\ud83c\udfac Sora 2: \u039e\u03b5\u03ba\u03af\u03bd\u03b7\u03c3\u03b5 \u03b7 \u03c0\u03b1\u03c1\u03b1\u03b3\u03c9\u03b3\u03ae\u2026")

        url = "https://api.openai.com/v1/videos"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

        body = {
            "model": "sora-2",
            "prompt": prompt,
            "size": size,
            "seconds": seconds,
        }

        async with httpx.AsyncClient(timeout=60) as c:
            r = await _request_with_retries(c, "POST", url, headers=headers, json_body=body)

        try:
            data = r.json() if r.content else {}
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            raise RuntimeError(f"Sora2 create error {r.status_code}: {data}")

        video_id = data.get("id")
        if not video_id:
            raise RuntimeError(f"No video id returned: {data}")

        # Poll status
        for _ in range(240):  # ~8 min at 2s
            async with httpx.AsyncClient(timeout=30) as c:
                vr = await _request_with_retries(
                    c, "GET", f"https://api.openai.com/v1/videos/{video_id}", headers=headers
                )

            try:
                v = vr.json()
            except Exception:
                await asyncio.sleep(2)
                continue

            status = v.get("status")
            if status == "completed":
                break
            if status == "failed":
                raise RuntimeError(f"Sora2 failed: {v}")

            await asyncio.sleep(2)

        # Download video
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            dr = await _request_with_retries(
                c, "GET", f"https://api.openai.com/v1/videos/{video_id}/content", headers=headers
            )

        if dr.status_code >= 400:
            raise RuntimeError(f"Sora2 download error {dr.status_code}: {(dr.text or '')[:300]}")

        video_bytes = dr.content

        name = f"sora2_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "sora2", public_url)

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
            caption="\u2705 Sora 2: \u0388\u03c4\u03bf\u03b9\u03bc\u03bf",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Sora2 job")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Sora2 fail", "system", video_id)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/sora2/generate")
async def sora2_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    prompt: str = Form(""),
    aspect: str = Form("portrait"),
    seconds: str = Form("8"),
):
    prompt = (prompt or "").strip()
    init_data = (tg_init_data or "").strip()
    size = _size_from_aspect(aspect)
    secs = _seconds_from_ui(seconds)

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(db_user_id, COST, f"Sora 2 ({secs}s)", "openai", "sora-2")
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "\ud83c\udfac Sora 2: \u03a4\u03bf \u03b2\u03af\u03bd\u03c4\u03b5\u03bf \u03b5\u03c4\u03bf\u03b9\u03bc\u03ac\u03b6\u03b5\u03c4\u03b1\u03b9\u2026")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_sora2_job,
        tg_chat_id,
        db_user_id,
        prompt,
        size,
        secs,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
