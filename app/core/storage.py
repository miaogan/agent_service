"""
Persistent storage module for agent configurations.

Provides JSON file-based storage for agent configurations.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.models.schemas import AgentConfig

logger = logging.getLogger("deepagent.service")


class AgentConfigStorage:
    """JSON file-based storage for agent configurations."""

    def __init__(self, storage_path: Path):
        """Initialize storage with the given path."""
        self.storage_path = storage_path
        self._ensure_storage_file()

    def _ensure_storage_file(self) -> None:
        """Ensure storage file exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._save_all({})
            logger.info(f"Created new storage file: {self.storage_path}")

    def _load_all(self) -> Dict[str, dict]:
        """Load all configurations from file."""
        try:
            with open(self.storage_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning(f"Failed to load storage, starting fresh: {e}")
            return {}

    def _save_all(self, data: Dict[str, dict]) -> None:
        """Save all configurations to file."""
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    def save(self, config: AgentConfig) -> None:
        """Save or update an agent configuration."""
        data = self._load_all()
        data[config.agent_id] = config.model_dump(mode="json")
        self._save_all(data)
        logger.info(f"Saved agent config: {config.agent_id}")

    def load(self, agent_id: str) -> Optional[AgentConfig]:
        """Load a specific agent configuration."""
        data = self._load_all()
        if agent_id in data:
            return AgentConfig(**data[agent_id])
        return None

    def load_all(self) -> List[AgentConfig]:
        """Load all agent configurations."""
        data = self._load_all()
        configs = []
        for agent_id, config_dict in data.items():
            try:
                configs.append(AgentConfig(**config_dict))
            except Exception as e:
                logger.warning(f"Failed to parse config {agent_id}: {e}")
        return configs

    def delete(self, agent_id: str) -> bool:
        """Delete an agent configuration."""
        data = self._load_all()
        if agent_id in data:
            del data[agent_id]
            self._save_all(data)
            logger.info(f"Deleted agent config: {agent_id}")
            return True
        return False

    def exists(self, agent_id: str) -> bool:
        """Check if an agent configuration exists."""
        data = self._load_all()
        return agent_id in data
