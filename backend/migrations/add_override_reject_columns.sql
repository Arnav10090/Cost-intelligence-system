-- Migration: Add override and rejection columns
-- Run before implementing audit override and approval reject endpoints

-- Add override columns to audit_trail table
ALTER TABLE audit_trail
ADD COLUMN IF NOT EXISTS override_reason TEXT,
ADD COLUMN IF NOT EXISTS overridden_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS overridden_by TEXT;

-- Add rejection columns to actions_taken table
ALTER TABLE actions_taken
ADD COLUMN IF NOT EXISTS rejection_reason TEXT,
ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS rejected_by TEXT;

-- Verify columns were added
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'audit_trail' AND column_name LIKE '%override%';

SELECT column_name FROM information_schema.columns 
WHERE table_name = 'actions_taken' AND column_name LIKE '%reject%';
