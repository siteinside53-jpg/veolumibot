from __future__ import annotations

import logging
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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

from config import BOT_TOKEN, DATABASE_URL, WEBHOOK_BASE_URL, PORT
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
# UI TEXT (ΕΛΛΗΝΙΚΑ)
# ======================
WELCOME_TITLE = "Καλώς ήρθες!"
WELCOME_TEXT = (
    "Το bot μας είναι ένα **AI Marketplace** με κορυφαία εργαλεία σε ένα μέρος ✅\n\n"
    "• Βίντεο (Veo / Kling / Runway)\n"
    "• Εικόνες (Nano Banana / Flux / Midjourney)\n"
    "• Audio (TTS / SFX / μουσική)\n\n"
    "💳 Πληρωμές: κάρτα / crypto / PayPal (όπως στο demo)\n"
    "⚡ Ξεκινάς με **δωρεάν credits**."
)

BTN_PROFILE = "👤 Το προφίλ μου"
BTN_VIDEO = "🎬 Δημιουργία βίντεο"
BTN_IMAGES = "🖼 Εικόνες"
BTN_AUDIO = "🎵 Audio"
BTN_PROMPTS = "💡 TG κανάλι με prompts"
BTN_SUPPORT = "☁️ Υποστήριξη"

# callback_data
CB_PROFILE = "profile"
CB_VIDEO = "video"
CB_IMAGES = "images"
CB_AUDIO = "audio"
CB_PROMPTS = "prompts"
CB_SUPPORT = "support"
CB_BACK = "back"

# ======================
# STATE KEYS
# ======================
WAITING_FOR_PROMPT = "waiting_for_prompt"   # values: None|"video"|"image"|"audio"


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BTN_PROFILE, callback_data=CB_PROFILE)],
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


# ======================
# HANDLERS
# ======================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)

    # Δώσε 5 credits στον νέο χρήστη μόνο την πρώτη φορά
    user = dbmod.get_user(DATABASE_URL, update.effective_user.id)
    # Αν θες “first-run” bonus πιο σωστά: βάλε flag. Για MVP κρατάμε default credits=5 στο schema.

    context.user_data[WAITING_FOR_PROMPT] = None

    await update.message.reply_text(
        f"{WELCOME_TITLE}\n\n{WELCOME_TEXT}",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)

    q = update.callback_query
    await q.answer()

    data = q.data
    tg_id = update.effective_user.id

    if data == CB_BACK:
        context.user_data[WAITING_FOR_PROMPT] = None
        await q.edit_message_text(
            "Μενού:",
            reply_markup=main_menu_kb()
        )
        return

    if data == CB_PROFILE:
        user = dbmod.get_user(DATABASE_URL, tg_id)
        jobs = dbmod.list_last_jobs(DATABASE_URL, tg_id, limit=5)

        last_jobs_txt = "—"
        if jobs:
            last_jobs_txt = "\n".join(
                [f"• #{j['id']} | {j['job_type']} | {j['status']}" for j in jobs]
            )

        txt = (
            "👤 **Το Προφίλ μου**\n\n"
            f"• ID: `{tg_id}`\n"
            f"• Username: @{user.username if user and user.username else '—'}\n"
            f"• Credits: **{user.credits if user else 0}**\n\n"
            "🧾 Τελευταίες εργασίες:\n"
            f"{last_jobs_txt}"
        )
        context.user_data[WAITING_FOR_PROMPT] = None
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=back_kb())
        return

    if data == CB_VIDEO:
        context.user_data[WAITING_FOR_PROMPT] = "video"
        await q.edit_message_text(
            "🎬 **Δημιουργία Βίντεο**\n\n"
            "Στείλε μου **το prompt** που θες (τι να δείξει το βίντεο).\n"
            "Tip: γράψε διάρκεια, στυλ, κάμερα, κίνηση, φωτισμό.",
            parse_mode="Markdown",
            reply_markup=back_kb()
        )
        return

    if data == CB_IMAGES:
        context.user_data[WAITING_FOR_PROMPT] = "image"
        await q.edit_message_text(
            "🖼 **Εικόνες**\n\n"
            "Στείλε μου **το prompt** για εικόνα.\n"
            "Αν θέλεις και reference photo, στείλε πρώτα τη φωτογραφία και μετά το prompt.",
            parse_mode="Markdown",
            reply_markup=back_kb()
        )
        return

    if data == CB_AUDIO:
        context.user_data[WAITING_FOR_PROMPT] = "audio"
        await q.edit_message_text(
            "🎵 **Audio**\n\n"
            "Στείλε μου prompt για:\n"
            "• voiceover / TTS ή\n"
            "• ηχητικό εφέ ή\n"
            "• μουσική.\n\n"
            "Π.χ. «ήρεμη ambient μουσική 15s, cinematic»",
            parse_mode="Markdown",
            reply_markup=back_kb()
        )
        return

    if data == CB_PROMPTS:
        context.user_data[WAITING_FOR_PROMPT] = None
        # Βάλε εδώ το δικό σου link (κανάλι telegram)
        await q.edit_message_text(
            "💡 **TG κανάλι με prompts**\n\n"
            "Βάλε εδώ το link του καναλιού σου.\n"
            "Π.χ. @YourPromptsChannel",
            parse_mode="Markdown",
            reply_markup=back_kb()
        )
        return

    if data == CB_SUPPORT:
        context.user_data[WAITING_FOR_PROMPT] = None
        await q.edit_message_text(
            "☁️ **Υποστήριξη**\n\n"
            "Γράψε εδώ το πρόβλημά σου ή στείλε στο @YourSupportUsername",
            parse_mode="Markdown",
            reply_markup=back_kb()
        )
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    tg_id = update.effective_user.id
    text = (update.message.text or "").strip()

    mode = context.user_data.get(WAITING_FOR_PROMPT)

    if not mode:
        await update.message.reply_text(
            "Διάλεξε από το μενού 👇",
            reply_markup=main_menu_kb()
        )
        return

    # credits check
    user = dbmod.get_user(DATABASE_URL, tg_id)
    if not user or user.credits <= 0:
        context.user_data[WAITING_FOR_PROMPT] = None
        await update.message.reply_text(
            "❌ Δεν έχεις credits.\n"
            "Σύντομα θα προσθέσουμε top-up / πληρωμές εδώ.",
            reply_markup=main_menu_kb()
        )
        return

    # χρέωσε 1 credit / job (MVP)
    dbmod.add_credits(DATABASE_URL, tg_id, delta=-1, reason=f"create_{mode}")

    # δημιούργησε job (stub). provider μπορείς να το ορίσεις αργότερα (veo/nano/flux/etc)
    job_id = dbmod.create_job(DATABASE_URL, tg_id, job_type=mode, prompt=text, provider=None)

    context.user_data[WAITING_FOR_PROMPT] = None

    await update.message.reply_text(
        "✅ Έτοιμο!\n\n"
        f"• Τύπος: {mode}\n"
        f"• Job ID: #{job_id}\n"
        f"• Χρεώθηκε: 1 credit\n\n"
        "Στο επόμενο βήμα θα συνδέσουμε provider (Veo/Nano/κλπ) και θα σου επιστρέφει αποτέλεσμα αυτόματα.",
        reply_markup=main_menu_kb()
    )


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    # MVP: αποδεχόμαστε φωτο, αλλά δεν την αποθηκεύουμε ακόμα.
    # Στο επόμενο βήμα μπορείς να τη σώσεις σε S3/R2 και να τη δώσεις σαν reference.
    await update.message.reply_text(
        "📸 Πήρα τη φωτογραφία.\n"
        "Τώρα στείλε το prompt σου (για να τη χρησιμοποιήσουμε ως reference)."
    )


# ======================
# WEBHOOK / POLLING
# ======================
async def on_startup(app: Application) -> None:
    dbmod.init_db(DATABASE_URL)
    log.info("DB initialized.")


def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(on_menu_click))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    return app


def run():
    app = build_app()

    if WEBHOOK_BASE_URL:
        # Webhook mode (καλύτερο για Railway)
        webhook_url = f"{WEBHOOK_BASE_URL.rstrip('/')}/{BOT_TOKEN}"
        log.info("Starting webhook on port %s | url=%s", PORT, webhook_url)

        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )
    else:
        # Polling mode (πιο απλό)
        log.info("Starting polling...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
