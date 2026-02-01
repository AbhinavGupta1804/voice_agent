-- Allow sender_type 'user' for inbound messages (from end customer)
-- Run this after creating conversation_threads and conversation_messages.

ALTER TABLE conversation_messages
  DROP CONSTRAINT IF EXISTS conversation_messages_sender_type_check;

ALTER TABLE conversation_messages
  ADD CONSTRAINT conversation_messages_sender_type_check
  CHECK (sender_type IN ('bot', 'client', 'user'));
