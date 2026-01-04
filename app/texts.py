# app/texts.py

# === Buttons (ΠΡΕΠΕΙ να υπάρχουν όπως τα περιμένει το bot/keyboard) ===
BTN_PROFILE = "👤 Το προφίλ μου"
BTN_VIDEO = "🎬 Δημιουργία βίντεο"
BTN_IMAGES = "🖼 Εικόνες"
BTN_AUDIO = "🎧 Ήχος"
BTN_PROMPTS = "💡 Κανάλι με prompts"
BTN_SUPPORT = "☁️ Υποστήριξη"

# === Your texts ===
START_TEXT = (
    "Καλώς ήρθες! 👋\n\n"
    "Το VeoLumiBot είναι το επίσημο AI bot δημιουργίας περιεχομένου.\n\n"
    "🎯 Όλες οι κορυφαίες AI τεχνολογίες σε ένα μέρος, με μία συνδρομή.\n\n"
    "Veo 3 • Nano Banana • Flux • Midjourney • Runway • Kling • Qwen\n"
    "και πολλά ακόμα.\n\n"
    "💰 Οι χαμηλότερες τιμές της αγοράς\n"
    "🌍 Πληρωμές από οποιοδήποτε σημείο του κόσμου\n"
    "💳 Κάρτες • Crypto • PayPal\n\n"
    "👇 Επίλεξε από το μενού για να ξεκινήσεις"
)

CREDITS_TEXT = (
    "⚡ Σου προστέθηκαν 5 credits!\n\n"
    "Μπορείς να τα χρησιμοποιήσεις για:\n"
    "🎬 Βίντεο\n"
    "🖼 Εικόνες\n"
    "🎧 Ήχο\n\n"
    "Καλή δημιουργία 🚀"
)

# Προσοχή: username μπορεί να είναι None
PROFILE_TEXT = (
    "👤 Το προφίλ σου\n\n"
    "🆔 Telegram ID: {tg_user_id}\n"
    "👤 Username: {username}\n\n"
    "⚡ Credits διαθέσιμα: {credits}"
)

ABOUT_TEXT = (
    "Τι μπορεί να κάνει αυτό το bot;\n\n"
    "Το VeoLumiBot είναι επίσημο AI εργαλείο δημιουργίας.\n\n"
    "Πατώντας /start αποδέχεσαι:\n"
    "• τους Όρους Χρήσης\n"
    "• την Πολιτική Απορρήτου\n\n"
    "🔗 https://telegra.ph/OROI-CHRISIS-VeoLumiBot"
)

# === Aliases για συμβατότητα με το bot.py που έχεις ===
WELCOME = START_TEXT

# Αν το bot.py κάνει format(PROFILE_FMT.format(...))
PROFILE_FMT = (
    "👤 *Το προφίλ μου*\n\n"
    "🆔 Telegram ID: `{tg_user_id}`\n"
    "👤 Username: *{username}*\n"
    "⚡ Credits: *{credits}*\n"
)
