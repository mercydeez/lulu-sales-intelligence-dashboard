-- 033_email_verified.sql
-- Email verification on signup. Existing + demo users default to verified=TRUE so
-- they're never nagged; new self-serve signups are created with FALSE and verify
-- via an emailed link.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT TRUE;

DO $$ BEGIN RAISE NOTICE 'users.email_verified ready'; END $$;
