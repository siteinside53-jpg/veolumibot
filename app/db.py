from contextlib import contextmanager
import psycopg
import psycopg.rows
from .config import DATABASE_URL

@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("Missing DATABASE_URL")
    with psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as conn:
        yield conn

def run_migrations():
    import os, glob
    base = os.path.join(os.path.dirname(__file__), "migrations")
    files = sorted(glob.glob(os.path.join(base, "*.sql")))
    with get_conn() as conn:
        cur = conn.cursor()
        for f in files:
            with open(f, "r", encoding="utf-8") as fp:
                cur.execute(fp.read())
        conn.commit()

def ensure_user(tg_user_id: int, username: str | None, first_name: str | None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE tg_user_id=%s", (tg_user_id,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE users SET tg_username=%s, tg_first_name=%s WHERE tg_user_id=%s",
                (username, first_name, tg_user_id),
            )
        else:
            # Δίνουμε “Free 5 credits” με το πρώτο start, σαν το παράδειγμα
            cur.execute(
                "INSERT INTO users (tg_user_id, tg_username, tg_first_name, credits) VALUES (%s,%s,%s,5) ",
                (tg_user_id, username, first_name),
            )
        conn.commit()

def get_user(tg_user_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE tg_user_id=%s", (tg_user_id,))
        return cur.fetchone()

def adjust_credits(user_id: int, delta: float, reason: str, provider: str | None = None, provider_ref: str | None = None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET credits = credits + %s WHERE id=%s", (delta, user_id))
        cur.execute(
            "INSERT INTO credit_ledger (user_id, delta, reason, provider, provider_ref) VALUES (%s,%s,%s,%s,%s)",
            (user_id, delta, reason, provider, provider_ref),
        )
        conn.commit()
