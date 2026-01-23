# app/routes/nanobanana.py
import os
import base64
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, HTMLResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_photo
from ..core.paths import IMAGES_DIR, BASE_DIR
from ..web_shared import public_base_url

from ..db import (
    spend_credits_by_user_id,
    add_credits_by_user_id,
    set_last_result,
)

router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()


def _gemini_model_name() -> str:
    return os.getenv("GEMINI_NANOBANANA_MODEL", "gemini-2.5-flash-image-preview").strip()


def _read_nanobanana_html() -> str:
    # Σύμφωνα με τη δομή σου: app/web_templates/nanobanana.html
    p = BASE_DIR / "web_templates" / "nanobanana.html"
    return p.read_text(encoding="utf-8")


@router.get("/nanobanana")
async def nanobanana_page():
    return HTMLResponse(_read_nanobanana_html())


async def _gemini_generate_one_image(
    prompt: str,
    aspect_ratio: str,
    image_size: str,
    output_format: str,
    images_data_urls: list[str],
) -> bytes:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")

    parts = [{"text": prompt}]

    # image->image (προαιρετικά)
    for du in (images_data_urls or [])[:8]:
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
        data = r.json()
        if r.status_code >= 400:
            raise RuntimeError(f"Gemini error {r.status_code}: {data}")

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"No candidates: {data}")

    parts_out = (((candidates[0].get("content") or {}).get("parts")) or [])
    img_b64 = None
    for p in parts_out:
        inline = p.get("inline_data") or p.get("inlineData")
        if inline and inline.get("data"):
            img_b64 = inline["data"]
            break

    if not img_b64:
        raise RuntimeError(f"No image in response: {data}")

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
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                output_format=output_format,
                images_data_urls=images_data_urls,
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
        # refund όλο το ποσό αν κάτι πάει λάθος
        try:
            add_credits_by_user_id(db_user_id, total_cost, "Refund NanoBanana fail", "system", None)
        except Exception:
            pass

        try:
            await tg_send_message(tg_chat_id, f"❌ Αποτυχία Banana AI.\nΛεπτομέρεια: {str(e)[:250]}")
        except Exception:
            pass


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
        return {"ok": False, "error": "empty_prompt"}

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

    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    try:
        spend_credits_by_user_id(db_user_id, TOTAL_COST, "Banana AI", "gemini", _gemini_model_name())
    except Exception:
        return {"ok": False, "error": "not_enough_credits"}

    try:
        await tg_send_message(tg_chat_id, f"🍌 Banana AI: Φτιάχνω {n_images} εικόνα/ες…")
    except Exception:
        pass

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
