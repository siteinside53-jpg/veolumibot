# /app/app/web_shared.py
from .config import WEBAPP_URL

CREDITS_PACKS = {
    "CREDITS_100":  {"credits": 100,  "amount_eur": 7.00,  "title": "100 Credits",   "desc": "100 credits"},
    "CREDITS_250":  {"credits": 250,  "amount_eur": 12.00, "title": "250 Credits",  "desc": "250 credits"},
    "CREDITS_500":  {"credits": 500,  "amount_eur": 22.00, "title": "500 Credits",     "desc": "500 credits"},
    "CREDITS_1000": {"credits": 1000, "amount_eur": 40.00, "title": "1000 Credits", "desc": "1000 credits"},
}

SUBSCRIPTION_PLANS = {
    "FREE":      {"name": "Free",      "credits": 5,    "amount_eur": 0.00,  "referral_pct": 0,  "features": ["Dokimi ergaleion", "Nano Banana, Midjourney, Flux k.a."]},
    "START":     {"name": "Start",     "credits": 100,  "amount_eur": 7.00,  "referral_pct": 5,  "features": ["Prosvasi se ola ta neirosystimata", "5% apo referral programma"]},
    "MIDDLE":    {"name": "Middle",    "credits": 250,  "amount_eur": 12.00, "referral_pct": 10, "features": ["Prosvasi se ola ta neirosystimata", "10% apo referral programma"]},
    "PRO":       {"name": "Pro",       "credits": 500,  "amount_eur": 22.00, "referral_pct": 15, "features": ["Prosvasi se ola ta neirosystimata", "15% apo referral programma"]},
    "CREATOR":   {"name": "Creator",   "credits": 1000, "amount_eur": 40.00, "referral_pct": 20, "features": ["Prosvasi se ola ta neirosystimata", "20% apo referral programma"]},
    "ULTRA_PRO": {"name": "ULTRA PRO", "credits": 2000, "amount_eur": 95.00, "referral_pct": 30, "features": ["Prosvasi se ola ta ergaleia AI", "Sora 2 \u2014 aperiorista", "Veo 3.1 \u2014 aperiorista", "Veo 3 \u2014 aperiorista", "Nano Banana \u2014 aperiorista", "Flux Kontext \u2014 aperiorista", "30% kerdos sto referral programma"]},
}

def packs_list():
    return [{"sku": k, **v} for k, v in CREDITS_PACKS.items()]

def plans_list():
    return [{"sku": k, **v} for k, v in SUBSCRIPTION_PLANS.items()]

def public_base_url() -> str:
    base = (WEBAPP_URL or "").strip().rstrip("/")
    return base or "https://veolumibot-production.up.railway.app"
