import os
import base64
import uuid
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_photo
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


@router.get("/grok", include_in_schema=False)
async def grok_page():
    p = Path(STATIC_DIR) / "grok.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="grok.html not found in static dir")
    return FileResponse(p)


def _grok_model_name() -> str:
    return (os.getenv("GROK_IMAGE_MODEL") or "grok-2-image").strip()


def _extract_image(data: dict):
    item0 = (data.get("data") or [None])[0] or {}
    if item0.get("b64_json"):
        return ("b64", item0["b64_json"])
    if item0.get("url"):
        return ("url", item0["url"])
    return None


async def _run_grok_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    cost: float,
):
    try:
        if not XAI_API_KEY:
            raise RuntimeError("XAI_API_KEY missing (set it in Railway env)")

        model = _grok_model_name()

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

        await tg_send_photo(
            chat_id=tg_chat_id,
            img_bytes=img_bytes,
            caption="✅ Grok Image: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Grok job")

        refunded = None

        # refund credits
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Grok fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Error refunding credits")

        # map error → greek reason/tips
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

    logger.warning(f"/api/grok/generate called mode={mode} modifier={modifier} aspect={aspect_ratio}")

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    if mode != "text_to_image":
        return JSONResponse(
            {"ok": False, "error": f"mode_not_supported_yet:{mode}"},
            status_code=400
        )

    COST = 1.0

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(db_user_id, COST, "Grok Image", "xai", _grok_model_name())
    except Exception as e:
        msg = str(e)
        logger.error(f"spend_credits failed: {msg}")
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "🧠 Grok: Η εικόνα ετοιμάζεται…")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_grok_job,
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
