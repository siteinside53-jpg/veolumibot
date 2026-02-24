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
from ..core.telegram_client import tg_send_message, tg_send_document
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

# In-memory store for callback results keyed by taskId
_callback_results: dict[str, dict] = {}


def _suno_headers() -> dict:
    if not SUNO_API_KEY:
        raise RuntimeError("SUNO_API_KEY missing (set it in Railway env)")
    return {
        "Authorization": f"Bearer {SUNO_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _vocal_gender(voice: str) -> str:
    """Map voice choice to Suno vocalGender param: 'm' or 'f'."""
    return "f" if voice == "female" else "m"


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
    mode: str,
    voice: str,
    description: str,
    title: str,
    style: str,
    lyrics: str,
    cost: float,
) -> None:
    try:
        headers = _suno_headers()
        gender = _vocal_gender(voice)

        if mode == "auto":
            # Automatic generation — customMode false
            # prompt = core concept, max 500 chars; no style/title
            body: dict = {
                "prompt": description[:500],
                "customMode": False,
                "instrumental": False,
                "model": "V5",
                "vocalGender": gender,
            }
        else:
            # Custom / personal generation — customMode true
            # prompt = lyrics (max 5000), style (max 1000), title (max 100)
            body = {
                "prompt": lyrics[:5000],
                "style": style[:1000],
                "title": title[:100],
                "customMode": True,
                "instrumental": False,
                "model": "V5",
                "vocalGender": gender,
            }

        # callBackUrl is required by apibox — we still poll, but must provide it
        body["callBackUrl"] = f"{public_base_url()}/api/sunov5/callback"

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

        logger.info("Suno create response [%s]: %s", r.status_code, json.dumps(data, ensure_ascii=False)[:1500])

        if r.status_code >= 400:
            raise RuntimeError(f"Suno create error {r.status_code}: {data}")

        # Extract task id from response
        # NOTE: data["data"] can be None (JSON null), so use `or {}` instead of default
        inner = data.get("data") or {}
        task_id = (
            inner.get("taskId")
            or inner.get("task_id")
            or data.get("task_id")
            or data.get("id")
        )
        if not task_id:
            raise RuntimeError(f"No task_id returned: {data}")

        # 2) Wait for result — check callback store first, then poll API
        poll_base = os.getenv("SUNO_POLL_URL", "https://apibox.erweima.ai/api/v1/generate/record-info").strip()
        status_data = {}
        found_via_callback = False

        for attempt in range(180):  # ~6 min at 2s
            # --- Check if callback already delivered the result ---
            if task_id in _callback_results:
                status_data = _callback_results.pop(task_id)
                logger.info("Got result from callback for task %s", task_id)
                found_via_callback = True
                break

            # --- Otherwise poll the API ---
            try:
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
                    logger.info("Got result from polling for task %s (status=%s)", task_id, status)
                    break
                if status in ("failed", "cancelled", "error"):
                    raise RuntimeError(f"Suno generation failed: {status_data}")
            except RuntimeError:
                raise
            except Exception as poll_err:
                logger.warning("Poll attempt %d failed: %s", attempt, poll_err)

            await asyncio.sleep(2)
        else:
            # Last chance — check callback one more time
            if task_id in _callback_results:
                status_data = _callback_results.pop(task_id)
                found_via_callback = True
                logger.info("Got result from callback (post-timeout) for task %s", task_id)
            else:
                raise RuntimeError("Suno generation timeout")

        # 3) Extract ALL audio items from response
        resp_data = status_data.get("data") or status_data
        items = resp_data.get("data") or resp_data.get("songs") or resp_data.get("tracks") or []
        if not isinstance(items, list):
            items = []

        def _extract_url(item: dict) -> str | None:
            """Get best audio URL from an item, skipping empty strings."""
            for key in ("audio_url", "stream_audio_url", "source_stream_audio_url", "sourceUrl", "url", "song_url"):
                val = item.get(key)
                if val:  # skip None and ''
                    return val
            return None

        # Collect all downloadable URLs
        audio_entries: list[dict] = []
        for item in items:
            url = _extract_url(item)
            if url:
                audio_entries.append({
                    "url": url,
                    "title": item.get("title") or "audio",
                })

        # Fallback: try top-level fields
        if not audio_entries:
            fallback_url = (
                resp_data.get("audio_url")
                or resp_data.get("stream_audio_url")
                or resp_data.get("url")
            )
            if fallback_url:
                audio_entries.append({"url": fallback_url, "title": "audio"})

        if not audio_entries:
            raise RuntimeError(f"No audio URL in response: {status_data}")

        # 4) Download and send ALL tracks to Telegram
        sent_count = 0
        for idx, entry in enumerate(audio_entries, 1):
            try:
                async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
                    ar = await c.get(entry["url"])
                    if ar.status_code >= 400:
                        logger.warning("Audio download error %d for track %d", ar.status_code, idx)
                        continue
                    audio_bytes = ar.content

                name = f"suno_v5_{uuid.uuid4().hex}.mp3"
                (AUDIOS_DIR / name).write_bytes(audio_bytes)

                public_url = f"{public_base_url()}/static/audios/{name}"
                set_last_result(db_user_id, "suno_v5", public_url)

                # Send as plain document (octet-stream forces Download view, not audio player)
                await tg_send_document(
                    chat_id=tg_chat_id,
                    file_bytes=audio_bytes,
                    filename="audio.mp3",
                    mime_type="application/octet-stream",
                )
                sent_count += 1
            except Exception as track_err:
                logger.warning("Failed to send track %d: %s", idx, track_err)

        if sent_count == 0:
            raise RuntimeError("All audio downloads/sends failed")

        # Final success message with resend + back button
        kb = {
            "inline_keyboard": [
                [{"text": "⚡ Πάρε αποτέλεσμα ξανά (δωρεάν)", "callback_data": "resend:suno_v5"}],
                [{"text": "← Πίσω", "callback_data": "menu:audio"}],
            ]
        }
        msg_text = f"✅ Suno V5: {sent_count} {'τραγούδια έτοιμα' if sent_count > 1 else 'τραγούδι έτοιμο'}!"
        async with httpx.AsyncClient(timeout=30) as c:
            await c.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": tg_chat_id, "text": msg_text,
                      "reply_markup": kb},
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
    mode = (payload.get("mode") or "auto").strip().lower()
    voice = (payload.get("voice") or "male").strip().lower()

    if mode not in ("auto", "custom"):
        mode = "auto"
    if voice not in ("male", "female"):
        voice = "male"

    # Extract fields based on mode
    description = ""
    title = ""
    style = ""
    lyrics = ""

    if mode == "auto":
        description = (payload.get("description") or "").strip()
        if not description:
            return JSONResponse({"ok": False, "error": "empty_description"}, status_code=400)
        if len(description) > 500:
            return JSONResponse({"ok": False, "error": "description_too_long"}, status_code=400)
    else:
        title = (payload.get("title") or "").strip()
        style = (payload.get("style") or "").strip()
        lyrics = (payload.get("lyrics") or "").strip()
        if not title:
            return JSONResponse({"ok": False, "error": "empty_title"}, status_code=400)
        if len(title) > 100:
            return JSONResponse({"ok": False, "error": "title_too_long"}, status_code=400)
        if not style:
            return JSONResponse({"ok": False, "error": "empty_style"}, status_code=400)
        if len(style) > 1000:
            return JSONResponse({"ok": False, "error": "style_too_long"}, status_code=400)
        if not lyrics:
            return JSONResponse({"ok": False, "error": "empty_lyrics"}, status_code=400)
        if len(lyrics) > 5000:
            return JSONResponse({"ok": False, "error": "lyrics_too_long"}, status_code=400)

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
        await tg_send_message(tg_chat_id, "🎵 Suno v5: Η μουσική ετοιμάζεται…")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_suno_v5_job,
        tg_chat_id,
        db_user_id,
        mode,
        voice,
        description,
        title,
        style,
        lyrics,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}


@router.post("/api/sunov5/callback")
async def suno_v5_callback(request: Request):
    """Callback endpoint for apibox Suno webhooks.
    Stores the result so the background polling loop picks it up.
    Skips 'text' callbacks (lyrics only, no audio yet)."""
    try:
        payload = await request.json()
        logger.info("Suno callback received: %s", json.dumps(payload, ensure_ascii=False)[:2000])

        inner = payload.get("data") or payload
        callback_type = (inner.get("callbackType") or "").lower()
        task_id = (
            inner.get("taskId")
            or inner.get("task_id")
            or payload.get("taskId")
            or payload.get("task_id")
        )

        if not task_id:
            logger.warning("Suno callback: no taskId found in payload")
            return {"ok": True}

        # Skip 'text' callbacks — they contain lyrics but no audio yet
        if callback_type == "text":
            logger.info("Skipping 'text' callback for task %s (audio not ready)", task_id)
            return {"ok": True}

        # Store the callback with actual audio data
        _callback_results[task_id] = payload
        logger.info("Stored callback result for task %s (type=%s)", task_id, callback_type)
    except Exception:
        logger.warning("Suno callback: could not parse body")
    return {"ok": True}
