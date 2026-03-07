"""
Test cases for API routes.
"""

import json
import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import get_settings


@pytest.fixture
def client():
    """Create a test client."""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def unique_id():
    """Generate unique ID for test agents."""
    return str(uuid.uuid4())[:8]


# ─── Health & Monitoring ────────────────────────────────────────────────────


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "DeepAgent"


def test_list_models(client):
    """Test listing available models."""
    response = client.get("/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert isinstance(data["models"], list)
    # Models may be empty if LiteLLM is not available
    # Just check the structure is correct


def test_pool_stats(client):
    """Test getting pool statistics."""
    response = client.get("/pool/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_configs" in data
    assert "active_agents" in data
    assert "agents" in data


# ─── Agent CRUD Operations ───────────────────────────────────────────────────


def test_create_agent_config(client, unique_id):
    """Test creating an agent configuration."""
    agent_id = f"test-agent-{unique_id}"
    response = client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Test Agent",
            "model": "glm-5",
            "max_turns": 50,
            "ttl_minutes": 30,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["agent_id"] == agent_id
    assert data["name"] == "Test Agent"
    assert data["model"] == "glm-5"


def test_create_duplicate_agent(client, unique_id):
    """Test creating a duplicate agent fails."""
    agent_id = f"duplicate-{unique_id}"
    # Create first
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Duplicate Agent",
            "model": "glm-5",
        },
    )

    # Try to create duplicate
    response = client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Another Agent",
            "model": "glm-5",
        },
    )
    assert response.status_code == 400


def test_create_agent_with_interrupt_on(client, unique_id):
    """Test creating an agent with interrupt_on configuration."""
    agent_id = f"safe-agent-{unique_id}"
    response = client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Safe Agent",
            "model": "glm-5",
            "interrupt_on": {"execute": True, "write_file": True},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["agent_id"] == agent_id
    assert data["interrupt_on"] == {"execute": True, "write_file": True}


def test_create_agent_with_mcp_servers(client, unique_id):
    """Test creating an agent with MCP server configuration."""
    agent_id = f"mcp-agent-{unique_id}"
    response = client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "MCP Agent",
            "model": "glm-5",
            "mcp_servers": [
                {
                    "name": "test_mcp",
                    "transport": "http",
                    "url": "http://localhost:8000/mcp"
                }
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["mcp_servers"] is not None
    assert len(data["mcp_servers"]) == 1


def test_list_agents(client):
    """Test listing agent configurations."""
    response = client.get("/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # At minimum, default agent should exist
    assert len(data) >= 1


def test_get_agent(client, unique_id):
    """Test getting a specific agent configuration."""
    agent_id = f"test-get-{unique_id}"
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Test Get Agent",
            "model": "glm-5",
        },
    )

    response = client.get(f"/agents/{agent_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == agent_id


def test_get_nonexistent_agent(client):
    """Test getting a nonexistent agent."""
    response = client.get("/agents/nonexistent-agent-xyz")
    assert response.status_code == 404


def test_update_agent(client, unique_id):
    """Test updating an agent configuration."""
    agent_id = f"test-update-{unique_id}"
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Original Name",
            "model": "glm-5",
        },
    )

    response = client.put(
        f"/agents/{agent_id}",
        json={"name": "Updated Name"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"


def test_update_agent_interrupt_on(client, unique_id):
    """Test updating interrupt_on configuration."""
    agent_id = f"test-interrupt-{unique_id}"
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Test Interrupt",
            "model": "glm-5",
        },
    )

    # Update with interrupt_on
    response = client.put(
        f"/agents/{agent_id}",
        json={"interrupt_on": {"execute": True}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["interrupt_on"] == {"execute": True}


def test_update_nonexistent_agent(client):
    """Test updating a nonexistent agent."""
    response = client.put(
        "/agents/nonexistent-agent-xyz",
        json={"name": "New Name"},
    )
    assert response.status_code == 404


def test_update_agent_model(client, unique_id):
    """Test updating agent model."""
    agent_id = f"test-model-{unique_id}"
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Test Update Model",
            "model": "glm-5",
        },
    )

    response = client.put(
        f"/agents/{agent_id}",
        json={"model": "qwen3.5:9b"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "qwen3.5:9b"


def test_delete_agent(client, unique_id):
    """Test deleting an agent configuration."""
    agent_id = f"test-delete-{unique_id}"
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Test Delete Agent",
            "model": "glm-5",
        },
    )

    response = client.delete(f"/agents/{agent_id}")
    assert response.status_code == 200

    # Verify deletion
    response = client.get(f"/agents/{agent_id}")
    assert response.status_code == 404


def test_delete_nonexistent_agent(client):
    """Test deleting a nonexistent agent."""
    response = client.delete("/agents/nonexistent-agent-xyz")
    assert response.status_code == 404


# ─── Chat Endpoints ──────────────────────────────────────────────────────────


def test_chat_stream_default_agent(client, unique_id):
    """Test chat stream with explicitly created default-like agent."""
    # Create an agent similar to default for testing
    agent_id = f"default-test-{unique_id}"
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Default-like Agent",
            "model": "glm-5",
        },
    )

    # Test chat with this agent
    response = client.post(
        f"/chat/{agent_id}/stream",
        json={
            "message": "Hello, how are you?",
            "thread_id": "test-thread-1",
            "model": "glm-5"
        },
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    # Read the streaming response
    content = response.text
    assert "data:" in content
    assert "[DONE]" in content


def test_chat_stream_with_specific_agent(client, unique_id):
    """Test chat stream with a specific agent."""
    agent_id = f"chat-test-{unique_id}"
    # Create a test agent
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Chat Test Agent",
            "model": "glm-5",
        },
    )

    response = client.post(
        f"/chat/{agent_id}/stream",
        json={
            "message": "Tell me a joke",
            "thread_id": "test-thread-2",
        },
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]


def test_chat_stream_nonexistent_agent(client):
    """Test chat stream with nonexistent agent."""
    response = client.post(
        "/chat/nonexistent-agent-xyz/stream",
        json={
            "message": "Hello",
            "thread_id": "test-thread-3",
        },
    )

    assert response.status_code == 404


def test_chat_stream_empty_message(client):
    """Test chat stream with empty message."""
    response = client.post(
        "/chat/stream",
        json={
            "message": "",
            "thread_id": "test-thread-4",
        },
    )

    assert response.status_code == 422  # Validation error


def test_chat_stream_invalid_model(client, unique_id):
    """Test chat stream with invalid model."""
    agent_id = f"invalid-model-{unique_id}"
    # Create agent with specific model
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Invalid Model Agent",
            "model": "invalid-model-xyz",
        },
    )

    # Try to chat with this agent - will fail at creation time
    response = client.post(
        f"/chat/{agent_id}/stream",
        json={
            "message": "Hello",
            "thread_id": "test-thread-5",
        },
    )

    # Agent exists but may fail to create instance with invalid model
    assert response.status_code in [200, 404, 500]


# ─── Human-in-the-Loop (Interrupt) ───────────────────────────────────────────


def test_chat_with_interrupt(client, unique_id):
    """Test chat that triggers interrupt."""
    agent_id = f"interrupt-{unique_id}"
    # Create agent with interrupt_on
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Interrupt Agent",
            "model": "glm-5",
            "interrupt_on": {"execute": True},
        },
    )

    # Note: Actual interrupt behavior depends on agent response
    # This test verifies the endpoint works, not the interrupt logic
    response = client.post(
        f"/chat/{agent_id}/stream",
        json={
            "message": "Execute a shell command",
            "thread_id": "interrupt-thread-1",
        },
    )

    assert response.status_code == 200


def test_resume_nonexistent_agent(client):
    """Test resume with nonexistent agent."""
    response = client.post(
        "/chat/nonexistent-agent-xyz/resume",
        json={
            "decision": "approve",
            "tool_call_id": "call_123",
            "thread_id": "resume-thread-1",
        },
    )

    assert response.status_code == 404


def test_resume_invalid_decision(client, unique_id):
    """Test resume with invalid decision."""
    agent_id = f"resume-test-{unique_id}"
    # Create agent
    client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Resume Test Agent",
            "model": "glm-5",
        },
    )

    response = client.post(
        f"/chat/{agent_id}/resume",
        json={
            "decision": "invalid_decision",
            "tool_call_id": "call_123",
            "thread_id": "resume-thread-2",
        },
    )

    assert response.status_code == 400


# ─── Validation Tests ────────────────────────────────────────────────────────


def test_create_agent_invalid_max_turns(client, unique_id):
    """Test creating agent with invalid max_turns."""
    agent_id = f"invalid-turns-{unique_id}"
    response = client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Invalid Turns Agent",
            "model": "glm-5",
            "max_turns": 200,  # Exceeds limit of 100
        },
    )

    assert response.status_code == 422  # Validation error


def test_create_agent_invalid_ttl(client, unique_id):
    """Test creating agent with invalid TTL."""
    agent_id = f"invalid-ttl-{unique_id}"
    response = client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Invalid TTL Agent",
            "model": "glm-5",
            "ttl_minutes": 2000,  # Exceeds limit of 1440
        },
    )

    assert response.status_code == 422  # Validation error


def test_create_agent_missing_required_fields(client):
    """Test creating agent without required fields."""
    response = client.post(
        "/agents",
        json={
            "name": "Missing ID Agent",
            # Missing agent_id
        },
    )

    assert response.status_code == 422  # Validation error


# ─── Default Agent ───────────────────────────────────────────────────────────


def test_default_agent_exists(client):
    """Test that default agent is created automatically."""
    response = client.get("/agents/default")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "default"
    assert data["name"] == "Default Agent"


# ─── Integration Tests ───────────────────────────────────────────────────────


def test_full_agent_lifecycle(client, unique_id):
    """Test complete agent lifecycle: create, read, update, delete."""
    agent_id = f"lifecycle-{unique_id}"

    # Create
    create_response = client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Lifecycle Agent",
            "model": "glm-5",
        },
    )
    assert create_response.status_code == 201

    # Read
    get_response = client.get(f"/agents/{agent_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Lifecycle Agent"

    # Update
    update_response = client.put(
        f"/agents/{agent_id}",
        json={"name": "Updated Lifecycle Agent"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated Lifecycle Agent"

    # Delete
    delete_response = client.delete(f"/agents/{agent_id}")
    assert delete_response.status_code == 200

    # Verify deletion
    verify_response = client.get(f"/agents/{agent_id}")
    assert verify_response.status_code == 404


def test_multiple_agents_isolation(client, unique_id):
    """Test that multiple agents are isolated."""
    agent_id_1 = f"isolation-1-{unique_id}"
    agent_id_2 = f"isolation-2-{unique_id}"

    # Create two agents
    client.post(
        "/agents",
        json={
            "agent_id": agent_id_1,
            "name": "Isolation Agent 1",
            "model": "glm-5",
        },
    )

    client.post(
        "/agents",
        json={
            "agent_id": agent_id_2,
            "name": "Isolation Agent 2",
            "model": "qwen3.5:9b",
        },
    )

    # Verify both exist independently
    response1 = client.get(f"/agents/{agent_id_1}")
    assert response1.status_code == 200
    assert response1.json()["model"] == "glm-5"

    response2 = client.get(f"/agents/{agent_id_2}")
    assert response2.status_code == 200
    assert response2.json()["model"] == "qwen3.5:9b"


def test_pool_stats_updates(client, unique_id):
    """Test that pool stats reflect agent changes."""
    agent_id = f"stats-test-{unique_id}"

    initial_stats = client.get("/pool/stats").json()
    initial_count = initial_stats["total_configs"]

    # Create new agent
    create_response = client.post(
        "/agents",
        json={
            "agent_id": agent_id,
            "name": "Stats Test Agent",
            "model": "glm-5",
        },
    )
    assert create_response.status_code == 201

    # Check stats updated
    updated_stats = client.get("/pool/stats").json()
    assert updated_stats["total_configs"] == initial_count + 1

    # Delete agent
    client.delete(f"/agents/{agent_id}")

    # Check stats reverted
    final_stats = client.get("/pool/stats").json()
    # Should be back to initial (may include default agent)
    assert final_stats["total_configs"] >= initial_count
