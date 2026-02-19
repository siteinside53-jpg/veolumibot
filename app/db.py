# app/db.py

import os
from pathlib import Path
from decimal import Decimal
from typing import Optional, List, Dict, Any
import secrets
import json
import uuid
from datetime import datetime, timezone

import psycopg
import psycopg.rows

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Λείπει το DATABASE_URL")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MAX_REF_LINKS = 10
START_FREE_CREDITS = Decimal("5.00")


# ======================
# CONNECTIONS
# ======================

def _conn_autocommit():
    return psycopg.connect(DATABASE_URL, autocommit=True)


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)


# ======================
# HELPERS
# ======================

def _to_decimal(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ======================
# MIGRATIONS
# ======================

def run_migrations():
    print(">>> RUNNING MIGRATIONS <<<", flush=True)
    print(f">>> migrations dir = {MIGRATIONS_DIR}", flush=True)

    with _conn_autocommit() as conn:
        with conn.cursor() as cur:

            # USERS
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
              id SERIAL PRIMARY KEY,
              tg_user_id BIGINT UNIQUE NOT NULL,
              tg_username TEXT,
              tg_first_name TEXT,
              credits NUMERIC(10,2) NOT NULL DEFAULT 0,
              credits_held NUMERIC(10,2) NOT NULL DEFAULT 0,
              freelancer_until TIMESTAMPTZ,
              created_at TIMESTAMPTZ DEFAULT now()
            );
            """)

            # LEDGER
            cur.execute("""
            CREATE TABLE IF NOT EXISTS credit_ledger (
              id SERIAL PRIMARY KEY,
              user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
              delta NUMERIC(10,2),
              balance_after NUMERIC(10,2),
              reason TEXT,
              provider TEXT,
              provider_ref TEXT,
              created_at TIMESTAMPTZ DEFAULT now()
            );
            """)

            # HOLDS
            cur.execute("""
            CREATE TABLE IF NOT EXISTS credit_holds (
              id SERIAL PRIMARY KEY,
              user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
              amount NUMERIC(10,2),
              status TEXT DEFAULT 'held',
              reason TEXT,
              provider TEXT,
              provider_ref TEXT,
              idempotency_key TEXT,
              created_at TIMESTAMPTZ DEFAULT now(),
              updated_at TIMESTAMPTZ DEFAULT now()
            );
            """)

            # GENERATION JOBS
            cur.execute("""
            CREATE TABLE IF NOT EXISTS generation_jobs (
              id UUID PRIMARY KEY,
              user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
              model TEXT,
              mode TEXT,
              hold_id INTEGER,
              provider_job_id TEXT,
              status TEXT DEFAULT 'queued',
              progress INTEGER,
              prompt TEXT,
              params JSONB,
              result_url TEXT,
              error TEXT,
              created_at TIMESTAMPTZ DEFAULT now(),
              updated_at TIMESTAMPTZ DEFAULT now()
            );
            """)

            # JOB MARKETPLACE
            cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id SERIAL PRIMARY KEY,
                creator_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                budget NUMERIC(10,2),
                status TEXT DEFAULT 'open',
                created_at TIMESTAMPTZ DEFAULT now()
            );
            """)

            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status_created
            ON jobs(status, created_at DESC);
            """)

            # FREELANCERS
            cur.execute("""
            CREATE TABLE IF NOT EXISTS freelancers (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                skills TEXT,
                about TEXT,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT now()
            );
            """)

            print(">>> ensured base tables exist", flush=True)

    # run sql migrations if exist
    if not MIGRATIONS_DIR.exists():
        print(">>> migrations folder ΔΕΝ βρέθηκε — συνεχίζουμε", flush=True)
        return

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        return

    with _conn_autocommit() as conn:
        with conn.cursor() as cur:
            for f in sql_files:
                print(f">>> applying {f.name}", flush=True)
                cur.execute(f.read_text(encoding="utf-8"))


# ======================
# USERS
# ======================

def ensure_user(tg_user_id, username, first_name):

    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO users (tg_user_id,tg_username,tg_first_name,credits)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (tg_user_id) DO NOTHING
                RETURNING *;
            """,(tg_user_id,username,first_name,START_FREE_CREDITS))

            row = cur.fetchone()

            if row:
                cur.execute("""
                    INSERT INTO credit_ledger
                    (user_id,delta,balance_after,reason,provider)
                    VALUES (%s,%s,%s,%s,'system')
                """,(row["id"],START_FREE_CREDITS,row["credits"],"Free start credits"))
                conn.commit()
                return row

            cur.execute("SELECT * FROM users WHERE tg_user_id=%s",(tg_user_id,))
            return cur.fetchone()


# ======================
# FREELANCER SUB
# ======================

def has_freelancer_access(user_id:int)->bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT freelancer_until FROM users WHERE id=%s",(user_id,))
            r=cur.fetchone()
            if not r or not r["freelancer_until"]:
                return False
            return r["freelancer_until"] > _now_utc()


def activate_freelancer(user_id:int,days:int=30):
    until = _now_utc().timestamp() + (days*86400)
    until = datetime.fromtimestamp(until,timezone.utc)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET freelancer_until=%s
                WHERE id=%s
            """,(until,user_id))
            conn.commit()


# ======================
# JOBS
# ======================

def create_job(user_id,title,desc,budget):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO jobs (creator_id,title,description,budget)
                VALUES (%s,%s,%s,%s)
            """,(user_id,title,desc,budget))
        conn.commit()


def list_open_jobs():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id,title,budget
                FROM jobs
                WHERE status='open'
                ORDER BY id DESC
                LIMIT 20
            """)
            return cur.fetchall()


def register_freelancer(user_id,skills,about):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO freelancers (user_id,skills,about)
                VALUES (%s,%s,%s)
                ON CONFLICT (user_id)
                DO UPDATE SET skills=EXCLUDED.skills, about=EXCLUDED.about
            """,(user_id,skills,about))
        conn.commit()


# ======================
# GENERATION JOBS
# ======================

def create_generation_job(user_id,model,mode,hold_id,prompt,params):
    job_id=str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO generation_jobs
                (id,user_id,model,mode,hold_id,prompt,params)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,(job_id,user_id,model,mode,hold_id,prompt,json.dumps(params,default=str)))
        conn.commit()

    return job_id


def update_generation_job(job_id,**fields):

    if not fields:
        return

    sets=[]
    vals=[]

    for k,v in fields.items():
        sets.append(f"{k}=%s")
        vals.append(v)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE generation_jobs SET {', '.join(sets)}, updated_at=now() WHERE id=%s",
                (*vals,job_id),
            )
        conn.commit()
