# app/routes/nanobanana.py
import os
import base64
import uuid
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, HTMLResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_photo
from ..core.paths import IMAGES_DIR, BASE_DIR
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
    # Nano Banana (Flash Image)
    return os.getenv("GEMINI_NANOBANANA_MODEL", "gemini-2.5-flash-image").strip()


SUPPORTED_MODELS = {
    "gemini-2.5-flash-image",
    "gemini-3-pro-image-preview",
}

_model_at_import = _gemini_model_name()
if _model_at_import not in SUPPORTED_MODELS:
    raise RuntimeError(f"Unsupported Gemini model: {_model_at_import}")


def _read_nanobanana_html() -> str:
    # app/web_templates/nanobanana.html
    p = BASE_DIR / "web_templates" / "nanobanana.html"
    return p.read_text(encoding="utf-8")


@router.get("/nanobanana")
async def nanobanana_page():
    return HTMLResponse(_read_nanobanana_html())


def _extract_gemini_image_b64(data: dict) -> Optional[str]:
    candidates = data.get("candidates") or []
    if not candidates:
        return None

    parts_out = (((candidates[0].get("content") or {}).get("parts")) or [])
    for p in parts_out:
        inline = p.get("inlineData") or p.get("inline_data") or p.get("inlineData".lower())
        # real responses usually use "inlineData" OR "inline_data"
        if isinstance(inline, dict) and inline.get("data"):
            return inline["data"]
    return None


async def _gemini_generate_one_image(
    prompt: str,
    images_data_urls: list[str],
    aspect_ratio: str,
    image_size: str,
) -> bytes:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing (set it in Railway env)")

    parts = [{"text": prompt}]

    for du in (images_data_urls or [])[:8]:
        if not isinstance(du, str):
            continue
        if not du.startswith("data:") or "base64," not in du:
            continue

        head, b64 = du.split("base64,", 1)
        mime = head.split(";")[0].replace("data:", "").strip() or "image/png"

        # your file used inlineData (camelCase) — keep it consistent
        parts.append({"inlineData": {"mimeType": mime, "data": b64.strip()}})

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
        r = await c.post(
            url,
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json=body,
        )

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

    return base64.b64decode(img_b64)


async def _run_nanobanana_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    image_size: str,
    output_format: str,
    images_data_urls: list[str],
    n_images: int,
    total_cost: float,
):
    try:
        ext = "png" if output_format.lower() == "png" else "jpg"
        last_public_url = None

        for idx in range(1, n_images + 1):
            img_bytes = await _gemini_generate_one_image(
                prompt=prompt,
                images_data_urls=images_data_urls,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
            )

            name = f"nb_{uuid.uuid4().hex}_{idx}.{ext}"
            (IMAGES_DIR / name).write_bytes(img_bytes)

            public_url = f"{public_base_url()}/static/images/{name}"
            last_public_url = public_url

            kb = {
                "inline_keyboard": [
                    [{"text": "🔽 Κατέβασε", "url": public_url}],
                    [{"text": "← Πίσω", "callback_data": "menu:images"}],
                ]
            }

            await tg_send_photo(
                chat_id=tg_chat_id,
                img_bytes=img_bytes,
                caption=f"✅ Banana AI: Έτοιμο ({idx}/{n_images})",
                reply_markup=kb,
            )

        if last_public_url:
            set_last_result(db_user_id, "nanobanana", last_public_url)

    except Exception as e:
        logger.exception("Error during NanoBanana job")

        refunded = None

        # refund όλο το ποσό αν κάτι πάει λάθος
        try:
            add_credits_by_user_id(db_user_id, total_cost, "Refund NanoBanana fail", "system", None)
            refunded = float(total_cost)
        except Exception:
            logger.exception("Error refunding credits")

        # ίδιο message format με Grok / NB Pro
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/nanobanana/generate")
async def nanobanana_generate(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    prompt = (payload.get("prompt") or "").strip()
    mode = (payload.get("mode") or "text2image").strip().lower()

    aspect_ratio = (payload.get("aspect_ratio") or "1:1").strip()
    image_size = (payload.get("image_size") or "1K").strip().upper()
    output_format = (payload.get("output_format") or "png").strip().lower()

    n_images = payload.get("n_images") or payload.get("n") or 1
    images_data_urls = payload.get("images_data_urls") or []

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    if not isinstance(n_images, int):
        try:
            n_images = int(n_images)
        except Exception:
            n_images = 1
    n_images = max(1, min(4, n_images))

    if not isinstance(images_data_urls, list):
        images_data_urls = []
    images_data_urls = images_data_urls[:5]  # όπως στο UI (0/5)

    if image_size not in ("1K", "2K", "4K"):
        image_size = "1K"
    if output_format not in ("png", "jpg"):
        output_format = "png"

    # Αν είναι text2image, αγνοούμε inputs
    if mode not in ("image_to_image", "image2image"):
        images_data_urls = []

    COST_PER_IMAGE = 0.5
    TOTAL_COST = float(COST_PER_IMAGE * n_images)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(db_user_id, TOTAL_COST, "Banana AI", "gemini", _gemini_model_name())
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, f"🍌 Banana AI: Φτιάχνω {n_images} εικόνα/ες…")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_nanobanana_job,
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        image_size,
        output_format,
        images_data_urls,
        n_images,
        TOTAL_COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": TOTAL_COST, "n_images": n_images}
