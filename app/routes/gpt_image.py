# app/routes/gpt_image.py
import os
import base64
import uuid

from fastapi import APIRouter, BackgroundTasks
from openai import OpenAI

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_document
from ..texts import map_provider_error_to_gr, tool_error_message_gr

from ..core.paths import IMAGES_DIR
from ..web_shared import public_base_url
from ..db import spend_credits_by_user_id, add_credits_by_user_id, set_last_result

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


async def _run_gpt_image_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    size: str,
    quality: str,
    cost: int,
):
    try:
        if client is None:
            raise RuntimeError("openai_not_configured")

        res = client.images.generate(
            model="gpt-image-1.5",
            prompt=prompt,
            size=size,
            quality=quality,
        )

        b64 = res.data[0].b64_json
        img = base64.b64decode(b64)

        name = f"{uuid.uuid4().hex}.png"
        (IMAGES_DIR / name).write_bytes(img)

        public_url = f"{public_base_url()}/static/images/{name}"
        set_last_result(db_user_id, "gpt_image", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "🔽 Κατέβασε", "url": public_url}],
                [{"text": "🔽 Πάρε αποτέλεσμα ξανά (δωρεάν)", "callback_data": "gptimg:repeat:last"}],
                [{"text": "← Πίσω", "callback_data": "menu:images"}],
            ]
        }

        await tg_send_document(
            chat_id=tg_chat_id,
            file_bytes=img,
            filename="photo.png",
            caption="✅ Η εικόνα δημιουργήθηκε",
            mime_type="image/png",
            reply_markup=kb,
        )

    except Exception as e:
        # 1) refund credits (best-effort)
        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund GPT Image fail", "system", None)
            refunded = float(cost)
        except Exception:
            pass

        # 2) friendly greek message (no raw errors)
        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            pass


@router.post("/api/gpt_image/generate")
async def gpt_image_generate(payload: dict, background_tasks: BackgroundTasks):
    init_data = payload.get("initData", "")
    prompt = (payload.get("prompt") or "").strip()
    ratio = payload.get("ratio", "1:1")
    quality = (payload.get("quality") or "medium").lower().strip()

    if not prompt:
        return {"ok": False, "error": "empty_prompt"}

    if client is None:
        return {"ok": False, "error": "openai_not_configured"}

    size_map = {
        "1:1": "1024x1024",
        "2:3": "1024x1536",
        "3:2": "1536x1024",
    }
    size = size_map.get(ratio, "1024x1024")

    if quality not in ("low", "medium", "high"):
        quality = "medium"

    cost_map = {"low": 1, "medium": 2, "high": 5}
    COST = cost_map[quality]

    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    try:
        spend_credits_by_user_id(db_user_id, COST, f"GPT Image ({quality})", "openai", "gpt-image-1.5")
    except Exception:
        return {"ok": False, "error": "not_enough_credits"}

    try:
        await tg_send_message(tg_chat_id, "🧪 Η εικόνα δημιουργείται… Το αποτέλεσμα θα έρθει εδώ.")
    except Exception:
        pass

    background_tasks.add_task(_run_gpt_image_job, tg_chat_id, db_user_id, prompt, size, quality, COST)
    return {"ok": True, "sent_to_telegram": True, "cost": COST}
