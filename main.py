#Add main bot code#
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = "8539722268:AAFhP7u_P9AE1SMU_Y6x0NsOcSG6Rxs9Ikw"  # βάλε εδώ το token από @BotFather

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Option 1", callback_data='1')],
        [InlineKeyboardButton("Option 2", callback_data='2')],
        [InlineKeyboardButton("Option 3", callback_data='3')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Καλώς ήρθες στο Lumibot! Επιλέξτε μία επιλογή:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text=f"Επιλέξατε: {query.data}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()
