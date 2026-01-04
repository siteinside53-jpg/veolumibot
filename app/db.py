# app/db.py
import os
from pathlib import Path

import psycopg
import psycopg.rows

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Λείπει το DATABASE_URL")

# ✅ ΕΣΥ έχεις migrations μέσα στο app/
# db.py: /app/app/db.py
# migrations: /app/app/migrations
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _conn():
    return psycopg.connect(DATABASE_URL, autocommit=True)


def run_migrations():
    print(">>> RUNNING MIGRATIONS <<<", flush=True)
    print(f">>> migrations dir = {MIGRATIONS_DIR}", flush=True)

    if not MIGRATIONS_DIR.exists():
        raise RuntimeError(f"Δεν υπάρχει migrations folder: {MIGRATIONS_DIR}")

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        raise RuntimeError("Δεν βρέθηκαν .sql migrations")

    with _conn() as conn:
        with conn.cursor() as cur:
            for f in sql_files:
                print(f">>> applying {f.name}", flush=True)
                cur.execute(f.read_text(encoding="utf-8"))


def ensure_user(tg_user_id, tg_username, tg_first_name):
    with _conn() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                INSERT INTO users (tg_user_id, tg_username, tg_first_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (tg_user_id) DO UPDATE
                SET tg_username = EXCLUDED.tg_username,
                    tg_first_name = EXCLUDED.tg_first_name
                RETURNING *;
                """,
                (tg_user_id, tg_username, tg_first_name),
            )
            return cur.fetchone()


def get_user(tg_user_id):
    with _conn() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                "SELECT * FROM users WHERE tg_user_id = %s",
                (tg_user_id,),
            )
            return cur.fetchone()
