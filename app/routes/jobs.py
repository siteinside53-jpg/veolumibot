# app/routes/jobs.py
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message
from ..db import (
    get_user,
    create_marketplace_job,
    list_marketplace_jobs,
    get_marketplace_job,
    get_my_marketplace_jobs,
    create_job_offer,
    list_offers_for_job,
    accept_job_offer,
    get_my_offers,
)

router = APIRouter(prefix="/api", tags=["jobs"])


# =========================================================
# Pydantic Models
# =========================================================
class JobCreateIn(BaseModel):
    initData: str
    title: str = Field(..., min_length=3, max_length=120)
    description: str = Field(..., min_length=10, max_length=2000)
    budget_eur: Optional[float] = None
    deadline_days: Optional[int] = None


class OfferCreateIn(BaseModel):
    initData: str
    message: str = Field(..., min_length=5, max_length=1000)
    price_eur: Optional[float] = None


class AcceptOfferIn(BaseModel):
    initData: str


class InitDataIn(BaseModel):
    initData: str


# =========================================================
# API: Create Job
# =========================================================
@router.post("/jobs")
async def api_create_job(payload: JobCreateIn):
    dbu = db_user_from_webapp(payload.initData)
    user_id = int(dbu["id"])

    job = create_marketplace_job(
        client_user_id=user_id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        budget_eur=payload.budget_eur,
        deadline_days=payload.deadline_days,
    )

    return {"ok": True, "job": _serialize_job(job)}


# =========================================================
# API: List Open Jobs
# =========================================================
@router.get("/jobs")
async def api_list_jobs(limit: int = 20):
    jobs = list_marketplace_jobs(status="open", limit=limit)
    return {"ok": True, "items": [_serialize_job(j) for j in jobs]}


# =========================================================
# API: Get Job Detail
# =========================================================
@router.get("/jobs/{job_id}")
async def api_get_job(job_id: str):
    job = get_marketplace_job(job_id)
    if not job:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "job": _serialize_job(job)}


# =========================================================
# API: Send Offer
# =========================================================
@router.post("/jobs/{job_id}/offer")
async def api_send_offer(job_id: str, payload: OfferCreateIn, background_tasks: BackgroundTasks):
    dbu = db_user_from_webapp(payload.initData)
    freelancer_id = int(dbu["id"])

    job = get_marketplace_job(job_id)
    if not job:
        return {"ok": False, "error": "not_found"}

    if str(job["status"]) != "open":
        return {"ok": False, "error": "job_not_open"}

    # Prevent self-offer
    if int(job["client_user_id"]) == freelancer_id:
        return {"ok": False, "error": "cannot_offer_own_job"}

    offer = create_job_offer(
        job_id=job_id,
        freelancer_user_id=freelancer_id,
        message=payload.message.strip(),
        price_eur=payload.price_eur,
    )

    # Notify job poster via Telegram
    background_tasks.add_task(
        _notify_new_offer,
        job=job,
        offer=offer,
        freelancer_name=dbu.get("tg_first_name") or dbu.get("tg_username") or "Freelancer",
    )

    return {"ok": True, "offer_id": str(offer["id"])}


# =========================================================
# API: List Offers for Job (owner only)
# =========================================================
@router.post("/jobs/{job_id}/offers")
async def api_list_offers(job_id: str, payload: InitDataIn):
    dbu = db_user_from_webapp(payload.initData)
    user_id = int(dbu["id"])

    job = get_marketplace_job(job_id)
    if not job:
        return {"ok": False, "error": "not_found"}

    if int(job["client_user_id"]) != user_id:
        return {"ok": False, "error": "not_owner"}

    offers = list_offers_for_job(job_id)
    return {"ok": True, "items": [_serialize_offer(o) for o in offers]}


# =========================================================
# API: Accept Offer (owner only)
# =========================================================
@router.post("/offers/{offer_id}/accept")
async def api_accept_offer(offer_id: str, payload: InitDataIn, background_tasks: BackgroundTasks):
    dbu = db_user_from_webapp(payload.initData)
    user_id = int(dbu["id"])

    result = accept_job_offer(offer_id)
    if not result:
        return {"ok": False, "error": "not_found"}

    # Verify ownership
    if int(result.get("client_user_id", 0)) != user_id:
        return {"ok": False, "error": "not_owner"}

    # Notify freelancer
    background_tasks.add_task(
        _notify_offer_accepted,
        result=result,
    )

    return {"ok": True}


# =========================================================
# API: My Jobs (posted by me)
# =========================================================
@router.post("/my/jobs")
async def api_my_jobs(payload: InitDataIn):
    dbu = db_user_from_webapp(payload.initData)
    user_id = int(dbu["id"])
    jobs = get_my_marketplace_jobs(user_id)
    return {"ok": True, "items": [_serialize_job(j) for j in jobs]}


# =========================================================
# API: My Offers (sent by me)
# =========================================================
@router.post("/my/offers")
async def api_my_offers(payload: InitDataIn):
    dbu = db_user_from_webapp(payload.initData)
    user_id = int(dbu["id"])
    offers = get_my_offers(user_id)
    return {"ok": True, "items": [_serialize_offer(o) for o in offers]}


# =========================================================
# Helpers
# =========================================================
def _serialize_job(j: dict) -> dict:
    return {
        "id": str(j["id"]),
        "title": j.get("title", ""),
        "description": j.get("description", ""),
        "budget_eur": float(j["budget_eur"]) if j.get("budget_eur") else None,
        "deadline_days": j.get("deadline_days"),
        "status": j.get("status", "open"),
        "client_name": j.get("tg_first_name") or j.get("tg_username") or "—",
        "offer_count": j.get("offer_count", 0),
        "created_at": str(j.get("created_at", "")),
    }


def _serialize_offer(o: dict) -> dict:
    return {
        "id": str(o["id"]),
        "job_id": str(o.get("job_id", "")),
        "message": o.get("message", ""),
        "price_eur": float(o["price_eur"]) if o.get("price_eur") else None,
        "status": o.get("status", "sent"),
        "freelancer_name": o.get("tg_first_name") or o.get("tg_username") or "—",
        "job_title": o.get("job_title", ""),
        "job_status": o.get("job_status", ""),
        "created_at": str(o.get("created_at", "")),
    }


async def _notify_new_offer(job: dict, offer: dict, freelancer_name: str):
    """Send Telegram notification to job poster about new offer."""
    try:
        client_tg_id = int(job["tg_user_id"])
        price_text = f"\n💰 Τιμή: {float(offer['price_eur']):.0f}€" if offer.get("price_eur") else ""
        text = (
            f"📩 Νέα πρόταση στην αγγελία σου!\n\n"
            f"📋 {job['title']}\n"
            f"👤 Από: {freelancer_name}\n"
            f"💬 {offer['message']}"
            f"{price_text}\n\n"
            f"Μπες στις Εργασίες για να δεις & αποδεχτείς."
        )

        kb = {
            "inline_keyboard": [
                [{"text": "✅ Αποδοχή", "callback_data": f"jobs:accept:{offer['id']}"}]
            ]
        }

        await tg_send_message(client_tg_id, text, reply_markup=kb)
    except Exception as e:
        print(f"[jobs] notify_new_offer error: {e}", flush=True)


async def _notify_offer_accepted(result: dict):
    """Send Telegram notification to freelancer when offer is accepted."""
    try:
        freelancer_tg_id = int(result["freelancer_tg_id"])
        job_title = result.get("job_title", "—")
        text = (
            f"✅ Η πρότασή σου έγινε δεκτή!\n\n"
            f"📋 Εργασία: {job_title}\n\n"
            f"Επικοινώνησε με τον πελάτη για τις λεπτομέρειες."
        )
        await tg_send_message(freelancer_tg_id, text)
    except Exception as e:
        print(f"[jobs] notify_offer_accepted error: {e}", flush=True)
