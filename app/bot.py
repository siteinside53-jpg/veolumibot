# app/bot.py
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from .config import BOT_TOKEN
from .db import run_migrations, ensure_user, get_user
from . import texts
from .keyboards import start_inline_menu, open_profile_webapp_kb

HERO_IMAGE_URL = "ΒΑΛΕ_ΕΔΩ_ΤΟ_DIRECT_IMAGE_URL_ΣΟΥ"  # πχ https://.../lumi.jpg


async def send_start_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Στέλνει το start card (photo + caption + inline menu)."""
    if update.message:
        ensure_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
        await update.message.reply_photo(
            photo=HERO_IMAGE_URL,
            caption=texts.START_CAPTION,
            reply_markup=start_inline_menu(),
        )
    elif update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.message.reply_photo(
            photo=HERO_IMAGE_URL,
            caption=texts.START_CAPTION,
            reply_markup=start_inline_menu(),
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_start_card(update, context)


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()

    u = q.from_user
    ensure_user(u.id, u.username, u.first_name)

    data = q.data or ""
    # menu:profile, menu:video, menu:images, menu:audio, menu:support, menu:home

    if data == "menu:home":
        # ξαναστέλνει το start card
        await q.message.reply_photo(
            photo=HERO_IMAGE_URL,
            caption=texts.START_CAPTION,
            reply_markup=start_inline_menu(),
        )
        return

    if data == "menu:profile":
        dbu = get_user(u.id) or {"tg_user_id": u.id, "tg_username": u.username, "credits": 0}
        await q.message.reply_text(
            texts.PROFILE_MD.format(
                tg_user_id=dbu["tg_user_id"],
                username=(dbu.get("tg_username") or "—"),
                credits=f'{float(dbu.get("credits", 0)):.2f}',
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=open_profile_webapp_kb(),
        )
        return

    if data in ("menu:video", "menu:images", "menu:audio"):
        await q.message.reply_text("🚧 Εδώ θα μπει το generator flow. (Template)")
        return

    if data == "menu:support":
        await q.message.reply_text("☁️ Υποστήριξη: γράψε εδώ το θέμα σου και θα σου απαντήσουμε. (Template)")
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
