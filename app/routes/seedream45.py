# app/routes/seedream45.py
import os
import uuid
import base64
import logging
import asyncio
from typing import Optional

import httpx
from fastapi import APIRouter, Request, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_photo
from ..core.paths import IMAGES_DIR
from ..web_shared import public_base_url
from ..db import spend_credits_by_user_id, add_credits_by_user_id, set_last_result
from ..texts import map_provider_error_to_gr, tool_error_message_gr

logger = logging.getLogger(__name__)
router = APIRouter()

SEEDREAM_API_KEY = os.getenv("SEEDREAM_API_KEY", "").strip()
SEEDREAM_API_URL = os.getenv(
    "SEEDREAM_API_URL", "https://api.seedream.ai/v1"
).strip()

COST = 1.3


def _seedream_headers() -> dict:
    if not SEEDREAM_API_KEY:
        raise RuntimeError("SEEDREAM_API_KEY missing (set it in Railway env)")
    return {
        "Authorization": f"Bearer {SEEDREAM_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _run_seedream45_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    cost: float,
) -> None:
    try:
        headers = _seedream_headers()

        body: dict = {
            "model": "seedream-4.5",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
        }

        # 1) Create generation
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{SEEDREAM_API_URL}/images/generations",
                json=body,
                headers=headers,
            )

        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:2000]}

        if r.status_code >= 400:
            raise RuntimeError(f"Seedream 4.5 create error {r.status_code}: {data}")

        # Check if result is immediate or async
        task_id = data.get("task_id") or data.get("id")
        img_bytes = None

        # Try to get image directly from response
        images = data.get("data") or data.get("images") or []
        if images and isinstance(images, list):
            first = images[0] if images else {}
            b = first.get("b64_json") or first.get("base64")
            if b:
                img_bytes = base64.b64decode(b)
            elif first.get("url"):
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
                    ir = await c.get(first["url"])
                    if ir.status_code < 400:
                        img_bytes = ir.content
                    else:
                        raise RuntimeError(f"Image download error {ir.status_code}")

        # If async, poll
        if not img_bytes and task_id:
            poll_url = f"{SEEDREAM_API_URL}/images/generations/{task_id}"
            for _ in range(120):  # ~4 min
                async with httpx.AsyncClient(timeout=30) as c:
                    pr = await c.get(poll_url, headers=_seedream_headers())

                try:
                    status_data = pr.json()
                except Exception:
                    status_data = {}

                status = (status_data.get("status") or "").lower()
                if status in ("succeeded", "completed", "done"):
                    images = status_data.get("data") or status_data.get("images") or []
                    if images:
                        first = images[0]
                        b = first.get("b64_json") or first.get("base64")
                        if b:
                            img_bytes = base64.b64decode(b)
                        elif first.get("url"):
                            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c2:
                                ir = await c2.get(first["url"])
                                img_bytes = ir.content
                    break
                if status in ("failed", "cancelled", "error"):
                    raise RuntimeError(f"Seedream 4.5 generation failed: {status_data}")

                await asyncio.sleep(2)

        if not img_bytes:
            raise RuntimeError("Seedream 4.5 did not return image data")

        name = f"seedream45_{uuid.uuid4().hex}.png"
        (IMAGES_DIR / name).write_bytes(img_bytes)

        public_url = f"{public_base_url()}/static/images/{name}"
        set_last_result(db_user_id, "seedream45", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "\ud83d\udd3d \u039a\u03b1\u03c4\u03ad\u03b2\u03b1\u03c3\u03b5", "url": public_url}],
                [{"text": "\u2190 \u03a0\u03af\u03c3\u03c9", "callback_data": "menu:images"}],
            ]
        }

        await tg_send_photo(
            chat_id=tg_chat_id,
            img_bytes=img_bytes,
            caption="\u2705 Seedream 4.5: \u0388\u03c4\u03bf\u03b9\u03bc\u03bf",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Seedream 4.5 job")
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Seedream 4.5 fail", "system", None)
            refunded = float(cost)
        except Exception:
            logger.exception("Refund failed")
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/seedream45/generate")
async def seedream45_generate(
    request: Request,
    background_tasks: BackgroundTasks,
):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    prompt = (payload.get("prompt") or "").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "1:1").strip()

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    try:
        dbu = db_user_from_webapp(init_data)
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(
            db_user_id, COST, "Seedream 4.5", "seedream", "seedream-4.5"
        )
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "\ud83d\uddbc Seedream 4.5: \u0397 \u03b5\u03b9\u03ba\u03cc\u03bd\u03b1 \u03b5\u03c4\u03bf\u03b9\u03bc\u03ac\u03b6\u03b5\u03c4\u03b1\u03b9\u2026")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_seedream45_job,
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
