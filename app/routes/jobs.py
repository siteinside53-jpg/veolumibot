# app/routes/jobs.py
"""
Jobs system (Telegram-side) for VeoLumiBot / UGenius.

What this module provides:
- Menus (Jobs hub, client menu, freelancer menu)
- Job posting flow (title -> description -> budget) via user_data state
- Jobs listing (open jobs)
- Job details + "Accept" button (paywalled by freelancer package)
- Simple freelancer package gate (checks users.is_freelancer boolean)
- Optional "become freelancer" action (manual toggle point; payment flow can set it)

How to use from bot.py:
- In callback handler:
    if data == "menu:jobs": await jobs_show_menu(update, context)
    if data == "jobs:client": await jobs_show_client_menu(update, context)
    if data == "jobs:freelancer": await jobs_show_freelancer_menu(update, context)
    if data == "jobs:post": await jobs_start_post(update, context)
    if data == "jobs:list": await jobs_list(update, context)
    if data.startswith("jobs:view:"): await jobs_view(update, context, int(data.split(":")[-1]))
    if data.startswith("jobs:accept:"): await jobs_accept(update, context, int(data.split(":")[-1]))
    if data == "jobs:buy_freelancer": await jobs_show_buy_freelancer(update, context)
    if data == "jobs:freelancer:how": await jobs_freelancer_how(update, context)
    if data == "jobs:client:help": await jobs_client_help(update, context)

- In message handler:
    if await jobs_handle_message(update, context): return

DB expectations:
- table jobs with columns:
    id, user_id, title, description, budget, status, created_at
  status: 'open' | 'assigned' | 'closed'
- table users has:
    id (db user id), tg_user_id, username, credits, is_freelancer boolean

You already have db_user_from_webapp for WebApp, but for Telegram flows we use tg_user_id
and a helper in db.py: get_or_create_user_by_tg(tg_user_id, username)
If you don't have it, add it.

IMPORTANT:
This module calls db functions that you must have in app/db.py:
- get_or_create_user_by_tg(tg_user_id:int, username:str|None) -> dict with "id"
- create_job(user_id:int, title:str, description:str, budget:int|float|str) -> int job_id
- list_open_jobs(limit:int=10) -> list[dict]
- get_job(job_id:int) -> dict|None
- set_job_assigned(job_id:int, freelancer_user_id:int) -> None  (optional, see below)
- user_is_freelancer(user_id:int) -> bool
"""

from __future__ import annotations

from typing import Any, Dict, Optional, List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

# You can localize these strings in texts.py later if you want
JOBS_HUB_TEXT = (
    "💼 <b>Jobs Hub</b>\n\n"
    "Επίλεξε τι θέλεις να κάνεις:"
)

CLIENT_HELP_TEXT = (
    "📝 <b>Τι να γράψω στο αίτημα;</b>\n\n"
    "✅ Τίτλος: 1 γραμμή με το ζητούμενο.\n"
    "✅ Περιγραφή: τι ακριβώς θες, deadline, παραδείγματα.\n"
    "✅ Budget: πόσα € διαθέτεις.\n\n"
    "Παράδειγμα:\n"
    "Τίτλος: «Landing page για συνεργείο»\n"
    "Περιγραφή: «1 σελίδα, φόρμα επικοινωνίας, 2 ενότητες υπηρεσιών, responsive»\n"
    "Budget: 150"
)

FREELANCER_HOW_TEXT = (
    "🧑‍💻 <b>Πώς δουλεύει για Freelancer</b>\n\n"
    "1) Βλέπεις διαθέσιμες εργασίες\n"
    "2) Ανοίγεις λεπτομέρειες\n"
    "3) Πατάς «Αποδοχή» για να αναλάβεις\n\n"
    "🔒 Η αποδοχή εργασιών απαιτεί Freelancer Package."
)

BUY_FREELANCER_TEXT = (
    "🔒 <b>Freelancer Package</b>\n\n"
    "Για να μπορείς να <b>αποδέχεσαι</b> και να αναλαμβάνεις εργασίες,\n"
    "πρέπει να έχεις ενεργό Freelancer Package.\n\n"
    "💳 Κόστος: <b>29€</b>\n"
    "Με την αγορά ενεργοποιείται στο προφίλ σου."
)

POST_SUCCESS_TEXT = "✅ Η εργασία δημοσιεύτηκε!"
NO_JOBS_TEXT = "📭 Δεν υπάρχουν διαθέσιμες εργασίες αυτή τη στιγμή."

# user_data keys
UD_STEP = "jobs_step"
UD_TITLE = "jobs_title"
UD_DESC = "jobs_desc"


# -------------------------
# DB helpers (import lazily)
# -------------------------

def _db():
    # local import to avoid circulars
    from .. import db as _dbmod
    return _dbmod


def _get_db_user_id_from_update(update: Update) -> int:
    """
    Ensure we have a DB user and return db_user_id.
    Requires db.get_or_create_user_by_tg(tg_user_id, username).
    """
    tg_user = update.effective_user
    if not tg_user:
        raise RuntimeError("No telegram user")

    tg_user_id = int(tg_user.id)
    username = (tg_user.username or "").strip() or None

    dbu = _db().get_or_create_user_by_tg(tg_user_id, username)
    return int(dbu["id"])


# -------------------------
# Keyboards (Telegram)
# -------------------------

def kb_jobs_hub() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔎 Ζητάω βοήθεια (πελάτης)", callback_data="jobs:client")],
            [InlineKeyboardButton("🧑‍💻 Είμαι freelancer", callback_data="jobs:freelancer")],
            [InlineKeyboardButton("📤 Ανάρτηση εργασίας", callback_data="jobs:post")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:home")],
        ]
    )

def kb_jobs_client() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 Δημιούργησε αίτημα", callback_data="jobs:post")],
            [InlineKeyboardButton("ℹ️ Τι να γράψω;", callback_data="jobs:client:help")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:jobs")],
        ]
    )

def kb_jobs_freelancer() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👀 Δες διαθέσιμες εργασίες", callback_data="jobs:list")],
            [InlineKeyboardButton("ℹ️ Πώς δουλεύει", callback_data="jobs:freelancer:how")],
            [InlineKeyboardButton("← Πίσω", callback_data="menu:jobs")],
        ]
    )

def kb_job_view(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Αποδοχή εργασίας", callback_data=f"jobs:accept:{job_id}")],
            [InlineKeyboardButton("← Πίσω", callback_data="jobs:list")],
        ]
    )

def kb_buy_freelancer() -> InlineKeyboardMarkup:
    # If you have a WebApp purchase page, replace callback with web_app url button.
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💳 Αγορά Freelancer Package (29€)", callback_data="jobs:buy_freelancer")],
            [InlineKeyboardButton("← Πίσω", callback_data="jobs:list")],
        ]
    )

def kb_back_to_jobs() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Πίσω", callback_data="menu:jobs")]])


# -------------------------
# Public: callback handlers
# -------------------------

async def jobs_show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text(JOBS_HUB_TEXT, reply_markup=kb_jobs_hub(), parse_mode="HTML")

async def jobs_show_client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text("👤 <b>Πελάτης</b>\n\nΕπίλεξε:", reply_markup=kb_jobs_client(), parse_mode="HTML")

async def jobs_show_freelancer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text("🧑‍💻 <b>Freelancer</b>\n\nΕπίλεξε:", reply_markup=kb_jobs_freelancer(), parse_mode="HTML")

async def jobs_client_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text(CLIENT_HELP_TEXT, reply_markup=kb_jobs_client(), parse_mode="HTML")

async def jobs_freelancer_how(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text(FREELANCER_HOW_TEXT, reply_markup=kb_jobs_freelancer(), parse_mode="HTML")


async def jobs_start_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Start multi-step posting flow (title -> desc -> budget) via messages.
    """
    q = update.callback_query
    if q:
        await q.answer()
        # reset flow
        context.user_data.pop(UD_TITLE, None)
        context.user_data.pop(UD_DESC, None)
        context.user_data[UD_STEP] = "title"

        await q.message.reply_text("📝 Στείλε <b>τίτλο</b> εργασίας:", parse_mode="HTML")
        await q.edit_message_text("📝 Ξεκινάμε ανάρτηση εργασίας…", reply_markup=kb_jobs_client(), parse_mode="HTML")


async def jobs_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q:
        await q.answer()

    items = _db().list_open_jobs(limit=10) or []
    if not items:
        if q:
            await q.edit_message_text(NO_JOBS_TEXT, reply_markup=kb_back_to_jobs(), parse_mode="HTML")
        return

    lines = ["📋 <b>Διαθέσιμες εργασίες</b>\n"]
    kb_rows = []
    for j in items:
        jid = int(j["id"])
        title = (j.get("title") or "").strip()[:60] or f"Job #{jid}"
        budget = j.get("budget")
        budget_txt = f"{budget}€" if budget is not None and str(budget).strip() != "" else "—"
        lines.append(f"• <b>{title}</b>  <i>({budget_txt})</i>")
        kb_rows.append([InlineKeyboardButton(f"💼 {title}", callback_data=f"jobs:view:{jid}")])

    kb_rows.append([InlineKeyboardButton("← Πίσω", callback_data="menu:jobs")])
    text = "\n".join(lines)

    if q:
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="HTML")


async def jobs_view(update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int) -> None:
    q = update.callback_query
    if q:
        await q.answer()

    job = _db().get_job(job_id)
    if not job:
        if q:
            await q.edit_message_text("❌ Η εργασία δεν βρέθηκε.", reply_markup=kb_back_to_jobs(), parse_mode="HTML")
        return

    title = (job.get("title") or "").strip() or f"Job #{job_id}"
    desc = (job.get("description") or "").strip() or "—"
    budget = job.get("budget")
    budget_txt = f"{budget}€" if budget is not None and str(budget).strip() != "" else "—"
    status = (job.get("status") or "open").strip()

    text = (
        f"💼 <b>{title}</b>\n"
        f"💰 Budget: <b>{budget_txt}</b>\n"
        f"📌 Status: <b>{status}</b>\n\n"
        f"📝 <b>Περιγραφή</b>\n{_escape_html(desc)}"
    )

    if q:
        await q.edit_message_text(text, reply_markup=kb_job_view(job_id), parse_mode="HTML")


async def jobs_accept(update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int) -> None:
    q = update.callback_query
    if q:
        await q.answer()

    db_user_id = _get_db_user_id_from_update(update)
    if not _db().user_is_freelancer(db_user_id):
        # Paywall
        text = BUY_FREELANCER_TEXT
        if q:
            await q.edit_message_text(text, reply_markup=kb_buy_freelancer(), parse_mode="HTML")
        return

    job = _db().get_job(job_id)
    if not job:
        if q:
            await q.edit_message_text("❌ Η εργασία δεν βρέθηκε.", reply_markup=kb_back_to_jobs(), parse_mode="HTML")
        return

    if (job.get("status") or "open") != "open":
        if q:
            await q.edit_message_text("⚠️ Αυτή η εργασία δεν είναι πλέον διαθέσιμη.", reply_markup=kb_back_to_jobs(), parse_mode="HTML")
        return

    # Assign (you can implement more complex flows later)
    _db().set_job_assigned(job_id, freelancer_user_id=db_user_id)

    if q:
        await q.edit_message_text(
            "✅ Τέλεια! Ανέλαβες την εργασία.\n\n"
            "📩 Επόμενο βήμα: σύντομα θα ανοίξει chat/συνεννόηση μέσα από το bot.",
            reply_markup=kb_back_to_jobs(),
            parse_mode="HTML",
        )


async def jobs_show_buy_freelancer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Placeholder: show instructions to buy.
    Replace with your real checkout flow (Stripe/PayPal/crypto) and then set users.is_freelancer = TRUE.
    """
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text(
            "💳 <b>Αγορά Freelancer Package</b>\n\n"
            "Αυτό είναι placeholder.\n"
            "Όταν συνδέσεις πληρωμές, εδώ θα γίνεται η αγορά.\n\n"
            "📌 Μετά την επιβεβαίωση πληρωμής: set users.is_freelancer = TRUE",
            reply_markup=kb_back_to_jobs(),
            parse_mode="HTML",
        )


# -------------------------
# Public: message handler
# -------------------------

async def jobs_handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Call this from your main text message handler.
    Returns True if the message was consumed by the jobs flow.
    """
    msg = update.effective_message
    if not msg or not msg.text:
        return False

    step = context.user_data.get(UD_STEP)
    if not step:
        return False

    text = msg.text.strip()

    # Step 1: title
    if step == "title":
        if len(text) < 3:
            await msg.reply_text("⚠️ Ο τίτλος είναι πολύ μικρός. Στείλε κάτι πιο περιγραφικό (>= 3 χαρακτήρες).")
            return True
        if len(text) > 120:
            await msg.reply_text("⚠️ Ο τίτλος είναι πολύ μεγάλος. Στείλε έως 120 χαρακτήρες.")
            return True

        context.user_data[UD_TITLE] = text
        context.user_data[UD_STEP] = "desc"
        await msg.reply_text("📄 Στείλε <b>περιγραφή</b> (τι ακριβώς χρειάζεσαι):", parse_mode="HTML")
        return True

    # Step 2: description
    if step == "desc":
        if len(text) < 10:
            await msg.reply_text("⚠️ Η περιγραφή είναι πολύ μικρή. Στείλε τουλάχιστον 10 χαρακτήρες.")
            return True
        if len(text) > 2000:
            await msg.reply_text("⚠️ Η περιγραφή είναι πολύ μεγάλη. Στείλε έως 2000 χαρακτήρες.")
            return True

        context.user_data[UD_DESC] = text
        context.user_data[UD_STEP] = "budget"
        await msg.reply_text("💰 Στείλε <b>budget</b> σε ευρώ (π.χ. 150):", parse_mode="HTML")
        return True

    # Step 3: budget
    if step == "budget":
        budget = _parse_budget(text)
        if budget is None:
            await msg.reply_text("⚠️ Δεν κατάλαβα budget. Στείλε έναν αριθμό (π.χ. 150).")
            return True

        title = context.user_data.get(UD_TITLE) or "—"
        desc = context.user_data.get(UD_DESC) or "—"
        db_user_id = _get_db_user_id_from_update(update)

        job_id = _db().create_job(
            user_id=db_user_id,
            title=title,
            description=desc,
            budget=budget,
        )

        # Clear flow
        context.user_data.pop(UD_STEP, None)
        context.user_data.pop(UD_TITLE, None)
        context.user_data.pop(UD_DESC, None)

        await msg.reply_text(
            f"{POST_SUCCESS_TEXT}\n\n"
            f"🆔 Job ID: <b>{job_id}</b>\n"
            f"Θα εμφανιστεί στη λίστα διαθέσιμων εργασιών.",
            parse_mode="HTML",
            reply_markup=kb_back_to_jobs(),
        )
        return True

    # Unknown step -> clear
    context.user_data.pop(UD_STEP, None)
    return False


# -------------------------
# Utilities
# -------------------------

def _parse_budget(s: str) -> Optional[int]:
    s = (s or "").strip()
    # allow "150", "150€", "150 eur"
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
        elif digits:
            # stop at first non-digit after starting
            break
    if not digits:
        return None
    try:
        v = int(digits)
        if v <= 0:
            return None
        return v
    except Exception:
        return None


def _escape_html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
