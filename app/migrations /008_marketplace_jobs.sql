-- 008_marketplace_jobs.sql

CREATE TABLE IF NOT EXISTS freelancer_profiles (
  user_id        BIGINT PRIMARY KEY,
  display_name   TEXT,
  bio            TEXT,
  skills         TEXT,      -- comma separated for v1 (ή json later)
  created_at     TIMESTAMP DEFAULT NOW(),
  updated_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS marketplace_jobs (
  id             UUID PRIMARY KEY,
  client_user_id BIGINT NOT NULL,
  title          TEXT NOT NULL,
  description    TEXT NOT NULL,
  budget_eur     NUMERIC(10,2),     -- optional
  deadline_days  INT,              -- optional
  status         TEXT NOT NULL DEFAULT 'open',  -- open|assigned|closed
  created_at     TIMESTAMP DEFAULT NOW(),
  updated_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_marketplace_jobs_status_created
ON marketplace_jobs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS job_offers (
  id             UUID PRIMARY KEY,
  job_id         UUID NOT NULL REFERENCES marketplace_jobs(id) ON DELETE CASCADE,
  freelancer_user_id BIGINT NOT NULL,
  message        TEXT NOT NULL,
  price_eur      NUMERIC(10,2), -- optional
  status         TEXT NOT NULL DEFAULT 'sent',  -- sent|accepted|rejected
  created_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_offers_job
ON job_offers(job_id, created_at DESC);
