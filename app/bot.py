import os
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from .config import BOT_TOKEN
from .db import run_migrations, ensure_user, get_user
from . import texts
from .keyboards import main_menu, open_profile_webapp_kb

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.username, u.first_name)
    await update.message.reply_text(texts.WELCOME, reply_markup=main_menu())

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    u = update.effective_user
    ensure_user(u.id, u.username, u.first_name)

    if txt == texts.BTN_PROFILE:
    dbu = get_user(u.id) or {"tg_user_id": u.id, "tg_username": u.username, "credits": 0}
    await update.message.reply_text(
        texts.PROFILE_TEXT.format(
            tg_user_id=dbu["tg_user_id"],
            username=(dbu["tg_username"] or "—"),
            credits=f'{float(dbu["credits"]):.2f}'
        ),
        reply_markup=open_profile_webapp_kb()
    )
    return

    # Placeholder routes (θα τα “δέσεις” μετά με generation endpoints)
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
