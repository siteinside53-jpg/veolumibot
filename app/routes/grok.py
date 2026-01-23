import os
import base64
import uuid
import logging  # Added logging for better error handling
from pathlib import Path
import httpx
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks  # Added missing imports
from fastapi.responses import FileResponse, JSONResponse  # Added JSONResponse import
from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_photo
from ..core.paths import STATIC_DIR
from ..web_shared import public_base_url
from ..db import (
    spend_credits_by_user_id,
    add_credits_by_user_id,
    set_last_result,
)

logging.basicConfig(level=logging.WARNING)  # Configure basic logging for the file
logger = logging.getLogger(__name__)

router = APIRouter()

XAI_API_KEY = os.getenv("XAI_API_KEY", "").strip()
IMAGES_DIR = Path(STATIC_DIR) / "images"  # Added IMAGES_DIR definition

@router.get("/grok", include_in_schema=False)
async def grok_page():
    p = Path(STATIC_DIR) / "grok.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="grok.html not found in static dir")
    return FileResponse(p)

def _grok_model_name() -> str:
    # άλλαξέ το αν θες άλλο grok image model
    return os.getenv("GROK_IMAGE_MODEL", "grok-2-image").strip()


async def _run_grok_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    cost: float,
):
    try:
        if not XAI_API_KEY:
            raise RuntimeError("XAI_API_KEY missing")

        body = {
            "model": _grok_model_name(),
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

        data = r.json()

        # Validate API response structure
        if r.status_code >= 400:
            raise RuntimeError(f"xAI error {r.status_code}: {data.get('error', 'Unknown Error')}")

        if not data.get("data") or not data["data"][0].get("b64_json"):
            raise RuntimeError("Invalid response structure from xAI API")

        img_b64 = data["data"][0]["b64_json"]
        img_bytes = base64.b64decode(img_b64)

        name = f"grok_{uuid.uuid4().hex}.png"
        img_path = IMAGES_DIR / name

        # Ensure the directory exists before saving
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
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
        logger.error(f"Error during Grok job: {e}")
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Grok fail", "system", None)
        except Exception as ex:
            logger.error(f"Error refunding credits: {ex}")

        try:
            await tg_send_message(
                tg_chat_id,
                f"❌ Αποτυχία Grok.\nΛεπτομέρεια: {str(e)[:250]}",
            )
        except Exception as ex:
            logger.error(f"Error sending failure message: {ex}")


@router.post("/api/grok/generate")
async def grok_generate(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Error parsing JSON request: {e}")
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    prompt = (payload.get("prompt") or "").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "1:1").strip()

    if not prompt:
        return {"ok": False, "error": "empty_prompt"}

    COST = 1  # βάλε ό,τι θέλεις

    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    try:
        spend_credits_by_user_id(db_user_id, COST, "Grok Image", "xai", _grok_model_name())
    except Exception as e:
        logger.error(f"Not enough credits: {e}")
        return {"ok": False, "error": "not_enough_credits"}

    try:
        await tg_send_message(tg_chat_id, "🧠 Grok: Η εικόνα ετοιμάζεται…")
    except Exception as e:
        logger.error(f"Failed to send preparation message: {e}")

    background_tasks.add_task(
        _run_grok_job,
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
