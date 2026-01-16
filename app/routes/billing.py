# app/routes/billing.py
import hmac
import json
import hashlib

import httpx
import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..config import (
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    CRYPTOCLOUD_API_KEY,
    CRYPTOCLOUD_SHOP_ID,
    CRYPTOCLOUD_WEBHOOK_SECRET,
    WEBAPP_URL,
)
from ..db import get_conn, add_credits_by_user_id
from ._shared import db_user_from_webapp, CREDITS_PACKS

router = APIRouter()

stripe.api_key = STRIPE_SECRET_KEY

@router.post("/api/stripe/checkout")
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

@router.post("/api/stripe/webhook")
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

@router.post("/api/cryptocloud/invoice")
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

    async with httpx.AsyncClient(timeout=20) as c:
        resp = await c.post(
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

@router.post("/api/cryptocloud/webhook")
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
