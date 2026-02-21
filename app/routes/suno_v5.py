# app/routes/suno_v5.py
import os
import uuid
import json
import base64
import logging
import asyncio
from typing import Optional

import httpx
from fastapi import APIRouter, Request, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message
from ..core.paths import VIDEOS_DIR
from ..web_shared import public_base_url
from ..db import spend_credits_by_user_id, add_credits_by_user_id, set_last_result
from ..texts import map_provider_error_to_gr, tool_error_message_gr
from ..config import BOT_TOKEN

logger = logging.getLogger(__name__)
router = APIRouter()

SUNO_API_KEY = os.getenv("SUNO_API_KEY", "").strip()
SUNO_API_URL = os.getenv("SUNO_API_URL", "https://apibox.erweima.ai/api/v1/generate").strip()

COST = 2.4

# Reuse VIDEOS_DIR for audio files (or create AUDIOS_DIR)
AUDIOS_DIR = VIDEOS_DIR.parent / "audios"
AUDIOS_DIR.mkdir(parents=True, exist_ok=True)


def _suno_headers() -> dict:
    if not SUNO_API_KEY:
        raise RuntimeError("SUNO_API_KEY missing (set it in Railway env)")
    return {
        "Authorization": f"Bearer {SUNO_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _tg_send_audio(
    chat_id: int,
    audio_bytes: bytes,
    filename: str = "audio.mp3",
    caption: str = "",
    reply_markup: Optional[dict] = None,
) -> dict:
    """Send audio file to Telegram via sendAudio API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
    data = {"chat_id": str(chat_id), "caption": caption}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    files = {"audio": (filename, audio_bytes, "audio/mpeg")}

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, data=data, files=files)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendAudio failed: {j}")
        return j["result"]


async def _run_suno_v5_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    genre: str,
    style: str,
    duration: int,
    cost: float,
) -> None:
    try:
        headers = _suno_headers()

        body: dict = {
            "prompt": prompt,
            "style": style,
            "title": prompt[:80],
            "customMode": True,
            "instrumental": False,
            "model": "V5",
            "wait": False,
        }
        if genre:
            body["tags"] = genre
        if duration:
            body["duration"] = duration

        # 1) Create generation
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                SUNO_API_URL,
                json=body,
                headers=headers,
            )

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            raise RuntimeError(f"Suno create error {r.status_code}: {data}")

        # Extract task id from response
        task_id = (
            data.get("data", {}).get("taskId")
            or data.get("task_id")
            or data.get("id")
        )
        if not task_id:
            raise RuntimeError(f"No task_id returned: {data}")

        # 2) Poll until done
        poll_base = os.getenv("SUNO_POLL_URL", "https://apibox.erweima.ai/api/v1/generate/record-info").strip()
        for _ in range(180):  # ~6 min at 2s
            async with httpx.AsyncClient(timeout=30) as c:
                pr = await c.get(
                    poll_base,
                    params={"taskId": task_id},
                    headers=_suno_headers(),
                )

            try:
                status_data = pr.json()
            except Exception:
                status_data = {}

            resp_data = status_data.get("data") or status_data
            status = (resp_data.get("status") or "").lower()

            if status in ("succeeded", "completed", "done", "complete"):
                break
            if status in ("failed", "cancelled", "error"):
                raise RuntimeError(f"Suno generation failed: {status_data}")

            await asyncio.sleep(2)
        else:
            raise RuntimeError("Suno generation timeout")

        # 3) Get audio URL
        resp_data = status_data.get("data") or status_data
        items = resp_data.get("data") or resp_data.get("songs") or resp_data.get("tracks") or []
        audio_url = None

        if isinstance(items, list) and items:
            first = items[0]
            audio_url = (
                first.get("audio_url")
                or first.get("sourceUrl")
                or first.get("url")
                or first.get("song_url")
            )
        if not audio_url:
            audio_url = (
                resp_data.get("audio_url")
                or resp_data.get("url")
            )
        if not audio_url:
            raise RuntimeError(f"No audio URL in response: {status_data}")

        # 4) Download audio
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            ar = await c.get(audio_url)
            if ar.status_code >= 400:
                raise RuntimeError(f"Audio download error {ar.status_code}")
            audio_bytes = ar.content

        name = f"suno_v5_{uuid.uuid4().hex}.mp3"
        (AUDIOS_DIR / name).write_bytes(audio_bytes)

        public_url = f"{public_base_url()}/static/audios/{name}"
        set_last_result(db_user_id, "suno_v5", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "\ud83d\udd3d \u039a\u03b1\u03c4\u03ad\u03b2\u03b1\u03c3\u03b5", "url": public_url}],
                [{"text": "\u2190 \u03a0\u03af\u03c3\u03c9", "callback_data": "menu:audio"}],
            ]
        }

        await _tg_send_audio(
            chat_id=tg_chat_id,
            audio_bytes=audio_bytes,
            filename=name,
            caption="\u2705 Suno v5: \u0388\u03c4\u03bf\u03b9\u03bc\u03bf",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Suno v5 job")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Suno v5 fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/sunov5/generate")
async def suno_v5_generate(
    request: Request,
    background_tasks: BackgroundTasks,
):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    prompt = (payload.get("prompt") or "").strip()
    genre = (payload.get("genre") or "").strip()
    style = (payload.get("style") or "").strip()
    duration_raw = payload.get("duration")

    try:
        duration = int(duration_raw) if duration_raw else 30
    except (ValueError, TypeError):
        duration = 30
    duration = max(10, min(240, duration))

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(
            db_user_id, COST, "Suno v5 Music", "suno", "suno-v5"
        )
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "\ud83c\udfb5 Suno v5: \u0397 \u03bc\u03bf\u03c5\u03c3\u03b9\u03ba\u03ae \u03b5\u03c4\u03bf\u03b9\u03bc\u03ac\u03b6\u03b5\u03c4\u03b1\u03b9\u2026")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_suno_v5_job,
        tg_chat_id,
        db_user_id,
        prompt,
        genre,
        style,
        duration,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
