import os
import time
import hmac
import hashlib
import base64
import asyncio
import httpx
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse

router = APIRouter()

KLING_BASE_URL = os.getenv("KLING_BASE_URL", "https://api.klingai.com")
KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY")
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY")


# -------------------------------------------------------------------
# AUTH HEADERS (Kling HMAC)
# -------------------------------------------------------------------
def kling_headers():
    ts = str(int(time.time()))
    msg = KLING_ACCESS_KEY + ts
    sign = hmac.new(
        KLING_SECRET_KEY.encode(),
        msg.encode(),
        hashlib.sha256
    ).digest()
    signature = base64.b64encode(sign).decode()

    return {
        "Content-Type": "application/json",
        "X-Access-Key": KLING_ACCESS_KEY,
        "X-Signature": signature,
        "X-Timestamp": ts,
    }


# -------------------------------------------------------------------
# CREATE TASK
# -------------------------------------------------------------------
async def _kling_create_task(payload: dict, image: UploadFile | None = None):
    if image:
        url = f"{KLING_BASE_URL}/v1/videos/image2video"
        payload["image"] = base64.b64encode(await image.read()).decode()
    else:
        url = f"{KLING_BASE_URL}/v1/videos/text2video"

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            url,
            headers=kling_headers(),
            json=payload
        )

    if r.status_code != 200:
        raise RuntimeError(f"Kling error {r.status_code}: {r.text}")

    return r.json()["data"]["task_id"]


# -------------------------------------------------------------------
# QUERY TASK (polling)
# -------------------------------------------------------------------
async def _kling_poll_task(task_id: str, timeout_sec=180):
    url = f"{KLING_BASE_URL}/v1/tasks/{task_id}"
    start = time.time()

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            r = await client.get(url, headers=kling_headers())
            if r.status_code != 200:
                raise RuntimeError(f"Kling poll error {r.status_code}: {r.text}")

            data = r.json()["data"]
            status = data.get("task_status")

            if status == "success":
                return data["task_result"]["videos"][0]["url"]

            if status == "failed":
                raise RuntimeError(data.get("task_status_msg", "Kling failed"))

            if time.time() - start > timeout_sec:
                raise TimeoutError("Kling task timeout")

            await asyncio.sleep(3)


# -------------------------------------------------------------------
# API ENDPOINT
# -------------------------------------------------------------------
@router.post("/api/kling26/generate")
async def kling26_generate(
    prompt: str = Form(...),
    duration: int = Form(5),
    aspect_ratio: str = Form("1:1"),
    image: UploadFile | None = File(None)
):
    payload = {
        "model_name": "kling-v2-6",
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "mode": "std"
    }

    try:
        task_id = await _kling_create_task(payload, image)
        video_url = await _kling_poll_task(task_id)

        return JSONResponse({
            "success": True,
            "task_id": task_id,
            "video_url": video_url
        })

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )
