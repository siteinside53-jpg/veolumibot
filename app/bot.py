import os
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from .config import BOT_TOKEN
from .db import run_migrations, ensure_user, get_user
from . import texts
from .keyboards import main_menu, open_profile_webapp_kb


# ✅ Local hero image inside repo
HERO_PATH = Path(__file__).parent / "assets" / "hero.jpg"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    u = update.effective_user
    ensure_user(u.id, u.username, u.first_name)

    # ✅ Στείλε κάρτα (εικόνα + caption) — με fallback αν λείπει εικόνα
    try:
        if HERO_PATH.exists():
            with HERO_PATH.open("rb") as f:
                await update.message.reply_photo(
                    photo=f,
                    caption=texts.START_CAPTION,
                    reply_markup=main_menu(),
                )
        else:
            await update.message.reply_text(
                texts.WELCOME + "\n\n(⚠️ Δεν βρέθηκε: app/assets/hero.jpg)",
                reply_markup=main_menu(),
            )
    except Exception as e:
        # ✅ Αν σκάσει κάτι, πάντα να απαντάει
        await update.message.reply_text(
            texts.WELCOME + f"\n\n(⚠️ start error: {e})",
            reply_markup=main_menu(),
        )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    txt = (update.message.text or "").strip()
    u = update.effective_user
    ensure_user(u.id, u.username, u.first_name)

    # ✅ PROFILE
    if txt == texts.BTN_PROFILE:
        dbu = get_user(u.id) or {"tg_user_id": u.id, "tg_username": u.username, "credits": 0}
        kb = open_profile_webapp_kb()

        await update.message.reply_text(
            texts.PROFILE_MD.format(
                tg_user_id=dbu["tg_user_id"],
                username=(dbu.get("tg_username") or "—"),
                credits=f'{float(dbu.get("credits", 0)):.2f}',
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
        return

    # Placeholder routes
    if txt in (texts.BTN_VIDEO, texts.BTN_IMAGES, texts.BTN_AUDIO):
        await update.message.reply_text("🚧 Εδώ θα μπει το generator flow. (Template)")
        return

    if txt == texts.BTN_SUPPORT:
        await update.message.reply_text("☁️ Υποστήριξη: γράψε εδώ το θέμα σου και θα σου απαντήσουμε. (Template)")
        return

    if txt == texts.BTN_PROMPTS:
        await update.message.reply_text("💡 Βάλε link στο κανάλι σου εδώ. (Template)")
        return

    await update.message.reply_text("Διάλεξε από το μενού 👇", reply_markup=main_menu())


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Missing BOT_TOKEN")

    run_migrations()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
