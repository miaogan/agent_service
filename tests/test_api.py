"""
Test cases for API routes.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import get_settings


@pytest.fixture
def client():
    """Create a test client."""
    app = create_app()
    return TestClient(app)


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_create_agent_config(client):
    """Test creating an agent configuration."""
    response = client.post(
        "/agents",
        json={
            "agent_id": "test-agent-1",
            "name": "Test Agent",
            "model": "glm-5",
            "max_turns": 50,
            "ttl_minutes": 30,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["agent_id"] == "test-agent-1"


def test_list_agents(client):
    """Test listing agent configurations."""
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": "test-agent-2",
            "name": "Test Agent 2",
            "model": "glm-5",
        },
    )

    response = client.get("/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_agent(client):
    """Test getting a specific agent configuration."""
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": "test-agent-3",
            "name": "Test Agent 3",
            "model": "glm-5",
        },
    )

    response = client.get("/agents/test-agent-3")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "test-agent-3"


def test_get_nonexistent_agent(client):
    """Test getting a nonexistent agent."""
    response = client.get("/agents/nonexistent")
    assert response.status_code == 404


def test_update_agent(client):
    """Test updating an agent configuration."""
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": "test-agent-4",
            "name": "Original Name",
            "model": "glm-5",
        },
    )

    response = client.put(
        "/agents/test-agent-4",
        json={"name": "Updated Name"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"


def test_delete_agent(client):
    """Test deleting an agent configuration."""
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": "test-agent-5",
            "name": "Test Agent 5",
            "model": "glm-5",
        },
    )

    response = client.delete("/agents/test-agent-5")
    assert response.status_code == 200

    # Verify deletion
    response = client.get("/agents/test-agent-5")
    assert response.status_code == 404


def test_pool_stats(client):
    """Test getting pool statistics."""
    response = client.get("/pool/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_configs" in data
    assert "active_agents" in data


def test_create_agent_with_interrupt_on(client):
    """Test creating an agent with interrupt_on configuration."""
    response = client.post(
        "/agents",
        json={
            "agent_id": "safe-agent",
            "name": "Safe Agent",
            "model": "glm-5",
            "interrupt_on": {"execute": True, "write_file": True},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["agent_id"] == "safe-agent"
    assert data["interrupt_on"] == {"execute": True, "write_file": True}


def test_update_agent_interrupt_on(client):
    """Test updating interrupt_on configuration."""
    # Create an agent first
    client.post(
        "/agents",
        json={
            "agent_id": "test-interrupt",
            "name": "Test Interrupt",
            "model": "glm-5",
        },
    )

    # Update with interrupt_on
    response = client.put(
        "/agents/test-interrupt",
        json={"interrupt_on": {"execute": True}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["interrupt_on"] == {"execute": True}


def test_list_models(client):
    """Test listing available models."""
    response = client.get("/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
