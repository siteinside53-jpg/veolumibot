# verify_telegram_init_data, db_user_from_webapp
# app/core/telegram_auth.py
import hmac, hashlib, json
from urllib.parse import parse_qsl
from fastapi import HTTPException

from ..config import BOT_TOKEN
from ..db import ensure_user, get_user

def verify_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(401, "Missing initData (open inside Telegram)")

    data = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_received = data.pop("hash", None)
    if not hash_received:
        raise HTTPException(401, "No hash")

    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(h, hash_received):
        raise HTTPException(401, "Invalid initData signature")

    user_json = data.get("user")
    if not user_json:
        raise HTTPException(401, "No user")

    try:
        return json.loads(user_json)
    except Exception:
        raise HTTPException(401, "Bad user json")

def db_user_from_webapp(init_data: str):
    tg_user = verify_telegram_init_data(init_data)
    tg_id = int(tg_user["id"])

    ensure_user(tg_id, tg_user.get("username"), tg_user.get("first_name"))
    dbu = get_user(tg_id)
    if not dbu:
        raise HTTPException(500, "User not found after ensure_user")
    return dbu
