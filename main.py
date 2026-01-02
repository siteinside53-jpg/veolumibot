from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import traceback
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

BUILD = "build_2026_01_02_fixed_v2"


# ======================
# LOGGING
# ======================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("veolumi")


# ======================
# RAILWAY PORT + URLs
# ======================
PORT = int(os.environ.get("PORT", "8080"))
BASE_URL = (PUBLIC_BASE_URL or "").rstrip("/")
WEBAPP_URL = f"{BASE_URL}/app" if BASE_URL else "/app"


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
# Error middleware (για να δεις ΑΚΡΙΒΩΣ τι σκάει) -- reduce info in prod
# ======================
@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        log.error("HTTP 500 on %s %s\n%s", request.method, request.path, tb)
        # In production do NOT expose traceback. Use an env flag to toggle.
        if os.environ.get("SHOW_ERRORS", "1") == "1":
            body = f"500 Internal Server Error\n\nBUILD={BUILD}\n\n{type(e).__name__}: {e}\n"
        else:
            body = f"500 Internal Server Error\n\nBUILD={BUILD}\n"
        return web.Response(
            text=body,
            status=500,
            content_type="text/plain; charset=utf-8",
        )


# ======================
# Telegram WebApp initData verify
# ======================
def verify_telegram_init_data(init_data: str, bot_token: str) -> dict:
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
# DB helpers (run sync DB code in thread pool)
# ======================
async def ensure_user(update: Update) -> None:
    if not update.effective_user:
        return
    u = update.effective_user
    try:
        # run potentially blocking DB operations in a thread
        await asyncio.to_thread(dbmod.upsert_user, DATABASE_URL, u.id, u.username, u.first_name)
        await asyncio.to_thread(dbmod.ensure_referral_code, DATABASE_URL, u.id)
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
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu_kb())


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    q = update.callback_query
    if not q:
        return
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
    if not update.effective_user or not update.message:
        return
    tg_id = update.effective_user.id
    text = (update.message.text or "").strip()

    mode = context.user_data.get(WAITING_FOR_PROMPT)
    if not mode:
        await update.message.reply_text("Διάλεξε από το μενού 👇", reply_markup=main_menu_kb())
        return

    try:
        # run blocking DB ops in threads
        user = await asyncio.to_thread(dbmod.get_user, DATABASE_URL, tg_id)
        if not user or getattr(user, "credits", 0) <= 0:
            context.user_data[WAITING_FOR_PROMPT] = None
            await update.message.reply_text("❌ Δεν έχεις credits.", reply_markup=main_menu_kb())
            return

        await asyncio.to_thread(dbmod.add_credits, DATABASE_URL, tg_id, -1, f"create_{mode}")
        job_id = await asyncio.to_thread(dbmod.create_job, DATABASE_URL, tg_id, job_type=mode, prompt=text, provider=None)
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
    await ensure_user(update)
    msg = update.effective_message
    data = ""
    if msg and getattr(msg, "web_app_data", None):
        data = msg.web_app_data.data or ""

    try:
        payload = json.loads(data)
    except Exception:
        if msg:
            await msg.reply_text("❌ Μη έγκυρα δεδομένα από το Mini App.", reply_markup=main_menu_kb())
        return

    if payload.get("action") == "buy_plan":
        plan = payload.get("plan", "FREE")
        if msg:
            await msg.reply_text(
                "🟣 Αίτημα αγοράς (demo)\n\n"
                f"Πακέτο: {plan}\n"
                "Στο επόμενο βήμα κουμπώνουμε πληρωμές (Stripe/PayPal/crypto) και αυτό θα φορτώνει credits αυτόματα.",
                reply_markup=main_menu_kb(),
            )
        return

    if msg:
        await msg.reply_text("ℹ️ Έλαβα εντολή από το Mini App.", reply_markup=main_menu_kb())


def build_bot_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(on_menu_click))
    # Make sure this filter exists in your PTB version. If not, replace with a custom predicate:
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


# ======================
# AIOHTTP routes
# ======================
async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "build": BUILD})


async def handle_root(request: web.Request) -> web.Response:
    # super simple handler (για να μην υπάρχει λόγος να σκάει)
    return web.Response(text=f"ROOT OK | {BUILD}", content_type="text/plain; charset=utf-8")


async def handle_favicon(request: web.Request) -> web.Response:
    return web.Response(status=204)


async def handle_app(request: web.Request) -> web.Response:
    here = os.path.dirname(__file__)
    path = os.path.join(here, "webapp", "index.html")
    if not os.path.exists(path):
        log.error("Webapp index not found: %s", path)
        return web.Response(text="Not found", status=404)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    return web.Response(text=html, content_type="text/html; charset=utf-8")


async def handle_api_me(request: web.Request) -> web.Response:
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
        # db ops in thread
        await asyncio.to_thread(dbmod.upsert_user, DATABASE_URL, tg_id, user_obj.get("username"), user_obj.get("first_name"))
        code = await asyncio.to_thread(dbmod.ensure_referral_code, DATABASE_URL, tg_id)
        u = await asyncio.to_thread(dbmod.get_user, DATABASE_URL, tg_id)
        if u:
            credits = getattr(u, "credits", 0)
            plan = getattr(u, "plan", "Free")
    except Exception as e:
        log.exception("DB error on /api/me: %s", e)

    referral_link = f"{BASE_URL}/r/{code}" if BASE_URL else f"/r/{code}"

    return web.json_response(
        {
            "tg_id": tg_id,
            "name": name,
            "photo_url": photo_url,
            "credits": credits,
            "plan": plan,
            "referral_link": referral_link,
        }
    )


async def handle_ref_redirect(request: web.Request) -> web.Response:
    code = request.match_info.get("code", "")
    bot_app: Application | None = request.app.get("bot_app")
    if not bot_app:
        return web.Response(text="Bot not ready yet", status=503)

    me = await bot_app.bot.get_me()
    url = f"https://t.me/{me.username}?start=ref_{code}"
    raise web.HTTPFound(url)


# ======================
# Start everything
# ======================
async def start_everything():
    log.info("ENV PORT=%s", PORT)
    log.info("PUBLIC_BASE_URL=%s", BASE_URL)
    log.info("WEBAPP_URL=%s", WEBAPP_URL)

    webapp = web.Application(middlewares=[error_middleware])
    webapp.add_routes(
        [
            web.get("/health", handle_health),
            web.get("/", handle_root),
            web.get("/favicon.ico", handle_favicon),
            web.get("/app", handle_app),
            web.post("/api/me", handle_api_me),
            web.get("/r/{code}", handle_ref_redirect),
        ]
    )

    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("✅ Web server LISTENING on 0.0.0.0:%s", PORT)

    # DB init (μην ρίξει το web) -- run in thread if it's blocking
    try:
        await asyncio.to_thread(dbmod.init_db, DATABASE_URL)
        log.info("DB initialized.")
    except Exception as e:
        log.exception("DB init failed (continuing): %s", e)

    # Bot polling
    async def bot_task():
        try:
            bot_app = build_bot_app()
            webapp["bot_app"] = bot_app
            # Run the bot polling in a thread so it doesn't block the aiohttp loop.
            # run_polling will initialize/start/idle internally; adjust if your PTB version differs.
            await asyncio.to_thread(bot_app.run_polling, drop_pending_updates=True)
            log.info("✅ Bot polling finished.")
        except Exception as e:
            log.exception("Bot failed: %s", e)

    asyncio.create_task(bot_task())

    # Keep alive
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        log.info("Shutting down web server and bot.")
        try:
            await runner.cleanup()
        except Exception:
            log.exception("Error during runner cleanup")


def run():
    asyncio.run(start_everything())


if __name__ == "__main__":
    run()
