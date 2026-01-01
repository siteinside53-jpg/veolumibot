import os
from typing import Optional, Dict
from datetime import datetime

import psycopg
import psycopg.rows

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ======================
# ENV
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Λείπει το BOT_TOKEN (Railway Variables)")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Λείπει το DATABASE_URL (Railway Variables). Πρόσθεσε PostgreSQL στο Railway.")

# ======================
# UI
# ======================
BTN_PROFILE = "👤 Το προφίλ μου"
BTN_VIDEO = "🎬 Δημιουργία βίντεο"
BTN_IMAGES = "🖼 Εικόνες"
BTN_AUDIO = "🎵 Ήχος"
BTN_PROMPTS = "💡 Κανάλι με prompts"
BTN_SUPPORT = "☁️ Υποστήριξη"

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(BTN_PROFILE)],
        [KeyboardButton(BTN_VIDEO)],
        [KeyboardButton(BTN_IMAGES)],
        [KeyboardButton(BTN_AUDIO)],
        [KeyboardButton(BTN_PROMPTS)],
        [KeyboardButton(BTN_SUPPORT)],
    ],
    resize_keyboard=True,
)

WELCOME_TEXT = (
    "Καλώς ήρθες! 👋\n"
    "Εδώ έχεις τα TOP AI εργαλεία σε ένα μέρος ✅\n\n"
    "Veo, Nano Banana, Flux, Midjourney, Runway, Kling και άλλα.\n"
    "Πολύ χαμηλές τιμές στην αγορά 🧃\n\n"
    "Πληρωμή με κάρτα / crypto / PayPal.\n"
    "Πρόσβαση από οπουδήποτε 🌍\n"
)

FREE_CREDITS_ON_FIRST_START = 5

# ======================
# STATE (μόνο προσωρινά στη μνήμη)
# Τα credits πλέον είναι στη DB
# ======================
USER_STATE: Dict[int, Optional[str]] = {}
USER_SELECTED_IMAGE_MODEL: Dict[int, Optional[str]] = {}

# ======================
# DB HELPERS
# ======================

def db_conn():
    # Railway DATABASE_URL είναι postgres://...
    return psycopg.connect(
        DATABASE_URL,
        row_factory=psycopg.rows.dict_row
    )
    
def init_db():
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                credits INT NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                type TEXT NOT NULL,              -- 'grant' | 'buy' | 'spend'
                amount INT NOT NULL,             -- positive int
                meta JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """)
        conn.commit()

def get_user(user_id: int):
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s;", (user_id,))
            return cur.fetchone()

def create_user_if_missing(user_id: int, username: str):
    """
    Αν δεν υπάρχει user, τον δημιουργεί και του δίνει FREE credits (μία φορά).
    """
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE user_id = %s;", (user_id,))
            exists = cur.fetchone()
            if exists:
                # update username αν άλλαξε
                cur.execute(
                    "UPDATE users SET username=%s, updated_at=NOW() WHERE user_id=%s;",
                    (username, user_id)
                )
                conn.commit()
                return False  # not first time

            # create with free credits
            cur.execute(
                "INSERT INTO users (user_id, username, credits) VALUES (%s, %s, %s);",
                (user_id, username, FREE_CREDITS_ON_FIRST_START)
            )
            cur.execute(
                "INSERT INTO transactions (user_id, type, amount, meta) VALUES (%s, 'grant', %s, %s);",
                (user_id, FREE_CREDITS_ON_FIRST_START, '{"reason":"first_start"}')
            )
            conn.commit()
            return True  # first time

def get_credits(user_id: int) -> int:
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT credits FROM users WHERE user_id=%s;", (user_id,))
            row = cur.fetchone()
            return int(row["credits"]) if row else 0

def add_credits(user_id: int, amount: int, tx_type: str, meta_json: str = "{}"):
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET credits = credits + %s, updated_at=NOW() WHERE user_id=%s;", (amount, user_id))
            cur.execute(
                "INSERT INTO transactions (user_id, type, amount, meta) VALUES (%s, %s, %s, %s::jsonb);",
                (user_id, tx_type, amount, meta_json)
            )
        conn.commit()

def spend_credits(user_id: int, amount: int, meta_json: str = "{}") -> bool:
    """
    Αφαιρεί credits αν υπάρχουν αρκετά. Επιστρέφει True/False.
    """
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT credits FROM users WHERE user_id=%s FOR UPDATE;", (user_id,))
            row = cur.fetchone()
            if not row:
                return False
            current = int(row["credits"])
            if current < amount:
                return False
            cur.execute("UPDATE users SET credits = credits - %s, updated_at=NOW() WHERE user_id=%s;", (amount, user_id))
            cur.execute(
                "INSERT INTO transactions (user_id, type, amount, meta) VALUES (%s, 'spend', %s, %s::jsonb);",
                (user_id, amount, meta_json)
            )
        conn.commit()
        return True

# ======================
# INLINE KEYBOARDS
# ======================

def image_models_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🍌 Nano Banana Pro (1 credit)", callback_data="img_model:nano")],
            [InlineKeyboardButton("🌈 Midjourney (2 credits)", callback_data="img_model:midjourney")],
            [InlineKeyboardButton("⚡ Flux (1 credit)", callback_data="img_model:flux")],
            [InlineKeyboardButton("⬅️ Πίσω", callback_data="back:main")],
        ]
    )

def buy_credits_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 10 credits (test)", callback_data="buy:10")],
            [InlineKeyboardButton("➕ 50 credits (test)", callback_data="buy:50")],
            [InlineKeyboardButton("⬅️ Πίσω", callback_data="back:main")],
        ]
    )

def cost_for_image_model(model: str) -> int:
    return {"nano": 1, "midjourney": 2, "flux": 1}.get(model, 1)

def model_label(model: str) -> str:
    return {"nano": "Nano Banana Pro", "midjourney": "Midjourney", "flux": "Flux"}.get(model, model)

def profile_text(user_id: int, username: str) -> str:
    credits = get_credits(user_id)
    return (
        "👤 Το προφίλ μου\n"
        f"• Χρήστης: @{username if username else 'unknown'}\n"
        f"• Credits: {credits}\n\n"
        "Θες να αγοράσεις credits;"
    )

# ======================
# HANDLERS
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    first_time = create_user_if_missing(user.id, user.username or "")

    USER_STATE[user.id] = None
    USER_SELECTED_IMAGE_MODEL[user.id] = None

    msg = WELCOME_TEXT
    if first_time:
        msg += f"\n✅ Σου δόθηκαν {FREE_CREDITS_ON_FIRST_START} credits ⚡ (μόνο την 1η φορά)\n"
    msg += "\nΧρησιμοποίησε το μενού κάτω 👇"

    await update.message.reply_text(msg, reply_markup=MAIN_MENU)

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user_if_missing(user.id, user.username or "")

    text = (update.message.text or "").strip()

    # αν περιμένουμε prompt για εικόνα
    if USER_STATE.get(user.id) == "awaiting_image_prompt":
        await handle_image_prompt(update, context)
        return

    if text == BTN_PROFILE:
        await update.message.reply_text(profile_text(user.id, user.username or ""), reply_markup=MAIN_MENU)
        await update.message.reply_text("💳 Αγορά credits:", reply_markup=buy_credits_keyboard())
        return

    if text == BTN_IMAGES:
        USER_STATE[user.id] = None
        USER_SELECTED_IMAGE_MODEL[user.id] = None
        await update.message.reply_text("🖼 Διάλεξε μοντέλο για δημιουργία εικόνας:", reply_markup=MAIN_MENU)
        await update.message.reply_text("Επιλογές μοντέλου:", reply_markup=image_models_keyboard())
        return

    if text == BTN_VIDEO:
        await update.message.reply_text("🎬 Δημιουργία βίντεο: (έρχεται)", reply_markup=MAIN_MENU)
        return

    if text == BTN_AUDIO:
        await update.message.reply_text("🎵 Εργαλεία ήχου: (έρχεται)", reply_markup=MAIN_MENU)
        return

    if text == BTN_PROMPTS:
        await update.message.reply_text("💡 Κανάλι με prompts: (βάλε link εδώ)", reply_markup=MAIN_MENU)
        return

    if text == BTN_SUPPORT:
        await update.message.reply_text("☁️ Υποστήριξη: (βάλε στοιχεία επικοινωνίας εδώ)", reply_markup=MAIN_MENU)
        return

    await update.message.reply_text("Χρησιμοποίησε το μενού κάτω 👇", reply_markup=MAIN_MENU)

async def on_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    create_user_if_missing(user.id, user.username or "")

    data = query.data or ""
    await query.answer()

    if data == "back:main":
        USER_STATE[user.id] = None
        USER_SELECTED_IMAGE_MODEL[user.id] = None
        await query.edit_message_text("✅ Επιστροφή στο κεντρικό μενού. Χρησιμοποίησε τα κουμπιά κάτω 👇")
        return

    if data.startswith("buy:"):
        amount = int(data.split(":")[1])
        add_credits(user.id, amount, "buy", meta_json=f'{{"source":"test_button","amount":{amount}}}')
        await query.edit_message_text(f"✅ Προστέθηκαν {amount} credits.\nCredits τώρα: {get_credits(user.id)}")
        return

    if data.startswith("img_model:"):
        model = data.split(":")[1]
        USER_SELECTED_IMAGE_MODEL[user.id] = model
        USER_STATE[user.id] = "awaiting_image_prompt"

        cost = cost_for_image_model(model)
        await query.edit_message_text(
            f"✅ Διάλεξες: {model_label(model)}\n"
            f"Κόστος: {cost} credit(s)\n\n"
            "✍️ Γράψε τώρα το prompt σου (σε ένα μήνυμα)."
        )
        return

async def handle_image_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user_if_missing(user.id, user.username or "")

    prompt = (update.message.text or "").strip()
    model = USER_SELECTED_IMAGE_MODEL.get(user.id)

    if not model:
        USER_STATE[user.id] = None
        await update.message.reply_text("❌ Δεν έχει επιλεγεί μοντέλο. Πάτα: 🖼 Εικόνες", reply_markup=MAIN_MENU)
        return

    cost = cost_for_image_model(model)
    ok = spend_credits(user.id, cost, meta_json=f'{{"tool":"image","model":"{model}","prompt":"{prompt[:200]}"}}')

    USER_STATE[user.id] = None
    USER_SELECTED_IMAGE_MODEL[user.id] = None

    if not ok:
        await update.message.reply_text(
            f"❌ Δεν έχεις αρκετά credits.\n"
            f"Έχεις: {get_credits(user.id)} | Χρειάζονται: {cost}\n\n"
            "Πήγαινε στο 👤 Το προφίλ μου για αγορά credits.",
            reply_markup=MAIN_MENU
        )
        return

    # MOCK αποτέλεσμα
    await update.message.reply_text(
        "🧪 (Δοκιμή) Δημιουργία εικόνας...\n"
        f"Μοντέλο: {model_label(model)}\n"
        f"Prompt: {prompt}\n\n"
        f"✅ Χρεώθηκαν {cost} credits. Υπόλοιπο: {get_credits(user.id)}",
        reply_markup=MAIN_MENU
    )

def main():
    init_db()  # ✅ δημιουργεί tables αν δεν υπάρχουν

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_inline))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    app.run_polling()

if __name__ == "__main__":
    main()
