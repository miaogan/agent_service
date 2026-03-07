"""
Test cases for agent configuration storage.
"""

import json
import pytest
import tempfile
from pathlib import Path

from app.core.storage import AgentConfigStorage
from app.models.schemas import AgentConfig


@pytest.fixture
def temp_storage_path():
    """Create a temporary storage file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{}")
        yield Path(f.name)


@pytest.fixture
def storage(temp_storage_path):
    """Create a storage instance."""
    return AgentConfigStorage(temp_storage_path)


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


def test_save_config(storage, sample_config):
    """Test saving an agent configuration."""
    storage.save(sample_config)

    assert storage.exists(sample_config.agent_id)
    loaded = storage.load(sample_config.agent_id)
    assert loaded.agent_id == sample_config.agent_id
    assert loaded.name == sample_config.name


def test_load_nonexistent_config(storage):
    """Test loading a nonexistent configuration."""
    result = storage.load("nonexistent")
    assert result is None


def test_load_all_configs(storage, sample_config):
    """Test loading all configurations."""
    config2 = AgentConfig(
        agent_id="test-agent-2",
        name="Test Agent 2",
        model="glm-5",
    )

    storage.save(sample_config)
    storage.save(config2)

    all_configs = storage.load_all()
    assert len(all_configs) == 2
    assert any(c.agent_id == sample_config.agent_id for c in all_configs)


def test_delete_config(storage, sample_config):
    """Test deleting a configuration."""
    storage.save(sample_config)
    assert storage.exists(sample_config.agent_id)

    result = storage.delete(sample_config.agent_id)
    assert result is True
    assert not storage.exists(sample_config.agent_id)


def test_delete_nonexistent_config(storage):
    """Test deleting a nonexistent configuration."""
    result = storage.delete("nonexistent")
    assert result is False


def test_update_config(storage, sample_config):
    """Test updating a configuration."""
    storage.save(sample_config)

    # Update
    sample_config.name = "Updated Name"
    storage.save(sample_config)

    loaded = storage.load(sample_config.agent_id)
    assert loaded.name == "Updated Name"
