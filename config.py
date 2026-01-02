import os
from typing import Optional


def must_env(name: str) -> str:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        raise RuntimeError(f"Λείπει το {name} (Railway Variables)")
    return v.strip()


BOT_TOKEN = must_env("BOT_TOKEN")
DATABASE_URL = must_env("DATABASE_URL")

# Βάλε το public url του Railway service σου:
# π.χ. https://web-production-82e83.up.railway.app
PUBLIC_BASE_URL = must_env("PUBLIC_BASE_URL")


def get_port(default: int = 8080) -> int:
    v = os.getenv("PORT")
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except ValueError:
        raise RuntimeError(f"Άκυρη τιμή για PORT: {v!r}")


PORT = get_port()
