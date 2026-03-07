"""
API request/response schemas.

Pydantic models for request validation and response serialization.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─── Agent Configuration ─────────────────────────────────────────────────────


class AgentStatus(str, Enum):
    """Agent runtime status."""

    IDLE = "idle"
    ACTIVE = "active"
    EXPIRED = "expired"


class AgentConfig(BaseModel):
    """Agent configuration model for persistence."""

    agent_id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Agent display name")
    model: str = Field(default="glm-5", description="Model name to use")
    system_prompt: Optional[str] = Field(
        default=None, description="Custom system prompt"
    )
    tools: List[str] = Field(
        default_factory=lambda: ["python_sandbox"],
        description="List of tool names to enable",
    )
    mcp_servers: Optional[List[Dict[str, str]]] = Field(
        default=None, description="MCP server configurations"
    )
    max_turns: int = Field(default=50, description="Maximum conversation turns")
    ttl_minutes: int = Field(default=30, description="TTL in minutes after last use")
    created_at: datetime = Field(
        default_factory=datetime.now, description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.now, description="Last update timestamp"
    )

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class AgentConfigCreate(BaseModel):
    """Model for creating a new agent configuration."""

    agent_id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Agent display name")
    model: str = Field(default="glm-5", description="Model name to use")
    system_prompt: Optional[str] = Field(default=None, description="Custom system prompt")
    tools: List[str] = Field(
        default_factory=lambda: ["python_sandbox"],
        description="List of tool names to enable",
    )
    mcp_servers: Optional[List[Dict[str, str]]] = Field(
        default=None, description="MCP server configurations"
    )
    max_turns: int = Field(default=50, ge=1, le=100, description="Maximum conversation turns")
    ttl_minutes: int = Field(default=30, ge=1, le=1440, description="TTL in minutes")


class AgentConfigUpdate(BaseModel):
    """Model for updating an existing agent configuration."""

    name: Optional[str] = Field(default=None, description="Agent display name")
    model: Optional[str] = Field(default=None, description="Model name to use")
    system_prompt: Optional[str] = Field(default=None, description="Custom system prompt")
    tools: Optional[List[str]] = Field(default=None, description="List of tool names")
    mcp_servers: Optional[List[Dict[str, str]]] = Field(
        default=None, description="MCP server configurations"
    )
    max_turns: Optional[int] = Field(default=None, ge=1, le=100)
    ttl_minutes: Optional[int] = Field(default=None, ge=1, le=1440)


class AgentRuntimeInfo(BaseModel):
    """Runtime information for an active agent instance."""

    agent_id: str
    status: AgentStatus = AgentStatus.IDLE
    current_turns: int = 0
    last_used_at: datetime = Field(default_factory=datetime.now)
    created_at: datetime = Field(default_factory=datetime.now)


class AgentInfo(BaseModel):
    """Complete agent information including config and runtime state."""

    config: AgentConfig
    runtime: Optional[AgentRuntimeInfo] = None


# ─── Chat Models ─────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Chat request model."""

    message: str = Field(..., min_length=1, description="User message")
    agent_id: Optional[str] = Field(default=None, description="Agent ID to use")
    model: str = Field(default="glm-5", description="Model name to use (fallback)")
    thread_id: str = Field(default="conversation1", description="Conversation thread ID")


class ChatResponse(BaseModel):
    """Chat response model for non-streaming responses."""

    content: str = Field(..., description="Response content")
    tools_used: list = Field(default_factory=list, description="List of tools used")
    agent_id: Optional[str] = Field(default=None, description="Agent ID used")
