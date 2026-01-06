# app/db.py
import os
from pathlib import Path
from decimal import Decimal
from typing import Optional, List, Dict, Any

import psycopg
import psycopg.rows

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Λείπει το DATABASE_URL")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

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

            print(">>> ensured tables users + credit_ledger exist", flush=True)

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
    Raises HTTP-ish RuntimeError if insufficient.
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
