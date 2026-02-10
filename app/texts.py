# app/texts.py

# === Buttons (ΠΡΕΠΕΙ να υπάρχουν όπως τα περιμένει το bot/keyboard) ===
BTN_PROFILE = "👤 Το προφίλ μου"
BTN_VIDEO = "🎬 Δημιουργία βίντεο"
BTN_IMAGES = "🖼 Εικόνες"
BTN_AUDIO = "🎧 Ήχος"
BTN_PROMPTS = "💡 Κανάλι με prompts"
BTN_SUPPORT = "☁️ Υποστήριξη"
BTN_MENU = "📋 Μενού"

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


# ==========================
# Friendly Tool Error (GR)
# ==========================

def map_provider_error_to_gr(raw_error: str) -> tuple[str, str]:
    """Μετατρέπει raw provider error σε (αιτία, τι να κάνεις) στα Ελληνικά."""
    e = (raw_error or "").lower()

    # Policy / moderation / blocked prompt
    if any(k in e for k in [
        "policy", "content policy", "moderation", "safety", "unsafe",
        "failed the review", "disallowed", "prohibited", "blocked",
        "prompt was rejected", "rejected"
    ]):
        return (
            "Το κείμενο/περιεχόμενο απορρίφθηκε (μη επιτρεπτό περιεχόμενο).",
            "Άλλαξε τη διατύπωση και απόφυγε ευαίσθητους ή απαγορευμένους όρους."
        )

    # Rate limit / quota
    if any(k in e for k in ["rate limit", "too many requests", "quota", "429"]):
        return (
            "Το εργαλείο έχει προσωρινό φόρτο (πάρα πολλά αιτήματα).",
            "Δοκίμασε ξανά σε λίγο ή με πιο σύντομο prompt."
        )

    # Timeouts / provider down
    if any(k in e for k in ["timeout", "timed out", "gateway", "502", "503", "504"]):
        return (
            "Το εργαλείο δεν απάντησε εγκαίρως.",
            "Δοκίμασε ξανά σε 30–60 δευτερόλεπτα."
        )

    # Bad/invalid images
    if any(k in e for k in ["invalid image", "cannot decode", "unsupported", "bad image", "corrupt"]):
        return (
            "Η εικόνα δεν διαβάζεται σωστά ή δεν υποστηρίζεται.",
            "Δοκίμασε άλλη εικόνα (JPG/PNG) ή ξανα-ανέβασέ την."
        )

    # Generic
    return (
        "Παρουσιάστηκε σφάλμα κατά τη δημιουργία.",
        "Δοκίμασε ξανά ή άλλαξε λίγο το prompt."
    )


def tool_error_message_gr(*, reason: str, tips: str, refunded: float | None = None) -> str:
    """Το μήνυμα που θα βλέπει ο χρήστης στο Telegram (χωρίς raw errors)."""
    msg = (
        "⛔ Δεν μπόρεσα να δημιουργήσω αποτέλεσμα\n"
        f"Αιτία: {reason}\n"
        f"Τι να κάνεις: {tips}"
    )
    if refunded is not None:
        msg += f"\n\n💎 Τα credits επιστράφηκαν: {refunded:.2f}"
    return msg
