import os, hmac, hashlib, json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import stripe
import httpx

from .config import BOT_TOKEN, WEBAPP_URL, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, CRYPTOCLOUD_API_KEY, CRYPTOCLOUD_SHOP_ID, CRYPTOCLOUD_WEBHOOK_SECRET
from .db import get_conn, ensure_user, get_user

stripe.api_key = STRIPE_SECRET_KEY

api = FastAPI()
templates = Jinja2Templates(directory="app/web_templates")

# Παράδειγμα “όπως αυτοί” (τα αλλάζεις μετά)
CREDITS_PACKS = {
    "CREDITS_100": {"credits": 100, "amount_eur": 7.50, "title": "Start", "desc": "100 credits"},
    "CREDITS_300": {"credits": 300, "amount_eur": 19.00, "title": "Boost", "desc": "300 credits"},
    "CREDITS_800": {"credits": 800, "amount_eur": 45.00, "title": "Pro Credits", "desc": "800 credits"},
}

def verify_telegram_init_data(init_data: str) -> dict:
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
    return json.loads(user_json)

def db_user_from_webapp(init_data: str):
    tg_user = verify_telegram_init_data(init_data)
    tg_id = int(tg_user["id"])
    ensure_user(tg_id, tg_user.get("username"), tg_user.get("first_name"))
    return get_user(tg_id)

@api.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    init_data = request.query_params.get("initData", "")
    dbu = db_user_from_webapp(init_data)
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "credits": f'{dbu["credits"]:.2f}', "packs": [{"sku": k, **v} for k, v in CREDITS_PACKS.items()]},
    )

@api.post("/api/stripe/checkout")
async def stripe_checkout(payload: dict):
    init_data = payload.get("initData", "")
    sku = payload.get("sku", "")
    if sku not in CREDITS_PACKS:
        raise HTTPException(400, "Unknown sku")
    if not (STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET):
        raise HTTPException(500, "Stripe not configured")

    dbu = db_user_from_webapp(init_data)
    pack = CREDITS_PACKS[sku]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO orders (user_id, kind, sku, amount_eur, currency, status, provider)
               VALUES (%s,'credits',%s,%s,'EUR','pending','stripe')
               RETURNING id""",
            (dbu["id"], sku, pack["amount_eur"])
        )
        order_id = cur.fetchone()["id"]
        conn.commit()

    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=f"{WEBAPP_URL}/profile?success=1",
        cancel_url=f"{WEBAPP_URL}/profile?canceled=1",
        line_items=[{
            "price_data": {
                "currency": "eur",
                "product_data": {"name": f'{pack["title"]} - {pack["desc"]}'},
                "unit_amount": int(pack["amount_eur"] * 100),
            },
            "quantity": 1,
        }],
        metadata={"order_id": str(order_id), "sku": sku}
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
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(400, "Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        sess = event["data"]["object"]
        order_id = int(sess["metadata"]["order_id"])
        sku = sess["metadata"]["sku"]
        pack = CREDITS_PACKS.get(sku)
        if not pack:
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
                """INSERT INTO credit_ledger (user_id, delta, reason, provider, provider_ref)
                   VALUES (%s,%s,%s,'stripe',%s)""",
                (order["user_id"], pack["credits"], f"Purchase {sku}", order["provider_ref"])
            )
            conn.commit()

    return JSONResponse({"ok": True})

@api.post("/api/cryptocloud/invoice")
async def cryptocloud_invoice(payload: dict):
    init_data = payload.get("initData", "")
    sku = payload.get("sku", "")
    if sku not in CREDITS_PACKS:
        raise HTTPException(400, "Unknown sku")
    if not (CRYPTOCLOUD_API_KEY and CRYPTOCLOUD_SHOP_ID):
        raise HTTPException(500, "CryptoCloud not configured")

    dbu = db_user_from_webapp(init_data)
    pack = CREDITS_PACKS[sku]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO orders (user_id, kind, sku, amount_eur, currency, status, provider)
               VALUES (%s,'credits',%s,%s,'EUR','pending','cryptocloud')
               RETURNING id""",
            (dbu["id"], sku, pack["amount_eur"])
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
            }
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
                """INSERT INTO credit_ledger (user_id, delta, reason, provider, provider_ref)
                   VALUES (%s,%s,%s,'cryptocloud',%s)""",
                (order["user_id"], pack["credits"], f"Purchase {sku}", order["provider_ref"])
            )
            conn.commit()

    return JSONResponse({"ok": True})
