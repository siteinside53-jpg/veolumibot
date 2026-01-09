# app/web.py
import hmac
import hashlib
import json
import time
from typing import Dict, Any, Optional, Tuple
from urllib.parse import parse_qsl
from .db import (
  get_conn, ensure_user, get_user, add_credits_by_user_id,
  create_referral_link, list_referrals
)
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import stripe
import httpx

from .config import (
    BOT_TOKEN,
    WEBAPP_URL,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    CRYPTOCLOUD_API_KEY,
    CRYPTOCLOUD_SHOP_ID,
    CRYPTOCLOUD_WEBHOOK_SECRET,
)

# ✅ ΜΟΝΟ αυτά τα imports από db.py (όχι διπλά)

# ======================
# Init
# ======================
stripe.api_key = STRIPE_SECRET_KEY

api = FastAPI()
templates = Jinja2Templates(directory="app/web_templates")

# ======================
# Packs
# ======================
CREDITS_PACKS = {
    "CREDITS_100":  {"credits": 100,  "amount_eur": 7.00,  "title": "Start",  "desc": "100 credits"},
    "CREDITS_250":  {"credits": 250,  "amount_eur": 12.00, "title": "Middle", "desc": "250 credits"},
    "CREDITS_500":  {"credits": 500,  "amount_eur": 22.00, "title": "Pro",    "desc": "500 credits"},
    "CREDITS_1000": {"credits": 1000, "amount_eur": 40.00, "title": "Creator","desc": "1000 credits"},
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
        {"name": "GPT image 1.5", "credits": "1–5"},
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

@api.get("/api/tools")
async def tools_catalog():
    return {"ok": True, "tools": TOOLS_CATALOG}
# ======================
# Root (για Chrome)
# ======================
@api.get("/")
async def root():
    return RedirectResponse(url="/profile")

# ======================
# Telegram WebApp initData verification (CORRECT)
# ======================
def verify_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(401, "Missing initData (open inside Telegram)")

    data = dict(parse_qsl(init_data, keep_blank_values=True))

    hash_received = data.pop("hash", None)
    if not hash_received:
        raise HTTPException(401, "No hash")

    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))

    # ✅ secret_key = HMAC_SHA256(bot_token, "WebAppData")
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

# ======================
# Pages
# ======================
@api.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "credits": "—", "packs": packs_list()},
    )

# ======================
# API: me
# ======================
@api.post("/api/me")
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
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{base}/getFile", params={"file_id": file_id})
        data = r.json()
        if not data.get("ok"):
            return None
        file_path = (data.get("result") or {}).get("file_path")
        if not file_path:
            return None
        return f"{base}/file/{file_path}"

async def _fetch_telegram_avatar_url(tg_user_id: int) -> Optional[str]:
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
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

@api.post("/api/avatar")
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
@api.post("/api/stripe/checkout")
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
        line_items=[{
            "price_data": {
                "currency": "eur",
                "product_data": {"name": f'{pack["title"]} - {pack["desc"]}'},
                "unit_amount": int(round(pack["amount_eur"] * 100)),
            },
            "quantity": 1,
        }],
        metadata={"order_id": str(order_id), "sku": sku},
    )

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE orders SET provider_ref=%s WHERE id=%s", (session.id, order_id))
        conn.commit()

    return {"url": session.url}

@api.post("/api/stripe/webhook")
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

        # ✅ Παίρνουμε order + κάνουμε paid μέσα σε transaction
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM orders WHERE id=%s FOR UPDATE", (order_id,))
            order = cur.fetchone()

            if not order or order["status"] == "paid":
                conn.commit()
                return JSONResponse({"ok": True})

            cur.execute("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))
            conn.commit()

        # ✅ ΕΔΩ ΓΙΝΕΤΑΙ το credit update + ledger entry (atomic μέσα στο db.py)
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
@api.post("/api/cryptocloud/invoice")
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

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
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

@api.post("/api/cryptocloud/webhook")
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

        # ✅ ΕΔΩ ΓΙΝΕΤΑΙ το credit update + ledger entry
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
@api.post("/api/ref/create")
async def ref_create(payload: dict):
    init_data = payload.get("initData", "")
    dbu = db_user_from_webapp(init_data)

    r = create_referral_link(dbu["id"])
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}

    # το link του bot σου (άλλαξε το VeoSeeBot σε δικό σου username bot)
    url = f"https://t.me/veolumi_bot?start=ref_{r['code']}"
    return {"ok": True, "ref": {"code": r["code"], "url": url}}

@api.post("/api/ref/list")
async def ref_list(payload: dict):
    init_data = payload.get("initData", "")
    dbu = db_user_from_webapp(init_data)

    rows = list_referrals(dbu["id"])
    # map για UI
    out = []
    for x in rows:
        out.append({
            "code": x["code"],
            "url": f"https://t.me/veolumi_bot?start=ref_{x['code']}",
            "invited": int(x["starts"] or 0),
            "purchased_eur": float(x["purchases_amount"] or 0),
        })

    return {"ok": True, "items": out, "limit": 10}
