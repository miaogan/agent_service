"""
Core configuration module.

Provides Pydantic settings management and application constants.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("deepagent.service")

# ─── Constants ──────────────────────────────────────────────────────────────

AGENT_MODE_SKILL = "skill"
AGENT_MODE_MCP = "mcp"
AGENT_MODE_BOTH = "both"
VALID_MODES = {AGENT_MODE_SKILL, AGENT_MODE_MCP, AGENT_MODE_BOTH}

# Persistent directory mount path in container (fixed)
PERSISTENT_MOUNT_PATH = "/workspace"

# Default MCP configuration
DEFAULT_MCP_CONFIG = {
    "my_fastmcp": {
        "transport": "http",
        "url": "http://127.0.0.1:8000/mcp",
    }
}


# ─── Settings ────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    root_dir: Path = Path(__file__).resolve().parent.parent.parent
    litellm_api_base: str = "http://127.0.0.1:4000"
    mcp_default_url: str = "http://127.0.0.1:8000/mcp"
    mcp_load_fail_continue: bool = True
    default_thread_id: str = "conversation1"
    default_model: str = "qwen3.5:9b"

    # PostgreSQL configuration
    database_url: Optional[str] = None  # e.g., postgresql://user:pass@host:port/db
    postgres_host: Optional[str] = None  # Set to None to disable PostgreSQL
    postgres_port: int = 5432
    postgres_user: str = "deepagent"
    postgres_password: str = "deepagent"
    postgres_db: str = "deepagent"

    # OpenSandbox configuration
    opensandbox_endpoint: str = "http://localhost:8000"
    opensandbox_api_key: Optional[str] = None

    # Sandbox persistent output directory (host path)
    # Use Unix-style path for compatibility
    sandbox_output_host_dir: str = "/workspace"

    @property
    def skill_dir(self) -> Path:
        """Get the skill directory path."""
        return self.root_dir / "skill"

    @property
    def workspace_dir(self) -> Path:
        """Get the workspace directory path."""
        return self.root_dir / "workspace"

    @property
    def effective_database_url(self) -> str:
        """Get the effective database URL, building from components if needed."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def async_database_url(self) -> str:
        """Get async database URL for asyncpg."""
        url = self.effective_database_url
        # Convert postgresql:// to postgresql+asyncpg://
        if url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + url[len("postgresql://"):]
        return url


def get_settings() -> Settings:
    """Get application settings singleton."""
    return Settings()


def ensure_directories(settings: Settings) -> None:
    """Ensure required directories exist."""
    settings.skill_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    os.makedirs(settings.sandbox_output_host_dir, exist_ok=True)
    logger.info(f"Sandbox persistent output directory ready: {settings.sandbox_output_host_dir}")
