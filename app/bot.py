# app/bot.py
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from .config import BOT_TOKEN
from . import texts
from .keyboards import (
    start_inline_menu,
    video_models_menu,
    image_models_menu,
    audio_models_menu,
)

from .db import (
    run_migrations,
    ensure_user,
    get_user,
    apply_referral_start,  # <--- χρησιμοποιούμε το “σωστό” σύστημα referrals (referrals/referral_joins/referral_events)
)

HERO_PATH = Path(__file__).parent / "assets" / "hero.png"

REF_BONUS_CREDITS = 1


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
        # fallback: στείλε νέο μήνυμα
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

    # ---- apply referral (counts + bonus + telegram notify) ----
    if ref_code:
        try:
            me = get_user(tg_id)
            if me:
                r = apply_referral_start(invited_user_id=int(me["id"]), code=ref_code, bonus_credits=REF_BONUS_CREDITS)
                if r.get("ok") and r.get("credited"):
                    # notify inviter
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
            # δεν θέλουμε να ρίχνει το /start λόγω referral
            pass

    # ---- normal flow ----
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

    if data == "menu:video":
        await edit_start_card(q, "👇 Επίλεξε μοντέλο AI για ΒΙΝΤΕΟ:", video_models_menu())
        return

    if data == "menu:images":
        await edit_start_card(q, "👇 Επίλεξε μοντέλο AI για ΕΙΚΟΝΕΣ:", image_models_menu())
        return

    if data == "menu:audio":
        await edit_start_card(q, "👇 Επίλεξε μοντέλο AI για ΗΧΟ:", audio_models_menu())
        return

    if data.startswith("menu:set:"):
        parts = data.split(":")
        if len(parts) == 4:
            kind = parts[2]
            model = parts[3]
            context.user_data[f"selected_{kind}"] = model

            await q.message.reply_text(
                f"✅ Επιλέχθηκε {kind.upper()}: {model}\n"
                f"Στείλε τώρα prompt ή εικόνα για να συνεχίσουμε."
            )
        return


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Missing BOT_TOKEN")

    run_migrations()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_menu_click, pattern=r"^menu:"))
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()

@dp.callback_query_handler(lambda c: c.data=="menu_jobs")
async def open_jobs(cb: CallbackQuery):
    await cb.message.edit_text(
        "💼 <b>Jobs Hub</b>\n\nΤι θέλεις να κάνεις;",
        reply_markup=jobs_menu(),
        parse_mode="HTML"
    )
