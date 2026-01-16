# app/routes/veo31.py
import os
import uuid
import base64
import asyncio
from typing import Dict, Any, Optional, List
from .web_shared import (
    db_user_from_webapp,
    tg_send_message,
    tg_send_photo,
    tg_send_video,
    verify_telegram_init_data,
)

import httpx
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form

from ._shared import (
    db_user_from_webapp,
    tg_send_message,
    tg_send_video,
    VIDEOS_DIR,
    public_base_url,
)
from ..db import (
    spend_credits_by_user_id,
    add_credits_by_user_id,
    set_last_result,
)

router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()


def _veo31_model_name() -> str:
    return os.getenv("GEMINI_VEO31_MODEL", "veo-3.1-generate-preview").strip()


@router.post("/api/veo31/generate")
async def veo31_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    mode: str = Form("text"),             # text | image | ref
    prompt: str = Form(""),
    aspect_ratio: str = Form("16:9"),
    image: Optional[UploadFile] = File(None),        # για image->video (start frame)
    ref_images: List[UploadFile] = File([]),         # για ref->video (1-3)
):
    init_data = (tg_init_data or "").strip()
    prompt = (prompt or "").strip()
    mode = (mode or "text").strip()

    if not prompt:
        return {"ok": False, "error": "empty_prompt"}

    if aspect_ratio not in ("16:9", "9:16"):
        aspect_ratio = "16:9"

    # credits mapping
    if mode == "text":
        COST = 10
    elif mode == "image":
        COST = 12
    else:
        COST = 60

    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    try:
        spend_credits_by_user_id(db_user_id, COST, f"Veo 3.1 ({mode})", "gemini", _veo31_model_name())
    except Exception:
        return {"ok": False, "error": "not_enough_credits"}

    # read files
    image_bytes = await image.read() if image else None
    ref_bytes: list[bytes] = []
    for f in (ref_images or [])[:3]:
        try:
            ref_bytes.append(await f.read())
        except Exception:
            pass

    # validations
    if mode == "image" and not image_bytes:
        try:
            add_credits_by_user_id(db_user_id, COST, "Refund Veo31 missing image", "system", None)
        except Exception:
            pass
        return {"ok": False, "error": "missing_image"}

    if mode == "ref" and (len(ref_bytes) < 1 or len(ref_bytes) > 3):
        try:
            add_credits_by_user_id(db_user_id, COST, "Refund Veo31 bad ref_images", "system", None)
        except Exception:
            pass
        return {"ok": False, "error": "bad_ref_images"}

    try:
        await tg_send_message(tg_chat_id, "🎬 Veo 3.1: Το βίντεο ετοιμάζεται…")
    except Exception:
        pass

    background_tasks.add_task(
        _run_veo31_job,
        tg_chat_id,
        db_user_id,
        mode,
        prompt,
        aspect_ratio,
        image_bytes,
        ref_bytes,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST, "message": "Στάλθηκε στο Telegram."}


async def _run_veo31_job(
    tg_chat_id: int,
    db_user_id: int,
    mode: str,  # "text" | "image" | "ref"
    prompt: str,
    aspect_ratio: str,
    image_bytes: Optional[bytes],   # for image->video
    ref_images: list[bytes],        # for ref->video
    cost: float,
):
    try:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY missing")

        await tg_send_message(tg_chat_id, "✅ Veo 3.1: Ξεκίνησε η παραγωγή (job).")

        model = _veo31_model_name()
        base_url = "https://generativelanguage.googleapis.com/v1beta"
        op_url = f"{base_url}/models/{model}:predictLongRunning"

        instance: Dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
        }

        # image->video (first frame)
        if mode == "image":
            instance["image"] = {
                "bytesBase64Encoded": base64.b64encode(image_bytes).decode("utf-8"),
                "mimeType": "image/png",
            }

        # reference->video (1-3 images)
        if mode == "ref":
            instance["reference_images"] = [
                {
                    "bytesBase64Encoded": base64.b64encode(b).decode("utf-8"),
                    "mimeType": "image/png",
                }
                for b in ref_images[:3]
            ]

        body = {"instances": [instance]}

        # start long-running operation
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                op_url,
                headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                json=body,
            )
            data = r.json()
            if r.status_code >= 400:
                raise RuntimeError(f"Veo31 start error {r.status_code}: {data}")

        op_name = data.get("name")
        if not op_name:
            raise RuntimeError(f"No operation name returned: {data}")

        await tg_send_message(tg_chat_id, "⏳ Veo 3.1: Περιμένω το αποτέλεσμα…")

        # poll
        status = None
        async with httpx.AsyncClient(timeout=60) as c:
            for _ in range(120):  # ~6 λεπτά max
                rs = await c.get(f"{base_url}/{op_name}", headers={"x-goog-api-key": GEMINI_API_KEY})
                status = rs.json()
                if rs.status_code >= 400:
                    raise RuntimeError(f"Veo31 poll error {rs.status_code}: {status}")
                if status.get("done") is True:
                    break
                await asyncio.sleep(3)

        if not status or status.get("done") is not True:
            raise RuntimeError("Veo31 timeout: operation not done.")

        # extract video uri
        video_uri = (
            (((status.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or [{}])[0]
            .get("video", {})
            .get("uri")
        )
        if not video_uri:
            raise RuntimeError(f"No video uri in response: {status}")

        # download bytes
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            vd = await c.get(video_uri, headers={"x-goog-api-key": GEMINI_API_KEY})
            if vd.status_code >= 400:
                raise RuntimeError(f"Video download error {vd.status_code}: {vd.text[:300]}")
            video_bytes = vd.content

        # store & public url
        name = f"veo31_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "veo31", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "🔽 Κατέβασε", "url": public_url}],
                [{"text": "← Πίσω", "callback_data": "menu:video"}],
            ]
        }

        await tg_send_video(
            chat_id=tg_chat_id,
            video_bytes=video_bytes,
            caption="✅ Veo 3.1: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        # refund
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Veo31 fail", "system", None)
        except Exception:
            pass

        try:
            await tg_send_message(
                tg_chat_id,
                f"❌ Αποτυχία Veo 3.1.\nΛεπτομέρεια: {str(e)[:250]}",
            )
        except Exception:
            pass
