import os

def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Λείπει το {name} (Railway Variables)")
    return v

BOT_TOKEN = must_env("BOT_TOKEN")
DATABASE_URL = must_env("DATABASE_URL")

# Βάλε το public url του Railway service σου:
# π.χ. https://web-production-82e83.up.railway.app
PUBLIC_BASE_URL = must_env("PUBLIC_BASE_URL")

PORT = int(os.getenv("PORT", "8080"))
