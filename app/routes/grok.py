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
    # xAI μπορεί να επιστρέφει error ως dict ή string
    err = None
    if isinstance(data, dict):
        err = data.get("error") or data.get("message") or data.get("detail")
    raise RuntimeError(f"xAI error {r.status_code}: {err or 'Unknown Error'}")

def _strip_data_url(s: str) -> str:
    # supports: "data:image/png;base64,AAAA..."
    if s.startswith("data:") and "base64," in s:
        return s.split("base64,", 1)[1]
    return s

async def _download_bytes(url: str) -> bytes:
    # κατεβάζουμε την εικόνα αν η xAI επιστρέψει url αντί για b64_json
    async with httpx.AsyncClient(timeout=120) as c2:
        rr = await c2.get(url)
        rr.raise_for_status()
        return rr.content

if not isinstance(data, dict):
    raise RuntimeError(f"Invalid xAI response type: {type(data)} - {data}")

items = data.get("data")
if not isinstance(items, list) or not items:
    raise RuntimeError(f"Invalid response structure from xAI API. Keys: {list(data.keys())}. Full: {data}")

item0 = items[0] if isinstance(items[0], dict) else None
if not isinstance(item0, dict):
    raise RuntimeError(f"Invalid xAI data[0] structure: {items[0]}")

# 1) Preferred: b64_json (may be raw base64 OR data-url)
b64 = item0.get("b64_json")
if isinstance(b64, str) and b64.strip():
    b64_clean = _strip_data_url(b64.strip())
    try:
        img_bytes = base64.b64decode(b64_clean)
    except Exception as e:
        raise RuntimeError(f"Failed to decode b64_json. Error: {e}. First 80 chars: {b64_clean[:80]}")
else:
    # 2) Alternative: url (download then send)
    url = item0.get("url")
    if isinstance(url, str) and url.strip():
        img_bytes = await _download_bytes(url.strip())
    else:
        raise RuntimeError(
            f"Invalid response structure from xAI API. data[0] keys: {list(item0.keys())}. Full: {data}"
        )

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
