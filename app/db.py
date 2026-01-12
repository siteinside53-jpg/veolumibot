# app/db.py
import os
from pathlib import Path
from decimal import Decimal
from typing import Optional, List, Dict, Any
import secrets

import psycopg
import psycopg.rows

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Λείπει το DATABASE_URL")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MAX_REF_LINKS = 10

# Start credits for new users
START_FREE_CREDITS = Decimal("5.00")


def _conn_autocommit():
    # Για migrations / απλά queries
    return psycopg.connect(DATABASE_URL, autocommit=True)


def get_conn():
    # Για web.py (dict_row) + transactions (default autocommit=False)
    return psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)


def run_migrations():
    """
    Ensures base tables exist even if migrations folder is missing.
    Then applies .sql migrations if present.
    """
    print(">>> RUNNING MIGRATIONS <<<", flush=True)
    print(f">>> migrations dir = {MIGRATIONS_DIR}", flush=True)

    with _conn_autocommit() as conn:
        with conn.cursor() as cur:
            # users
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

            # credit_ledger
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
            # REFERRALS TABLES (για το νέο σύστημα που δείχνεις στο web)
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

            print(">>> ensured tables users + credit_ledger + referrals/referral_joins/referral_events exist", flush=True)

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
            # 1) Try insert NEW user with starting credits
            cur.execute(
                """
                INSERT INTO users (tg_user_id, tg_username, tg_first_name, credits)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tg_user_id) DO NOTHING
                RETURNING *;
                """,
                (tg_user_id, tg_username, tg_first_name, START_FREE_CREDITS),
            )
            inserted = cur.fetchone()

            if inserted:
                # New user: write ledger (+5)
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

            # 2) Existing user: update basic fields + return row
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


# ======================
# Credits + Ledger (atomic)
# ======================
def _to_decimal(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


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
            # lock user row
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
