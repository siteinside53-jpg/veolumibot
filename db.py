from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import secrets
import psycopg
import psycopg.rows


@dataclass
class User:
    tg_id: int
    username: Optional[str]
    first_name: Optional[str]
    credits: int
    plan: str
    referral_code: Optional[str]


def connect(db_url: str):
    """Create a connection to the PostgreSQL database."""
    return psycopg.connect(db_url, row_factory=psycopg.rows.dict_row)


def init_db(db_url: str) -> None:
    """Initialize the database schema, create tables, and apply migrations."""
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            # Create `users` table if not exists
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                credits INT NOT NULL DEFAULT 0,
                plan TEXT NOT NULL DEFAULT 'Free',
                referral_code TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
            # Add missing columns if needed
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'Free';")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT;")

            # Create `jobs` table if not exists
            cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id BIGSERIAL PRIMARY KEY,
                tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                job_type TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                provider TEXT,
                result_url TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
        conn.commit()


def upsert_user(db_url: str, tg_id: int, username: Optional[str], first_name: Optional[str]) -> User:
    """Insert or update a user's record, and return the updated record."""
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO users (tg_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (tg_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                updated_at = NOW()
            RETURNING tg_id, username, first_name, credits, plan, referral_code;
            """, (tg_id, username, first_name))
            row = cur.fetchone()
        conn.commit()
    return User(**row)


def get_user(db_url: str, tg_id: int) -> Optional[User]:
    """Retrieve a user by their Telegram ID."""
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT tg_id, username, first_name, credits, plan, referral_code
            FROM users WHERE tg_id=%s;
            """, (tg_id,))
            row = cur.fetchone()
    return User(**row) if row else None


def ensure_referral_code(db_url: str, tg_id: int) -> str:
    """Ensure a user has a referral code, generating one if necessary."""
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT referral_code FROM users WHERE tg_id=%s;", (tg_id,))
            row = cur.fetchone()
            code = row["referral_code"] if row else None
            if not code:
                code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10]
                cur.execute("UPDATE users SET referral_code=%s, updated_at=NOW() WHERE tg_id=%s;", (code, tg_id))
        conn.commit()
    return code


def add_credits(db_url: str, tg_id: int, delta: int, reason: str) -> int:
    """Add credits to a user's account and return the updated total."""
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE users
            SET credits = credits + %s, updated_at = NOW()
            WHERE tg_id = %s
            RETURNING credits;
            """, (delta, tg_id))
            row = cur.fetchone()
        conn.commit()
    return row["credits"]


def set_plan(db_url: str, tg_id: int, plan: str) -> None:
    """Update the user's subscription plan."""
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET plan=%s, updated_at=NOW() WHERE tg_id=%s;", (plan, tg_id))
        conn.commit()


def create_job(db_url: str, tg_id: int, job_type: str, prompt: str, provider: Optional[str] = None) -> int:
    """Create a job and return the job ID."""
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO jobs (tg_id, job_type, prompt, status, provider)
            VALUES (%s, %s, %s, 'queued', %s)
            RETURNING id;
            """, (tg_id, job_type, prompt, provider))
            row = cur.fetchone()
        conn.commit()
    return row["id"]
