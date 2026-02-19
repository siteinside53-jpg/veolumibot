# app/routes/jobs.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

# Lazy import to avoid circulars
def _db():
    from .. import db as _dbmod
    return _dbmod


# =========================================================
# FastAPI Router (THIS is what web.py expects to import)
# =========================================================
router = APIRouter(prefix="", tags=["jobs"])


# =========================================================
# Pydantic Models
# =========================================================
class JobCreateIn(BaseModel):
    title: str = Field(..., min_length=3, max_length=120)
    description: str = Field(..., min_length=10, max_length=2000)
    budget: Optional[int] = Field(default=None, ge=1, le=1_000_000)

class JobOut(BaseModel):
    id: int
    title: str
    description: str
    budget: Optional[int] = None
    status: str

class JobListOut(BaseModel):
    items: List[JobOut]

class AcceptOut(BaseModel):
    ok: bool
    message: str

class FreelancerStatusOut(BaseModel):
    is_freelancer: bool


# =========================================================
# Helpers
# =========================================================
def _get_user_from_request(request: Request) -> Dict[str, Any]:
    """
    You likely already have telegram_auth/web_shared helpers.
    For now, we try common patterns:
    - request.state.user (set by middleware)
    - request.state.db_user
    - request.headers: X-TG-USER-ID / X-USER-ID
    Adapt if needed.
    """
    u = getattr(request.state, "user", None) or getattr(request.state, "db_user", None)
    if isinstance(u, dict) and "id" in u:
        return u

    # Fallback via headers (if you pass them from WebApp)
    tg = request.headers.get("X-TG-USER-ID")
    if tg:
        # expects db.get_or_create_user_by_tg(tg_user_id, username)
        return _db().get_or_create_user_by_tg(int(tg), username=None)

    uid = request.headers.get("X-USER-ID")
    if uid:
        return {"id": int(uid)}

    raise HTTPException(status_code=401, detail="Unauthorized (no user in request)")


def _ensure_job_exists(job_id: int) -> Dict[str, Any]:
    job = _db().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# =========================================================
# API: Jobs
# =========================================================
@router.post("/jobs", response_model=JobOut)
def create_job(request: Request, payload: JobCreateIn):
    user = _get_user_from_request(request)
    user_id = int(user["id"])

    job_id = _db().create_job(
        user_id=user_id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        budget=payload.budget,
    )
    job = _db().get_job(job_id)
    if not job:
        raise HTTPException(status_code=500, detail="Job created but not retrievable")

    return JobOut(
        id=int(job["id"]),
        title=str(job.get("title") or ""),
        description=str(job.get("description") or ""),
        budget=job.get("budget"),
        status=str(job.get("status") or "open"),
    )


@router.get("/jobs", response_model=JobListOut)
def list_jobs(limit: int = 20):
    items = _db().list_open_jobs(limit=limit) or []
    out: List[JobOut] = []
    for j in items:
        out.append(
            JobOut(
                id=int(j["id"]),
                title=str(j.get("title") or ""),
                description=str(j.get("description") or ""),
                budget=j.get("budget"),
                status=str(j.get("status") or "open"),
            )
        )
    return JobListOut(items=out)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int):
    job = _ensure_job_exists(job_id)
    return JobOut(
        id=int(job["id"]),
        title=str(job.get("title") or ""),
        description=str(job.get("description") or ""),
        budget=job.get("budget"),
        status=str(job.get("status") or "open"),
    )


@router.post("/jobs/{job_id}/accept", response_model=AcceptOut)
def accept_job(request: Request, job_id: int):
    user = _get_user_from_request(request)
    user_id = int(user["id"])

    # Paywall: must be freelancer
    if not _db().user_is_freelancer(user_id):
        raise HTTPException(
            status_code=402,
            detail="Freelancer package required",
        )

    job = _ensure_job_exists(job_id)
    if str(job.get("status") or "open") != "open":
        raise HTTPException(status_code=409, detail="Job not available")

    # Assign
    _db().set_job_assigned(job_id, freelancer_user_id=user_id)

    return AcceptOut(ok=True, message="Job accepted")


# =========================================================
# API: Freelancer package (profile integration)
# =========================================================
@router.get("/me/freelancer", response_model=FreelancerStatusOut)
def freelancer_status(request: Request):
    user = _get_user_from_request(request)
    user_id = int(user["id"])
    return FreelancerStatusOut(is_freelancer=bool(_db().user_is_freelancer(user_id)))


@router.post("/me/freelancer/activate", response_model=FreelancerStatusOut)
def freelancer_activate(request: Request):
    """
    Temporary/manual endpoint:
    Later you will call this from payment webhook confirmation.
    """
    user = _get_user_from_request(request)
    user_id = int(user["id"])
    _db().set_user_is_freelancer(user_id, True)
    return FreelancerStatusOut(is_freelancer=True)


# =========================================================
# OPTIONAL: Telegram-side helpers (if you want to keep them here)
# =========================================================

# If you prefer, you can keep Telegram handlers in a separate module (recommended),
# but leaving them here doesn't hurt as long as imports are OK.

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes


def tg_kb_jobs_hub() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔎 Ζητάω βοήθεια (πελάτης)", callback_data="jobs:client")],
            [InlineKeyboardButton("🧑‍💻 Είμαι freelancer", callback_data="jobs:freelancer")],
            [InlineKeyboardButton("📤 Ανάρτηση εργασίας", callback_data="jobs:post")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )


async def tg_jobs_show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()
    await q.edit_message_text(
        "💼 <b>Jobs Hub</b>\n\nΕπίλεξε τι θέλεις να κάνεις:",
        reply_markup=tg_kb_jobs_hub(),
        parse_mode="HTML",
    )
