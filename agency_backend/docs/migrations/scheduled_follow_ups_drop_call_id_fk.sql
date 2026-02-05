-- Drop FK on scheduled_follow_ups.call_id so we can create follow-ups for
-- no-answer / call_initiation_failure (conversation_id has no row in calls).
-- call_id remains a reference label; it may or may not exist in calls.

ALTER TABLE scheduled_follow_ups
  DROP CONSTRAINT IF EXISTS scheduled_follow_ups_call_id_fkey;
