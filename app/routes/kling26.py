import os
import time
import hmac
import base64
import hashlib
import httpx

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY")
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY")
KLING_BASE_URL = os.getenv("KLING_BASE_URL", "https://api.klingai.com")


# ---------- AUTH ----------
def kling_headers():
    ts = str(int(time.time()))
    msg = KLING_ACCESS_KEY + ts
    sign = hmac.new(
        KLING_SECRET_KEY.encode(),
        msg.encode(),
        hashlib.sha256
    ).digest()

    return {
        "Content-Type": "application/json",
        "X-Access-Key": KLING_ACCESS_KEY,
        "X-Signature": base64.b64encode(sign).decode(),
        "X-Timestamp": ts,
    }


# ---------- REQUEST MODEL ----------
class Kling26Request(BaseModel):
    generation_type: str              # "text" | "image"
    prompt: str
    negative_prompt: Optional[str] = ""
    duration: int                     # 5 ή 10
    aspect_ratio: str                 # "1:1" | "9:16" | "16:9"
    image: Optional[str] = None       # base64 or url


# ---------- CREATE TASK ----------
async def create_kling_task(data: Kling26Request):
    if data.generation_type == "text":
        url = f"{KLING_BASE_URL}/v1/videos/text2video"
    else:
        url = f"{KLING_BASE_URL}/v1/videos/image2video"

    payload = {
        "model_name": "kling-v2-6",
        "prompt": data.prompt,
        "negative_prompt": data.negative_prompt,
        "duration": data.duration,
        "aspect_ratio": data.aspect_ratio,
        "mode": "std",
    }

    if data.generation_type == "image":
        payload["image"] = data.image

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            url,
            headers=kling_headers(),
            json=payload
        )

    if r.status_code != 200:
        raise RuntimeError(f"Kling error {r.status_code}: {r.text}")

    return r.json()


# ---------- API ----------
@router.post("/api/kling26/generate")
async def kling26_generate(req: Kling26Request):
    try:
        result = await create_kling_task(req)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )
