# app/web.py
import hmac
import hashlib
import json
import time
from typing import Dict, Any, Optional, Tuple

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
from .db import get_conn, ensure_user, get_user

# ======================
# Init
# ======================
stripe.api_key = STRIPE_SECRET_KEY

api = FastAPI()
templates = Jinja2Templates(directory="app/web_templates")

# ======================
# Packs (edit as you want)
# ======================
CREDITS_PACKS: Dict[str, Dict[str, Any]] = {
    "CREDITS_100": {"credits": 100, "amount_eur": 7.50, "title": "Start", "desc": "100 credits"},
    "CREDITS_300": {"credits": 300, "amount_eur": 19.00, "title": "Boost", "desc": "300 credits"},
    "CREDITS_800": {"credits": 800, "amount_eur": 45.00, "title": "Pro", "desc": "800 credits"},
}


def packs_list():
    return [{"sku": k, **v} for k, v in CREDITS_PACKS.items()]


# ======================
# Root (fix: "detail not found" on Chrome)
# ======================
@api.get("/")
async def root():
    return RedirectResponse(url="/profile")


# ======================
# Telegram WebApp initData verification
# ======================
def verify_telegram_init_data(init_data: str) -> dict:
    """
    Verifies Telegram WebApp initData signature.
    Returns decoded user dict.
    """
    if not init_data:
        raise HTTPException(401, "Missing initData")

    pairs = [p.split("=", 1) for p in init_data.split("&") if "=" in p]
    data = {k: v for k, v in pairs}

    hash_received = data.pop("hash", None)
    if not hash_received:
        raise HTTPException(401, "No hash")

    data_check_string = "\n".join([f"{k}={data[k]}" for k in sorted(data.keys())])
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if h != hash_received:
        raise HTTPException(401, "Invalid initData signature")

    user_json = data.get("user")
    if not user_json:
        raise HTTPException(401, "No user")

    try:
        return json.loads(user_json)
    except Exception:
        raise HTTPException(401, "Bad user json")


def db_user_from_webapp(init_data: str):
    """
    Ensures user exists in DB based on initData.
    Returns DB user row (dict).
    """
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
    """
    Telegram WebApp provides initData via JS.
    We render the page and page JS calls /api/me to load user data.
    """
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "credits": "—",
            "packs": packs_list(),
        },
    )


# ======================
# API: load current user (credits)
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
# API: Telegram avatar helper
# ======================
# small in-memory cache: user_id -> (url, expires_at)
_AVATAR_CACHE: Dict[int, Tuple[str, float]] = {}
_AVATAR_TTL_SECONDS = 60 * 30  # 30 minutes


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

        result = data.get("result") or {}
        photos = result.get("photos") or []
        if not photos or not photos[0]:
            return None

        best = photos[0][-1]  # biggest size
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
        raise HTTPException(500, "WEBAPP_URL missing (needed for success/cancel urls)")

    dbu = db_user_from_webapp(init_data)
    pack = CREDITS_PACKS[sku]

    # Create pending order
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

    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=f"{WEBAPP_URL.rstrip('/')}/profile?success=1",
        cancel_url=f"{WEBAPP_URL.rstrip('/')}/profile?canceled=1",
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

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM orders WHERE id=%s FOR UPDATE", (order_id,))
            order = cur.fetchone()

            if not order or order["status"] == "paid":
                conn.commit()
                return JSONResponse({"ok": True})

            cur.execute("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))
            cur.execute("UPDATE users SET credits = credits + %s WHERE id=%s", (pack["credits"], order["user_id"]))
            cur.execute(
                """
                INSERT INTO credit_ledger (user_id, delta, reason, provider, provider_ref)
                VALUES (%s,%s,%s,'stripe',%s)
                """,
                (order["user_id"], pack["credits"], f"Purchase {sku}", order.get("provider_ref")),
            )
            conn.commit()

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

            sku = order["sku"]
            pack = CREDITS_PACKS.get(sku)
            if not pack:
                conn.commit()
                return JSONResponse({"ok": True})

            cur.execute("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))
            cur.execute("UPDATE users SET credits = credits + %s WHERE id=%s", (pack["credits"], order["user_id"]))
            cur.execute(
                """
                INSERT INTO credit_ledger (user_id, delta, reason, provider, provider_ref)
                VALUES (%s,%s,%s,'cryptocloud',%s)
                """,
                (order["user_id"], pack["credits"], f"Purchase {sku}", order.get("provider_ref")),
            )
            conn.commit()

    return JSONResponse({"ok": True})
