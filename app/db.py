# app/db.py
import os
from pathlib import Path

import psycopg
import psycopg.rows

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Λείπει το DATABASE_URL")

BASE_DIR = Path(__file__).resolve().parent

# Πιθανά paths για migrations (για να μην “σπάει” στο Railway)
CANDIDATE_MIGRATIONS_DIRS = [
    BASE_DIR / "migrations",          # /app/app/migrations
    BASE_DIR.parent / "migrations",   # /app/migrations
    Path.cwd() / "app" / "migrations",
    Path.cwd() / "migrations",
]


def _conn():
    # autocommit=True για DDL (CREATE TABLE, CREATE EXTENSION κλπ)
    return psycopg.connect(DATABASE_URL, autocommit=True)


def _find_migrations_dir() -> Path:
    print(">>> RUNNING MIGRATIONS <<<", flush=True)
    print(f">>> __file__ = {__file__}", flush=True)
    print(f">>> cwd = {Path.cwd()}", flush=True)
    print(f">>> BASE_DIR = {BASE_DIR}", flush=True)

    migrations_dir = None
    for p in CANDIDATE_MIGRATIONS_DIRS:
        print(f">>> checking migrations dir: {p}", flush=True)
        if p.exists() and p.is_dir():
            migrations_dir = p
            break

    if migrations_dir is None:
        raise RuntimeError(
            "Δεν βρήκα migrations folder. Δοκίμασα:\n" +
            "\n".join(str(p) for p in CANDIDATE_MIGRATIONS_DIRS)
        )

    return migrations_dir


def run_migrations():
    migrations_dir = _find_migrations_dir()

    sql_files = sorted(migrations_dir.glob("*.sql"))
    print(f">>> migrations_dir = {migrations_dir}", flush=True)
    print(f">>> found sql files: {[f.name for f in sql_files]}", flush=True)

    if not sql_files:
        raise RuntimeError(f"Δεν βρέθηκαν .sql migrations μέσα στο: {migrations_dir}")

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
