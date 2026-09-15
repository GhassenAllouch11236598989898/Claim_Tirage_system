-- Claims Triage System - PostgreSQL Initialization
-- This script runs automatically when the PostgreSQL container starts for the first time.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Claims table
CREATE TABLE IF NOT EXISTS claims (
    claim_id VARCHAR PRIMARY KEY,
    description TEXT NOT NULL,
    policy_number VARCHAR NOT NULL,
    policy_limit FLOAT NOT NULL,
    claimant_name VARCHAR NOT NULL,
    incident_date VARCHAR NOT NULL,
    claimed_amount FLOAT NOT NULL,
    supporting_info TEXT,
    
    -- Status tracking
    status VARCHAR DEFAULT 'submitted',
    current_agent VARCHAR DEFAULT 'start',
    submitted_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    
    -- Agent outputs (JSON)
    classification_output JSONB,
    severity_output JSONB,
    review_output JSONB,
    human_gate_output JSONB,
    
    -- Final decision
    final_decision VARCHAR,
    final_payout FLOAT,
    
    -- Budget tracking
    total_tokens INTEGER DEFAULT 0,
    total_latency_ms FLOAT DEFAULT 0.0,
    
    -- Error
    error TEXT
);

-- Trace steps table
CREATE TABLE IF NOT EXISTS traces (
    step_id VARCHAR PRIMARY KEY,
    claim_id VARCHAR NOT NULL REFERENCES claims(claim_id),
    agent_name VARCHAR NOT NULL,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    latency_ms FLOAT,
    tokens_used INTEGER DEFAULT 0,
    input_data JSONB,
    output_data JSONB,
    reasoning TEXT DEFAULT '',
    status VARCHAR DEFAULT 'started',
    error TEXT
);

-- Approvals table
CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    claim_id VARCHAR NOT NULL REFERENCES claims(claim_id),
    decision VARCHAR,
    reviewer_name VARCHAR,
    notes TEXT,
    reason_for_review TEXT NOT NULL,
    routed_at TIMESTAMP DEFAULT NOW(),
    decided_at TIMESTAMP,
    is_pending BOOLEAN DEFAULT TRUE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_traces_claim_id ON traces(claim_id);
CREATE INDEX IF NOT EXISTS idx_approvals_claim_id ON approvals(claim_id);
CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(is_pending) WHERE is_pending = TRUE;
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
