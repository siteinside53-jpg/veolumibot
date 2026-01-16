# app/web_shared.py
from .config import WEBAPP_URL

CREDITS_PACKS = {
    "CREDITS_100": {"credits": 100, "amount_eur": 7.00, "title": "Start", "desc": "100 credits"},
    "CREDITS_250": {"credits": 250, "amount_eur": 12.00, "title": "Middle", "desc": "250 credits"},
    "CREDITS_500": {"credits": 500, "amount_eur": 22.00, "title": "Pro", "desc": "500 credits"},
    "CREDITS_1000": {"credits": 1000, "amount_eur": 40.00, "title": "Creator", "desc": "1000 credits"},
}

def packs_list():
    return [{"sku": k, **v} for k, v in CREDITS_PACKS.items()]

def public_base_url() -> str:
    base = (WEBAPP_URL or "").strip().rstrip("/")
    if base:
        return base
    return "https://veolumibot-production.up.railway.app"
