# app/routes/sora2pro.py
import os
import uuid
import json
import asyncio
import random
from typing import Optional, List, Dict, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_video
from ..core.paths import VIDEOS_DIR
from ..web_shared import public_base_url
from ..db import spend_credits_by_user_id, add_credits_by_user_id, set_last_result

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


# ----------------------------
# UI -> API mapping helpers
# ----------------------------
def _size_from_aspect(aspect: str) -> str:
    a = (aspect or "").lower().strip()
    if a in ("portrait", "9:16", "vertical"):
        return "720x1280"
    return "1280x720"


def _seconds_from_ui(seconds: str) -> str:
    """
    Sora API (σύμφωνα με το error σου) δέχεται ΜΟΝΟ: '4' | '8' | '12'
    Επιστρέφουμε STRING, όχι int.
    """
    s = str(seconds or "").strip()
    if s in ("4", "8", "12"):
        return s
    # default
    return "8"


def _quality_from_ui(q: str) -> str:
    q = (q or "standard").lower().strip()
    return "high" if q == "high" else "standard"


def _mode_from_ui(m: str) -> str:
    m = (m or "text").lower().strip()
    if m in ("image", "storyboard"):
        return m
    return "text"


def _guess_image_mime(filename: str) -> str:
    f = (filename or "").lower()
    if f.endswith(".jpg") or f.endswith(".jpeg"):
        return "image/jpeg"
    if f.endswith(".webp"):
        return "image/webp"
    return "image/png"


# ----------------------------
# HTTP retry helper
# ----------------------------
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
                sleep_s = min(20.0, base_sleep * (2 ** (attempt - 1)))
                sleep_s *= 0.7 + random.random() * 0.6  # jitter
                await asyncio.sleep(sleep_s)
                continue

            return r

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            sleep_s = min(20.0, base_sleep * (2 ** (attempt - 1)))
            sleep_s *= 0.7 + random.random() * 0.6
            await asyncio.sleep(sleep_s)

    if last_exc:
        raise RuntimeError(f"Network/transient failure after retries: {last_exc}")
    raise RuntimeError("Transient failure after retries")


# ----------------------------
# OpenAI Sora API calls
# ----------------------------
async def _openai_video_create(
    *,
    model: str,
    prompt: str,
    size: str,
    seconds: str,  # MUST be '4'/'8'/'12'
    quality: str,
    input_reference_bytes: Optional[bytes],
    input_reference_name: Optional[str],
) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")

    url = "https://api.openai.com/v1/videos"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    # multipart/form-data (ώστε να υποστηρίζει input_reference)
    data = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "seconds": str(seconds),
    }

    data_with_quality = dict(data)
    data_with_quality["quality"] = quality

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
        # First try including quality
        if files:
            r = await _request_with_retries(
                c,
                "POST",
                url,
                headers=headers,
                data=data_with_quality,
                files=files,
                max_attempts=8,
                base_sleep=1.2,
            )
        else:
            r = await _request_with_retries(
                c,
                "POST",
                url,
                headers=headers,
                json_body=data_with_quality,
                max_attempts=8,
                base_sleep=1.2,
            )

        j = r.json() if r.content else {}

        # fallback: αν δεν δέχεται quality, ξαναδοκίμασε χωρίς
        if r.status_code == 400 and isinstance(j, dict) and "quality" in data_with_quality:
            if files:
                r2 = await _request_with_retries(
                    c,
                    "POST",
                    url,
                    headers=headers,
                    data=data,
                    files=files,
                    max_attempts=8,
                    base_sleep=1.2,
                )
            else:
                r2 = await _request_with_retries(
                    c,
                    "POST",
                    url,
                    headers=headers,
                    json_body=data,
                    max_attempts=8,
                    base_sleep=1.2,
                )
            j2 = r2.json() if r2.content else {}
            if r2.status_code >= 400:
                raise RuntimeError(f"Sora create error {r2.status_code}: {j2}")
            return j2

        if r.status_code >= 400:
            raise RuntimeError(f"Sora create error {r.status_code}: {j}")

        return j


async def _openai_video_retrieve(video_id: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")

    url = f"https://api.openai.com/v1/videos/{video_id}"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    async with httpx.AsyncClient(timeout=30) as c:
        r = await _request_with_retries(c, "GET", url, headers=headers, max_attempts=10, base_sleep=1.2)
        j = r.json() if r.content else {}
        if r.status_code >= 400:
            raise RuntimeError(f"Sora retrieve error {r.status_code}: {j}")
        return j


async def _openai_video_download(video_id: str) -> bytes:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")

    url = f"https://api.openai.com/v1/videos/{video_id}/content"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
        r = await _request_with_retries(c, "GET", url, headers=headers, max_attempts=10, base_sleep=2.0)

        if r.status_code == 404:
            # Συνήθως σημαίνει expired / no longer available
            txt = r.text[:300]
            raise RuntimeError(f"Sora content not available (404): {txt}")

        if r.status_code >= 400:
            raise RuntimeError(f"Sora download error {r.status_code}: {r.text[:300]}")

        return r.content


# ----------------------------
# Storyboard -> prompt composition
# ----------------------------
def _build_storyboard_prompt(scenes: List[Dict[str, Any]], base_prompt: str) -> str:
    lines: List[str] = []
    if base_prompt:
        lines.append(base_prompt.strip())
        lines.append("")
    lines.append("Storyboard:")
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


# ----------------------------
# Background job
# ----------------------------
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
):
    warned_transient = False
    video_id: Optional[str] = None

    try:
        await tg_send_message(tg_chat_id, "🎬 Sora 2 Pro: Ξεκίνησε η παραγωγή…")

        final_prompt = prompt
        input_reference_bytes = None
        input_reference_name = None

        if mode == "image":
            input_reference_bytes = image_bytes
            input_reference_name = image_name
        elif mode == "storyboard":
            final_prompt = _build_storyboard_prompt(storyboard_scenes, prompt)
            # προαιρετικά: storyboard_ref ως input_reference έχει ήδη περαστεί (image_bytes/image_name)

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

        status = created.get("status")
        last_progress = None

        # Poll μέχρι completion
        for _ in range(240):  # ~8 λεπτά αν sleep 2s (με retries μέσα)
            try:
                v = await _openai_video_retrieve(video_id)
            except Exception as e:
                if not warned_transient:
                    warned_transient = True
                    try:
                        await tg_send_message(tg_chat_id, "⚠️ Παροδικό σφάλμα από OpenAI. Συνεχίζω…")
                    except Exception:
                        pass
                await asyncio.sleep(2)
                continue

            status = v.get("status")
            prog = v.get("progress")

            if prog is not None and prog != last_progress:
                last_progress = prog
                try:
                    await tg_send_message(tg_chat_id, f"⏳ Sora 2 Pro: {int(prog)}%")
                except Exception:
                    pass

            if status == "completed":
                break
            if status == "failed":
                raise RuntimeError(f"Sora failed: {v}")

            await asyncio.sleep(2)

        if status != "completed":
            raise RuntimeError(f"Sora timeout/not completed. status={status}")

        # Download MP4 (με retries)
        video_bytes = await _openai_video_download(video_id)

        # Save locally
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

        await tg_send_video(
            chat_id=tg_chat_id,
            video_bytes=video_bytes,
            caption="✅ Sora 2 Pro: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        # refund credits (μόνο όταν δεν παραδώσαμε mp4)
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Sora2Pro fail", "system", video_id)
        except Exception:
            pass

        try:
            await tg_send_message(
                tg_chat_id,
                f"❌ Αποτυχία Sora 2 Pro.\nΛεπτομέρεια: {str(e)[:300]}",
            )
        except Exception:
            pass


# ----------------------------
# API endpoint
# ----------------------------
@router.post("/api/sora2pro/generate")
async def sora2pro_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    mode: str = Form("text"),                  # text | image | storyboard
    prompt: str = Form(""),
    aspect: str = Form("portrait"),            # portrait | landscape
    seconds: str = Form("8"),                  # 4 | 8 | 12
    quality: str = Form("standard"),           # standard | high
    image: Optional[UploadFile] = File(None),  # image->video
    storyboard_json: str = Form("[]"),         # storyboard scenes list
    storyboard_ref: Optional[UploadFile] = File(None),  # optional reference
):
    init_data = (tg_init_data or "").strip()
    prompt = (prompt or "").strip()

    mode = _mode_from_ui(mode)
    size = _size_from_aspect(aspect)
    secs = _seconds_from_ui(seconds)
    q = _quality_from_ui(quality)

    if not prompt:
        return {"ok": False, "error": "empty_prompt"}

    # parse storyboard scenes
    scenes: List[Dict[str, Any]] = []
    if mode == "storyboard":
        try:
            scenes = json.loads(storyboard_json or "[]")
            if not isinstance(scenes, list):
                scenes = []
        except Exception:
            scenes = []

    # file bytes
    image_bytes: Optional[bytes] = None
    image_name: Optional[str] = None

    if mode == "image":
        if not image:
            return {"ok": False, "error": "missing_image"}
        image_bytes = await image.read()
        image_name = image.filename or "image.png"

    if mode == "storyboard" and storyboard_ref:
        image_bytes = await storyboard_ref.read()
        image_name = storyboard_ref.filename or "ref.png"

    # credits (ρύθμισέ το όπως θες)
    # π.χ. baseline 18 για 8s standard, scale με seconds/quality
    base = 18
    if secs == "4":
        base = 12
    elif secs == "12":
        base = 26
    if q == "high":
        base = int(round(base * 1.35))

    COST = base

    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    try:
        spend_credits_by_user_id(db_user_id, COST, f"Sora 2 Pro ({mode},{secs}s,{q})", "openai", "sora-2-pro")
    except Exception:
        return {"ok": False, "error": "not_enough_credits"}

    try:
        await tg_send_message(tg_chat_id, "🎬 Sora 2 Pro: Το βίντεο ετοιμάζεται…")
    except Exception:
        pass

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
