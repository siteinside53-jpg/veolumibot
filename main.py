from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from urllib.parse import parse_qsl

from aiohttp import web

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, DATABASE_URL, PUBLIC_BASE_URL
PORT = int(os.environ.get("PORT", "8080"))
import db as dbmod


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ai-marketplace-bot")


BTN_VIDEO = "🎬 Δημιουργία βίντεο"
BTN_IMAGES = "🖼 Εικόνες"
BTN_AUDIO = "🎵 Audio"
BTN_PROMPTS = "💡 TG κανάλι με prompts"
BTN_SUPPORT = "☁️ Υποστήριξη"

CB_VIDEO = "video"
CB_IMAGES = "images"
CB_AUDIO = "audio"
CB_PROMPTS = "prompts"
CB_SUPPORT = "support"
CB_BACK = "back"

WAITING_FOR_PROMPT = "waiting_for_prompt"  # None|"video"|"image"|"audio"

WEBAPP_URL = f"{PUBLIC_BASE_URL.rstrip('/')}/app"


# ----------------------
# Telegram initData verify (Mini App)
# ----------------------
def verify_telegram_init_data(init_data: str, bot_token: str) -> dict:
    """
    Returns parsed data dict if valid, raises ValueError if invalid.
    Based on Telegram WebApp validation.
    """
    if not init_data:
        raise ValueError("Empty initData")

    data = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("Missing hash")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Invalid hash")

    return data


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Το προφίλ μου", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(BTN_VIDEO, callback_data=CB_VIDEO)],
        [InlineKeyboardButton(BTN_IMAGES, callback_data=CB_IMAGES)],
        [InlineKeyboardButton(BTN_AUDIO, callback_data=CB_AUDIO)],
        [InlineKeyboardButton(BTN_PROMPTS, callback_data=CB_PROMPTS)],
        [InlineKeyboardButton(BTN_SUPPORT, callback_data=CB_SUPPORT)],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Πίσω στο Μενού", callback_data=CB_BACK)]])

async def ensure_user(update: Update) -> None:
    if not update.effective_user:
        return
    u = update.effective_user
    dbmod.upsert_user(DATABASE_URL, u.id, u.username, u.first_name)
    dbmod.ensure_referral_code(DATABASE_URL, u.id)


# ----------------------
# Telegram Handlers
# ----------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    context.user_data[WAITING_FOR_PROMPT] = None

    text = (
        "Καλώς ήρθες!\n\n"
        "Το bot μας είναι ένα AI Marketplace με κορυφαία εργαλεία σε ένα μέρος ✅\n\n"
        "• Βίντεο (Veo / Kling / Runway)\n"
        "• Εικόνες (Nano Banana / Flux / Midjourney)\n"
        "• Audio (TTS / SFX / μουσική)\n\n"
        "💳 Πληρωμές: κάρτα / crypto / PayPal (όπως στο demo)\n"
        "⚡ Ξεκινάς με δωρεάν credits."
    )

    await update.message.reply_text(text, reply_markup=main_menu_kb())


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    q = update.callback_query
    await q.answer()

    data = q.data

    if data == CB_BACK:
        context.user_data[WAITING_FOR_PROMPT] = None
        await q.edit_message_text("Μενού:", reply_markup=main_menu_kb())
        return

    if data == CB_VIDEO:
        context.user_data[WAITING_FOR_PROMPT] = "video"
        await q.edit_message_text(
            "🎬 **Δημιουργία Βίντεο**\n\nΣτείλε μου το prompt.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return

    if data == CB_IMAGES:
        context.user_data[WAITING_FOR_PROMPT] = "image"
        await q.edit_message_text(
            "🖼 **Εικόνες**\n\nΣτείλε μου το prompt για εικόνα.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return

    if data == CB_AUDIO:
        context.user_data[WAITING_FOR_PROMPT] = "audio"
        await q.edit_message_text(
            "🎵 **Audio**\n\nΣτείλε μου prompt για voiceover / SFX / μουσική.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return

    if data == CB_PROMPTS:
        context.user_data[WAITING_FOR_PROMPT] = None
        await q.edit_message_text(
            "💡 **TG κανάλι με prompts**\n\nΒάλε εδώ το κανάλι σου π.χ. @YourPromptsChannel",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return

    if data == CB_SUPPORT:
        context.user_data[WAITING_FOR_PROMPT] = None
        await q.edit_message_text(
            "☁️ **Υποστήριξη**\n\nΣτείλε στο @YourSupportUsername",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    tg_id = update.effective_user.id
    text = (update.message.text or "").strip()

    mode = context.user_data.get(WAITING_FOR_PROMPT)
    if not mode:
        await update.message.reply_text("Διάλεξε από το μενού 👇", reply_markup=main_menu_kb())
        return

    user = dbmod.get_user(DATABASE_URL, tg_id)
    if not user or user.credits <= 0:
        context.user_data[WAITING_FOR_PROMPT] = None
        await update.message.reply_text("❌ Δεν έχεις credits.", reply_markup=main_menu_kb())
        return

    dbmod.add_credits(DATABASE_URL, tg_id, delta=-1, reason=f"create_{mode}")
    job_id = dbmod.create_job(DATABASE_URL, tg_id, job_type=mode, prompt=text, provider=None)

    context.user_data[WAITING_FOR_PROMPT] = None
    await update.message.reply_text(
        f"✅ Έτοιμο!\n• Τύπος: {mode}\n• Job ID: #{job_id}\n• Χρεώθηκε: 1 credit",
        reply_markup=main_menu_kb(),
    )


async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Όταν πατάει "Αγορά" μέσα στο Mini App, το tg.sendData(...) έρχεται εδώ.
    """
    await ensure_user(update)
    msg = update.effective_message
    data = msg.web_app_data.data if msg and msg.web_app_data else ""
    tg_id = update.effective_user.id

    try:
        payload = json.loads(data)
    except Exception:
        await msg.reply_text("❌ Μη έγκυρα δεδομένα από το Mini App.", reply_markup=main_menu_kb())
        return

    if payload.get("action") == "buy_plan":
        plan = payload.get("plan", "FREE")

        # Demo flow: δεν χρεώνουμε κάρτα ακόμα. Απλά δείχνουμε τι θα γινόταν.
        await msg.reply_text(
            "🟣 Αίτημα αγοράς (demo)\n\n"
            f"Πακέτο: {plan}\n"
            "Στο επόμενο βήμα κουμπώνουμε πληρωμές (Stripe/PayPal/crypto) και αυτό θα φορτώνει credits αυτόματα.",
            reply_markup=main_menu_kb(),
        )
        return

    await msg.reply_text("ℹ️ Έλαβα εντολή από το Mini App.", reply_markup=main_menu_kb())


def build_bot_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(on_menu_click))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


# ----------------------
# AIOHTTP Web Server (serves /app + /api/me)
# ----------------------
async def handle_app(request: web.Request) -> web.Response:
    here = os.path.dirname(__file__)
    path = os.path.join(here, "webapp", "index.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    return web.Response(text=html, content_type="text/html; charset=utf-8")


async def handle_api_me(request: web.Request) -> web.Response:
    body = await request.json()
    init_data = (body.get("initData") or "").strip()

    try:
        data = verify_telegram_init_data(init_data, BOT_TOKEN)
        user_json = data.get("user")
        if not user_json:
            raise ValueError("Missing user")
        user_obj = json.loads(user_json)
        tg_id = int(user_obj["id"])
    except Exception:
        return web.json_response({"error": "unauthorized"}, status=401)

    # ensure exists in DB
    dbmod.upsert_user(DATABASE_URL, tg_id, user_obj.get("username"), user_obj.get("first_name"))
    code = dbmod.ensure_referral_code(DATABASE_URL, tg_id)
    u = dbmod.get_user(DATABASE_URL, tg_id)

    name = user_obj.get("first_name") or user_obj.get("username") or "—"
    photo_url = user_obj.get("photo_url")  # Telegram often provides it in initData user object

    referral_link = f"{PUBLIC_BASE_URL.rstrip('/')}/r/{code}"  # απλό referral link demo

    return web.json_response({
        "tg_id": tg_id,
        "name": name,
        "photo_url": photo_url,
        "credits": u.credits if u else 0,
        "plan": u.plan if u else "Free",
        "referral_link": referral_link,
    })


async def handle_ref_redirect(request: web.Request) -> web.Response:
    # demo: απλά redirect στο bot start with parameter
    code = request.match_info.get("code", "")
    bot_username = (await request.app["bot_app"].bot.get_me()).username
    url = f"https://t.me/{bot_username}?start=ref_{code}"
    raise web.HTTPFound(url)


async def start_everything():
    # init db
    dbmod.init_db(DATABASE_URL)
    log.info("DB initialized.")

    # start bot (polling) in background
    bot_app = build_bot_app()
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)
    log.info("Bot polling started.")
    # aiohttp server
    webapp = web.Application()
    webapp["bot_app"] = bot_app
    webapp.add_routes([
        web.get("/app", handle_app),
        web.post("/api/me", handle_api_me),
        web.get("/r/{code}", handle_ref_redirect),
        web.get("/", lambda r: web.Response(text="OK")),
    ])

    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Web server started on port %s", PORT)

    # keep running
    while True:
        await asyncio.sleep(3600)


def run():
    asyncio.run(start_everything())


if __name__ == "__main__":
    run()
