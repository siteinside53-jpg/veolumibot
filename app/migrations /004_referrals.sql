-- app/migrations/004_referrals.sql
CREATE TABLE IF NOT EXISTS referrals (
  id BIGSERIAL PRIMARY KEY,
  owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_referrals_owner ON referrals(owner_user_id);

CREATE TABLE IF NOT EXISTS referral_events (
  id BIGSERIAL PRIMARY KEY,
  referral_id BIGINT NOT NULL REFERENCES referrals(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,          -- start | purchase
  amount_eur NUMERIC(12,2),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ref_events_ref ON referral_events(referral_id, created_at DESC);
