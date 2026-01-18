# app/db.py
import os
from pathlib import Path
from decimal import Decimal
from typing import Optional, List, Dict, Any
import secrets
import json
import uuid
from datetime import datetime, timezone

import psycopg
import psycopg.rows

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Λείπει το DATABASE_URL")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MAX_REF_LINKS = 10

# Start credits for new users
START_FREE_CREDITS = Decimal("5.00")


# ----------------------
# Connections
# ----------------------
def _conn_autocommit():
    # Για migrations / απλά queries
    return psycopg.connect(DATABASE_URL, autocommit=True)


def get_conn():
    # Για app transactions (dict_row) + autocommit=False by default
    return psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)


# ----------------------
# Helpers
# ----------------------
def _to_decimal(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------
# Migrations bootstrap
# ----------------------
def run_migrations():
    """
    Ensures base tables exist even if migrations folder is missing.
    Also performs lightweight, idempotent schema upgrades (ADD COLUMN IF NOT EXISTS).
    Then applies .sql migrations if present.
    """
    print(">>> RUNNING MIGRATIONS <<<", flush=True)
    print(f">>> migrations dir = {MIGRATIONS_DIR}", flush=True)

    with _conn_autocommit() as conn:
        with conn.cursor() as cur:
            # -------------------------
            # users (base)
            # -------------------------
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
              id SERIAL PRIMARY KEY,
              tg_user_id BIGINT UNIQUE NOT NULL,
              tg_username TEXT,
              tg_first_name TEXT,
              credits NUMERIC(10,2) NOT NULL DEFAULT 0,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)

            # --- upgrades for users ---
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credits_held NUMERIC(10,2) NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();")

            # -------------------------
            # credit_ledger
            # -------------------------
            cur.execute("""
            CREATE TABLE IF NOT EXISTS credit_ledger (
              id SERIAL PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              delta NUMERIC(10,2) NOT NULL,
              balance_after NUMERIC(10,2) NOT NULL,
              reason TEXT NOT NULL,
              provider TEXT,
              provider_ref TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)

            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_id_created_at
            ON credit_ledger(user_id, created_at DESC);
            """)

            # -------------------------
            # last_results
            # -------------------------
            cur.execute("""
            CREATE TABLE IF NOT EXISTS last_results (
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              model TEXT NOT NULL,
              result_url TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (user_id, model)
            );
            """)

            # -------------------------
            # credit_holds
            # -------------------------
            cur.execute("""
            CREATE TABLE IF NOT EXISTS credit_holds (
              id SERIAL PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              amount NUMERIC(10,2) NOT NULL,
              status TEXT NOT NULL DEFAULT 'held', -- held | captured | released
              reason TEXT,
              provider TEXT,
              provider_ref TEXT,
              idempotency_key TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)

            # unique idempotency per user (only when key not null)
            cur.execute("""
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'credit_holds_user_idempotency_uq'
              ) THEN
                CREATE UNIQUE INDEX credit_holds_user_idempotency_uq
                ON credit_holds(user_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL;
              END IF;
            END$$;
            """)

            # -------------------------
            # generation_jobs
            # -------------------------
            cur.execute("""
            CREATE TABLE IF NOT EXISTS generation_jobs (
              id UUID PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              model TEXT NOT NULL,
              mode TEXT,
              hold_id INTEGER REFERENCES credit_holds(id) ON DELETE SET NULL,
              provider_job_id TEXT,
              status TEXT NOT NULL DEFAULT 'queued', -- queued|in_progress|completed|failed|canceled
              progress INTEGER,
              prompt TEXT,
              params JSONB,
              result_url TEXT,
              error TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)

            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_generation_jobs_user_created_at
            ON generation_jobs(user_id, created_at DESC);
            """)

            # -------------------------
            # referrals
            # -------------------------
            cur.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
              id SERIAL PRIMARY KEY,
              owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              code TEXT UNIQUE NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS referral_joins (
              id SERIAL PRIMARY KEY,
              referral_id INTEGER NOT NULL REFERENCES referrals(id) ON DELETE CASCADE,
              invited_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(referral_id, invited_user_id)
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS referral_events (
              id SERIAL PRIMARY KEY,
              referral_id INTEGER NOT NULL REFERENCES referrals(id) ON DELETE CASCADE,
              event_type TEXT NOT NULL, -- 'start' | 'purchase'
              amount_eur NUMERIC(10,2),
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)

            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_referral_events_referral_id_created_at
            ON referral_events(referral_id, created_at DESC);
            """)

            print(">>> ensured base tables exist (users/ledger/holds/jobs/referrals/last_results)", flush=True)

    # Apply .sql migrations if any
    if not MIGRATIONS_DIR.exists():
        print(">>> migrations folder ΔΕΝ βρέθηκε — συνεχίζουμε χωρίς crash", flush=True)
        return

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        print(">>> Δεν υπάρχουν .sql migrations", flush=True)
        return

    with _conn_autocommit() as conn:
        with conn.cursor() as cur:
            for f in sql_files:
                print(f">>> applying {f.name}", flush=True)
                cur.execute(f.read_text(encoding="utf-8"))
    with _conn_autocommit() as conn:
        with conn.cursor() as cur:
            for f in sql_files:
                print(f">>> applying {f.name}", flush=True)
                cur.execute(f.read_text(encoding="utf-8"))


# ======================
# Users
# ======================
def ensure_user(tg_user_id: int, tg_username: Optional[str], tg_first_name: Optional[str]) -> Dict[str, Any]:
    """
    Creates user if missing.
    If new user -> gives START_FREE_CREDITS and writes credit_ledger entry.
    Always updates username/first_name on existing users.
    Returns user row (dict).
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (tg_user_id, tg_username, tg_first_name, credits, credits_held)
                VALUES (%s, %s, %s, %s, 0)
                ON CONFLICT (tg_user_id) DO NOTHING
                RETURNING *;
                """,
                (tg_user_id, tg_username, tg_first_name, START_FREE_CREDITS),
            )
            inserted = cur.fetchone()

            if inserted:
                cur.execute(
                    """
                    INSERT INTO credit_ledger (user_id, delta, balance_after, reason, provider, provider_ref)
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    (
                        inserted["id"],
                        START_FREE_CREDITS,
                        inserted["credits"],
                        "Free start credits",
                        "system",
                        None,
                    ),
                )
                conn.commit()
                return inserted

            cur.execute(
                """
                UPDATE users
                SET tg_username = %s,
                    tg_first_name = %s
                WHERE tg_user_id = %s
                RETURNING *;
                """,
                (tg_username, tg_first_name, tg_user_id),
            )
            row = cur.fetchone()
            conn.commit()
            return row


def get_user(tg_user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE tg_user_id=%s", (tg_user_id,))
            return cur.fetchone()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
            return cur.fetchone()


# ======================
# Credits + Ledger (atomic)
# ======================
def add_credits_by_user_id(
    user_id: int,
    amount,
    reason: str,
    provider: Optional[str] = None,
    provider_ref: Optional[str] = None,
) -> Decimal:
    """
    Adds credits and writes credit_ledger entry atomically.
    Returns new balance (Decimal).
    """
    amount = _to_decimal(amount)
    if amount <= 0:
        raise ValueError("amount must be > 0")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, credits FROM users WHERE id=%s FOR UPDATE", (user_id,))
            u = cur.fetchone()
            if not u:
                raise RuntimeError("User not found")

            new_balance = _to_decimal(u["credits"]) + amount

            cur.execute("UPDATE users SET credits=%s WHERE id=%s", (new_balance, user_id))
            cur.execute(
                """
                INSERT INTO credit_ledger (user_id, delta, balance_after, reason, provider, provider_ref)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (user_id, amount, new_balance, reason, provider, provider_ref),
            )

            conn.commit()
            return new_balance


def spend_credits_by_user_id(
    user_id: int,
    amount,
    reason: str,
    provider: Optional[str] = None,
    provider_ref: Optional[str] = None,
) -> Decimal:
    """
    Subtracts credits (spend) and writes credit_ledger entry atomically.
    Raises RuntimeError if insufficient.
    Returns new balance.
    """
    amount = _to_decimal(amount)
    if amount <= 0:
        raise ValueError("amount must be > 0")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, credits FROM users WHERE id=%s FOR UPDATE", (user_id,))
            u = cur.fetchone()
            if not u:
                raise RuntimeError("User not found")

            bal = _to_decimal(u["credits"])
            if bal < amount:
                raise RuntimeError(f"Insufficient credits: have {bal}, need {amount}")

            new_balance = bal - amount

            cur.execute("UPDATE users SET credits=%s WHERE id=%s", (new_balance, user_id))
            cur.execute(
                """
                INSERT INTO credit_ledger (user_id, delta, balance_after, reason, provider, provider_ref)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (user_id, -amount, new_balance, reason, provider, provider_ref),
            )

            conn.commit()
            return new_balance


def add_credits_by_tg_id(
    tg_user_id: int,
    amount,
    reason: str,
    provider: Optional[str] = None,
    provider_ref: Optional[str] = None,
) -> Decimal:
    u = get_user(tg_user_id)
    if not u:
        raise RuntimeError("User not found")
    return add_credits_by_user_id(u["id"], amount, reason, provider, provider_ref)


def spend_credits_by_tg_id(
    tg_user_id: int,
    amount,
    reason: str,
    provider: Optional[str] = None,
    provider_ref: Optional[str] = None,
) -> Decimal:
    u = get_user(tg_user_id)
    if not u:
        raise RuntimeError("User not found")
    return spend_credits_by_user_id(u["id"], amount, reason, provider, provider_ref)


def get_ledger_by_tg_id(tg_user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    u = get_user(tg_user_id)
    if not u:
        return []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, delta, balance_after, reason, provider, provider_ref, created_at
                FROM credit_ledger
                WHERE user_id=%s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (u["id"], limit),
            )
            return cur.fetchall()


# ======================
# HOLD / CAPTURE / RELEASE (Billing-safe for async jobs)
# ======================
def create_credit_hold(
    user_id: int,
    amount,
    reason: str,
    provider: Optional[str] = None,
    provider_ref: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    HOLD: Δεσμεύει credits (credits_held) και δημιουργεί εγγραφή credit_holds.
    Idempotent per user_id + idempotency_key (αν δοθεί).
    """
    amount = _to_decimal(amount)
    if amount <= 0:
        raise ValueError("amount must be > 0")

    with get_conn() as conn:
        with conn.cursor() as cur:
            if idempotency_key:
                cur.execute(
                    "SELECT * FROM credit_holds WHERE user_id=%s AND idempotency_key=%s",
                    (user_id, idempotency_key),
                )
                existing = cur.fetchone()
                if existing:
                    conn.commit()
                    return existing

            cur.execute("SELECT id, credits, credits_held FROM users WHERE id=%s FOR UPDATE", (user_id,))
            u = cur.fetchone()
            if not u:
                raise RuntimeError("User not found")

            credits = _to_decimal(u["credits"])
            held = _to_decimal(u["credits_held"])
            available = credits - held

            if available < amount:
                raise RuntimeError(f"Insufficient credits: have {available}, need {amount}")

            new_held = held + amount
            cur.execute("UPDATE users SET credits_held=%s WHERE id=%s", (new_held, user_id))

            cur.execute(
                """
                INSERT INTO credit_holds (user_id, amount, status, reason, provider, provider_ref, idempotency_key)
                VALUES (%s, %s, 'held', %s, %s, %s, %s)
                RETURNING *;
                """,
                (user_id, amount, reason, provider, provider_ref, idempotency_key),
            )
            hold = cur.fetchone()
            conn.commit()
            return hold


def capture_credit_hold(
    hold_id: int,
    reason: str,
    provider: Optional[str] = None,
    provider_ref: Optional[str] = None,
) -> bool:
    """
    CAPTURE: Μετατρέπει HOLD σε πραγματική χρέωση.
    - Μειώνει credits_held
    - Μειώνει credits
    - Γράφει credit_ledger delta = -amount
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM credit_holds WHERE id=%s FOR UPDATE", (hold_id,))
            h = cur.fetchone()
            if not h:
                raise RuntimeError("Hold not found")

            if h["status"] == "captured":
                conn.commit()
                return True
            if h["status"] != "held":
                # released/canceled -> δεν κάνουμε capture
                conn.commit()
                return False

            user_id = int(h["user_id"])
            amount = _to_decimal(h["amount"])

            cur.execute("SELECT id, credits, credits_held FROM users WHERE id=%s FOR UPDATE", (user_id,))
            u = cur.fetchone()
            if not u:
                raise RuntimeError("User not found")

            credits = _to_decimal(u["credits"])
            held = _to_decimal(u["credits_held"])

            if held < amount:
                raise RuntimeError("credits_held invariant broken")

            new_held = held - amount
            new_credits = credits - amount
            if new_credits < 0:
                raise RuntimeError("credits invariant broken")

            cur.execute(
                "UPDATE users SET credits=%s, credits_held=%s WHERE id=%s",
                (new_credits, new_held, user_id),
            )

            cur.execute(
                """
                INSERT INTO credit_ledger (user_id, delta, balance_after, reason, provider, provider_ref)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (user_id, -amount, new_credits, reason, provider, provider_ref),
            )

            cur.execute(
                "UPDATE credit_holds SET status='captured', provider=%s, provider_ref=%s, updated_at=now() WHERE id=%s",
                (provider, provider_ref, hold_id),
            )
            conn.commit()
            return True


def release_credit_hold(
    hold_id: int,
    provider: Optional[str] = None,
    provider_ref: Optional[str] = None,
    reason: Optional[str] = None,
) -> bool:
    """
    RELEASE: Αποδεσμεύει HOLD (δεν υπάρχει χρέωση).
    - Μειώνει credits_held
    - Δεν αλλάζει credits
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM credit_holds WHERE id=%s FOR UPDATE", (hold_id,))
            h = cur.fetchone()
            if not h:
                raise RuntimeError("Hold not found")

            if h["status"] == "released":
                conn.commit()
                return True
            if h["status"] != "held":
                conn.commit()
                return True

            user_id = int(h["user_id"])
            amount = _to_decimal(h["amount"])

            cur.execute("SELECT id, credits_held FROM users WHERE id=%s FOR UPDATE", (user_id,))
            u = cur.fetchone()
            if not u:
                raise RuntimeError("User not found")

            held = _to_decimal(u["credits_held"])
            new_held = held - amount
            if new_held < 0:
                new_held = Decimal("0")

            cur.execute("UPDATE users SET credits_held=%s WHERE id=%s", (new_held, user_id))
            cur.execute(
                """
                UPDATE credit_holds
                SET status='released',
                    provider=%s,
                    provider_ref=%s,
                    reason=COALESCE(%s, reason),
                    updated_at=now()
                WHERE id=%s
                """,
                (provider, provider_ref, reason, hold_id),
            )
            conn.commit()
            return True


def get_credit_summary_by_user_id(user_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT credits, credits_held FROM users WHERE id=%s", (user_id,))
            u = cur.fetchone()
            if not u:
                return {"credits": Decimal("0"), "credits_held": Decimal("0"), "credits_available": Decimal("0")}
            credits = _to_decimal(u["credits"])
            held = _to_decimal(u["credits_held"])
            return {"credits": credits, "credits_held": held, "credits_available": credits - held}


# ======================
# Jobs (async tracking)
# ======================
def create_generation_job(
    user_id: int,
    model: str,
    mode: str,
    hold_id: Optional[int],
    prompt: str,
    params: Dict[str, Any],
    provider_job_id: Optional[str] = None,
    status: str = "queued",
) -> str:
    job_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO generation_jobs (id, user_id, model, mode, hold_id, provider_job_id, status, progress, prompt, params)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (job_id, user_id, model, mode, hold_id, provider_job_id, status, 0, prompt, json.dumps(params)),
            )
            conn.commit()
    return job_id


def update_generation_job(job_id: str, **fields) -> None:
    allowed = {"status", "progress", "provider_job_id", "result_url", "error"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=%s")
            vals.append(v)
    if not sets:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE generation_jobs SET {', '.join(sets)}, updated_at=now() WHERE id=%s",
                (*vals, job_id),
            )
            conn.commit()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s", (job_id,))
            return cur.fetchone()


def list_jobs_by_user_id(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, model, mode, status, progress, result_url, error, created_at, updated_at
                FROM generation_jobs
                WHERE user_id=%s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return cur.fetchall()


# ======================
# Referrals
# ======================
def create_referral_link(owner_user_id: int) -> dict:
    """
    Δημιουργεί νέο referral link για τον user, μέχρι MAX_REF_LINKS.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM referrals WHERE owner_user_id=%s", (owner_user_id,))
            c = cur.fetchone()["c"]
            if c >= MAX_REF_LINKS:
                return {"ok": False, "error": "limit_reached"}

            code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")
            cur.execute(
                "INSERT INTO referrals (owner_user_id, code) VALUES (%s,%s) RETURNING id, code, created_at",
                (owner_user_id, code),
            )
            row = cur.fetchone()
            conn.commit()
            return {"ok": True, **row}


def list_referrals(owner_user_id: int) -> list:
    """
    Λίστα links + μετρήσεις (starts, purchases_amount)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.id, r.code, r.created_at,
                  COALESCE(SUM(CASE WHEN e.event_type='start' THEN 1 ELSE 0 END),0) AS starts,
                  COALESCE(SUM(CASE WHEN e.event_type='purchase' THEN e.amount_eur ELSE 0 END),0) AS purchases_amount
                FROM referrals r
                LEFT JOIN referral_events e ON e.referral_id = r.id
                WHERE r.owner_user_id=%s
                GROUP BY r.id
                ORDER BY r.created_at DESC
                """,
                (owner_user_id,),
            )
            return cur.fetchall()


def record_referral_purchase(code: str, amount_eur) -> bool:
    """
    Καταγράφει purchase amount για code.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM referrals WHERE code=%s", (code,))
            r = cur.fetchone()
            if not r:
                return False
            cur.execute(
                "INSERT INTO referral_events (referral_id, event_type, amount_eur) VALUES (%s,'purchase',%s)",
                (r["id"], amount_eur),
            )
            conn.commit()
            return True


def apply_referral_start(invited_user_id: int, code: str, bonus_credits: int = 1) -> dict:
    """
    Αν ο invited_user ΔΕΝ έχει ξαναμπεί από referral, τότε:
    - καταγράφει join
    - γράφει referral_event start
    - δίνει bonus credits στον owner του referral
    Επιστρέφει: {ok, credited, owner_user_id, owner_tg_user_id, bonus}
    """
    with get_conn() as conn:
        cur = conn.cursor()

        # βρες referral + owner
        cur.execute(
            """
            SELECT r.id AS referral_id, r.owner_user_id, u.tg_user_id AS owner_tg_user_id
            FROM referrals r
            JOIN users u ON u.id = r.owner_user_id
            WHERE r.code = %s
            """,
            (code,),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return {"ok": False, "error": "bad_code"}

        referral_id = row["referral_id"]
        owner_user_id = row["owner_user_id"]
        owner_tg_user_id = row["owner_tg_user_id"]

        # μην δίνεις bonus στον ίδιο χρήστη αν άνοιξε το δικό του link
        if owner_user_id == invited_user_id:
            conn.commit()
            return {"ok": True, "credited": False, "reason": "self_ref"}

        # προσπάθησε να γράψεις join (αν έχει ήδη invited_user_id, θα αποτύχει λόγω UNIQUE)
        try:
            cur.execute(
                """
                INSERT INTO referral_joins (referral_id, invited_user_id)
                VALUES (%s, %s)
                """,
                (referral_id, invited_user_id),
            )
        except Exception:
            conn.rollback()
            return {"ok": True, "credited": False, "reason": "already_joined"}

        # γράψε event start
        cur.execute(
            """
            INSERT INTO referral_events (referral_id, event_type, amount_eur)
            VALUES (%s, 'start', NULL)
            """,
            (referral_id,),
        )

        conn.commit()

    # δώσε bonus στον owner (γράφει και ledger)
    add_credits_by_user_id(
        owner_user_id,
        bonus_credits,
        f"Referral bonus (+{bonus_credits}) από νέο χρήστη",
        "referral",
        code,
    )

    return {
        "ok": True,
        "credited": True,
        "owner_user_id": owner_user_id,
        "owner_tg_user_id": owner_tg_user_id,
        "bonus": bonus_credits,
    }


def get_referral_owner_by_code(code: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM referrals WHERE code=%s", (code,))
        return cur.fetchone()

def set_last_result(user_id: int, model: str, result_url: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO last_results (user_id, model, result_url)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, model)
                DO UPDATE SET result_url = EXCLUDED.result_url, created_at = now()
                """,
                (user_id, model, result_url),
            )
            conn.commit()


def get_last_result_by_tg_id(tg_user_id: int, model: str) -> Optional[str]:
    u = get_user(tg_user_id)
    if not u:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT result_url FROM last_results WHERE user_id=%s AND model=%s",
                (u["id"], model),
            )
            row = cur.fetchone()
            return (row or {}).get("result_url")
