-- 007_credit_holds_and_jobs.sql

ALTER TABLE users
ADD COLUMN IF NOT EXISTS credits_held numeric(18,6) NOT NULL DEFAULT 0;

-- Holds
CREATE TABLE IF NOT EXISTS credit_holds (
  id bigserial PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES users(id),
  amount numeric(18,6) NOT NULL,
  status text NOT NULL DEFAULT 'held', -- held | captured | released
  reason text,
  provider text,
  provider_ref text,
  idempotency_key text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS credit_holds_user_idempotency_uq
ON credit_holds(user_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;

-- Jobs
CREATE TABLE IF NOT EXISTS generation_jobs (
  id uuid PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES users(id),
  model text NOT NULL,               -- "gpt-image", "nanobanana_pro", "veo31", "sora-2-pro"
  mode text,                         -- "text" | "image" | ...
  hold_id bigint REFERENCES credit_holds(id),
  provider_job_id text,              -- id από OpenAI/Gemini κλπ
  status text NOT NULL DEFAULT 'queued', -- queued|in_progress|completed|failed|canceled
  progress int,
  prompt text,
  params jsonb,
  result_url text,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS generation_jobs_user_idx ON generation_jobs(user_id, created_at DESC);
