-- 032_2fa_backup_codes.sql
-- One-time recovery codes for 2FA (M1) so a lost authenticator doesn't lock a user
-- out. Stored as SHA-256 hashes (the codes are high-entropy, like API keys), each
-- consumed on use. Shown to the user once, at enrollment.
ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_backup_codes JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$ BEGIN RAISE NOTICE '2FA backup codes column ready'; END $$;
