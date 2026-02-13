-- Create support_tickets table
CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id SERIAL PRIMARY KEY,
    customer_name TEXT NOT NULL,
    phone_number TEXT,
    issue_description TEXT NOT NULL,
    priority TEXT DEFAULT 'Medium', -- High, Medium, Low
    status TEXT DEFAULT 'Open',     -- Open, In Progress, Resolved, Closed
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create a trigger to automatically update 'updated_at' when a row is modified
CREATE OR REPLACE FUNCTION update_ticket_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_ticket_timestamp ON support_tickets;

CREATE TRIGGER set_ticket_timestamp
BEFORE UPDATE ON support_tickets
FOR EACH ROW
EXECUTE FUNCTION update_ticket_timestamp();

-- Create an index on phone_number for faster lookups (since users will query their own tickets)
CREATE INDEX IF NOT EXISTS idx_tickets_phone_number ON support_tickets(phone_number);
