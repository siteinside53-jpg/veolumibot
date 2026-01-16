# app/routes/gpt_image.py
import os, base64, uuid
from fastapi import APIRouter, BackgroundTasks
from openai import OpenAI

from ..core.telegram_auth import db_user_from_webapp
from ..core.telegram_client import tg_send_message, tg_send_photo
from ..core.paths import IMAGES_DIR
from ..db import spend_credits_by_user_id, add_credits_by_user_id

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY","").strip()
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

async def _run_gpt_image_job(...): 
    # paste δικό σου

@router.post("/gpt_image/generate")  # θα μπει prefix="/api" στο include_router
async def gpt_image_generate(payload: dict, background_tasks: BackgroundTasks):
    # paste δικό σου
