-- =====================================================
-- 003_credit_ledger_balance_after.sql
-- Προσθέτει ιστορικό υπολοίπου + index για ledger
-- =====================================================

-- 1) Προσθήκη balance_after (αν δεν υπάρχει)
-- app/migrations/003_credit_ledger_balance_after.sql

ALTER TABLE credit_ledger
ADD COLUMN IF NOT EXISTS balance_after NUMERIC(12,2);

-- 2) Index για γρηγορο ιστορικο ανα user
CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_created
ON credit_ledger (user_id, created_at DESC);

-- Δεν “γεμίζουμε” παλιά rows αυτόματα (θέλει ειδικό backfill)
-- τα αφήνουμε NULL αν είναι παλιά.
-- 3) (Προαιρετικό αλλά ΚΑΛΟ) Fix για παλιές εγγραφές
-- Αν υπάρχουν παλιά rows χωρίς balance_after, βάλε NULL ή delta
UPDATE credit_ledger
SET balance_after = NULL
WHERE balance_after IS NULL;
