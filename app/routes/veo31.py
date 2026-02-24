# app/routes/veo31.py
import os
import uuid
import base64
import asyncio
import logging
from typing import Dict, Any, Optional, List

import httpx
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_document
from ..core.paths import VIDEOS_DIR
from ..web_shared import public_base_url

from ..db import (
    spend_credits_by_user_id,
    add_credits_by_user_id,
    set_last_result,
)

from ..texts import map_provider_error_to_gr, tool_error_message_gr

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()


def _veo31_model_name() -> str:
    return os.getenv("GEMINI_VEO31_MODEL", "veo-3.1-generate-preview").strip()


@router.post("/api/veo31/generate")
async def veo31_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    mode: str = Form("text"),  # text | image | ref
    prompt: str = Form(""),
    aspect_ratio: str = Form("16:9"),
    image: Optional[UploadFile] = File(None),        # image->video start frame
    ref_images: List[UploadFile] = File([]),         # ref->video (1-3 images)
):
    init_data = (tg_init_data or "").strip()
    prompt = (prompt or "").strip()
    mode = (mode or "text").strip().lower()
    aspect_ratio = (aspect_ratio or "16:9").strip()

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    if mode == "text":
        COST = 10
    elif mode == "image":
        COST = 12
    elif mode == "ref":
        COST = 60
    else:
        return JSONResponse({"ok": False, "error": "bad_mode"}, status_code=400)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(db_user_id, COST, f"Veo 3.1 ({mode})", "gemini", _veo31_model_name())
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    image_bytes = await image.read() if image else None

    ref_bytes: list[bytes] = []
    for f in (ref_images or [])[:3]:
        try:
            ref_bytes.append(await f.read())
        except Exception:
            pass

    if mode == "image" and not image_bytes:
        try:
            add_credits_by_user_id(db_user_id, COST, "Refund Veo31 missing image", "system", None)
        except Exception:
            logger.exception("Refund Veo31 missing image failed")
        return JSONResponse({"ok": False, "error": "missing_image"}, status_code=400)

    if mode == "ref" and (len(ref_bytes) < 1 or len(ref_bytes) > 3):
        try:
            add_credits_by_user_id(db_user_id, COST, "Refund Veo31 bad ref_images", "system", None)
        except Exception:
            logger.exception("Refund Veo31 bad ref_images failed")
        return JSONResponse({"ok": False, "error": "bad_ref_images"}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "🎬 Veo 3.1: Το βίντεο ετοιμάζεται…")
    except Exception:
        logger.exception("Failed to send preparation message")

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

    return {"ok": True, "sent_to_telegram": True, "cost": COST}


async def _run_veo31_job(
    tg_chat_id: int,
    db_user_id: int,
    mode: str,
    prompt: str,
    aspect_ratio: str,
    image_bytes: Optional[bytes],
    ref_images: list[bytes],
    cost: float,
):
    try:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY missing (set it in Railway env)")

        model = _veo31_model_name()
        base_url = "https://generativelanguage.googleapis.com/v1beta"
        op_url = f"{base_url}/models/{model}:predictLongRunning"

        ratio_hint = ""
        if aspect_ratio == "16:9":
            ratio_hint = "Output in landscape 16:9 (wide cinematic framing)."
        elif aspect_ratio == "9:16":
            ratio_hint = "Output in vertical 9:16 (portrait framing for reels)."

        final_prompt = f"{ratio_hint}\n{prompt}".strip()

        instance: Dict[str, Any] = {"prompt": final_prompt}

        if mode == "image":
            instance["image"] = {
                "bytesBase64Encoded": base64.b64encode(image_bytes).decode("utf-8"),
                "mimeType": "image/png",
            }
        elif mode == "ref":
            instance["reference_images"] = [
                {
                    "bytesBase64Encoded": base64.b64encode(b).decode("utf-8"),
                    "mimeType": "image/png",
                }
                for b in ref_images[:3]
            ]

        body = {"instances": [instance]}

        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                op_url,
                headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                json=body,
            )

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            raise RuntimeError(f"Veo31 start error {r.status_code}: {data}")

        op_name = data.get("name")
        if not op_name:
            raise RuntimeError(f"No operation name returned: {data}")

        status = None
        async with httpx.AsyncClient(timeout=60) as c:
            for _ in range(120):  # ~6 λεπτά
                rs = await c.get(f"{base_url}/{op_name}", headers={"x-goog-api-key": GEMINI_API_KEY})
                try:
                    status = rs.json()
                except Exception:
                    status = {"raw": (rs.text or "")[:2000]}
                if rs.status_code >= 400:
                    raise RuntimeError(f"Veo31 poll error {rs.status_code}: {status}")
                if status.get("done") is True:
                    break
                await asyncio.sleep(3)

        if not status or status.get("done") is not True:
            raise RuntimeError("Veo31 timeout: operation not done.")

        video_uri = (
            (((status.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or [{}])[0]
            .get("video", {})
            .get("uri")
        )
        if not video_uri:
            raise RuntimeError(f"No video uri in response: {status}")

        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            vd = await c.get(video_uri, headers={"x-goog-api-key": GEMINI_API_KEY})
            if vd.status_code >= 400:
                raise RuntimeError(f"Video download error {vd.status_code}: {(vd.text or '')[:300]}")
            video_bytes = vd.content

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

        await tg_send_document(
            chat_id=tg_chat_id,
            file_bytes=video_bytes,
            filename="video.mp4",
            mime_type="video/mp4",
            caption="✅ Veo 3.1: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Veo31 job")

        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Veo31 fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Error refunding credits")

        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")
