# app/web_shared.py
from .config import WEBAPP_URL

CREDITS_PACKS = {
    "CREDITS_100":  {"credits": 100,  "amount_eur": 7.00,  "title": "100 Credits",  "desc": "100 credits"},
    "CREDITS_250":  {"credits": 250,  "amount_eur": 12.00, "title": "250 Credits",  "desc": "250 credits"},
    "CREDITS_500":  {"credits": 500,  "amount_eur": 22.00, "title": "500 Credits",  "desc": "500 credits"},
    "CREDITS_1000": {"credits": 1000, "amount_eur": 40.00, "title": "1000 Credits", "desc": "1000 credits"},
}

SUBSCRIPTION_PLANS = {
    "FREE":       {"name": "Free",       "credits": 5,    "amount_eur": 0.00,   "referral_pct": 0,  "desc": "5 credits",
                   "features": ["Δοκιμή εργαλείων", "Nano Banana, Midjourney, Flux κ.ά."]},
    "START":      {"name": "Start",      "credits": 100,  "amount_eur": 7.00,   "referral_pct": 5,  "desc": "100 credits",
                   "features": ["Πρόσβαση σε όλα τα νευροσυστήματα", "5% στο referral πρόγραμμα"]},
    "MIDDLE":     {"name": "Middle",     "credits": 250,  "amount_eur": 12.00,  "referral_pct": 10, "desc": "250 credits",
                   "features": ["Πρόσβαση σε όλα τα νευροσυστήματα", "10% στο referral πρόγραμμα"]},
    "PRO":        {"name": "Pro",        "credits": 500,  "amount_eur": 22.00,  "referral_pct": 15, "desc": "500 credits",
                   "features": ["Πρόσβαση σε όλα τα νευροσυστήματα", "15% στο referral πρόγραμμα"]},
    "CREATOR":    {"name": "Creator",    "credits": 1000, "amount_eur": 40.00,  "referral_pct": 20, "desc": "1000 credits",
                   "features": ["Πρόσβαση σε όλα τα νευροσυστήματα", "20% στο referral πρόγραμμα"]},
    "ULTRA_PRO":  {"name": "ULTRA PRO",  "credits": 2000, "amount_eur": 95.00,  "referral_pct": 30, "desc": "2000 credits",
                   "features": ["Πρόσβαση σε όλα τα εργαλεία AI", "Gemini 3 Flash — απεριόριστα",
                                "Sora 2 — απεριόριστα", "Veo 3.1 — απεριόριστα", "Veo 3 — απεριόριστα",
                                "Nano Banana — απεριόριστα", "Flux Kontext — απεριόριστα",
                                "30% κέρδος στο referral πρόγραμμα"]},
    "UNLIMITED":  {"name": "UNLIMITED",  "credits": 3000, "amount_eur": 108.00, "referral_pct": 30, "desc": "3000 credits",
                   "features": ["Πρόσβαση σε όλα τα εργαλεία AI", "Gemini 3 Flash — απεριόριστα",
                                "Sora 2 — απεριόριστα", "Veo 3.1 — απεριόριστα", "Veo 3 — απεριόριστα",
                                "Nano Banana — απεριόριστα", "Flux Kontext — απεριόριστα",
                                "Kling V3 — απεριόριστα", "Midjourney — απεριόριστα",
                                "30% κέρδος στο referral πρόγραμμα"]},
}

def packs_list():
    return [{"sku": k, **v} for k, v in CREDITS_PACKS.items()]

def plans_list():
    return [{"sku": k, **v} for k, v in SUBSCRIPTION_PLANS.items()]

def public_base_url() -> str:
    base = (WEBAPP_URL or "").strip().rstrip("/")
    return base or "https://veolumibot-production.up.railway.app"
