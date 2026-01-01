import os
from typing import Dict, Optional

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
# CONFIG
# ======================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Λείπει το BOT_TOKEN (Railway Variables)")

# Menu labels (Reply Keyboard)
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

# ======================
# SIMPLE IN-MEMORY STORE (για testing)
# (Μετά το κάνουμε DB)
# ======================

# credits per user_id
USER_CREDITS: Dict[int, int] = {}

# state per user_id
# possible: None | "awaiting_image_prompt" | "awaiting_video_prompt" | "awaiting_audio_prompt"
USER_STATE: Dict[int, Optional[str]] = {}

# selected model per user_id
USER_SELECTED_IMAGE_MODEL: Dict[int, Optional[str]] = {}

# Initial free credits for first time users
FREE_CREDITS_ON_FIRST_START = 5


def ensure_user(user_id: int) -> None:
    """Initialize user if not exists."""
    if user_id not in USER_CREDITS:
        USER_CREDITS[user_id] = FREE_CREDITS_ON_FIRST_START
    if user_id not in USER_STATE:
        USER_STATE[user_id] = None
    if user_id not in USER_SELECTED_IMAGE_MODEL:
        USER_SELECTED_IMAGE_MODEL[user_id] = None


# ======================
# HELPERS: UI
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
            [InlineKeyboardButton("➕ 10 credits (Mock)", callback_data="buy:10")],
            [InlineKeyboardButton("➕ 50 credits (Mock)", callback_data="buy:50")],
            [InlineKeyboardButton("⬅️ Πίσω", callback_data="back:main")],
        ]
    )

def video_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎬 Veo (coming)", callback_data="vid_model:veo")],
            [InlineKeyboardButton("🎞 Runway (coming)", callback_data="vid_model:runway")],
            [InlineKeyboardButton("🌀 Kling (coming)", callback_data="vid_model:kling")],
            [InlineKeyboardButton("⬅️ Πίσω", callback_data="back:main")],
        ]
    )

def audio_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗣 Text → Voice (coming)", callback_data="aud:tts")],
            [InlineKeyboardButton("🎭 Voice → Voice (coming)", callback_data="aud:voice2voice")],
            [InlineKeyboardButton("🎛 Sound FX (coming)", callback_data="aud:sfx")],
            [InlineKeyboardButton("⬅️ Πίσω", callback_data="back:main")],
        ]
    )

def profile_text(user_id: int, username: str) -> str:
    credits = USER_CREDITS.get(user_id, 0)
    return (
        "👤 Το προφίλ μου\n"
        f"• Χρήστης: @{username if username else 'unknown'}\n"
        f"• Credits: {credits}\n\n"
        "Θες να αγοράσεις credits;"
    )


def cost_for_image_model(model: str) -> int:
    return {"nano": 1, "midjourney": 2, "flux": 1}.get(model, 1)


def model_label(model: str) -> str:
    return {"nano": "Nano Banana Pro", "midjourney": "Midjourney", "flux": "Flux"}.get(model, model)


# ======================
# HANDLERS
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)

    # reset state on start
    USER_STATE[user.id] = None
    USER_SELECTED_IMAGE_MODEL[user.id] = None

    # show welcome + menu + free credits line (only if first time already handled in ensure_user)
    welcome = WELCOME_TEXT + f"\n✅ Σου δόθηκαν {FREE_CREDITS_ON_FIRST_START} credits ⚡ (για δοκιμή)\n\n" \
                            "Χρησιμοποίησε το μενού κάτω 👇"
    await update.message.reply_text(welcome, reply_markup=MAIN_MENU)


async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)

    text = (update.message.text or "").strip()

    # If user is in a state waiting for prompt, treat message as prompt
    if USER_STATE.get(user.id) == "awaiting_image_prompt":
        await handle_image_prompt(update, context)
        return

    if text == BTN_PROFILE:
        await update.message.reply_text(profile_text(user.id, user.username or ""), reply_markup=MAIN_MENU)
        # show inline buy options as separate message (like app screens)
        await update.message.reply_text("💳 Αγορά credits:", reply_markup=buy_credits_keyboard())
        return

    if text == BTN_IMAGES:
        USER_STATE[user.id] = None
        USER_SELECTED_IMAGE_MODEL[user.id] = None
        await update.message.reply_text("🖼 Διάλεξε μοντέλο για δημιουργία εικόνας:", reply_markup=MAIN_MENU)
        await update.message.reply_text("Επιλογές μοντέλου:", reply_markup=image_models_keyboard())
        return

    if text == BTN_VIDEO:
        await update.message.reply_text("🎬 Δημιουργία βίντεο (menu):", reply_markup=MAIN_MENU)
        await update.message.reply_text("Επιλογές:", reply_markup=video_menu_keyboard())
        return

    if text == BTN_AUDIO:
        await update.message.reply_text("🎵 Εργαλεία ήχου (menu):", reply_markup=MAIN_MENU)
        await update.message.reply_text("Επιλογές:", reply_markup=audio_menu_keyboard())
        return

    if text == BTN_PROMPTS:
        await update.message.reply_text("💡 Κανάλι με prompts: (βάλε εδώ link όταν είναι έτοιμο)\n\nπ.χ. https://t.me/TO_KANALI_SOU", reply_markup=MAIN_MENU)
        return

    if text == BTN_SUPPORT:
        await update.message.reply_text("☁️ Υποστήριξη:\nΣτείλε μήνυμα εδώ ή βάλε email/φόρμα.\n\n(βάλε στοιχεία επικοινωνίας)", reply_markup=MAIN_MENU)
        return

    await update.message.reply_text("Χρησιμοποίησε το μενού κάτω 👇", reply_markup=MAIN_MENU)


async def on_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all inline button callbacks."""
    query = update.callback_query
    user = update.effective_user
    ensure_user(user.id)

    data = query.data or ""
    await query.answer()

    # Back to main
    if data == "back:main":
        USER_STATE[user.id] = None
        USER_SELECTED_IMAGE_MODEL[user.id] = None
        await query.edit_message_text("✅ Επιστροφή στο κεντρικό μενού. Χρησιμοποίησε τα κουμπιά κάτω 👇")
        return

    # Buy credits (mock)
    if data.startswith("buy:"):
        amount = int(data.split(":")[1])
        USER_CREDITS[user.id] += amount
        await query.edit_message_text(f"✅ Προστέθηκαν {amount} credits (δοκιμαστικό).\nCredits τώρα: {USER_CREDITS[user.id]}")
        return

    # Image model select
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

    # Video model select (coming)
    if data.startswith("vid_model:"):
        model = data.split(":")[1]
        await query.edit_message_text(f"🎬 {model.upper()} (coming soon)\nΘα το ενεργοποιήσουμε μετά.")
        return

    # Audio actions (coming)
    if data.startswith("aud:"):
        await query.edit_message_text("🎵 Coming soon — θα το ενεργοποιήσουμε μετά.")
        return


async def handle_image_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)

    prompt = (update.message.text or "").strip()
    model = USER_SELECTED_IMAGE_MODEL.get(user.id)

    if not model:
        USER_STATE[user.id] = None
        await update.message.reply_text("❌ Δεν έχει επιλεγεί μοντέλο. Πάτα: 🖼 Εικόνες", reply_markup=MAIN_MENU)
        return

    # Check credits
    cost = cost_for_image_model(model)
    credits = USER_CREDITS.get(user.id, 0)

    if credits < cost:
        USER_STATE[user.id] = None
        USER_SELECTED_IMAGE_MODEL[user.id] = None
        await update.message.reply_text(
            f"❌ Δεν έχεις αρκετά credits.\nΈχεις: {credits} | Χρειάζονται: {cost}\n\n"
            "Πήγαινε στο 👤 Το προφίλ μου για αγορά credits.",
            reply_markup=MAIN_MENU
        )
        return

    # Spend credits
    USER_CREDITS[user.id] -= cost

    # Reset state
    USER_STATE[user.id] = None
    USER_SELECTED_IMAGE_MODEL[user.id] = None

    # MOCK result (no real API yet)
    await update.message.reply_text(
        "🧪 (Δοκιμή) Δημιουργία εικόνας...\n"
        f"Μοντέλο: {model_label(model)}\n"
        f"Prompt: {prompt}\n\n"
        f"✅ Χρεώθηκαν {cost} credits. Υπόλοιπο: {USER_CREDITS[user.id]}",
        reply_markup=MAIN_MENU
    )

    # Here later we'll call real API and then send photo:
    # await update.message.reply_photo(photo=image_url, caption="✅ Έτοιμο!")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_inline))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    app.run_polling()


if __name__ == "__main__":
    main()
