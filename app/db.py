import os
import psycopg

DATABASE_URL = os.environ["DATABASE_URL"]

def get_conn():
    return psycopg.connect(DATABASE_URL)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                tg_user_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)
            conn.commit()

def ensure_user(tg_user_id: int, username: str, first_name: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE tg_user_id = %s",
                (tg_user_id,)
            )
            row = cur.fetchone()
            if row:
                return row[0]

            cur.execute(
                """
                INSERT INTO users (tg_user_id, username, first_name)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (tg_user_id, username, first_name)
            )
            user_id = cur.fetchone()[0]
            conn.commit()
            return user_id
