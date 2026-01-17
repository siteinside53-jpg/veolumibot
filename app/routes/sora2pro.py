# app/routes/sora2pro.py
import os
import uuid
import json
import asyncio
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


def _size_from_aspect(aspect: str) -> str:
    # Sora API δουλεύει με "size" π.χ. 1280x720, όχι aspect_ratio.
    # Portrait = 720x1280, Landscape = 1280x720
    a = (aspect or "").lower().strip()
    if a in ("portrait", "9:16", "vertical"):
        return "720x1280"
    return "1280x720"


def _seconds_from_ui(seconds: str) -> int:
    try:
        s = int(str(seconds).strip())
    except Exception:
        s = 10
    return 15 if s == 15 else 10


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


async def _openai_video_create(
    *,
    model: str,
    prompt: str,
    size: str,
    seconds: int,
    quality: str,
    input_reference_bytes: Optional[bytes],
    input_reference_name: Optional[str],
) -> Dict[str, Any]:
    """
    Σημαντικό:
    - Χωρίς input_reference -> στέλνουμε JSON (application/json)
    - Με input_reference -> στέλνουμε multipart/form-data (files + data)
    Αυτό αποφεύγει το 400 "application/x-www-form-urlencoded".
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")

    url = "https://api.openai.com/v1/videos"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    # Base payload
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "seconds": seconds,
    }
    payload_with_quality = dict(payload)
    payload_with_quality["quality"] = quality

    has_ref = bool(input_reference_bytes)

    async with httpx.AsyncClient(timeout=60) as c:
        if not has_ref:
            # TEXT MODE -> JSON
            r = await c.post(url, headers=headers, json=payload_with_quality)
            j = r.json() if r.content else {}

            # fallback: retry χωρίς quality
            if r.status_code == 400 and isinstance(j, dict):
                r2 = await c.post(url, headers=headers, json=payload)
                j2 = r2.json() if r2.content else {}
                if r2.status_code >= 400:
                    raise RuntimeError(f"Sora create error {r2.status_code}: {j2}")
                return j2

            if r.status_code >= 400:
                raise RuntimeError(f"Sora create error {r.status_code}: {j}")

            return j

        # IMAGE/REF MODE -> multipart/form-data
        files = {
            "input_reference": (
                input_reference_name or "ref.png",
                input_reference_bytes,
                _guess_image_mime(input_reference_name or "ref.png"),
            )
        }

        # σε multipart τα πεδία είναι strings
        data = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "seconds": str(seconds),
            "quality": quality,
        }

        r = await c.post(url, headers=headers, files=files, data=data)
        j = r.json() if r.content else {}

        # fallback: retry χωρίς quality
        if r.status_code == 400 and isinstance(j, dict):
            data2 = dict(data)
            data2.pop("quality", None)
            r2 = await c.post(url, headers=headers, files=files, data=data2)
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
        r = await c.get(url, headers=headers)
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
        r = await c.get(url, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"Sora download error {r.status_code}: {r.text[:400]}")
        return r.content


def _build_storyboard_prompt(scenes: List[Dict[str, Any]], base_prompt: str) -> str:
    # Δεν υπάρχει “storyboard” field στο API snippet, οπότε το υλοποιούμε ως prompt composition.
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


async def _run_sora2pro_job(
    tg_chat_id: int,
    db_user_id: int,
    mode: str,
    prompt: str,
    size: str,
    seconds: int,
    quality: str,
    image_bytes: Optional[bytes],
    image_name: Optional[str],
    storyboard_scenes: List[Dict[str, Any]],
    cost: int,
):
    try:
        await tg_send_message(tg_chat_id, "🎬 Sora 2 Pro: Ξεκίνησε η παραγωγή…")

        final_prompt = prompt
        input_reference_bytes: Optional[bytes] = None
        input_reference_name: Optional[str] = None

        if mode == "image":
            input_reference_bytes = image_bytes
            input_reference_name = image_name
        elif mode == "storyboard":
            final_prompt = _build_storyboard_prompt(storyboard_scenes, prompt)
            # Αν υπάρχει storyboard_ref (το περνάς σαν image_bytes/image_name), τότε το χρησιμοποιούμε ως input_reference
            if image_bytes:
                input_reference_bytes = image_bytes
                input_reference_name = image_name

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

        # Poll (~8 λεπτά max με sleep 2s)
        for _ in range(240):
            v = await _openai_video_retrieve(video_id)
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

        await tg_send_video(
            chat_id=tg_chat_id,
            video_bytes=video_bytes,
            caption="✅ Sora 2 Pro: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        # refund
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund Sora2Pro fail", "system", None)
        except Exception:
            pass
        try:
            await tg_send_message(
                tg_chat_id,
                f"❌ Αποτυχία Sora 2 Pro.\nΛεπτομέρεια: {str(e)[:300]}",
            )
        except Exception:
            pass


@router.post("/api/sora2pro/generate")
async def sora2pro_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    mode: str = Form("text"),                 # text | image | storyboard
    prompt: str = Form(""),
    aspect: str = Form("portrait"),           # portrait | landscape
    seconds: str = Form("10"),                # 10 | 15
    quality: str = Form("standard"),          # standard | high
    image: Optional[UploadFile] = File(None), # image->video
    storyboard_json: str = Form("[]"),        # storyboard scenes list
    storyboard_ref: Optional[UploadFile] = File(None),  # optional reference for storyboard
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

        # validate sum duration == secs
        total = 0.0
        for s in scenes:
            try:
                total += float(s.get("seconds") or 0)
            except Exception:
                pass

        if abs(total - float(secs)) > 0.01:
            return {"ok": False, "error": "storyboard_sum_mismatch"}

    # file bytes
    image_bytes: Optional[bytes] = None
    image_name: Optional[str] = None

    if mode == "image":
        if not image:
            return {"ok": False, "error": "missing_image"}
        image_bytes = await image.read()
        image_name = image.filename or "image.png"

    if mode == "storyboard" and storyboard_ref:
        # optional: storyboard reference image (acts like input_reference)
        image_bytes = await storyboard_ref.read()
        image_name = storyboard_ref.filename or "ref.png"

    # credits
    COST = 18 if q == "standard" else 24

    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    try:
        spend_credits_by_user_id(
            db_user_id,
            COST,
            f"Sora 2 Pro ({mode},{secs}s,{q})",
            "openai",
            "sora-2-pro",
        )
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
