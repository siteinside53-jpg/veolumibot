# app/texts.py

# === Buttons (ΠΡΕΠΕΙ να υπάρχουν όπως τα περιμένει το bot/keyboard) ===
BTN_PROFILE = "👤 Το προφίλ μου"
BTN_VIDEO = "🎬 Δημιουργία βίντεο"
BTN_IMAGES = "🖼 Εικόνες"
BTN_AUDIO = "🎧 Ήχος"
BTN_PROMPTS = "💡 Κανάλι με prompts"
BTN_SUPPORT = "☁️ Υποστήριξη"

# === START CARD (σαν αυτού) ===
START_CAPTION = (
    "Καλώς ήρθατε!\n"
    "Το bot μας — όλες οι TOP AI τεχνολογίες σε ένα μέρος, με μία συνδρομή ✅\n\n"
    "Veo 3 • Nano Banana • Flux • Midjourney\n"
    "Runway • Kling • Qwen και πολλά ακόμα.\n\n"
    "Οι χαμηλότερες τιμές στην αγορά 💵\n"
    "Πληρωμές από οποιοδήποτε σημείο του κόσμου 🌍\n"
    "Κάρτες • Crypto • PayPal 💳\n\n"
    "👇 Διάλεξε από το μενού"
)

# (αν κάπου αλλού χρησιμοποιείς START_TEXT / WELCOME, τα κρατάμε)
START_TEXT = START_CAPTION
WELCOME = START_CAPTION

CREDITS_TEXT = (
    "⚡ Σου προστέθηκαν 5 credits!\n\n"
    "Μπορείς να τα χρησιμοποιήσεις για:\n"
    "🎬 Βίντεο\n"
    "🖼 Εικόνες\n"
    "🎧 Ήχο\n\n"
    "Καλή δημιουργία 🚀"
)

# Απλό profile (χωρίς markdown)
PROFILE_TEXT = (
    "👤 Το προφίλ σου\n\n"
    "🆔 Telegram ID: {tg_user_id}\n"
    "👤 Username: {username}\n\n"
    "⚡ Credits διαθέσιμα: {credits}"
)

# Markdown profile (για bot.py που έχει ParseMode.MARKDOWN)
PROFILE_MD = (
    "👤 *Το προφίλ μου*\n\n"
    "🆔 Telegram ID: `{tg_user_id}`\n"
    "👤 Username: *{username}*\n"
    "⚡ Credits: *{credits}*\n"
)

# alias για συμβατότητα με παλιότερο κώδικα
PROFILE_FMT = PROFILE_MD

ABOUT_TEXT = (
    "Τι μπορεί να κάνει αυτό το bot;\n\n"
    "Το VeoLumiBot είναι επίσημο AI εργαλείο δημιουργίας.\n\n"
    "Πατώντας /start αποδέχεσαι:\n"
    "• τους Όρους Χρήσης\n"
    "• την Πολιτική Απορρήτου\n\n"
    "🔗 https://telegra.ph/OROI-CHRISIS-VeoLumiBot"
)
