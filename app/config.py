# app/config.py
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

CRYPTOCLOUD_API_KEY = os.getenv("CRYPTOCLOUD_API_KEY", "")
CRYPTOCLOUD_SHOP_ID = os.getenv("CRYPTOCLOUD_SHOP_ID", "")
CRYPTOCLOUD_WEBHOOK_SECRET = os.getenv("CRYPTOCLOUD_WEBHOOK_SECRET", "")

# --- AI Provider Keys ---
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "")
SEEDANCE_API_KEY = os.getenv("SEEDANCE_API_KEY", "")
HAILUO_API_KEY = os.getenv("HAILUO_API_KEY", "")
TOPAZ_API_KEY = os.getenv("TOPAZ_API_KEY", "")
SEEDREAM_API_KEY = os.getenv("SEEDREAM_API_KEY", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
SUNO_API_KEY = os.getenv("SUNO_API_KEY", "")
