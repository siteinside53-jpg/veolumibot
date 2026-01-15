# app/web.py
import os
import hmac
import hashlib
import json
import time
import base64
import uuid
import asyncio
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, List
from urllib.parse import parse_qsl

import httpx
import stripe
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI

from .config import (
    BOT_TOKEN,
    WEBAPP_URL,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    CRYPTOCLOUD_API_KEY,
    CRYPTOCLOUD_SHOP_ID,
    CRYPTOCLOUD_WEBHOOK_SECRET,
)
from .db import (
    get_conn,
    ensure_user,
    get_user,
    add_credits_by_user_id,
    spend_credits_by_user_id,
    create_referral_link,
    list_referrals,
    set_last_result,
)

# ======================
# Init
# ======================
stripe.api_key = STRIPE_SECRET_KEY

# IMPORTANT: να λέγεται app για να ταιριάζει με uvicorn app.web:app
app = FastAPI()
api = app  # alias για συμβατότητα αν κάπου έχεις uvicorn app.web:api

# ----------------------
# Paths
# ----------------------
BASE_DIR = Path(__file__).resolve().parent                 # /app/app
TEMPLATES_DIR = BASE_DIR / "web_templates"                 # /app/app/web_templates
STATIC_DIR = BASE_DIR / "static"                           # /app/app/static
IMAGES_DIR = STATIC_DIR / "images"                         # /app/app/static/images
VIDEOS_DIR = STATIC_DIR / "videos"


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ----------------------
# Static files (NO CRASH)
# ----------------------
def _ensure_dir(path: Path):
    """
    Φτιάχνει directory.
    Αν υπάρχει FILE με ίδιο όνομα, το σβήνει και το ξαναφτιάχνει ως directory.
    """
    if path.exists() and path.is_file():
        path.unlink()
    path.mkdir(parents=True, exist_ok=True)

_ensure_dir(STATIC_DIR)
_ensure_dir(IMAGES_DIR)
_ensure_dir(VIDEOS_DIR)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ----------------------
# OpenAI
# ----------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ======================
# Packs
# ======================
CREDITS_PACKS = {
    "CREDITS_100": {"credits": 100, "amount_eur": 7.00, "title": "Start", "desc": "100 credits"},
    "CREDITS_250": {"credits": 250, "amount_eur": 12.00, "title": "Middle", "desc": "250 credits"},
    "CREDITS_500": {"credits": 500, "amount_eur": 22.00, "title": "Pro", "desc": "500 credits"},
    "CREDITS_1000": {"credits": 1000, "amount_eur": 40.00, "title": "Creator", "desc": "1000 credits"},
}

def packs_list():
    return [{"sku": k, **v} for k, v in CREDITS_PACKS.items()]

TOOLS_CATALOG = {
    "video": [
        {"name": "Kling 2.6 Motion", "credits": "20–75"},
        {"name": "Kling 01", "credits": "15–25"},
        {"name": "Kling V1 Avatar", "credits": "16–32"},
        {"name": "Kling 2.6", "credits": "11–44"},
        {"name": "Kling 2.1", "credits": "5–64"},
        {"name": "Sora 2 PRO", "credits": "18–60"},
        {"name": "Veo 3.1", "credits": "12"},
        {"name": "Sora 2", "credits": "6"},
        {"name": "Veo 3", "credits": "10"},
        {"name": "Midjourney", "credits": "2–13"},
        {"name": "Runway Aleph", "credits": "22"},
        {"name": "Runway", "credits": "6"},
        {"name": "Seedance", "credits": "1–20"},
        {"name": "Kling 2.5 Turbo", "credits": "8–17"},
        {"name": "Wan 2.5", "credits": "12–30"},
        {"name": "Hailuo 02", "credits": "6–12"},
    ],
    "photo": [
        {"name": "GPT image", "credits": "2"},
        {"name": "Seedream 4.5", "credits": "1.3"},
        {"name": "Nano Banana Pro", "credits": "4"},
        {"name": "Nano Banana", "credits": "0.5"},
        {"name": "Qwen", "credits": "1"},
        {"name": "Seedream", "credits": "1–4"},
        {"name": "Midjourney", "credits": "2"},
    ],
    "audio": [
        {"name": "Suno V5", "credits": "2.4"},
        {"name": "Eleven Labs", "credits": "1–30"},
    ],
}

# ======================
# Health
# ======================
@app.get("/health")
async def health():
    return {"ok": True}

# ======================
# Root
# ======================
@app.get("/")
async def root():
    return RedirectResponse(url="/profile")

@api.get("/gpt-image", response_class=HTMLResponse)
async def gpt_image_page(request: Request):
    return templates.TemplateResponse("gpt-image.html", {"request": request})

@api.get("/nanobanana-pro", response_class=HTMLResponse)
async def nanobanana_pro_page(request: Request):
    return templates.TemplateResponse("nanobananapro.html", {"request": request})

@api.get("/veo31", response_class=HTMLResponse)
async def veo31_page(request: Request):
    return templates.TemplateResponse("veo31.html", {"request": request})

# ======================
# Tools API
# ======================
@app.get("/api/tools")
async def tools_catalog():
    return {"ok": True, "tools": TOOLS_CATALOG}

# ======================
# Telegram WebApp initData verification
# ======================
def verify_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(401, "Missing initData (open inside Telegram)")

    data = dict(parse_qsl(init_data, keep_blank_values=True))

    hash_received = data.pop("hash", None)
    if not hash_received:
        raise HTTPException(401, "No hash")

    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))

    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(h, hash_received):
        raise HTTPException(401, "Invalid initData signature")

    user_json = data.get("user")
    if not user_json:
        raise HTTPException(401, "No user")

    try:
        return json.loads(user_json)
    except Exception:
        raise HTTPException(401, "Bad user json")

def db_user_from_webapp(init_data: str):
    tg_user = verify_telegram_init_data(init_data)
    tg_id = int(tg_user["id"])

    ensure_user(tg_id, tg_user.get("username"), tg_user.get("first_name"))

    dbu = get_user(tg_id)
    if not dbu:
        raise HTTPException(500, "User not found after ensure_user")
    return dbu

def _gemini_model_name() -> str:
    # Nano Banana Pro
    return os.getenv("GEMINI_NANOBANANA_PRO_MODEL", "gemini-3-pro-image-preview").strip()

async def _run_nanobanana_pro_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    aspect_ratio: str,
    image_size: str,      # "1K" | "2K" | "4K"
    output_format: str,   # "png" | "jpg"
    images_data_urls: list[str],
    cost: float,
):
    try:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY missing")

        # build "parts": text + optional inline images
        parts = [{"text": prompt}]

        # images_data_urls are like "data:image/png;base64,...."
        for du in images_data_urls[:8]:
            if not du.startswith("data:") or "base64," not in du:
                continue
            head, b64 = du.split("base64,", 1)
            mime = head.split(";")[0].replace("data:", "").strip() or "image/png"
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime,
                        "data": b64.strip(),
                    }
                }
            )

        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size,
                },
            },
        }

        model = _gemini_model_name()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, params={"key": GEMINI_API_KEY}, json=body)
            data = r.json()
            if r.status_code >= 400:
                raise RuntimeError(f"Gemini error {r.status_code}: {data}")

        # parse image from response
        # candidates[0].content.parts[?].inline_data.data is base64
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"No candidates: {data}")

        c0 = candidates[0]
        parts_out = (((c0.get("content") or {}).get("parts")) or [])
        img_b64 = None
        img_mime = None
        for p in parts_out:
            inline = p.get("inline_data") or p.get("inlineData") or None
            if inline and inline.get("data"):
                img_b64 = inline["data"]
                img_mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                break

        if not img_b64:
            raise RuntimeError(f"No image in response: {data}")

        img_bytes = base64.b64decode(img_b64)

        ext = "png" if output_format.lower() == "png" else "jpg"
        name = f"nbpro_{uuid.uuid4().hex}.{ext}"
        (IMAGES_DIR / name).write_bytes(img_bytes)

        public_base = (WEBAPP_URL or "").strip().rstrip("/")
        if not public_base:
            public_base = "https://veolumibot-production.up.railway.app"
        public_url = f"{public_base}/static/images/{name}"

        # store last result so "repeat last" is free
        set_last_result(db_user_id, "nano_banana_pro", public_url)

        kb = {
            "inline_keyboard": [
                [{"text": "🔽 Κατέβασε", "url": public_url}],
                [{"text": "🔁 Πάρε αποτέλεσμα ξανά (δωρεάν)", "callback_data": "nbpro:repeat:last"}],
                [{"text": "← Πίσω", "callback_data": "menu:images"}],
            ]
        }

        await tg_send_photo(
            chat_id=tg_chat_id,
            img_bytes=img_bytes,
            caption="✅ Nano Banana Pro: Έτοιμο",
            reply_markup=kb,
        )

    except Exception as e:
        # refund credits
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund NanoBananaPro fail", "system", None)
        except Exception:
            pass

        try:
            await tg_send_message(
                tg_chat_id,
                f"❌ Αποτυχία Nano Banana Pro.\nΛεπτομέρεια: {str(e)[:250]}",
            )
        except Exception:
            pass

def _veo31_model_name() -> str:
    return os.getenv("GEMINI_VEO31_MODEL", "veo-3.1-generate-preview").strip()

@app.post("/api/veo31/generate")
async def veo31_generate(
    background_tasks: BackgroundTasks,
    tg_init_data: str = Form(""),
    mode: str = Form("text"),
    prompt: str = Form(""),
    aspect_ratio: str = Form("16:9"),
    duration_seconds: int = Form(8),
    resolution: str = Form("720p"),
    negative_prompt: str = Form(""),
    seed: str = Form(""),
    image: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None),# for image->video
    ref_images: List[UploadFile] = File([])                   # for ref->video (1-3)
):
    init_data = (tg_init_data or "").strip()
    prompt = (prompt or "").strip()
    mode = (mode or "text").strip()

    if not prompt:
        return {"ok": False, "error": "empty_prompt"}

    # basic validation
    if aspect_ratio not in ("16:9", "9:16"):
        aspect_ratio = "16:9"
    if duration_seconds not in (4, 6, 8):
        duration_seconds = 8
        return {"ok": False, "error": "1080p_4k_requires_8s"}

    seed_int: Optional[int] = None
    if (seed or "").strip().isdigit():
        seed_int = int(seed.strip())

    # credits mapping (βάλε ό,τι θες)
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
        spend_credits_by_user_id(
        db_user_id,
        COST,
        f"Veo 3.1 ({mode})",
        "gemini",
        _veo31_model_name(),
    )
    except Exception:
        return {"ok": False, "error": "not_enough_credits"}

    # read files (optional)
    image_bytes = await image.read() if image else None
    ref_bytes = []
    for f in (ref_images or [])[:3]:
        try:
            ref_bytes.append(await f.read())
        except Exception:
            pass

    try:
        await tg_send_message(tg_chat_id, "🎬 Veo 3.1: Το βίντεο ετοιμάζεται…")
    except Exception:
        pass

    background_tasks.add_task(
    schedule_coro,
    _run_veo31_job(
        tg_chat_id,
        db_user_id,
        mode,
        prompt,
        aspect_ratio,
        duration_seconds,
        (negative_prompt or "").strip(),
        seed_int,
        image_bytes,
        ref_bytes,
        COST,
    ),
)
    return {"ok": True, "sent_to_telegram": True, "cost": COST, "message": "Στάλθηκε στο Telegram."}

async def _run_veo31_job(
    tg_chat_id: int,
    db_user_id: int,
    mode: str,  # "text" | "image" | "ref"
    prompt: str,
    aspect_ratio: str,
    duration_seconds: int,
    negative_prompt: str,
    seed: Optional[int],
    image_bytes: Optional[bytes],          # for image->video (start frame)
    ref_images: list[bytes],               # for reference->video (1-3)
    cost: float,
):
    try:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY missing")

        await tg_send_message(tg_chat_id, "✅ Veo 3.1: Ξεκίνησε η παραγωγή (job).")

        model = _veo31_model_name()
        base_url = "https://generativelanguage.googleapis.com/v1beta"
        op_url = f"{base_url}/models/{model}:predictLongRunning"

        # ---- build instances payload (REST) ----
        instance: Dict[str, Any] = {"prompt": prompt}

        # Official docs mention aspect_ratio and also support 9:16 / 16:9.  [oai_citation:1‡Google AI for Developers](https://ai.google.dev/gemini-api/docs/video?example=dialogue)
        instance["aspect_ratio"] = aspect_ratio

        # duration/resolution are supported by Veo 3.1 variants (8s, 720p/1080p/4k).  [oai_citation:2‡Google AI for Developers](https://ai.google.dev/gemini-api/docs/video?example=dialogue)
        instance["duration_seconds"] = duration_seconds

        if negative_prompt:
            instance["negative_prompt"] = negative_prompt
        if seed is not None:
            instance["seed"] = seed

        # image->video (first frame)
        if mode == "image":
            if not image_bytes:
                raise RuntimeError("Λείπει εικόνα για Image → Video.")
            instance["image"] = {
                "bytesBase64Encoded": base64.b64encode(image_bytes).decode("utf-8"),
                "mimeType": "image/png",
            }

        # reference->video (1-3 images)
        if mode == "ref":
            if not ref_images:
                raise RuntimeError("Χρειάζονται 1–3 εικόνες για Reference → Video.")
            instance["reference_images"] = [
                {
                    "bytesBase64Encoded": base64.b64encode(b).decode("utf-8"),
                    "mimeType": "image/png",
                }
                for b in ref_images[:3]
            ]

        body = {"instances": [instance]}

        # ---- start long-running operation ----
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

        # ---- poll operation ----
        await tg_send_message(tg_chat_id, "⏳ Veo 3.1: Περιμένω το αποτέλεσμα…")

        status = None
        async with httpx.AsyncClient(timeout=60) as c:
            for _ in range(120):  # ~120 * 3s = 6 λεπτά max (ρύθμισε όπως θες)
                rs = await c.get(
                    f"{base_url}/{op_name}",
                    headers={"x-goog-api-key": GEMINI_API_KEY},
                )
                status = rs.json()
                if rs.status_code >= 400:
                    raise RuntimeError(f"Veo31 poll error {rs.status_code}: {status}")

                if status.get("done") is True:
                    break

                await asyncio.sleep(3)

        if not status or status.get("done") is not True:
            raise RuntimeError("Veo31 timeout: operation not done.")

        # ---- extract download URI (official path) ----  [oai_citation:3‡Google AI for Developers](https://ai.google.dev/gemini-api/docs/video?example=dialogue)
        video_uri = (
            (((status.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or [{}])[0]
            .get("video", {})
            .get("uri")
        )
        if not video_uri:
            raise RuntimeError(f"No video uri in response: {status}")

        # ---- download bytes ----
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            vd = await c.get(video_uri, headers={"x-goog-api-key": GEMINI_API_KEY})
            if vd.status_code >= 400:
                raise RuntimeError(f"Video download error {vd.status_code}: {vd.text[:300]}")
            video_bytes = vd.content

        # ---- store & public URL ----
        name = f"veo31_{uuid.uuid4().hex}.mp4"
        (VIDEOS_DIR / name).write_bytes(video_bytes)

        public_base = (WEBAPP_URL or "").strip().rstrip("/") or "https://veolumibot-production.up.railway.app"
        public_url = f"{public_base}/static/videos/{name}"

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

@app.post("/api/nanobanana-pro/generate")
async def nanobanana_pro_generate(request: Request, background_tasks: BackgroundTasks):
    # DEBUG: δες αν έρχεται JSON ή κάτι άλλο
    try:
        raw = await request.body()
        print(">>> NBPRO RAW BODY:", raw[:3000], flush=True)
    except Exception as e:
        print(">>> NBPRO BODY READ ERROR:", e, flush=True)

    try:
        payload = await request.json()
        print(">>> NBPRO PAYLOAD JSON:", payload, flush=True)
    except Exception as e:
        print(">>> NBPRO JSON PARSE ERROR:", e, flush=True)
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = payload.get("initData", "")
    prompt = (payload.get("prompt") or "").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "1:1").strip()
    image_size = (payload.get("image_size") or "1K").strip().upper()
    output_format = (payload.get("output_format") or "png").strip().lower()
    images_data_urls = payload.get("images_data_urls") or []

    if not prompt:
        return {"ok": False, "error": "empty_prompt"}

    if not isinstance(images_data_urls, list):
        images_data_urls = []

    if image_size not in ("1K", "2K", "4K"):
        image_size = "1K"
    if output_format not in ("png", "jpg"):
        output_format = "png"

    COST = 4

    # Θα σκάσει 401 εδώ αν initData είναι λάθος/άδειο
    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])
    db_user_id = int(dbu["id"])

    try:
        spend_credits_by_user_id(
            db_user_id, COST, "Nano Banana Pro", "gemini", _gemini_model_name()
        )
    except Exception:
        return {"ok": False, "error": "not_enough_credits"}

    try:
        await tg_send_message(tg_chat_id, "🍌 Nano Banana Pro: Η εικόνα ετοιμάζεται…")
    except Exception as e:
        print(">>> NBPRO tg_send_message failed:", e, flush=True)

    background_tasks.add_task(
    schedule_coro,
    _run_nanobanana_pro_job(
        tg_chat_id,
        db_user_id,
        prompt,
        aspect_ratio,
        image_size,
        output_format,
        images_data_urls,
        COST,
    ),

)

    return {"ok": True, "sent_to_telegram": True, "cost": COST}
# ======================
# Telegram helpers (send result in chat)
# ======================
async def tg_send_message(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json={"chat_id": chat_id, "text": text})
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {j}")

def schedule_coro(coro):
    asyncio.create_task(coro)

async def tg_send_photo(
    chat_id: int,
    img_bytes: bytes,
    caption: str = "",
    reply_markup: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {"chat_id": str(chat_id), "caption": caption}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    files = {"photo": ("photo.png", img_bytes, "image/png")}

    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(url, data=data, files=files)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendPhoto failed: {j}")
        return j["result"]

async def tg_send_video(
    chat_id: int,
    video_bytes: bytes,
    caption: str = "",
    reply_markup: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
    data = {"chat_id": str(chat_id), "caption": caption}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    files = {"video": ("video.mp4", video_bytes, "video/mp4")}

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, data=data, files=files)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendVideo failed: {j}")
        return j["result"]

async def _run_gpt_image_job(
    tg_chat_id: int,
    db_user_id: int,
    prompt: str,
    size: str,
    quality: str,
    cost: int,
):
    """
    Background job:
    - generate στο OpenAI
    - sendPhoto στο Telegram chat (όπως στο screenshot)
    - αν fail: refund + sendMessage
    """
    try:
        res = client.images.generate(
            model="gpt-image-1.5",
            prompt=prompt,
            size=size,
            quality=quality,
        )

        b64 = res.data[0].b64_json
        img = base64.b64decode(b64)

        # (προαιρετικό) αποθήκευση για debug
        name = f"{uuid.uuid4().hex}.png"
        (IMAGES_DIR / name).write_bytes(img)

        kb = {
            "inline_keyboard": [
                [{"text": "🔽 Πάρε αποτέλεσμα ξανά (δωρεάν)", "callback_data": "gptimg:repeat:last"}],
                [{"text": "← Πίσω", "callback_data": "menu:images"}],
            ]
        }

        await tg_send_photo(
            chat_id=tg_chat_id,
            img_bytes=img,
            caption="✅ Η εικόνα δημιουργήθηκε",
            reply_markup=kb,
        )

    except Exception as e:
        # refund credits
        try:
            add_credits_by_user_id(db_user_id, cost, "Refund GPT Image fail", "system", None)
        except Exception:
            pass

        # ενημέρωση στο Telegram
        try:
            await tg_send_message(
                tg_chat_id,
                f"❌ Αποτυχία δημιουργίας εικόνας.\nΛεπτομέρεια: {str(e)[:250]}",
            )
        except Exception:
            pass

# ======================
# Pages
# ======================
@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "credits": "—", "packs": packs_list()},
    )

# ======================
# API: me
# ======================
@app.post("/api/me")
async def me(payload: dict):
    init_data = payload.get("initData", "")
    dbu = db_user_from_webapp(init_data)

    return {
        "ok": True,
        "user": {
            "id": dbu["tg_user_id"],
            "username": dbu.get("tg_username") or "",
            "credits": float(dbu.get("credits", 0) or 0),
        },
        "packs": packs_list(),
    }

# ======================
# API: Telegram avatar
# ======================
_AVATAR_CACHE: Dict[int, Tuple[str, float]] = {}
_AVATAR_TTL_SECONDS = 60 * 30

async def _get_telegram_file_url(file_id: str) -> Optional[str]:
    if not file_id:
        return None
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=15) as client_http:
        r = await client_http.get(f"{base}/getFile", params={"file_id": file_id})
        data = r.json()
        if not data.get("ok"):
            return None
        file_path = (data.get("result") or {}).get("file_path")
        if not file_path:
            return None
        return f"{base}/file/{file_path}"

async def _fetch_telegram_avatar_url(tg_user_id: int) -> Optional[str]:
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=15) as client_http:
        r = await client_http.get(
            f"{base}/getUserProfilePhotos",
            params={"user_id": tg_user_id, "limit": 1},
        )
        data = r.json()
        if not data.get("ok"):
            return None
        photos = (data.get("result") or {}).get("photos") or []
        if not photos or not photos[0]:
            return None
        best = photos[0][-1]
        file_id = best.get("file_id")
        if not file_id:
            return None
        return await _get_telegram_file_url(file_id)

@app.post("/api/avatar")
async def avatar(payload: dict):
    init_data = payload.get("initData", "")
    tg_user = verify_telegram_init_data(init_data)
    tg_id = int(tg_user["id"])

    now = time.time()
    cached = _AVATAR_CACHE.get(tg_id)
    if cached and cached[1] > now:
        return {"ok": True, "url": cached[0]}

    url = await _fetch_telegram_avatar_url(tg_id)
    if not url:
        _AVATAR_CACHE[tg_id] = ("", now + 60)
        return {"ok": True, "url": ""}

    _AVATAR_CACHE[tg_id] = (url, now + _AVATAR_TTL_SECONDS)
    return {"ok": True, "url": url}

# ======================
# Stripe
# ======================
@app.post("/api/stripe/checkout")
async def stripe_checkout(payload: dict):
    init_data = payload.get("initData", "")
    sku = payload.get("sku", "")

    if sku not in CREDITS_PACKS:
        raise HTTPException(400, "Unknown sku")

    if not STRIPE_SECRET_KEY:
        raise HTTPException(500, "Stripe not configured: STRIPE_SECRET_KEY missing")
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "Stripe not configured: STRIPE_WEBHOOK_SECRET missing")
    if not WEBAPP_URL:
        raise HTTPException(500, "WEBAPP_URL missing")

    dbu = db_user_from_webapp(init_data)
    pack = CREDITS_PACKS[sku]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (user_id, kind, sku, amount_eur, currency, status, provider)
            VALUES (%s,'credits',%s,%s,'EUR','pending','stripe')
            RETURNING id
            """,
            (dbu["id"], sku, pack["amount_eur"]),
        )
        order_id = cur.fetchone()["id"]
        conn.commit()

    base = WEBAPP_URL.rstrip("/")
    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=f"{base}/profile?success=1",
        cancel_url=f"{base}/profile?canceled=1",
        line_items=[
            {
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": f'{pack["title"]} - {pack["desc"]}'},
                    "unit_amount": int(round(pack["amount_eur"] * 100)),
                },
                "quantity": 1,
            }
        ],
        metadata={"order_id": str(order_id), "sku": sku},
    )

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE orders SET provider_ref=%s WHERE id=%s", (session.id, order_id))
        conn.commit()

    return {"url": session.url}

@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "Stripe webhook secret missing")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(400, "Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        sess = event["data"]["object"]
        meta = sess.get("metadata") or {}
        order_id = int(meta.get("order_id", "0"))
        sku = meta.get("sku", "")

        pack = CREDITS_PACKS.get(sku)
        if not (order_id and pack):
            return JSONResponse({"ok": True})

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM orders WHERE id=%s FOR UPDATE", (order_id,))
            order = cur.fetchone()

            if not order or order["status"] == "paid":
                conn.commit()
                return JSONResponse({"ok": True})

            cur.execute("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))
            conn.commit()

        add_credits_by_user_id(
            order["user_id"],
            pack["credits"],
            f"Purchase {sku}",
            "stripe",
            order.get("provider_ref"),
        )

    return JSONResponse({"ok": True})

# ======================
# CryptoCloud
# ======================
@app.post("/api/cryptocloud/invoice")
async def cryptocloud_invoice(payload: dict):
    init_data = payload.get("initData", "")
    sku = payload.get("sku", "")

    if sku not in CREDITS_PACKS:
        raise HTTPException(400, "Unknown sku")

    if not CRYPTOCLOUD_API_KEY:
        raise HTTPException(500, "CryptoCloud not configured: CRYPTOCLOUD_API_KEY missing")
    if not CRYPTOCLOUD_SHOP_ID:
        raise HTTPException(500, "CryptoCloud not configured: CRYPTOCLOUD_SHOP_ID missing")

    dbu = db_user_from_webapp(init_data)
    pack = CREDITS_PACKS[sku]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (user_id, kind, sku, amount_eur, currency, status, provider)
            VALUES (%s,'credits',%s,%s,'EUR','pending','cryptocloud')
            RETURNING id
            """,
            (dbu["id"], sku, pack["amount_eur"]),
        )
        order_id = cur.fetchone()["id"]
        conn.commit()

    async with httpx.AsyncClient(timeout=20) as client_http:
        resp = await client_http.post(
            "https://api.cryptocloud.plus/v2/invoice/create",
            headers={"Authorization": f"Token {CRYPTOCLOUD_API_KEY}"},
            json={
                "shop_id": CRYPTOCLOUD_SHOP_ID,
                "amount": float(pack["amount_eur"]),
                "currency": "EUR",
                "order_id": str(order_id),
                "description": f'{pack["title"]} - {pack["desc"]}',
            },
        )
        data = resp.json()
        if not data.get("status"):
            raise HTTPException(400, f"CryptoCloud error: {data}")

    invoice_id = data["result"]["uuid"]
    pay_url = data["result"]["link"]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE orders SET provider_ref=%s WHERE id=%s", (invoice_id, order_id))
        conn.commit()

    return {"url": pay_url}

@app.post("/api/cryptocloud/webhook")
async def cryptocloud_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("Signature", "")

    if CRYPTOCLOUD_WEBHOOK_SECRET:
        calc = hmac.new(CRYPTOCLOUD_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if calc != signature:
            raise HTTPException(400, "Bad signature")

    payload = json.loads(body.decode())
    order_id = int(payload.get("order_id", "0"))
    status = payload.get("status")

    if status == "paid" and order_id:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM orders WHERE id=%s FOR UPDATE", (order_id,))
            order = cur.fetchone()

            if not order or order["status"] == "paid":
                conn.commit()
                return JSONResponse({"ok": True})

            pack = CREDITS_PACKS.get(order["sku"])
            if not pack:
                conn.commit()
                return JSONResponse({"ok": True})

            cur.execute("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))
            conn.commit()

        add_credits_by_user_id(
            order["user_id"],
            pack["credits"],
            f"Purchase {order['sku']}",
            "cryptocloud",
            order.get("provider_ref"),
        )

    return JSONResponse({"ok": True})

# ======================
# API: referrals
# ======================
@app.post("/api/ref/create")
async def ref_create(payload: dict):
    init_data = payload.get("initData", "")
    dbu = db_user_from_webapp(init_data)

    r = create_referral_link(dbu["id"])
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}

    url = f"https://t.me/veolumi_bot?start=ref_{r['code']}"
    return {"ok": True, "ref": {"code": r["code"], "url": url}}

@app.post("/api/ref/list")
async def ref_list(payload: dict):
    init_data = payload.get("initData", "")
    dbu = db_user_from_webapp(init_data)

    rows = list_referrals(dbu["id"])
    out = []
    for x in rows:
        out.append(
            {
                "code": x["code"],
                "url": f"https://t.me/veolumi_bot?start=ref_{x['code']}",
                "invited": int(x["starts"] or 0),
                "purchased_eur": float(x["purchases_amount"] or 0),
            }
        )

    return {"ok": True, "items": out, "limit": 10}



# ======================
# API: GPT Image (send result in Telegram chat)
# ======================
@app.post("/api/gpt_image/generate")
async def gpt_image_generate(payload: dict, background_tasks: BackgroundTasks):
    init_data = payload.get("initData", "")
    mode = (payload.get("mode") or "text2img").strip()  # (δεν το χρησιμοποιούμε ακόμη)
    prompt = (payload.get("prompt") or "").strip()
    ratio = payload.get("ratio", "1:1")
    quality = (payload.get("quality") or "medium").lower().strip()

    if not prompt:
        return {"ok": False, "error": "empty_prompt"}

    if client is None:
        return {"ok": False, "error": "openai_not_configured"}

    # Valid sizes για gpt-image-1.5
    size_map = {
        "1:1": "1024x1024",
        "2:3": "1024x1536",  # portrait
        "3:2": "1536x1024",  # landscape
    }
    size = size_map.get(ratio, "1024x1024")

    if quality not in ("low", "medium", "high"):
        quality = "medium"

    # Credits ανά ποιότητα
    cost_map = {"low": 1, "medium": 2, "high": 5}
    COST = cost_map[quality]

    dbu = db_user_from_webapp(init_data)
    tg_chat_id = int(dbu["tg_user_id"])  # DM chat_id (συνήθως ίδιο με user id)
    db_user_id = int(dbu["id"])          # internal DB user id

    # Χρέωση credits upfront
    try:
        spend_credits_by_user_id(
            db_user_id,
            COST,
            f"GPT Image ({quality})",
            "openai",
            "gpt-image-1.5",
        )
    except Exception:
        return {"ok": False, "error": "not_enough_credits"}

    # (προαιρετικό) ενημέρωση στο Telegram ότι ξεκίνησε
    try:
        await tg_send_message(tg_chat_id, "🧪 Η εικόνα δημιουργείται… Το αποτέλεσμα θα έρθει εδώ.")
    except Exception:
        pass

    # Background job: generate + sendPhoto στο Telegram
    background_tasks.add_task(
        _run_gpt_image_job,
        tg_chat_id,
        db_user_id,
        prompt,
        size,
        quality,
        COST,
    )

    # Άμεση απάντηση στο WebApp για να δείξει popup τύπου Telegram
    return {"ok": True, "sent_to_telegram": True, "cost": COST}
