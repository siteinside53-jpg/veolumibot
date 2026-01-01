from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Literal, Any
from datetime import datetime, timezone
import psycopg
import psycopg.rows

JobType = Literal["video", "image", "audio"]

@dataclass
class User:
    tg_id: int
    username: Optional[str]
    first_name: Optional[str]
    credits: int
    created_at: datetime
    updated_at: datetime

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def connect(db_url: str):
    return psycopg.connect(db_url, row_factory=psycopg.rows.dict_row)

def init_db(db_url: str) -> None:
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                credits INTEGER NOT NULL DEFAULT 5,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id BIGSERIAL PRIMARY KEY,
                tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                job_type TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued', -- queued|running|done|failed
                provider TEXT, -- π.χ. veo|nano|flux|runway
                result_url TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id BIGSERIAL PRIMARY KEY,
                tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
        conn.commit()

def upsert_user(db_url: str, tg_id: int, username: Optional[str], first_name: Optional[str]) -> User:
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO users (tg_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (tg_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                updated_at = NOW()
            RETURNING tg_id, username, first_name, credits, created_at, updated_at;
            """, (tg_id, username, first_name))
            row = cur.fetchone()
        conn.commit()
    return User(**row)

def get_user(db_url: str, tg_id: int) -> Optional[User]:
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT tg_id, username, first_name, credits, created_at, updated_at
            FROM users WHERE tg_id=%s;
            """, (tg_id,))
            row = cur.fetchone()
    return User(**row) if row else None

def add_credits(db_url: str, tg_id: int, delta: int, reason: str) -> int:
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET credits = credits + %s, updated_at = NOW() WHERE tg_id=%s RETURNING credits;",
                        (delta, tg_id))
            new_credits = cur.fetchone()["credits"]
            cur.execute("INSERT INTO transactions (tg_id, delta, reason) VALUES (%s, %s, %s);",
                        (tg_id, delta, reason))
        conn.commit()
    return new_credits

def create_job(db_url: str, tg_id: int, job_type: JobType, prompt: str, provider: Optional[str]=None) -> int:
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO jobs (tg_id, job_type, prompt, provider)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """, (tg_id, job_type, prompt, provider))
            job_id = int(cur.fetchone()["id"])
        conn.commit()
    return job_id

def list_last_jobs(db_url: str, tg_id: int, limit: int = 5) -> list[dict[str, Any]]:
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT id, job_type, status, provider, created_at
            FROM jobs
            WHERE tg_id=%s
            ORDER BY id DESC
            LIMIT %s;
            """, (tg_id, limit))
            rows = cur.fetchall()
    return rows or []
