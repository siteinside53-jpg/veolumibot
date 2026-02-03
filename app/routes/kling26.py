import os
import base64
import uuid
import time
import logging
from pathlib import Path
from typing import Optional, Literal

import httpx
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message  # βάλε και tg_send_video αν το έχεις
from ..core.paths import STATIC_DIR
from ..web_shared import public_base_url
from ..db import (
    spend_credits_by_user_id,
    add_credits_by_user_id,
    set_last_result,
)

logger = logging.getLogger(__name__)
router = APIRouter()

KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY", "").strip()
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY", "").strip()
KLING_API_BASE = (os.getenv("KLING_API_BASE") or "").strip() or "https://api.klingai.com"

VIDEOS_DIR = Path(STATIC_DIR) / "videos"


Mode = Literal["text_to_video", "image_to_video"]


def _cost_credits(duration_sec: int, generate_audio: bool) -> float:
    """
    UI logic όπως στο screenshot:
    5s no-audio: 11
    5s audio: 22
    10s no-audio: 22
    10s audio: 44
    """
    base = 11
    if int(duration_sec) == 10:
        base *= 2
    if generate_audio:
        base *= 2
    return float(base)


def _require_kling_keys():
    if not KLING_ACCESS_KEY or not KLING_SECRET_KEY:
        raise RuntimeError("Missing KLING_ACCESS_KEY / KLING_SECRET_KEY in env")


def _parse_image_data_url(image_data_url: str) -> bytes:
    """
    Expect: data:image/png;base64,....
    """
    if not image_data_url.startswith("data:"):
        raise RuntimeError("image_data_url must be a data URL (data:image/...;base64,...)")
    try:
        header, b64 = image_data_url.split(",", 1)
    except Exception:
        raise RuntimeError("Invalid image_data_url format")

    if ";base64" not in header:
        raise RuntimeError("image_data_url must be base64 encoded")

    try:
        return base64.b64decode(b64)
    except Exception:
        raise RuntimeError("Failed to decode base64 image")


def _kling_headers() -> dict:
    """
    TODO: Βάλε εδώ τα πραγματικά headers/signature που απαιτεί η Kling.
    Κρατάω placeholders ώστε να το κουμπώσεις εύκολα.
    """
    # Παράδειγμα placeholder (ΔΕΝ είναι απαραίτητα σωστό για Kling):
    return {
        "Content-Type": "application/json",
        "X-Access-Key": KLING_ACCESS_KEY,
        # "X-Signature": "...",
        # "X-Timestamp": "...",
    }


async def _kling_create_task(
    *,
    mode: Mode,
    prompt: str,
    aspect_ratio: str,
    duration_sec: int,
    generate_audio: bool,
    image_bytes: Optional[bytes],
) -> str:
    """
    TODO: Κάνε implement με τα πραγματικά endpoints του Kling.
    Συνήθως pattern:
      - POST /.../text2video  -> returns task_id
      - POST /.../image2video -> returns task_id
    """
    _require_kling_keys()

    if mode == "image_to_video" and not image_bytes:
        raise RuntimeError("image_bytes required for image_to_video")

    # ---- PLACEHOLDER endpoint paths (βάλε τα σωστά) ----
    if mode == "text_to_video":
        url = f"{KLING_API_BASE}/v1/video/text2video"
        body = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration": int(duration_sec),
            "with_audio": bool(generate_audio),
        }
    else:
        url = f"{KLING_API_BASE}/v1/video/image2video"
        body = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration": int(duration_sec),
            "with_audio": bool(generate_audio),
            # Αν η Kling θέλει URL upload, εδώ θα χρειαστεί 1ο step upload.
            # Αν δέχεται base64:
            "image_base64": base64.b64encode(image_bytes).decode("utf-8"),
        }

    headers = _kling_headers()

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, json=body, headers=headers)

    data = None
    try:
        data = r.json()
    except Exception:
        data = {"raw": (r.text or "")[:2000]}

    if r.status_code >= 400:
        err = None
        if isinstance(data, dict):
            err = data.get("error") or data.get("message") or data.get("msg")
        raise RuntimeError(f"Kling error {r.status_code}: {err or 'Unknown error'}")

    # ---- PLACEHOLDER extraction (βάλε τα σωστά keys) ----
    task_id = None
    if isinstance(data, dict):
        task_id = data.get("task_id") or data.get("id") or (data.get("data") or {}).get("task_id")

    if not task_id:
        raise RuntimeError("Kling did not return task_id (check response structure)")
    return str(task_id)


async def _kling_poll_until_done(task_id: str, *, timeout_sec: int = 600) -> dict:
    """
    TODO: Βάλε το σωστό polling endpoint / response fields.
    """
    _require_kling_keys()
    headers = _kling_headers()

    # ---- PLACEHOLDER ----
    url = f"{KLING_API_BASE}/v1/video/tasks/{task_id}"

    started = time.time()
    async with httpx.AsyncClient(timeout=60) as c:
        while True:
            r = await c.get(url, headers=headers)
            try:
                data = r.json()
            except Exception:
                data = {"raw": (r.text or "")[:2000]}

            if r.status_code >= 400:
                err = None
                if isinstance(data, dict):
                    err = data.get("error") or data.get("message") or data.get("msg")
                raise RuntimeError(f"Kling poll error {r.status_code}: {err or 'Unknown error'}")

            # ---- PLACEHOLDER status handling ----
            # Αναμενόμενα statuses (παράδειγμα): pending/running/success/failed
            status = None
            if isinstance(data, dict):
                status = (data.get("status") or (data.get("data") or {}).get("status") or "").lower()

            if status in ("success", "succeeded", "done", "completed"):
                return data
            if status in ("failed", "error"):
                reason = None
                if isinstance(data, dict):
                    reason = data.get("error") or data.get("message") or (data.get("data") or {}).get("error")
                raise RuntimeError(f"Kling task failed: {reason or 'Unknown reason'}")

            if time.time() - started > timeout_sec:
                raise RuntimeError("Kling task timeout")

            await asyncio_sleep(2.0)


async def _kling_download_video_bytes(done_payload: dict) -> bytes:
    """
    TODO: Από το done payload πάρε το video URL (ή base64) και κατέβασέ το.
    """
    # ---- PLACEHOLDER extraction ----
    video_url = None
    if isinstance(done_payload, dict):
        video_url = (
            done_payload.get("video_url")
            or (done_payload.get("data") or {}).get("video_url")
            or (done_payload.get("data") or {}).get("url")
        )

    if not video_url:
        raise RuntimeError("No video_url found in Kling completion payload")

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(str(video_url))
        if r.status_code >= 400:
            raise RuntimeError(f"Failed to download video: {r.status_code}")
        return r.content


async def asyncio_sleep(seconds: float):
    # μικρό helper χωρίς να τραβάς extra imports παντού
    import asyncio
    await asyncio.sleep(seconds)


async def _run_kling_job(
    tg_chat_id: int,
    db_user_id: int,
    *,
    mode: Mode,
    prompt: str,
    aspect_ratio: str,
    duration_sec: int,
    generate_audio: bool,
    image_data_url: Optional[str],
    cost: float,
):
    try:
        image_bytes = None
        if mode == "image_to_video":
            if not image_data_url:
                raise RuntimeError("image_data_url required for image_to_video")
            image_bytes = _parse_image_data_url(image_data_url)

        task_id = await _kling_create_task(
            mode=mode,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            duration_sec=duration_sec,
            generate_audio=generate_audio,
            image_bytes=image_bytes,
        )

        done = await _kling_poll_until_done(task_id)
        video_bytes = await _kling_download_video_bytes(done)

        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        name = f"kling26_{uuid.uuid4().hex}.mp4"
        vid_path = VIDEOS_DIR / name
        vid_path.write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "kling26", public_url)

        # Αν έχεις tg_send_video στο project σου, καλύτερα να το στείλεις σαν video.
        await tg_send_message(
            tg_chat_id,
            f"✅ Kling 2.6: Έτοιμο!\n🔽 {public_url}",
        )

    except Exception as e:
        logger.exception("Error during Kling 2.6 job")

        # refund credits
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Kling26 fail", "system", None)
        except Exception:
            logger.exception("Error refunding credits")

        try:
            await tg_send_message(
                tg_chat_id,
                f"❌ Αποτυχία Kling 2.6.\nΛεπτομέρεια: {str(e)[:250]}",
            )
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/kling26/generate")
async def kling26_generate(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    mode: Mode = (payload.get("mode") or "text_to_video").strip()
    prompt = (payload.get("prompt") or "").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "1:1").strip()
    duration_sec = int(payload.get("duration_sec") or 5)
    generate_audio = bool(payload.get("generate_audio") or False)
    image_data_url = payload.get("image_data_url")

    if mode not in ("text_to_video", "image_to_video"):
        return JSONResponse({"ok": False, "error": "bad_mode"}, status_code=400)

    if not prompt or len(prompt) > 1000:
        return JSONResponse({"ok": False, "error": "empty_or_too_long_prompt"}, status_code=400)

    if duration_sec not in (5, 10):
        return JSONResponse({"ok": False, "error": "bad_duration"}, status_code=400)

    if aspect_ratio not in ("1:1", "9:16", "16:9"):
        return JSONResponse({"ok": False, "error": "bad_aspect"}, status_code=400)

    if mode == "image_to_video" and not image_data_url:
        return JSONResponse({"ok": False, "error": "missing_image"}, status_code=400)

    # auth
    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    # credits
    COST = _cost_credits(duration_sec, generate_audio)
    try:
        spend_credits_by_user_id(db_user_id, COST, "Kling 2.6 Video", "kling", "kling-2.6")
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "🎬 Kling 2.6: Το video ετοιμάζεται…")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_kling_job,
        tg_chat_id,
        db_user_id,
        mode=mode,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        duration_sec=duration_sec,
        generate_audio=generate_audio,
        image_data_url=image_data_url,
        cost=COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
