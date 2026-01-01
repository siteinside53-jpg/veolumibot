import os

def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Λείπει το {name} (Railway Variables)")
    return v

BOT_TOKEN = must_env("BOT_TOKEN")
DATABASE_URL = must_env("DATABASE_URL")

# Προαιρετικά:
# Αν θες webhook (συνιστάται), βάλε WEBHOOK_BASE_URL π.χ. https://your-app.up.railway.app
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").strip()

# Railway δίνει PORT
PORT = int(os.getenv("PORT", "8080"))
