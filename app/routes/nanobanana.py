# app/routes/nanobanana.py
import base64
import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_photo
from ..core.paths import IMAGES_DIR, WEB_TEMPLATES_DIR
from ..web_shared import public_base_url

from ..db import (
    spend_credits_by_user_id,
    add_credits_by_user_id,
    set_last_result,
)

# Εσύ είπες ότι έχεις ήδη: app/api/nanobanana/generate
# Θα υποθέσω ότι εκεί μέσα υπάρχει async function: run_nanobanana(payload: dict) -> dict
# που επιστρέφει: {"ok": True, "image_b64": "...", "mime": "image/png"} ή {"ok": False, "error": "..."}
from ..api.nanobanana.generate import run_nanobanana  # <-- αν το λένε αλλιώς, άλλαξε 1 γραμμή εδώ

router = APIRouter()

# Credits cost (βάλε ό,τι θες)
NANOBANANA_COST_PER_IMAGE = 0.5


@router.get("/nanobanana", response_class=HTMLResponse)
def nanobanana_page():
    html_path = WEB_TEMPLATES_DIR / "nanobanana.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


async def _run_nanobanana_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    images_data_urls: list[str],
    n: int,
    cost_total: float,
):
    try:
        # Κάλεσε το δικό σου API module
        # Προτείνω να περνάμε “καθαρό” payload χωρίς initData (αυτό το χειριστήκαμε ήδη)
        payload = {
            "prompt": prompt,
            "images_data_urls": images_data_urls,
            "n": n,
        }

        result = await run_nanobanana(payload)  # <-- πρέπει να επιστρέφει dict

        if not result or not result.get("ok"):
            raise RuntimeError(result.get("error") if isinstance(result, dict) else "unknown_error")

        # Υποστηρίζουμε 1 εικόνα για αρχή (όπως στο pro)
        img_b64 = result.get("image_b64")
        mime = (result.get("mime") or "image/png").lower()

        if not img_b64:
            raise RuntimeError("No image in result")

        img_bytes = base64.b64decode(img_b64)

        ext = "png" if "png" in mime else "jpg"
        name = f"nb_{uuid.uuid4().hex}.{ext}"
        (IMAGES_DIR / name).write_bytes(img_bytes)

        public_url = f"{public_base_url()}/static/images/{name}"
        set_last_result(db_user_id, "nanobanana", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "🔽 Κατέβασε", "url": public_url}],
                [{"text": "← Πίσω", "callback_data": "menu:images"}],
            ]
        }

        await tg_send_photo(
            chat_id=tg_chat_id,
            img_bytes=img_bytes,
            caption="✅ Nano Banana: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        # refund
        try:
            add_credits_by_user_id(db_user_id, cost_total, "Refund NanoBanana fail", "system", None)
        except Exception:
            pass

        try:
            await tg_send_message(
                tg_chat_id,
                f"❌ Αποτυχία Nano Banana.\nΛεπτομέρεια: {str(e)[:250]}"
            )
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
    images_data_urls = payload.get("images_data_urls") or []
    n = payload.get("n") or 1

    if not prompt:
        return {"ok": False, "error": "empty_prompt"}

    if not isinstance(images_data_urls, list):
        images_data_urls = []

    try:
        n = int(n)
    except Exception:
        n = 1
    if n < 1:
        n = 1
    if n > 4:
        n = 4

    COST = float(NANOBANANA_COST_PER_IMAGE) * float(n)

    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    try:
        spend_credits_by_user_id(db_user_id, COST, f"Nano Banana x{n}", "nanobanana", None)
    except Exception:
        return {"ok": False, "error": "not_enough_credits"}

    try:
        await tg_send_message(tg_chat_id, "🍌 Nano Banana: Η εικόνα ετοιμάζεται…")
    except Exception:
        pass

    background_tasks.add_task(
        _run_nanobanana_job,
        tg_chat_id,
        db_user_id,
        prompt,
        images_data_urls,
        n,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST, "n": n}
