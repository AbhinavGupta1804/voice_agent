-- Full Database Setup Script with Dummy Data
-- Description: Creates all tables and inserts sample data for testing
-- Date: 2026-02-01

-- Drop existing tables if they exist (in correct order due to foreign keys)
DROP TABLE IF EXISTS scheduled_follow_ups CASCADE;
DROP TABLE IF EXISTS call_topics CASCADE;
DROP TABLE IF EXISTS notification_preferences CASCADE;
DROP TABLE IF EXISTS calls CASCADE;

-- ============================================
-- 1. CREATE TABLES
-- ============================================

-- Main calls table
CREATE TABLE calls (
    call_id VARCHAR(128) PRIMARY KEY,
    client_name VARCHAR(255) NOT NULL,
    phone_number VARCHAR(50),
    transcript TEXT,
    summary TEXT,
    follow_up_date DATE,
    conversion_status BOOLEAN DEFAULT FALSE,
    duration_sec INTEGER DEFAULT 0,
    call_timestamp TIMESTAMPTZ DEFAULT NOW(),
    recording_url TEXT,
    sentiment VARCHAR(20),
    call_type VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Call topics table
CREATE TABLE call_topics (
    id SERIAL PRIMARY KEY,
    call_id VARCHAR(128) REFERENCES calls(call_id) ON DELETE CASCADE,
    topic VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Notification preferences table
CREATE TABLE notification_preferences (
    id SERIAL PRIMARY KEY,
    call_id VARCHAR(128) REFERENCES calls(call_id) ON DELETE CASCADE,
    notify_email BOOLEAN DEFAULT FALSE,
    notify_whatsapp BOOLEAN DEFAULT FALSE,
    email_address VARCHAR(255),
    whatsapp_number VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scheduled follow-ups table
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

-- ============================================
-- 2. CREATE INDEXES
-- ============================================

-- Index for fast lookup of pending follow-ups
CREATE INDEX idx_followups_pending ON scheduled_follow_ups(scheduled_at) 
    WHERE status = 'pending';

-- Prevent duplicate pending follow-ups for same call
CREATE UNIQUE INDEX idx_followups_unique ON scheduled_follow_ups(call_id) 
    WHERE status IN ('pending', 'processing');

-- Index for status queries
CREATE INDEX idx_followups_status ON scheduled_follow_ups(status);

-- Index for call_id lookups
CREATE INDEX idx_call_topics_call_id ON call_topics(call_id);
CREATE INDEX idx_notification_prefs_call_id ON notification_preferences(call_id);

-- Index for timestamp queries
CREATE INDEX idx_calls_timestamp ON calls(call_timestamp DESC);

-- ============================================
-- 3. INSERT DUMMY DATA
-- ============================================

-- Insert sample calls
INSERT INTO calls (call_id, client_name, phone_number, transcript, summary, follow_up_date, conversion_status, duration_sec, call_timestamp, sentiment, call_type) VALUES
('conv_sample001', 'Rahul Sharma', '+919876543210', 
'Agent: Hello, this is calling from XYZ Company. Am I speaking with Rahul?
Customer: Yes, this is Rahul.
Agent: Great! I wanted to discuss our new product offering.
Customer: I am interested but I am busy right now. Can you call me tomorrow at 3 PM?
Agent: Sure, I will call you tomorrow at 3 PM. Thank you!',
'Customer Rahul Sharma expressed interest in the product but was busy. Requested callback tomorrow at 3 PM.',
'2026-02-02',
FALSE,
120,
NOW() - INTERVAL '2 hours',
'positive',
'outbound'),

('conv_sample002', 'Priya Patel', '+919123456789',
'Agent: Hello, is this Priya?
Customer: Yes, speaking.
Agent: I am calling about the insurance plan we discussed last week.
Customer: Oh yes! I have decided to go ahead with it. Please proceed.
Agent: Excellent! I will send you the documents right away.
Customer: Perfect, thank you!',
'Customer Priya Patel confirmed purchase of insurance plan. Conversion successful.',
NULL,
TRUE,
180,
NOW() - INTERVAL '5 hours',
'positive',
'outbound'),

('conv_sample003', 'Amit Kumar', '+919988776655',
'Agent: Good morning! This is from ABC Services.
Customer: I am not interested. Please do not call again.
Agent: I understand. Have a good day.',
'Customer Amit Kumar declined the offer and requested no further calls.',
NULL,
FALSE,
45,
NOW() - INTERVAL '1 day',
'negative',
'outbound'),

('conv_sample004', 'Sneha Reddy', '+919876501234',
'Agent: Hello Sneha, calling about your recent inquiry.
Customer: Yes, I wanted more information about the pricing.
Agent: Our basic plan starts at 999 rupees per month.
Customer: That sounds reasonable. Let me discuss with my family and I will get back to you in 2 days.
Agent: Sure, take your time. I will follow up with you.',
'Customer Sneha Reddy interested in pricing. Needs 2 days to discuss with family before decision.',
'2026-02-03',
FALSE,
240,
NOW() - INTERVAL '3 hours',
'neutral',
'inbound'),

('conv_sample005', 'Vikram Singh', '+919123450987',
'Agent: Hi Vikram, this is a follow-up call regarding the demo you attended.
Customer: Yes, I really liked the demo. I want to sign up for the premium plan.
Agent: Wonderful! Let me get your details and process the signup.
Customer: Great, please go ahead.',
'Customer Vikram Singh converted after demo. Signed up for premium plan.',
NULL,
TRUE,
300,
NOW() - INTERVAL '6 hours',
'positive',
'outbound');

-- Insert call topics
INSERT INTO call_topics (call_id, topic) VALUES
('conv_sample001', 'Product Inquiry'),
('conv_sample001', 'Callback Request'),
('conv_sample002', 'Insurance Plan'),
('conv_sample002', 'Conversion'),
('conv_sample003', 'Not Interested'),
('conv_sample004', 'Pricing Inquiry'),
('conv_sample004', 'Family Discussion'),
('conv_sample005', 'Demo Follow-up'),
('conv_sample005', 'Premium Plan Signup');

-- Insert notification preferences
INSERT INTO notification_preferences (call_id, notify_email, notify_whatsapp, email_address, whatsapp_number) VALUES
('conv_sample001', TRUE, TRUE, 'rahul.sharma@example.com', '+919876543210'),
('conv_sample002', TRUE, FALSE, 'priya.patel@example.com', NULL),
('conv_sample003', FALSE, FALSE, NULL, NULL),
('conv_sample004', FALSE, TRUE, NULL, '+919876501234'),
('conv_sample005', TRUE, TRUE, 'vikram.singh@example.com', '+919123450987');

-- Insert scheduled follow-ups (some pending, some completed)
INSERT INTO scheduled_follow_ups (call_id, phone_number, client_name, scheduled_at, status, context) VALUES
('conv_sample001', '+919876543210', 'Rahul Sharma', 
NOW() + INTERVAL '1 day' + INTERVAL '15 hours',  -- Tomorrow at 3 PM
'pending',
'{"original_call_summary": "Customer interested in product but was busy", "callback_reason": "Product discussion", "customer_preference": "Call at 3 PM"}'::jsonb),

('conv_sample004', '+919876501234', 'Sneha Reddy',
NOW() + INTERVAL '2 days',  -- In 2 days
'pending',
'{"original_call_summary": "Customer needs time to discuss pricing with family", "callback_reason": "Pricing follow-up", "customer_preference": "Call in 2 days"}'::jsonb),

('conv_sample002', '+919123456789', 'Priya Patel',
NOW() - INTERVAL '1 hour',  -- Already executed
'completed',
'{"original_call_summary": "Follow-up on insurance plan", "callback_reason": "Document confirmation"}'::jsonb);

-- Update executed_at for completed follow-up
UPDATE scheduled_follow_ups 
SET executed_at = NOW() - INTERVAL '30 minutes'
WHERE status = 'completed';

-- ============================================
-- 4. VERIFICATION QUERIES
-- ============================================

-- Show table counts
SELECT 'calls' as table_name, COUNT(*) as row_count FROM calls
UNION ALL
SELECT 'call_topics', COUNT(*) FROM call_topics
UNION ALL
SELECT 'notification_preferences', COUNT(*) FROM notification_preferences
UNION ALL
SELECT 'scheduled_follow_ups', COUNT(*) FROM scheduled_follow_ups;

-- Show pending follow-ups
SELECT 
    id,
    client_name,
    phone_number,
    scheduled_at,
    status,
    context->>'callback_reason' as reason
FROM scheduled_follow_ups
WHERE status = 'pending'
ORDER BY scheduled_at;

-- Show recent calls with conversion status
SELECT 
    call_id,
    client_name,
    phone_number,
    conversion_status,
    sentiment,
    call_type,
    call_timestamp
FROM calls
ORDER BY call_timestamp DESC;
