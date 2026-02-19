# app/routes/jobs_router.py
import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core.telegram_auth import db_user_from_webapp
from ..db import list_jobs_by_user_id, get_job

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------
# Jobs API (generation_jobs)
# ---------------------------
# Σκοπός:
# - Να μπορεί το WebApp/Telegram UI να δείχνει "Jobs" (ουρά, ιστορικό, status)
# - Χωρίς να δένουμε κάθε εργαλείο σε δικό του endpoint polling
#
# Note: Το table generation_jobs + helpers υπάρχουν ήδη στο db.py (007_credit_holds_and_jobs.sql)


@router.post("/api/jobs/list")
async def jobs_list(request: Request):
    """Λίστα τελευταίων jobs του χρήστη (μέσω Telegram WebApp initData)."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    init_data = (payload.get("initData") or payload.get("tg_init_data") or "").strip()
    limit = payload.get("limit") or 50

    try:
        limit = int(limit)
    except Exception:
        limit = 50
    limit = max(1, min(200, limit))

    try:
        dbu = db_user_from_webapp(init_data)
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        rows = list_jobs_by_user_id(db_user_id, limit=limit)
        # rows already dicts (RealDictCursor). Make sure params are JSON serializable.
        for r in rows:
            # datetime objects -> isoformat for web
            for k in ("created_at", "updated_at"):
                if k in r and hasattr(r[k], "isoformat"):
                    r[k] = r[k].isoformat()
        return {"ok": True, "jobs": rows}
    except Exception as e:
        logger.exception("jobs_list failed")
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)


@router.get("/api/jobs/{job_id}")
async def job_get(job_id: str, initData: Optional[str] = None):
    """Παίρνει ένα job by id. Προαιρετικά περνάς initData ως query για auth."""
    init_data = (initData or "").strip()
    if not init_data:
        # Επιτρέπουμε read χωρίς initData μόνο αν θες public polling.
        # Για ασφάλεια, το κρατάμε κλειστό.
        return JSONResponse({"ok": False, "error": "auth_required"}, status_code=401)

    try:
        dbu = db_user_from_webapp(init_data)
        db_user_id = int(dbu["id"])
    except Exception:
        return JSONResponse({"ok": False, "error": "auth_failed"}, status_code=401)

    try:
        row = get_job(job_id)
        if not row:
            return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)

        # ownership check
        if int(row.get("user_id")) != db_user_id:
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

        # datetime -> isoformat
        for k in ("created_at", "updated_at"):
            if k in row and hasattr(row[k], "isoformat"):
                row[k] = row[k].isoformat()

        return {"ok": True, "job": row}
    except Exception as e:
        logger.exception("job_get failed")
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)
