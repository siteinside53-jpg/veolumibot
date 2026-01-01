import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv(8539722268:AAFhP7u_P9AE1SMU_Y6x0NsOcSG6Rxs9Ikw)
if not BOT_TOKEN:
    raise RuntimeError("Λείπει το BOT_TOKEN (Railway Variables)")

# ✅ Μόνιμο κάτω μενού (όπως στο παράδειγμα, στα Ελληνικά)
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("👤 Το προφίλ μου")],
        [KeyboardButton("🎬 Δημιουργία βίντεο")],
        [KeyboardButton("🖼 Εικόνες (Image Generation)")],
        [KeyboardButton("🎵 Ήχος (Audio)")],
        [KeyboardButton("💡 Κανάλι με prompts")],
        [KeyboardButton("☁️ Υποστήριξη")],
    ],
    resize_keyboard=True,
)

WELCOME_TEXT = (
    "Καλώς ήρθες! 👋\n"
    "Εδώ έχεις τα TOP AI εργαλεία σε ένα μέρος ✅\n\n"
    "Veo, Nano Banana, Flux, Midjourney, Runway, Kling και άλλα.\n"
    "Πολύ χαμηλές τιμές στην αγορά 🧃\n\n"
    "Πληρωμή με κάρτα / crypto / PayPal.\n"
    "Πρόσβαση από οπουδήποτε 🌍\n\n"
    "✅ Σου δόθηκαν 5 credits ⚡"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Στέλνουμε welcome + εμφανίζουμε το κάτω μενού
    await update.message.reply_text(WELCOME_TEXT, reply_markup=MAIN_MENU)

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "👤 Το προφίλ μου":
        await update.message.reply_text(
            "👤 Προφίλ\n"
            "Credits: (σύντομα)\n"
            "Πακέτα credits: (σύντομα)\n"
            "Ιστορικό: (σύντομα)"
        )
        return

    if text == "🖼 Εικόνες (Image Generation)":
        await update.message.reply_text(
            "🖼 Επιλογή μοντέλου εικόνας (σύντομα):\n"
            "• Nano Banana Pro\n"
            "• Midjourney\n"
            "• Flux\n\n"
            "Θέλεις να το κάνουμε με κουμπιά επιλογής (inline) όπως στο VeoSeeBot;"
        )
        return

    if text == "🎬 Δημιουργία βίντεο":
        await update.message.reply_text(
            "🎬 Βίντεο (σύντομα):\n"
            "• Veo\n"
            "• Runway\n"
            "• Kling"
        )
        return

    if text == "🎵 Ήχος (Audio)":
        await update.message.reply_text(
            "🎵 Ήχος (σύντομα):\n"
            "• Text to Speech\n"
            "• Voice αλλαγή\n"
            "• Sound FX"
        )
        return

    if text == "💡 Κανάλι με prompts":
        await update.message.reply_text("💡 Κανάλι: (θα βάλουμε link εδώ)")
        return

    if text == "☁️ Υποστήριξη":
        await update.message.reply_text("☁️ Υποστήριξη: (θα βάλουμε τρόπο επικοινωνίας)")
        return

    await update.message.reply_text("Χρησιμοποίησε το μενού κάτω 👇", reply_markup=MAIN_MENU)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    app.run_polling()

if __name__ == "__main__":
    main()
