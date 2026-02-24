# app/routes/sora2pro.py
import os
import uuid
import json
import asyncio
import random
import logging
from typing import Optional, List, Dict, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_document
from ..core.paths import VIDEOS_DIR
from ..web_shared import public_base_url
from ..db import spend_credits_by_user_id, add_credits_by_user_id, set_last_result
from ..texts import map_provider_error_to_gr, tool_error_message_gr

logger = logging.getLogger(__name__)
router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


def _size_from_aspect(aspect: str) -> str:
    a = (aspect or "").lower().strip()
    return "720x1280" if a in ("portrait", "9:16", "vertical") else "1280x720"


def _seconds_from_ui(seconds: str) -> str:
    s = str(seconds or "").strip()
    return s if s in ("4", "8", "12") else "8"


def _quality_from_ui(q: str) -> str:
    return "high" if (q or "standard").lower().strip() == "high" else "standard"


def _mode_from_ui(m: str) -> str:
    m = (m or "text").lower().strip()
    return m if m in ("image", "storyboard") else "text"


def _guess_image_mime(filename: str) -> str:
    f = (filename or "").lower()
    if f.endswith(".jpg") or f.endswith(".jpeg"):
        return "image/jpeg"
    if f.endswith(".webp"):
        return "image/webp"
    return "image/png"


def _is_transient_http(code: int) -> bool:
    return code in _TRANSIENT_STATUSES


async def _request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    params: Dict[str, Any] | None = None,
    data: Dict[str, Any] | None = None,
    files: Any = None,
    json_body: Dict[str, Any] | None = None,
    max_attempts: int = 10,
    base_sleep: float = 1.5,
) -> httpx.Response:
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            r = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                data=data,
                files=files,
                json=json_body,
            )

            if _is_transient_http(r.status_code):
                sleep_s = min(20.0, base_sleep * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
                await asyncio.sleep(sleep_s)
                continue

            return r

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            sleep_s = min(20.0, base_sleep * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
            await asyncio.sleep(sleep_s)

    raise RuntimeError(f"Network/transient failure after retries: {last_exc or 'Unknown error'}")


async def _openai_video_create(
    *,
    model: str,
    prompt: str,
    size: str,
    seconds: str,
    quality: str,
    input_reference_bytes: Optional[bytes],
    input_reference_name: Optional[str],
) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing (set it in Railway env)")

    url = "https://api.openai.com/v1/videos"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    data = {"model": model, "prompt": prompt, "size": size, "seconds": seconds}
    data_with_quality = {**data, "quality": quality}

    files = None
    if input_reference_bytes:
        files = {
            "input_reference": (
                input_reference_name or "ref.png",
                input_reference_bytes,
                _guess_image_mime(input_reference_name or "ref.png"),
            )
        }

    async with httpx.AsyncClient(timeout=60) as c:
        # 1) attempt with quality
        if files:
            r = await _request_with_retries(c, "POST", url, headers=headers, data=data_with_quality, files=files)
        else:
            r = await _request_with_retries(c, "POST", url, headers=headers, json_body=data_with_quality)

        try:
            j = r.json() if r.content else {}
        except Exception:
            j = {"raw": (r.text or "")[:2000]}

        # 2) if quality rejected, retry without it
        if r.status_code == 400 and "quality" in data_with_quality:
            if files:
                r2 = await _request_with_retries(c, "POST", url, headers=headers, data=data, files=files)
            else:
                r2 = await _request_with_retries(c, "POST", url, headers=headers, json_body=data)

            try:
                j2 = r2.json() if r2.content else {}
            except Exception:
                j2 = {"raw": (r2.text or "")[:2000]}

            if r2.status_code >= 400:
                raise RuntimeError(f"Sora create error {r2.status_code}: {j2}")
            return j2

        if r.status_code >= 400:
            raise RuntimeError(f"Sora create error {r.status_code}: {j}")

        return j


async def _openai_video_retrieve(video_id: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing (set it in Railway env)")

    url = f"https://api.openai.com/v1/videos/{video_id}"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    async with httpx.AsyncClient(timeout=30) as c:
        r = await _request_with_retries(c, "GET", url, headers=headers)

    if r.status_code >= 400:
        raise RuntimeError(f"Sora retrieve error {r.status_code}: {(r.text or '')[:300]}")

    try:
        return r.json()
    except Exception:
        raise RuntimeError(f"Sora retrieve non-json: {(r.text or '')[:300]}")


async def _openai_video_download(video_id: str) -> bytes:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing (set it in Railway env)")

    url = f"https://api.openai.com/v1/videos/{video_id}/content"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
        r = await _request_with_retries(c, "GET", url, headers=headers)

    if r.status_code == 404:
        raise RuntimeError("Sora content not available (404)")
    if r.status_code >= 400:
        raise RuntimeError(f"Sora download error {r.status_code}: {(r.text or '')[:300]}")

    return r.content


def _build_storyboard_prompt(scenes: List[Dict[str, Any]], base_prompt: str) -> str:
    lines = [base_prompt.strip(), "", "Storyboard:"] if base_prompt else ["Storyboard:"]
    t = 0.0
    for i, s in enumerate(scenes, start=1):
        try:
            sec = float(s.get("seconds") or 0)
        except Exception:
            sec = 0.0
        p = (s.get("prompt") or "").strip()
        lines.append(f"- Scene {i} ({sec:.1f}s, t={t:.1f}→{t+sec:.1f}): {p}")
        t += sec
    return "\n".join(lines).strip()


async def _run_sora2pro_job(
    tg_chat_id: int,
    db_user_id: int,
    mode: str,
    prompt: str,
    size: str,
    seconds: str,
    quality: str,
    image_bytes: Optional[bytes],
    image_name: Optional[str],
    storyboard_scenes: List[Dict[str, Any]],
    cost: int,
) -> None:
    warned_transient = False
    video_id: Optional[str] = None

    try:
        await tg_send_message(tg_chat_id, "🎬 Sora 2 Pro: Ξεκίνησε η παραγωγή…")

        final_prompt = prompt
        input_reference_bytes, input_reference_name = None, None

        if mode == "image":
            input_reference_bytes, input_reference_name = image_bytes, image_name
        elif mode == "storyboard":
            final_prompt = _build_storyboard_prompt(storyboard_scenes, prompt)

        created = await _openai_video_create(
            model="sora-2-pro",
            prompt=final_prompt,
            size=size,
            seconds=seconds,
            quality=quality,
            input_reference_bytes=input_reference_bytes,
            input_reference_name=input_reference_name,
        )

        video_id = created.get("id")
        if not video_id:
            raise RuntimeError(f"No video id returned: {created}")

        # poll status
        for _ in range(240):  # ~8 minutes at 2s
            try:
                v = await _openai_video_retrieve(video_id)
            except Exception:
                if not warned_transient:
                    warned_transient = True
                    await tg_send_message(tg_chat_id, "⚠️ Παροδικό σφάλμα από OpenAI. Συνεχίζω…")
                await asyncio.sleep(2)
                continue

            status = v.get("status")
            if status == "completed":
                break
            if status == "failed":
                raise RuntimeError(f"Sora failed: {v}")

            await asyncio.sleep(2)

        video_bytes = await _openai_video_download(video_id)

        name = f"sora2pro_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_url = f"{public_base_url()}/static/videos/{name}"
        set_last_result(db_user_id, "sora2pro", public_url)

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
            caption="✅ Sora 2 Pro: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        logger.exception("Error during Sora2Pro job")

        refunded = None
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Sora2Pro fail", "system", video_id)
            refunded = float(cost)
        except Exception:
            logger.exception("Error refunding credits")

        try:
            reason, tips = map_provider_error_to_gr(str(e))
            msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
            await tg_send_message(tg_chat_id, msg)
        except Exception:
            logger.exception("Error sending failure message")


@router.post("/api/sora2pro/generate")
async def sora2pro_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    mode: str = Form("text"),
    prompt: str = Form(""),
    aspect: str = Form("portrait"),
    seconds: str = Form("8"),
    quality: str = Form("standard"),
    image: Optional[UploadFile] = File(None),
    storyboard_json: str = Form("[]"),
    storyboard_ref: Optional[UploadFile] = File(None),
):
    prompt = (prompt or "").strip()
    mode = _mode_from_ui(mode)
    size = _size_from_aspect(aspect)
    secs = _seconds_from_ui(seconds)
    q = _quality_from_ui(quality)

    if not prompt:
        return JSONResponse({"ok": False, "error": "empty_prompt"}, status_code=400)

    scenes: List[Dict[str, Any]] = []
    if mode == "storyboard":
        try:
            parsed = json.loads(storyboard_json or "[]")
            scenes = parsed if isinstance(parsed, list) else []
        except Exception:
            scenes = []

    image_bytes = None
    image_name = None

    if mode == "image":
        if not image:
            return JSONResponse({"ok": False, "error": "missing_image"}, status_code=400)
        image_bytes = await image.read()
        image_name = image.filename or "image.png"

    if mode == "storyboard" and storyboard_ref:
        image_bytes = await storyboard_ref.read()
        image_name = storyboard_ref.filename or "ref.png"

    base = 18
    if secs == "4":
        base = 12
    elif secs == "12":
        base = 26
    if q == "high":
        base = int(round(base * 1.35))

    COST = base

    try:
        dbu = db_user_from_webapp(tg_init_data.strip())
        tg_chat_id = int(dbu["tg_user_id"])
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        spend_credits_by_user_id(
            db_user_id,
            COST,
            f"Sora 2 Pro ({mode},{secs}s,{q})",
            "openai",
            "sora-2-pro",
        )
    except Exception as e:
        msg = str(e)
        if "not enough" in msg.lower():
            return JSONResponse({"ok": False, "error": "not_enough_credits"}, status_code=402)
        return JSONResponse({"ok": False, "error": msg[:200]}, status_code=400)

    try:
        await tg_send_message(tg_chat_id, "🎬 Sora 2 Pro: Το βίντεο ετοιμάζεται…")
    except Exception:
        logger.exception("Failed to send preparation message")

    background_tasks.add_task(
        _run_sora2pro_job,
        tg_chat_id,
        db_user_id,
        mode,
        prompt,
        size,
        secs,
        q,
        image_bytes,
        image_name,
        scenes,
        COST,
    )

    return {"ok": True, "sent_to_telegram": True, "cost": COST, "message": "Στάλθηκε στο Telegram."}
