# app/bot.py
import os
import logging
from pathlib import Path
from decimal import Decimal

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from .config import BOT_TOKEN
from . import texts
from .keyboards import (
    start_inline_menu,
    video_models_menu,
    video_models_menu_page1,
    video_models_menu_page2,
    image_models_menu,
    audio_models_menu,
    text_models_menu,
    jobs_menu,
    jobs_client_menu,
    jobs_freelancer_menu,
)

from .db import (
    run_migrations,
    ensure_user,
    get_user,
    apply_referral_start,
    spend_credits_by_tg_id,
    add_credits_by_tg_id,
)

logger = logging.getLogger(__name__)

HERO_PATH = Path(__file__).parent / "assets" / "hero.png"
REF_BONUS_CREDITS = 1

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()


async def send_start_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.username, u.first_name)

    hero_exists = HERO_PATH.exists()

    try:
        if update.message:
            if hero_exists:
                await update.message.reply_photo(
                    photo=HERO_PATH.open("rb"),
                    caption=texts.START_CAPTION,
                    reply_markup=start_inline_menu(),
                )
            else:
                await update.message.reply_text(
                    texts.START_CAPTION,
                    reply_markup=start_inline_menu(),
                )
            return

        if update.callback_query:
            q = update.callback_query
            await q.answer()
            if hero_exists:
                await q.message.reply_photo(
                    photo=HERO_PATH.open("rb"),
                    caption=texts.START_CAPTION,
                    reply_markup=start_inline_menu(),
                )
            else:
                await q.message.reply_text(
                    texts.START_CAPTION,
                    reply_markup=start_inline_menu(),
                )
            return

    except Exception as e:
        if update.message:
            await update.message.reply_text(f"Start error: {e}")
        elif update.callback_query:
            await update.callback_query.message.reply_text(f"Start error: {e}")


async def edit_start_card(q, caption: str, reply_markup):
    msg = q.message
    try:
        await msg.edit_caption(caption=caption, reply_markup=reply_markup)
    except BadRequest:
        if HERO_PATH.exists():
            await msg.reply_photo(
                photo=HERO_PATH.open("rb"),
                caption=caption,
                reply_markup=reply_markup,
            )
        else:
            await msg.reply_text(caption, reply_markup=reply_markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tg_id = int(user.id)
    ensure_user(tg_id, user.username, user.first_name)

    # ---- referral parsing ----
    ref_code = None
    if context.args:
        arg0 = (context.args[0] or "").strip()
        if arg0.startswith("ref_"):
            ref_code = arg0.replace("ref_", "", 1).strip()

    # ---- apply referral ----
    if ref_code:
        try:
            me = get_user(tg_id)
            if me:
                r = apply_referral_start(invited_user_id=int(me["id"]), code=ref_code, bonus_credits=REF_BONUS_CREDITS)
                if r.get("ok") and r.get("credited"):
                    inviter_tg = int(r["owner_tg_user_id"])
                    bonus = r.get("bonus", REF_BONUS_CREDITS)
                    try:
                        await context.bot.send_message(
                            chat_id=inviter_tg,
                            text=f"✅ Σου πιστώθηκε {bonus} credit από προσκληθέντα φίλο.",
                        )
                    except Exception:
                        pass
        except Exception:
            pass

    await send_start_card(update, context)


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return

    await q.answer()

    u = q.from_user
    ensure_user(u.id, u.username, u.first_name)

    data = q.data or ""

    if data == "menu:home":
        await edit_start_card(q, texts.START_CAPTION, start_inline_menu())
        return

    # Video menus (paginated)
    if data == "menu:video":
        await edit_start_card(q, "👇 Επίλεξε μοντέλο AI για ΒΙΝΤΕΟ:", video_models_menu_page1())
        return

    if data == "menu:video:1":
        await edit_start_card(q, "👇 Επίλεξε μοντέλο AI για ΒΙΝΤΕΟ:", video_models_menu_page1())
        return

    if data == "menu:video:2":
        await edit_start_card(q, "👇 Επίλεξε μοντέλο AI για ΒΙΝΤΕΟ (σελ. 2):", video_models_menu_page2())
        return

    if data == "menu:images":
        await edit_start_card(q, "👇 Επίλεξε μοντέλο AI για ΕΙΚΟΝΕΣ:", image_models_menu())
        return

    if data == "menu:audio":
        await edit_start_card(q, "👇 Επίλεξε μοντέλο AI για ΗΧΟ:", audio_models_menu())
        return

    if data == "menu:text":
        await edit_start_card(q, "👇 Επίλεξε μοντέλο AI για ΚΕΙΜΕΝΟ:", text_models_menu())
        return

    if data == "menu:jobs":
        await edit_start_card(
            q,
            "💼 Εργασίες\n\nΕπίλεξε τι θέλεις να κάνεις:",
            jobs_menu(),
        )
        return

    if data.startswith("menu:set:"):
        parts = data.split(":")
        if len(parts) == 4:
            kind = parts[2]
            model = parts[3]
            context.user_data[f"selected_{kind}"] = model

            if model == "gemini3flash":
                await q.message.reply_text(
                    "✅ Gemini 3 Flash ενεργοποιήθηκε.\n"
                    "Στείλε τώρα ένα μήνυμα για να σου απαντήσω."
                )
            elif model == "qwen_ai":
                await q.message.reply_text(
                    "✅ Qwen AI ενεργοποιήθηκε.\n"
                    "Στείλε τώρα prompt για δημιουργία εικόνας."
                )
            elif model == "flux_kontext":
                await q.message.reply_text(
                    "✅ Flux Kontext ενεργοποιήθηκε.\n"
                    "Στείλε τώρα prompt (ή εικόνα + prompt) για να δημιουργήσω."
                )
            else:
                await q.message.reply_text(
                    f"✅ Επιλέχθηκε {kind.upper()}: {model}\n"
                    f"Στείλε τώρα prompt ή εικόνα για να συνεχίσουμε."
                )
        return


async def on_jobs_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()

    u = q.from_user
    ensure_user(u.id, u.username, u.first_name)

    data = q.data or ""

    if data == "jobs:client":
        await edit_start_card(q, "🧑‍💼 Πελάτης\n\nΤι θέλεις να κάνεις;", jobs_client_menu())
        return

    if data == "jobs:freelancer":
        await edit_start_card(q, "🧑‍💻 Freelancer\n\nΤι θέλεις να κάνεις;", jobs_freelancer_menu())
        return

    if data == "jobs:client:help":
        await q.message.reply_text(
            "ℹ️ Τι να γράψω στο αίτημα:\n"
            "• Τι θες να φτιαχτεί\n"
            "• Deadline\n"
            "• Budget\n"
            "• Παραδείγματα/links\n"
            "• Τι μορφή παράδοσης θέλεις (π.χ. αρχείο .zip, Figma, κτλ)"
        )
        return

    if data == "jobs:freelancer:how":
        await q.message.reply_text(
            "ℹ️ Πώς δουλεύει:\n"
            "• Βλέπεις εργασίες\n"
            "• Στέλνεις πρόταση/μήνυμα\n"
            "• Συμφωνείτε όρους & παράδοση\n\n"
            "Σύντομα θα γίνει πλήρης marketplace ροή."
        )
        return

    if data == "jobs:list":
        await q.message.reply_text("📭 Προς το παρόν το listing θα έρθει από το backend (Railway).")
        return

    if data == "jobs:post":
        await q.message.reply_text("📝 Η ανάρτηση εργασίας θα γίνει από το backend (Railway). Θα το κουμπώσουμε αμέσως μετά.")
        return


# ========================
# Inline text handler (Gemini 3 Flash, Qwen AI, Flux Kontext)
# ========================
async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages for inline tools (Gemini Flash, Qwen AI, etc.)."""
    if not update.message or not update.message.text:
        return

    u = update.effective_user
    tg_id = int(u.id)
    text = update.message.text.strip()

    selected_text = context.user_data.get("selected_text")
    selected_image = context.user_data.get("selected_image")

    # --- Gemini 3 Flash (text AI) ---
    if selected_text == "gemini3flash":
        if not GEMINI_API_KEY:
            await update.message.reply_text("⚠️ Gemini API key δεν έχει ρυθμιστεί.")
            return

        COST = Decimal("0.5")
        try:
            spend_credits_by_tg_id(tg_id, COST, "Gemini 3 Flash chat", "gemini", "gemini-3-flash")
        except Exception:
            await update.message.reply_text("❌ Δεν έχεις αρκετά credits.")
            return

        await update.message.reply_text("💬 Σκέφτομαι...")

        try:
            body = {
                "contents": [{"parts": [{"text": text}]}],
            }
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                    params={"key": GEMINI_API_KEY},
                    json=body,
                )
            data = r.json()
            if r.status_code >= 400:
                raise RuntimeError(f"Gemini error: {data}")

            reply = ""
            candidates = data.get("candidates") or []
            if candidates:
                parts = (candidates[0].get("content") or {}).get("parts") or []
                for p in parts:
                    if p.get("text"):
                        reply += p["text"]

            if not reply:
                reply = "(Δεν λήφθηκε απάντηση)"

            await update.message.reply_text(reply[:4096])

        except Exception as e:
            logger.exception("Gemini Flash error")
            try:
                add_credits_by_tg_id(tg_id, COST, "Refund Gemini Flash fail", "system", None)
            except Exception:
                pass
            await update.message.reply_text(f"⛔ Σφάλμα: Δοκίμασε ξανά.")
        return

    # --- Qwen AI (image generation via inline) ---
    if selected_image == "qwen_ai":
        qwen_key = os.getenv("QWEN_API_KEY", "").strip()
        if not qwen_key:
            await update.message.reply_text("⚠️ Qwen API key δεν έχει ρυθμιστεί.")
            return

        COST = Decimal("1")
        try:
            spend_credits_by_tg_id(tg_id, COST, "Qwen AI image", "qwen", "qwen-ai")
        except Exception:
            await update.message.reply_text("❌ Δεν έχεις αρκετά credits.")
            return

        await update.message.reply_text("🤖 Δημιουργία εικόνας Qwen AI...")

        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
                    headers={
                        "Authorization": f"Bearer {qwen_key}",
                        "Content-Type": "application/json",
                        "X-DashScope-Async": "enable",
                    },
                    json={
                        "model": "wanx-v1",
                        "input": {"prompt": text},
                        "parameters": {"n": 1, "size": "1024*1024"},
                    },
                )
            data = r.json()
            if r.status_code >= 400:
                raise RuntimeError(f"Qwen error: {data}")

            # Qwen returns async task - get result URL
            output = data.get("output") or {}
            results = output.get("results") or []
            if results and results[0].get("url"):
                await update.message.reply_photo(photo=results[0]["url"], caption="✅ Qwen AI: Έτοιμο")
            else:
                raise RuntimeError(f"No image URL: {data}")

        except Exception as e:
            logger.exception("Qwen AI error")
            try:
                add_credits_by_tg_id(tg_id, COST, "Refund Qwen AI fail", "system", None)
            except Exception:
                pass
            await update.message.reply_text("⛔ Σφάλμα: Δοκίμασε ξανά.")
        return


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Missing BOT_TOKEN")

    run_migrations()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # Jobs handler
    app.add_handler(CallbackQueryHandler(on_jobs_click, pattern=r"^jobs:"))

    # Menu handler
    app.add_handler(CallbackQueryHandler(on_menu_click, pattern=r"^menu:"))

    # Inline text messages (Gemini Flash, Qwen AI)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_message))

    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
