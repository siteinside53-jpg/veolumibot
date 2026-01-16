# app/routes/tools.py
from fastapi import APIRouter

router = APIRouter()

TOOLS_CATALOG = {
    "video": [
        {"name": "Kling 2.6 Motion", "credits": "20–75"},
        {"name": "Kling 01", "credits": "15–25"},
        {"name": "Kling V1 Avatar", "credits": "16–32"},
        {"name": "Kling 2.6", "credits": "11–44"},
        {"name": "Kling 2.1", "credits": "5–64"},
        {"name": "Sora 2 PRO", "credits": "18–60"},
        {"name": "Veo 3.1", "credits": "12"},
        {"name": "Sora 2", "credits": "6"},
        {"name": "Veo 3", "credits": "10"},
        {"name": "Midjourney", "credits": "2–13"},
        {"name": "Runway Aleph", "credits": "22"},
        {"name": "Runway", "credits": "6"},
        {"name": "Seedance", "credits": "1–20"},
        {"name": "Kling 2.5 Turbo", "credits": "8–17"},
        {"name": "Wan 2.5", "credits": "12–30"},
        {"name": "Hailuo 02", "credits": "6–12"},
    ],
    "photo": [
        {"name": "GPT image", "credits": "2"},
        {"name": "Seedream 4.5", "credits": "1.3"},
        {"name": "Nano Banana Pro", "credits": "4"},
        {"name": "Nano Banana", "credits": "0.5"},
        {"name": "Qwen", "credits": "1"},
        {"name": "Seedream", "credits": "1–4"},
        {"name": "Midjourney", "credits": "2"},
    ],
    "audio": [
        {"name": "Suno V5", "credits": "2.4"},
        {"name": "Eleven Labs", "credits": "1–30"},
    ],
}

@router.get("/api/tools")
async def tools_catalog():
    return {"ok": True, "tools": TOOLS_CATALOG}
