-- Migration: Create scheduled_follow_ups table
-- Description: Stores scheduled follow-up calls based on transcript analysis
-- Date: 2025-01-31

CREATE TABLE scheduled_follow_ups (
    id SERIAL PRIMARY KEY,
    
    -- Link to original call
    call_id VARCHAR(128) REFERENCES calls(call_id),
    
    -- Who to contact
    phone_number VARCHAR(50) NOT NULL,
    client_name VARCHAR(255),
    
    -- When to follow up (full datetime with timezone)
    scheduled_at TIMESTAMPTZ NOT NULL,
    
    -- Status tracking
    status VARCHAR(20) DEFAULT 'pending' 
        CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
    
    -- For retries
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    last_error TEXT,
    
    -- Context for follow-up call (summary, notes from original call)
    context JSONB,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    executed_at TIMESTAMPTZ
);

-- Index for fast lookup of pending follow-ups
CREATE INDEX idx_followups_pending ON scheduled_follow_ups(scheduled_at) 
    WHERE status = 'pending';

-- Prevent duplicate pending follow-ups for same call
CREATE UNIQUE INDEX idx_followups_unique ON scheduled_follow_ups(call_id) 
    WHERE status IN ('pending', 'processing');

-- Index for status queries
CREATE INDEX idx_followups_status ON scheduled_follow_ups(status);

-- Comments for documentation
COMMENT ON TABLE scheduled_follow_ups IS 'Stores scheduled follow-up calls extracted from call transcripts';
COMMENT ON COLUMN scheduled_follow_ups.scheduled_at IS 'When the follow-up call should be executed (timezone-aware)';
COMMENT ON COLUMN scheduled_follow_ups.context IS 'JSON object containing call summary and other context for the follow-up';
COMMENT ON COLUMN scheduled_follow_ups.status IS 'Current status: pending (waiting), processing (executing), completed (done), failed (error), cancelled (user cancelled)';
