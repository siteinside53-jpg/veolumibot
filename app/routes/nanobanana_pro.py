# app/routes/nanobanana_pro.py
import os
import base64
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from .web_shared import (
    db_user_from_webapp,
    tg_send_message,
    tg_send_photo,
)

from ._shared import (
    db_user_from_webapp,
    tg_send_message,
    tg_send_photo,
    IMAGES_DIR,
    public_base_url,
)
from ..db import (
    spend_credits_by_user_id,
    add_credits_by_user_id,
    set_last_result,
)

router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()


def _gemini_model_name() -> str:
    # Nano Banana Pro
    return os.getenv("GEMINI_NANOBANANA_PRO_MODEL", "gemini-3-pro-image-preview").strip()


async def _run_nanobanana_pro_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,     # "1:1" | "3:2" | "2:3" etc (ό,τι στέλνει το WebApp σου)
    image_size: str,       # "1K" | "2K" | "4K"
    output_format: str,    # "png" | "jpg"
    images_data_urls: list[str],
    cost: float,
):
    try:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY missing")

        # build "parts": text + optional inline images
        parts = [{"text": prompt}]

        # images_data_urls are like "data:image/png;base64,...."
        for du in images_data_urls[:8]:
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
            data = r.json()
            if r.status_code >= 400:
                raise RuntimeError(f"Gemini error {r.status_code}: {data}")

        # parse image from response
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"No candidates: {data}")

        c0 = candidates[0]
        parts_out = (((c0.get("content") or {}).get("parts")) or [])
        img_b64 = None
        for p in parts_out:
            inline = p.get("inline_data") or p.get("inlineData") or None
            if inline and inline.get("data"):
                img_b64 = inline["data"]
                break

        if not img_b64:
            raise RuntimeError(f"No image in response: {data}")

        img_bytes = base64.b64decode(img_b64)

        ext = "png" if output_format.lower() == "png" else "jpg"
        name = f"nbpro_{uuid.uuid4().hex}.{ext}"
        (IMAGES_DIR / name).write_bytes(img_bytes)

        public_url = f"{public_base_url()}/static/images/{name}"

        # store last result so "repeat last" is free
        set_last_result(db_user_id, "nano_banana_pro", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "🔽 Κατέβασε", "url": public_url}],
                [{"text": "🔁 Πάρε αποτέλεσμα ξανά (δωρεάν)", "callback_data": "nbpro:repeat:last"}],
                [{"text": "← Πίσω", "callback_data": "menu:images"}],
            ]
        }

        await tg_send_photo(
            chat_id=tg_chat_id,
            img_bytes=img_bytes,
            caption="✅ Nano Banana Pro: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        # refund credits
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund NanoBananaPro fail", "system", None)
        except Exception:
            pass

        try:
            await tg_send_message(
                tg_chat_id,
                f"❌ Αποτυχία Nano Banana Pro.\nΛεπτομέρεια: {str(e)[:250]}",
            )
        except Exception:
            pass


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
        return {"ok": False, "error": "empty_prompt"}

    if not isinstance(images_data_urls, list):
        images_data_urls = []

    if image_size not in ("1K", "2K", "4K"):
        image_size = "1K"
    if output_format not in ("png", "jpg"):
        output_format = "png"

    COST = 4

    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    try:
        spend_credits_by_user_id(db_user_id, COST, "Nano Banana Pro", "gemini", _gemini_model_name())
    except Exception:
        return {"ok": False, "error": "not_enough_credits"}

    try:
        await tg_send_message(tg_chat_id, "🍌 Nano Banana Pro: Η εικόνα ετοιμάζεται…")
    except Exception:
        pass

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
