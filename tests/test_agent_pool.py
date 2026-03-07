"""
Test cases for agent pool functionality.
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.models.schemas import AgentConfig, AgentRuntimeInfo, AgentStatus
from app.services.agent_pool import AgentPool, PooledAgent


@pytest.fixture
def sample_config():
    """Create a sample agent configuration."""
    return AgentConfig(
        agent_id="test-agent-1",
        name="Test Agent",
        model="glm-5",
        max_turns=50,
        ttl_minutes=30,
    )


@pytest.fixture
def mock_agent_factory():
    """Create a mock agent factory."""
    return AsyncMock(return_value=MagicMock())


@pytest.mark.asyncio
async def test_pool_start_stop(mock_agent_factory):
    """Test pool start and stop."""
    pool = AgentPool(mock_agent_factory)

    await pool.start()
    assert pool._running is True

    await pool.stop()
    assert pool._running is False


@pytest.mark.asyncio
async def test_register_config(sample_config, mock_agent_factory):
    """Test registering an agent configuration."""
    pool = AgentPool(mock_agent_factory)
    pool.register_config(sample_config)

    assert sample_config.agent_id in pool._configs


@pytest.mark.asyncio
async def test_get_agent_creates_instance(sample_config, mock_agent_factory):
    """Test getting an agent creates a new instance."""
    pool = AgentPool(mock_agent_factory)
    pool.register_config(sample_config)

    pooled = await pool.get(sample_config.agent_id)

    assert pooled is not None
    assert pooled.config.agent_id == sample_config.agent_id
    mock_agent_factory.assert_called_once()


@pytest.mark.asyncio
async def test_get_agent_reuses_instance(sample_config, mock_agent_factory):
    """Test getting an agent reuses existing instance."""
    pool = AgentPool(mock_agent_factory)
    pool.register_config(sample_config)

    # Get agent twice
    pooled1 = await pool.get(sample_config.agent_id)
    pooled2 = await pool.get(sample_config.agent_id)

    assert pooled1 is pooled2
    mock_agent_factory.assert_called_once()  # Should only create once


@pytest.mark.asyncio
async def test_increment_turn(sample_config, mock_agent_factory):
    """Test incrementing turn counter."""
    pool = AgentPool(mock_agent_factory)
    pool.register_config(sample_config)
    await pool.get(sample_config.agent_id)

    # Increment turns
    for i in range(5):
        result = pool.increment_turn(sample_config.agent_id)
        assert result is True

    assert pool._pool[sample_config.agent_id].runtime.current_turns == 5


@pytest.mark.asyncio
async def test_max_turns_exceeded(sample_config, mock_agent_factory):
    """Test that max turns limit is enforced."""
    sample_config.max_turns = 3
    pool = AgentPool(mock_agent_factory)
    pool.register_config(sample_config)
    await pool.get(sample_config.agent_id)

    # Increment to max
    result = True
    for i in range(3):
        result = pool.increment_turn(sample_config.agent_id)

    # Last increment should return False
    assert result is False
    assert pool._pool[sample_config.agent_id].runtime.status == AgentStatus.EXPIRED


@pytest.mark.asyncio
async def test_remove_agent(sample_config, mock_agent_factory):
    """Test removing an agent from pool."""
    pool = AgentPool(mock_agent_factory)
    pool.register_config(sample_config)
    await pool.get(sample_config.agent_id)

    result = await pool.remove(sample_config.agent_id)

    assert result is True
    assert sample_config.agent_id not in pool._pool


@pytest.mark.asyncio
async def test_pool_stats(mock_agent_factory):
    """Test getting pool statistics."""
    pool = AgentPool(mock_agent_factory)

    config1 = AgentConfig(agent_id="agent-1", name="Agent 1", model="glm-5")
    config2 = AgentConfig(agent_id="agent-2", name="Agent 2", model="glm-5")

    pool.register_config(config1)
    pool.register_config(config2)

    stats = pool.get_stats()

    assert stats["total_configs"] == 2
    assert stats["active_agents"] == 0
