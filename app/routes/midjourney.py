"""
Midjourney routes (FastAPI)

Σημείωση:
- Το Midjourney δεν έχει επίσημο API. Συνήθως το υλοποιείς με Discord automation (bot + /imagine).
- Εδώ δίνω ένα "καθαρό" HTTP contract για το UI σου: submit job, get status, (optional) webhook update.

Προσαρμόζεις τα TODO σημεία στο δικό σου discord worker / queue (Celery/RQ/BackgroundTasks).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, conint, constr

router = APIRouter(prefix="/api/midjourney", tags=["midjourney"])

# ======== Models ========

RatioStr = constr(pattern=r"^\d{1,2}:\d{1,2}$")  # e.g. "1:1", "9:16"

class MidjourneyGenerateRequest(BaseModel):
    prompt: constr(min_length=1, max_length=2000) = Field(..., description="Το prompt")
    ratio: RatioStr = Field("1:1", description="Αναλογία πλευρών π.χ. 1:1")
    stylize: conint(ge=0, le=1000) = 100
    chaos: conint(ge=0, le=3000) = 0
    variety: conint(ge=0, le=100) = 0

    # Optional: image-to-image (αν το UI σου το προσθέσει αργότερα)
    image_url: Optional[str] = Field(None, description="URL input εικόνας (προαιρετικό)")

class MidjourneyGenerateResponse(BaseModel):
    job_id: str
    status: str = "queued"  # queued|running|succeeded|failed
    credits_charged: float = 2.0

class MidjourneyStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: int = 0
    result_urls: list[str] = Field(default_factory=list)
    error: Optional[str] = None


# ======== In-memory demo store (αντικατάστησέ το με DB/Redis) ========

@dataclass
class _Job:
    status: str
    progress: int
    payload: Dict[str, Any]
    result_urls: list[str]
    error: Optional[str] = None

_JOBS: Dict[str, _Job] = {}


# ======== Helpers (TODO: αντικατάσταση με discord automation) ========

def _estimate_credits(_: MidjourneyGenerateRequest) -> float:
    # Αν έχεις διαφορετική χρέωση ανά ρύθμιση, άλλαξέ το εδώ.
    return 2.0

def _submit_to_worker(job_id: str, req: MidjourneyGenerateRequest) -> None:
    """
    TODO: Εδώ κάνεις enqueue σε worker που μιλάει με Discord:
      - στέλνεις /imagine prompt + params
      - παίρνεις message updates
      - στο τέλος γράφεις result URLs στο DB/Redis
    """
    # Demo: απλά μένει queued
    return


# ======== Routes ========

@router.post("/generate", response_model=MidjourneyGenerateResponse)
def generate(req: MidjourneyGenerateRequest) -> MidjourneyGenerateResponse:
    # Basic validation / safety
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Το prompt είναι κενό.")

    job_id = uuid.uuid4().hex
    credits = _estimate_credits(req)

    _JOBS[job_id] = _Job(
        status="queued",
        progress=0,
        payload=req.model_dump(),
        result_urls=[],
        error=None,
    )

    _submit_to_worker(job_id, req)

    return MidjourneyGenerateResponse(job_id=job_id, status="queued", credits_charged=credits)


@router.get("/status/{job_id}", response_model=MidjourneyStatusResponse)
def status(job_id: str) -> MidjourneyStatusResponse:
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Δεν βρέθηκε job.")
    return MidjourneyStatusResponse(
        job_id=job_id,
        status=job.status,
        progress=job.progress,
        result_urls=job.result_urls,
        error=job.error,
    )


class MidjourneyWebhookUpdate(BaseModel):
    """
    Optional endpoint για να σε ενημερώνει ο worker (ή external service/proxy)
    """
    job_id: str
    status: constr(pattern=r"^(queued|running|succeeded|failed)$")
    progress: conint(ge=0, le=100) = 0
    result_urls: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    secret: Optional[str] = None


@router.post("/webhook/update", response_model=MidjourneyStatusResponse)
def webhook_update(update: MidjourneyWebhookUpdate) -> MidjourneyStatusResponse:
    secret = os.getenv("MIDJOURNEY_WEBHOOK_SECRET")
    if secret:
        if update.secret != secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret.")

    job = _JOBS.get(update.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Δεν βρέθηκε job.")

    job.status = update.status
    job.progress = update.progress
    job.result_urls = update.result_urls
    job.error = update.error

    return MidjourneyStatusResponse(
        job_id=update.job_id,
        status=job.status,
        progress=job.progress,
        result_urls=job.result_urls,
        error=job.error,
    )

