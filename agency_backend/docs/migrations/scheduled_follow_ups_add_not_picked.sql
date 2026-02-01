-- Add 'not_picked' status for follow-ups that were never answered after all retries.

ALTER TABLE scheduled_follow_ups
  DROP CONSTRAINT IF EXISTS scheduled_follow_ups_status_check;

ALTER TABLE scheduled_follow_ups
  ADD CONSTRAINT scheduled_follow_ups_status_check
  CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled', 'not_picked'));
