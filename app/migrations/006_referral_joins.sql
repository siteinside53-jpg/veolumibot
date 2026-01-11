CREATE TABLE IF NOT EXISTS referral_joins (
  id BIGSERIAL PRIMARY KEY,
  referral_id BIGINT NOT NULL REFERENCES referrals(id) ON DELETE CASCADE,
  invited_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(invited_user_id)
);

CREATE INDEX IF NOT EXISTS idx_referral_joins_referral
ON referral_joins(referral_id, created_at DESC);
