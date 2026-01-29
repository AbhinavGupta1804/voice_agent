-- Migration: Add call_type column to calls table
-- Description: Adds a column to track whether a call is 'inbound' or 'outbound'
-- Date: 2024

-- Add call_type column (VARCHAR with CHECK constraint for data integrity)
ALTER TABLE calls 
ADD COLUMN call_type VARCHAR(20) CHECK (call_type IN ('inbound', 'outbound'));

-- Optional: Add a comment to document the column
COMMENT ON COLUMN calls.call_type IS 'Type of call: inbound (customer calls in) or outbound (agent calls out)';

-- Optional: If you want to backfill existing records, you can set a default
-- For existing records, you might want to set a default or leave NULL initially
-- Example to set all existing records to NULL (they'll need to be updated manually or via application logic):
-- UPDATE calls SET call_type = NULL WHERE call_type IS NULL;

-- If you prefer to make it NOT NULL after backfilling data, run:
-- ALTER TABLE calls ALTER COLUMN call_type SET NOT NULL;
