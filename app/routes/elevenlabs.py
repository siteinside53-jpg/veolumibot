# app/routes/elevenlabs.py
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
from ..core.telegram_client import tg_send_message, tg_send_document
from ..core.paths import VIDEOS_DIR
from ..web_shared import public_base_url
from ..db import spend_credits_by_user_id, add_credits_by_user_id, set_last_result
from ..texts import map_provider_error_to_gr, tool_error_message_gr
from ..config import BOT_TOKEN

logger = logging.getLogger(__name__)
router = APIRouter()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_BASE_URL = os.getenv(
    "ELEVENLABS_BASE_URL", "https://api.elevenlabs.io/v1"
).strip()

# Reuse or create audios dir
AUDIOS_DIR = VIDEOS_DIR.parent / "audios"
AUDIOS_DIR.mkdir(parents=True, exist_ok=True)


def _elevenlabs_headers() -> dict:
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY missing (set it in Railway env)")
    return {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }


def _compute_cost(text: str) -> float:
    """Cost based on character count: ~0.3 per 500 chars, min 0.5."""
    chars = len(text)
    cost = max(0.5, round(chars / 500 * 0.3, 2))
    return cost


def _output_format_to_mime(fmt: str) -> tuple[str, str]:
    """Return (file extension, mime type) for the given format."""
    fmt = (fmt or "mp3").lower().strip()
    if fmt == "wav":
        return "wav", "audio/wav"
    if fmt == "ogg":
        return "ogg", "audio/ogg"
    return "mp3", "audio/mpeg"


async def _tg_send_audio(
    chat_id: int,
    audio_bytes: bytes,
    filename: str = "audio.mp3",
    mime: str = "audio/mpeg",
    caption: str = "",
    reply_markup: Optional[dict] = None,
) -> dict:
    """Send audio file to Telegram via sendAudio API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
    data = {"chat_id": str(chat_id), "caption": caption}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    files = {"audio": (filename, audio_bytes, mime)}

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, data=data, files=files)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendAudio failed: {j}")
        return j["result"]


async def _tg_send_voice(
    chat_id: int,
    audio_bytes: bytes,
    caption: str = "",
    reply_markup: Optional[dict] = None,
) -> dict:
    """Send voice message to Telegram via sendVoice API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice"
    data = {"chat_id": str(chat_id), "caption": caption}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    files = {"voice": ("voice.ogg", audio_bytes, "audio/ogg")}

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, data=data, files=files)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendVoice failed: {j}")
        return j["result"]


async def _run_elevenlabs_job(
    tg_chat_id: int,
    db_user_id: int,
    text: str,
    voice_id: str,
    output_format: str,
    cost: float,
) -> None:
    try:
        if not ELEVENLABS_API_KEY:
            raise RuntimeError("ELEVENLABS_API_KEY missing (set it in Railway env)")

        ext, mime = _output_format_to_mime(output_format)

        # ElevenLabs TTS API
        tts_url = f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_id}"

        body = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": f"audio/{ext}" if ext != "mp3" else "audio/mpeg",
        }

        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(tts_url, json=body, headers=headers)

        if r.status_code >= 400:
            try:
                err_data = r.json()
            except Exception:
                err_data = {"raw": (r.text or "")[:2000]}
            raise RuntimeError(f"ElevenLabs TTS error {r.status_code}: {err_data}")

        audio_bytes = r.content
        if not audio_bytes:
            raise RuntimeError("ElevenLabs returned empty audio")

        name = f"elevenlabs_{uuid.uuid4().hex}.{ext}"
        (AUDIOS_DIR / name).write_bytes(audio_bytes)

        public_url = f"{public_base_url()}/static/audios/{name}"
        set_last_result(db_user_id, "elevenlabs", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "\u2190 \u03a0\u03af\u03c3\u03c9", "callback_data": "menu:audio"}],
            ]
        }

        await tg_send_document(
            chat_id=tg_chat_id,
            file_bytes=audio_bytes,
            filename="audio.mp3",
            caption="✅ ElevenLabs TTS: Έτοιμο",
            mime_type="audio/mpeg",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during ElevenLabs job")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund ElevenLabs fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/elevenlabs/generate")
async def elevenlabs_generate(
    request: Request,
    background_tasks: BackgroundTasks,
):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    text = (payload.get("text") or "").strip()
    voice_id = (payload.get("voice_id") or "21m00Tcm4TlvDq8ikWAM").strip()  # Rachel default
    output_format = (payload.get("format") or "mp3").strip().lower()

    if output_format not in ("mp3", "wav", "ogg"):
        output_format = "mp3"

    if not text:
        return JSONResponse({"ok": False, "error": "empty_text"}, status_code=400)

    if len(text) > 5000:
        return JSONResponse({"ok": False, "error": "text_too_long"}, status_code=400)

    COST = _compute_cost(text)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(
            db_user_id, COST, f"ElevenLabs TTS ({len(text)} chars)", "elevenlabs", "eleven_multilingual_v2"
        )
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "\ud83c\udfa4 ElevenLabs: \u03a4\u03bf audio \u03b5\u03c4\u03bf\u03b9\u03bc\u03ac\u03b6\u03b5\u03c4\u03b1\u03b9\u2026")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_elevenlabs_job,
        tg_chat_id,
        db_user_id,
        text,
        voice_id,
        output_format,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
