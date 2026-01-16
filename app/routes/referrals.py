# app/routes/referrals.py
from fastapi import APIRouter
from ..core.telegram_auth import db_user_from_webapp
from ..db import create_referral_link, list_referrals

router = APIRouter()

@router.post("/api/ref/create")
async def ref_create(payload: dict):
    dbu = db_user_from_webapp(payload.get("initData",""))
    r = create_referral_link(dbu["id"])
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    url = f"https://t.me/veolumi_bot?start=ref_{r['code']}"
    return {"ok": True, "ref": {"code": r["code"], "url": url}}

@router.post("/api/ref/list")
async def ref_list(payload: dict):
    dbu = db_user_from_webapp(payload.get("initData",""))
    rows = list_referrals(dbu["id"])
    out = []
    for x in rows:
        out.append({
            "code": x["code"],
            "url": f"https://t.me/veolumi_bot?start=ref_{x['code']}",
            "invited": int(x["starts"] or 0),
            "purchased_eur": float(x["purchases_amount"] or 0),
        })
    return {"ok": True, "items": out, "limit": 10}
