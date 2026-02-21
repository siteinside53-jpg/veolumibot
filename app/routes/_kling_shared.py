# app/routes/_kling_shared.py
"""Shared Kling API helpers: JWT auth, create task, poll task."""
import os
import time
import json
import base64
import hmac
import hashlib
import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY", "").strip()
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY", "").strip()
KLING_BASE_URL = os.getenv("KLING_BASE_URL", "https://api.klingai.com").strip()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _jwt_hs256(payload: Dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def kling_headers() -> Dict[str, str]:
    if not KLING_ACCESS_KEY or not KLING_SECRET_KEY:
        raise RuntimeError("Missing KLING_ACCESS_KEY / KLING_SECRET_KEY (Railway env)")
    now = int(time.time())
    token = _jwt_hs256(
        payload={"iss": KLING_ACCESS_KEY, "iat": now, "nbf": now - 5, "exp": now + 30 * 60},
        secret=KLING_SECRET_KEY,
    )
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def _safe_json(r: httpx.Response) -> Dict[str, Any]:
    try:
        return r.json()
    except Exception:
        return {"raw": (r.text or "")[:4000]}


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


async def create_kling_video_task(payload: dict, endpoint: str = "/v1/videos/text2video") -> str:
    url = _join(KLING_BASE_URL, endpoint)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, json=payload, headers=kling_headers())
        data = await _safe_json(r)
    if r.status_code != 200 or data.get("code") != 0:
        raise RuntimeError(f"Kling create error: {data}")
    task_id = (data.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"Kling create error: missing task_id: {data}")
    return task_id


async def poll_kling_video_task(task_id: str, endpoint: str = "/v1/videos/text2video") -> str:
    url = _join(KLING_BASE_URL, f"{endpoint}/{task_id}")
    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(80):
            r = await client.get(url, headers=kling_headers())
            data = await _safe_json(r)
            if r.status_code != 200 or data.get("code") != 0:
                raise RuntimeError(f"Kling query error: {data}")
            item = data.get("data") or {}
            status = item.get("task_status")
            if status == "succeed":
                videos = (item.get("task_result") or {}).get("videos") or []
                if videos and videos[0].get("url"):
                    return videos[0]["url"]
                raise RuntimeError(f"Kling success but no video url: {item}")
            if status == "failed":
                raise RuntimeError(f"Kling task failed: {item.get('task_status_msg')}")
            await asyncio.sleep(5)
    raise RuntimeError("Kling task timeout")
