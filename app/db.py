import os
import psycopg
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

def get_conn():
    return psycopg.connect(DATABASE_URL)

def run_migrations():
    print(">>> RUNNING MIGRATIONS <<<")

    migrations_dir = Path(__file__).parent / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))

    print("Found migrations:", [f.name for f in files])

    with get_conn() as conn:
        with conn.cursor() as cur:
            for f in files:
                print("Executing:", f.name)
                sql = f.read_text()
                cur.execute(sql)
        conn.commit()

    print(">>> MIGRATIONS DONE <<<")
    with get_conn() as conn:
        with conn.cursor() as cur:
            for f in files:
                sql = f.read_text()
                cur.execute(sql)
        conn.commit()

def ensure_user(tg_user_id, username, first_name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE tg_user_id = %s",
                (tg_user_id,)
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    INSERT INTO users (tg_user_id, tg_username, tg_first_name)
                    VALUES (%s, %s, %s)
                    """,
                    (tg_user_id, username, first_name)
                )
        conn.commit()

def get_user(tg_user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tg_user_id, tg_username, credits
                FROM users WHERE tg_user_id = %s
                """,
                (tg_user_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "tg_user_id": row[0],
                "tg_username": row[1],
                "credits": float(row[2]),
            }
