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

START_FREE_CREDITS = Decimal("5.00")


def _conn_autocommit():
    return psycopg.connect(DATABASE_URL, autocommit=True)


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)


def run_migrations():
    """
    Εφαρμόζει ΟΛΑ τα .sql migrations που υπάρχουν στον φάκελο app/migrations.
    (Τα migrations πρέπει να είναι idempotent: CREATE TABLE IF NOT EXISTS, ADD COLUMN IF NOT EXISTS κλπ)
    """
    print(">>> RUNNING MIGRATIONS <<<", flush=True)
    print(f">>> migrations dir = {MIGRATIONS_DIR}", flush=True)

    if not MIGRATIONS_DIR.exists():
        print(">>> migrations folder ΔΕΝ βρέθηκε — συνεχίζουμε", flush=True)
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
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
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


# ======================
# Credits + Ledger
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


# ======================
# Referrals
# ======================
def create_referral_link(owner_user_id: int) -> dict:
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


def record_referral_start(code: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM referrals WHERE code=%s", (code,))
            r = cur.fetchone()
            if not r:
                return False
            cur.execute(
                "INSERT INTO referral_events (referral_id, event_type) VALUES (%s,'start')",
                (r["id"],),
            )
            conn.commit()
            return True


def record_referral_purchase(code: str, amount_eur) -> bool:
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
