-- DeepAgent Service Database Initialization
-- Generated: 2026-03-07

-- ─────────────────────────────────────────────────────────────────────────────
-- Extensions
-- ─────────────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────────────
-- Agent Configurations Table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_configs (
    agent_id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    model VARCHAR(100) NOT NULL DEFAULT 'glm-5',
    system_prompt TEXT,
    tools JSONB DEFAULT '[]',
    mcp_servers JSONB DEFAULT '[]',
    interrupt_on JSONB DEFAULT '{}',
    max_turns INTEGER DEFAULT 50,
    ttl_minutes INTEGER DEFAULT 30,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Conversation Threads Table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS conversation_threads (
    thread_id VARCHAR(255) PRIMARY KEY,
    agent_id VARCHAR(255) REFERENCES agent_configs(agent_id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Conversation Messages Table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS conversation_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id VARCHAR(255) REFERENCES conversation_threads(thread_id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT,
    tool_calls JSONB,
    tool_call_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_thread_id ON conversation_messages(thread_id);
CREATE INDEX idx_messages_created_at ON conversation_messages(created_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- Interrupt Decisions Table (Human-in-the-Loop)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS interrupt_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id VARCHAR(255) REFERENCES conversation_threads(thread_id) ON DELETE CASCADE,
    tool_call_id VARCHAR(255) NOT NULL,
    tool_name VARCHAR(255) NOT NULL,
    decision VARCHAR(50) NOT NULL,  -- 'approve', 'reject', 'edit'
    edited_args JSONB,
    decided_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_interrupts_thread_id ON interrupt_decisions(thread_id);
CREATE INDEX idx_interrupts_tool_call_id ON interrupt_decisions(tool_call_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Trigger: Update timestamp on update
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_agent_configs_updated_at
    BEFORE UPDATE ON agent_configs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_conversation_threads_updated_at
    BEFORE UPDATE ON conversation_threads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ─────────────────────────────────────────────────────────────────────────────
-- Default Agent
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO agent_configs (agent_id, name, model, tools, interrupt_on, max_turns, ttl_minutes)
VALUES (
    'default',
    'Default Agent',
    'glm-5',
    '["python_sandbox"]',
    '{"execute": true}',
    100,
    60
) ON CONFLICT (agent_id) DO NOTHING;
