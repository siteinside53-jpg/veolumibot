# app/routes/nanobanana_pro.py
import os
import base64
import uuid
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_document
from ..core.paths import IMAGES_DIR
from ..web_shared import public_base_url

from ..texts import map_provider_error_to_gr, tool_error_message_gr
from ..db import (
    spend_credits_by_user_id,
    add_credits_by_user_id,
    set_last_result,
)

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()


def _gemini_model_name() -> str:
    return os.getenv("GEMINI_NANOBANANA_PRO_MODEL", "gemini-3-pro-image-preview").strip()


def _extract_gemini_image_b64(data: dict) -> str | None:
    candidates = data.get("candidates") or []
    if not candidates:
        return None

    parts_out = (((candidates[0].get("content") or {}).get("parts")) or [])
    for p in parts_out:
        inline = p.get("inline_data") or p.get("inlineData")
        if inline and inline.get("data"):
            return inline["data"]
    return None


async def _run_nanobanana_pro_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    image_size: str,
    output_format: str,
    images_data_urls: list[str],
    cost: float,
):
    try:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY missing (set it in Railway env)")

        parts = [{"text": prompt}]

        # images_data_urls: ["data:image/png;base64,...", ...]
        for du in images_data_urls[:8]:
            if not isinstance(du, str):
                continue
            if not du.startswith("data:") or "base64," not in du:
                continue

            head, b64 = du.split("base64,", 1)
            mime = head.split(";")[0].replace("data:", "").strip() or "image/png"
            parts.append({"inline_data": {"mime_type": mime, "data": b64.strip()}})

        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size,
                },
            },
        }

        model = _gemini_model_name()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, params={"key": GEMINI_API_KEY}, json=body)

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            err = None
            if isinstance(data, dict):
                err = data.get("error") or data.get("message") or data
            raise RuntimeError(f"Gemini error {r.status_code}: {err}")

        img_b64 = _extract_gemini_image_b64(data)
        if not img_b64:
            raise RuntimeError("Gemini did not return image data")

        img_bytes = base64.b64decode(img_b64)

        ext = "png" if output_format.lower() == "png" else "jpg"
        name = f"nbpro_{uuid.uuid4().hex}.{ext}"
        (IMAGES_DIR / name).write_bytes(img_bytes)

        public_url = f"{public_base_url()}/static/images/{name}"
        set_last_result(db_user_id, "nano_banana_pro", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "⚡ Πάρε αποτέλεσμα ξανά (δωρεάν)", "callback_data": "resend:nano_banana_pro"}],

                [{"text": "← Πίσω", "callback_data": "menu:images"}],
            ]
        }

        await tg_send_document(
            chat_id=tg_chat_id,
            file_bytes=img_bytes,
            filename="photo.png",
            caption="✅ Nano Banana Pro: Έτοιμο",
            mime_type="image/png",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during NanoBananaPro job")

        refunded = None

        # refund credits
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund NanoBananaPro fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Error refunding credits")

        # map error → greek reason/tips + send friendly message (same format as Grok)
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/nanobanana-pro/generate")
async def nanobanana_pro_generate(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    prompt = (payload.get("prompt") or "").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "1:1").strip()
    image_size = (payload.get("image_size") or "1K").strip().upper()
    output_format = (payload.get("output_format") or "png").strip().lower()
    images_data_urls = payload.get("images_data_urls") or []

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    if not isinstance(images_data_urls, list):
        images_data_urls = []

    if image_size not in ("1K", "2K", "4K"):
        image_size = "1K"
    if output_format not in ("png", "jpg"):
        output_format = "png"

    COST = 4.0

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(db_user_id, COST, "Nano Banana Pro", "gemini", _gemini_model_name())
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "🍌 Nano Banana Pro: Η εικόνα ετοιμάζεται…")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_nanobanana_pro_job,
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        image_size,
        output_format,
        images_data_urls,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
