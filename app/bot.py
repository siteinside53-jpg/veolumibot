# app/bot.py
from pathlib import Path
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
    image_models_menu,
    audio_models_menu,
    jobs_menu,
    jobs_client_menu,
    jobs_freelancer_menu,
)

from .db import (
    run_migrations,
    ensure_user,
    get_user,
    apply_referral_start,
    create_job,
    list_open_jobs,
    register_freelancer,
)

HERO_PATH = Path(__file__).parent / "assets" / "hero.png"
REF_BONUS_CREDITS = 1


# =========================
# UI helpers
# =========================

async def edit_or_send(msg, text, kb=None):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except:
        await msg.reply_text(text, reply_markup=kb, parse_mode="HTML")


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.first_name)

    ref_code = None
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            ref_code = arg.replace("ref_", "")

    if ref_code:
        try:
            me = get_user(user.id)
            if me:
                r = apply_referral_start(me["id"], ref_code, REF_BONUS_CREDITS)
                if r.get("credited"):
                    await context.bot.send_message(
                        r["owner_tg_user_id"],
                        f"✅ Σου πιστώθηκε {REF_BONUS_CREDITS} credit από referral"
                    )
        except:
            pass

    if HERO_PATH.exists():
        await update.message.reply_photo(
            HERO_PATH.open("rb"),
            caption=texts.START_CAPTION,
            reply_markup=start_inline_menu()
        )
    else:
        await update.message.reply_text(
            texts.START_CAPTION,
            reply_markup=start_inline_menu()
        )


# =========================
# MENU HANDLER
# =========================

async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    ensure_user(q.from_user.id, q.from_user.username, q.from_user.first_name)

    data = q.data

    if data == "menu:home":
        await edit_or_send(q.message, texts.START_CAPTION, start_inline_menu())

    elif data == "menu:video":
        await edit_or_send(q.message, "👇 Video models", video_models_menu())

    elif data == "menu:images":
        await edit_or_send(q.message, "👇 Image models", image_models_menu())

    elif data == "menu:audio":
        await edit_or_send(q.message, "👇 Audio models", audio_models_menu())

    elif data == "menu:jobs":
        await edit_or_send(q.message, "💼 Jobs Hub", jobs_menu())

    elif data.startswith("menu:set:"):
        _,_,kind,model = data.split(":")
        context.user_data["selected"]=model
        await q.message.reply_text(f"✅ Selected {kind}: {model}")


# =========================
# JOBS HANDLER
# =========================

async def on_jobs_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data

    # menu
    if data == "jobs:client":
        await edit_or_send(q.message,"🧑‍💼 Client menu", jobs_client_menu())

    elif data == "jobs:freelancer":
        await edit_or_send(q.message,"🧑‍💻 Freelancer menu", jobs_freelancer_menu())

    # list jobs
    elif data == "jobs:list":
        jobs = list_open_jobs()
        if not jobs:
            await q.message.reply_text("Δεν υπάρχουν εργασίες.")
            return

        txt = "<b>Jobs</b>\n\n"
        for j in jobs:
            txt += f"#{j['id']} — {j['title']} | 💰 {j['budget']}\n"

        await q.message.reply_text(txt, parse_mode="HTML")

    # start job post
    elif data == "jobs:post":
        context.user_data["state"]="job_title"
        await q.message.reply_text("Τίτλος εργασίας?")

    # freelancer register
    elif data == "jobs:register":
        context.user_data["state"]="freelancer_skills"
        await q.message.reply_text("Skills σου?")


# =========================
# TEXT ROUTER (STATE MACHINE)
# =========================

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if not state:
        return

    txt = update.message.text

    # job title
    if state=="job_title":
        context.user_data["job"]={"title":txt}
        context.user_data["state"]="job_desc"
        await update.message.reply_text("Περιγραφή?")

    elif state=="job_desc":
        context.user_data["job"]["desc"]=txt
        context.user_data["state"]="job_budget"
        await update.message.reply_text("Budget?")

    elif state=="job_budget":
        job=context.user_data.pop("job")
        context.user_data["state"]=None

        create_job(update.effective_user.id,job["title"],job["desc"],txt)

        await update.message.reply_text("🚀 Job δημοσιεύτηκε!")

    # freelancer
    elif state=="freelancer_skills":
        context.user_data["freelancer"]={"skills":txt}
        context.user_data["state"]="freelancer_about"
        await update.message.reply_text("Πες λίγα για σένα")

    elif state=="freelancer_about":
        data=context.user_data.pop("freelancer")
        context.user_data["state"]=None

        register_freelancer(update.effective_user.id,data["skills"],txt)

        await update.message.reply_text("✅ Έγινες freelancer!")


# =========================
# MAIN
# =========================

def main():
    run_migrations()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_jobs_click, pattern="^jobs:"))
    app.add_handler(CallbackQueryHandler(on_menu_click, pattern="^menu:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    app.run_polling()


if __name__=="__main__":
    main()
