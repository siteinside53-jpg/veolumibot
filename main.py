# main.py — Telegram AI Marketplace + Mini App (AIOHTTP) on the SAME Railway service
# ✅ Railway-ready: always binds to 0.0.0.0:$PORT
# ✅ /health returns {"ok": true}
# ✅ /app serves webapp/index.html
# ✅ /api/me returns profile info (validated via Telegram initData)
# ✅ Bot runs in background (polling)

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
import db as dbmod


# ======================
# LOGGING
# ======================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ai-marketplace-bot")


# ======================
# RAILWAY PORT + URLs
# ======================
PORT = int(os.environ.get("PORT", "8080"))
BASE_URL = PUBLIC_BASE_URL.rstrip("/")
WEBAPP_URL = f"{BASE_URL}/app"


# ======================
# UI
# ======================
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


# ======================
# Telegram WebApp initData verify
# ======================
def verify_telegram_init_data(init_data: str, bot_token: str) -> dict:
    """
    Validates Telegram WebApp initData.
    Returns parsed data dict if valid, raises ValueError otherwise.
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


# ======================
# Telegram UI Keyboards
# ======================
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


# ======================
# DB helpers
# ======================
async def ensure_user(update: Update) -> None:
    if not update.effective_user:
        return
    u = update.effective_user
    # DB can fail; do not crash bot
    try:
        dbmod.upsert_user(DATABASE_URL, u.id, u.username, u.first_name)
        dbmod.ensure_referral_code(DATABASE_URL, u.id)
    except Exception as e:
        log.exception("DB error in ensure_user: %s", e)


# ======================
# Telegram handlers
# ======================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    context.user_data[WAITING_FOR_PROMPT] = None

    text = (
        "Καλώς ήρθες!\n\n"
        "Το bot μας είναι ένα AI Marketplace με κορυφαία εργαλεία σε ένα μέρος ✅\n\n"
        "• Βίντεο (Veo / Kling / Runway)\n"
        "• Εικόνες (Nano Banana / Flux / Midjourney)\n"
        "• Audio (TTS / SFX / μουσική)\n\n"
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

    # Try to use credits (do not crash if DB down)
    try:
        user = dbmod.get_user(DATABASE_URL, tg_id)
        if not user or user.credits <= 0:
            context.user_data[WAITING_FOR_PROMPT] = None
            await update.message.reply_text("❌ Δεν έχεις credits.", reply_markup=main_menu_kb())
            return

        dbmod.add_credits(DATABASE_URL, tg_id, delta=-1, reason=f"create_{mode}")
        job_id = dbmod.create_job(DATABASE_URL, tg_id, job_type=mode, prompt=text, provider=None)
    except Exception as e:
        log.exception("DB error on create job: %s", e)
        context.user_data[WAITING_FOR_PROMPT] = None
        await update.message.reply_text("⚠️ Προσωρινό πρόβλημα με τη βάση. Ξαναδοκίμασε.", reply_markup=main_menu_kb())
        return

    context.user_data[WAITING_FOR_PROMPT] = None
    await update.message.reply_text(
        f"✅ Έτοιμο!\n• Τύπος: {mode}\n• Job ID: #{job_id}\n• Χρεώθηκε: 1 credit",
        reply_markup=main_menu_kb(),
    )


async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    When Mini App calls tg.sendData(JSON.stringify(...)) this arrives here.
    """
    await ensure_user(update)
    msg = update.effective_message
    data = msg.web_app_data.data if msg and msg.web_app_data else ""

    try:
        payload = json.loads(data)
    except Exception:
        await msg.reply_text("❌ Μη έγκυρα δεδομένα από το Mini App.", reply_markup=main_menu_kb())
        return

    if payload.get("action") == "buy_plan":
        plan = payload.get("plan", "FREE")
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


# ======================
# AIOHTTP routes
# ======================
async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text="OK", content_type="text/plain; charset=utf-8")


async def handle_app(request: web.Request) -> web.Response:
    """
    Serves webapp/index.html
    """
    try:
        here = os.path.dirname(__file__)
        path = os.path.join(here, "webapp", "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        return web.Response(text=html, content_type="text/html; charset=utf-8")
    except Exception as e:
        return web.Response(
            text=f"APP ERROR: {type(e).__name__}: {e}",
            status=500,
            content_type="text/plain; charset=utf-8",
        )


async def handle_api_me(request: web.Request) -> web.Response:
    """
    Mini App calls this with { initData }.
    Returns profile info.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad_json"}, status=400)

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

    name = user_obj.get("first_name") or user_obj.get("username") or "—"
    photo_url = user_obj.get("photo_url")
    credits = 0
    plan = "Free"
    code = "na"

    try:
        dbmod.upsert_user(DATABASE_URL, tg_id, user_obj.get("username"), user_obj.get("first_name"))
        code = dbmod.ensure_referral_code(DATABASE_URL, tg_id)
        u = dbmod.get_user(DATABASE_URL, tg_id)
        if u:
            credits = u.credits
            plan = getattr(u, "plan", "Free")
    except Exception as e:
        log.exception("DB error on /api/me: %s", e)

    referral_link = f"{BASE_URL}/r/{code}"

    return web.json_response({
        "tg_id": tg_id,
        "name": name,
        "photo_url": photo_url,
        "credits": credits,
        "plan": plan,
        "referral_link": referral_link,
    })


async def handle_ref_redirect(request: web.Request) -> web.Response:
    """
    /r/<code> -> redirect to bot start=ref_<code>
    """
    code = request.match_info.get("code", "")
    bot_app: Application = request.app.get("bot_app")
    if not bot_app:
        # Bot not ready yet
        return web.Response(text="Bot not ready yet", status=503)

    me = await bot_app.bot.get_me()
    url = f"https://t.me/{me.username}?start=ref_{code}"
    raise web.HTTPFound(url)


# ======================
# Start everything (WEB first, then DB + bot)
# ======================
async def start_everything():
    log.info("ENV PORT=%s", PORT)
    log.info("PUBLIC_BASE_URL=%s", BASE_URL)
    log.info("WEBAPP_URL=%s", WEBAPP_URL)

    # 1) Start WEB server first (Railway needs a listening port)
    webapp = web.Application()
    webapp.add_routes([
        web.get("/health", handle_health),
        web.get("/", handle_root),
        web.get("/app", handle_app),
        web.post("/api/me", handle_api_me),
        web.get("/r/{code}", handle_ref_redirect),
    ])

    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    log.info("About to start web server on %s", PORT)
    await site.start()
    log.info("✅ Web server LISTENING on 0.0.0.0:%s", PORT)

    # 2) Init DB (but never crash the web server)
    try:
        dbmod.init_db(DATABASE_URL)
        log.info("DB initialized.")
    except Exception as e:
        log.exception("DB init failed (continuing): %s", e)

    # 3) Start BOT in background (polling)
    async def bot_task():
        try:
            bot_app = build_bot_app()
            webapp["bot_app"] = bot_app  # needed for referral redirect
            await bot_app.initialize()
            await bot_app.start()
            await bot_app.updater.start_polling(drop_pending_updates=True)
            log.info("✅ Bot polling started.")
        except Exception as e:
            log.exception("Bot failed: %s", e)

    asyncio.create_task(bot_task())

    # Keep process alive
    while True:
        await asyncio.sleep(3600)


def run():
    asyncio.run(start_everything())


if __name__ == "__main__":
    run()
