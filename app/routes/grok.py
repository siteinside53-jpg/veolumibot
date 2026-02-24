import os
import base64
import uuid
import asyncio
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_document
from ..texts import map_provider_error_to_gr, tool_error_message_gr
from ..core.paths import STATIC_DIR
from ..web_shared import public_base_url
from ..db import (
    spend_credits_by_user_id,
    add_credits_by_user_id,
    set_last_result,
)

logger = logging.getLogger(__name__)
router = APIRouter()

XAI_API_KEY = os.getenv("XAI_API_KEY", "").strip()
IMAGES_DIR = Path(STATIC_DIR) / "images"
VIDEOS_DIR = Path(STATIC_DIR) / "videos"

COSTS = {
    "text_to_image": 0.8,
    "text_to_video": 4.0,
    "image_to_video": 4.0,
}


@router.get("/grok", include_in_schema=False)
async def grok_page():
    p = Path(STATIC_DIR) / "grok.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="grok.html not found in static dir")
    return FileResponse(p)


def _grok_image_model() -> str:
    return (os.getenv("GROK_IMAGE_MODEL") or "grok-2-image").strip()


def _extract_image(data: dict):
    item0 = (data.get("data") or [None])[0] or {}
    if item0.get("b64_json"):
        return ("b64", item0["b64_json"])
    if item0.get("url"):
        return ("url", item0["url"])
    return None


# ──────────────────────────────────
# IMAGE generation job
# ──────────────────────────────────
async def _run_grok_image_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    cost: float,
):
    try:
        if not XAI_API_KEY:
            raise RuntimeError("XAI_API_KEY missing (set it in Railway env)")

        model = _grok_image_model()

        body = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "png",
        }

        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                "https://api.x.ai/v1/images/generations",
                json=body,
                headers=headers,
            )

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            err = None
            if isinstance(data, dict):
                err = data.get("error") or data.get("message")
            raise RuntimeError(f"xAI error {r.status_code}: {err or 'Unknown Error'}")

        img = _extract_image(data)
        if not img:
            raise RuntimeError("xAI did not return image data")

        kind, value = img

        if kind == "b64":
            img_bytes = base64.b64decode(value)
        elif kind == "url":
            async with httpx.AsyncClient() as c:
                img_bytes = (await c.get(value)).content

        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        name = f"grok_{uuid.uuid4().hex}.png"
        img_path = IMAGES_DIR / name
        img_path.write_bytes(img_bytes)

        public_url = f"{public_base_url()}/static/images/{name}"
        set_last_result(db_user_id, "grok", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "🔽 Κατέβασε", "url": public_url}],
                [{"text": "← Πίσω", "callback_data": "menu:images"}],
            ]
        }

        await tg_send_document(
            chat_id=tg_chat_id,
            file_bytes=img_bytes,
            filename="photo.png",
            caption="✅ Grok Image: Έτοιμο",
            mime_type="image/png",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Grok image job")
        _handle_grok_error(tg_chat_id, db_user_id, cost, e)


# ──────────────────────────────────
# VIDEO generation job
# ──────────────────────────────────
async def _run_grok_video_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    image_data_url: str | None,
    cost: float,
):
    try:
        if not XAI_API_KEY:
            raise RuntimeError("XAI_API_KEY missing (set it in Railway env)")

        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json",
        }

        body: dict = {
            "model": "grok-imagine-video",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration": 8,
            "resolution": "720p",
        }

        # Image-to-video: attach image
        if image_data_url:
            body["image"] = {"url": image_data_url}

        # Step 1: create generation request
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                "https://api.x.ai/v1/videos/generations",
                json=body,
                headers=headers,
            )

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            err = None
            if isinstance(data, dict):
                err = data.get("error") or data.get("message")
            raise RuntimeError(f"xAI video error {r.status_code}: {err or 'Unknown Error'}")

        request_id = data.get("request_id")
        if not request_id:
            raise RuntimeError("xAI did not return request_id")

        # Step 2: poll for completion
        poll_url = f"https://api.x.ai/v1/videos/generations/{request_id}"
        video_url = None
        max_wait = 480  # 8 minutes
        elapsed = 0
        interval = 5

        async with httpx.AsyncClient(timeout=60) as c:
            while elapsed < max_wait:
                await asyncio.sleep(interval)
                elapsed += interval

                pr = await c.get(poll_url, headers={"Authorization": f"Bearer {XAI_API_KEY}"})

                try:
                    pdata = pr.json()
                except Exception:
                    continue

                status = pdata.get("status", "")

                if status == "done":
                    video_info = pdata.get("video") or {}
                    video_url = video_info.get("url")
                    break
                elif status == "expired":
                    raise RuntimeError("xAI video generation expired")
                # else pending → keep polling

        if not video_url:
            raise RuntimeError("xAI video generation timed out")

        # Step 3: download video
        async with httpx.AsyncClient(timeout=120) as c:
            vr = await c.get(video_url)
            video_bytes = vr.content

        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        name = f"grok_{uuid.uuid4().hex}.mp4"
        vid_path = VIDEOS_DIR / name
        vid_path.write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "grok_video", public_url)

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
            caption="✅ Grok Video: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Grok video job")
        await _handle_grok_error(tg_chat_id, db_user_id, cost, e)


async def _handle_grok_error(tg_chat_id, db_user_id, cost, e):
    refunded = None
    try:
        add_credits_by_user_id(db_user_id, cost, "Refund Grok fail", "system", None)
        refunded = float(cost)
    except Exception:
        logger.exception("Error refunding credits")

    try:
        reason, tips = map_provider_error_to_gr(str(e))
        msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
        await tg_send_message(tg_chat_id, msg)
    except Exception:
        logger.exception("Error sending failure message")


@router.post("/api/grok/generate")
async def grok_generate(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    prompt = (payload.get("prompt") or "").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "1:1").strip()
    mode = (payload.get("mode") or "text_to_image").strip()
    modifier = (payload.get("modifier") or "spicy").strip()
    images_data_urls = payload.get("images_data_urls") or []

    logger.warning(f"/api/grok/generate called mode={mode} modifier={modifier} aspect={aspect_ratio}")

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    if mode not in COSTS:
        return JSONResponse({"ok": False, "error": f"unknown_mode:{mode}"}, status_code=400)

    COST = COSTS[mode]

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(db_user_id, COST, f"Grok {mode}", "xai", "grok-imagine")
    except Exception as e:
        msg = str(e)
        logger.error(f"spend_credits failed: {msg}")
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    if mode == "text_to_image":
        try:
            await tg_send_message(tg_chat_id, "🧠 Grok: Η εικόνα ετοιμάζεται…")
        except Exception:
            logger.exception("Failed to send preparation message")

        background_tasks.add_task(
            _run_grok_image_job,
            tg_chat_id,
            db_user_id,
            prompt,
            aspect_ratio,
            COST,
        )

    elif mode in ("text_to_video", "image_to_video"):
        image_data_url = None
        if mode == "image_to_video" and images_data_urls:
            image_data_url = images_data_urls[0]

        try:
            await tg_send_message(tg_chat_id, "🎬 Grok: Το βίντεο ετοιμάζεται… (μπορεί 2-5 λεπτά)")
        except Exception:
            logger.exception("Failed to send preparation message")

        background_tasks.add_task(
            _run_grok_video_job,
            tg_chat_id,
            db_user_id,
            prompt,
            aspect_ratio,
            image_data_url,
            COST,
        )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
