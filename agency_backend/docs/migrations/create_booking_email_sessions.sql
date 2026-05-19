-- WhatsApp booking email sessions (replaces Redis for call_id <-> phone <-> email bridge)
CREATE TABLE IF NOT EXISTS booking_email_sessions (
    call_id VARCHAR(128) PRIMARY KEY,
    phone VARCHAR(32) NOT NULL,
    customer_name VARCHAR(255) NOT NULL DEFAULT '',
    selected_time VARCHAR(128) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    email VARCHAR(254) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_booking_email_sessions_phone_pending
    ON booking_email_sessions (phone, created_at DESC)
    WHERE status = 'pending';

COMMENT ON TABLE booking_email_sessions IS 'Short-lived sessions linking Retell call_id to WhatsApp email collection';
