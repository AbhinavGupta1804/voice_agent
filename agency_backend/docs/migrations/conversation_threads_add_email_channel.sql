-- Migration: Add email channel support to conversation_threads
-- Description: Store email threads by email_address; allow phone_number to be NULL for email.
-- Run after conversation_threads and conversation_messages exist.
-- Date: 2026-02-01

-- Add email address column (NULL for whatsapp/sms threads)
ALTER TABLE conversation_threads
  ADD COLUMN IF NOT EXISTS email_address VARCHAR(255) NULL;

-- Allow phone_number to be NULL for email-only threads (if currently NOT NULL, drop and re-add)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'conversation_threads' AND column_name = 'phone_number'
  ) THEN
    ALTER TABLE conversation_threads ALTER COLUMN phone_number DROP NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  NULL; -- column may already allow NULL
END $$;

-- Unique index for email channel: one thread per (email_address, channel)
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_threads_email_channel
  ON conversation_threads (email_address, channel)
  WHERE channel = 'email';

-- Drop existing unique on (phone_number, channel) so we can allow NULL phone_number for email
ALTER TABLE conversation_threads DROP CONSTRAINT IF EXISTS conversation_threads_phone_number_channel_key;

-- Unique for whatsapp/sms: one thread per (phone_number, channel)
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_threads_phone_channel
  ON conversation_threads (phone_number, channel)
  WHERE channel IN ('whatsapp', 'sms');

COMMENT ON COLUMN conversation_threads.email_address IS 'For channel=email, the user email. Null for whatsapp/sms.';
