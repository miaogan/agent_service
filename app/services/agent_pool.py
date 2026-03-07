"""
Agent pool management module.

Manages agent instances with TTL and turn limits.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from app.models.schemas import AgentConfig, AgentRuntimeInfo, AgentStatus

logger = logging.getLogger("deepagent.service")


@dataclass
class PooledAgent:
    """Wrapper for a pooled agent instance."""

    config: AgentConfig
    instance: Any
    runtime: AgentRuntimeInfo = field(default_factory=lambda: AgentRuntimeInfo(agent_id=""))

    def __post_init__(self):
        self.runtime.agent_id = self.config.agent_id
        self.runtime.created_at = datetime.now()
        self.runtime.last_used_at = datetime.now()


class AgentPool:
    """
    Agent pool manager with TTL and turn limits.

    Features:
    - Lazy initialization of agents
    - TTL-based expiration (default 30 minutes after last use)
    - Turn-based expiration (default 50 turns max)
    - Background cleanup task
    """

    def __init__(
        self,
        agent_factory,
        default_ttl_minutes: int = 30,
        default_max_turns: int = 50,
        cleanup_interval_seconds: int = 60,
    ):
        """Initialize the agent pool."""
        self.agent_factory = agent_factory
        self.default_ttl_minutes = default_ttl_minutes
        self.default_max_turns = default_max_turns
        self.cleanup_interval_seconds = cleanup_interval_seconds

        self._pool: Dict[str, PooledAgent] = {}
        self._configs: Dict[str, AgentConfig] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Agent pool started with background cleanup")

    async def stop(self) -> None:
        """Stop the background cleanup task and clear pool."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        await self.clear()
        logger.info("Agent pool stopped")

    def register_config(self, config: AgentConfig) -> None:
        """Register an agent configuration (without creating instance)."""
        self._configs[config.agent_id] = config
        logger.debug(f"Registered agent config: {config.agent_id}")

    async def unregister_config(self, agent_id: str) -> bool:
        """Unregister an agent configuration and remove from pool."""
        if agent_id in self._configs:
            del self._configs[agent_id]
        return await self.remove(agent_id)

    async def get(self, agent_id: str) -> Optional[PooledAgent]:
        """
        Get an agent from the pool by ID.

        Creates the agent if not in pool but config exists.
        Returns None if agent doesn't exist or is expired.
        """
        async with self._lock:
            # Check if in pool
            if agent_id in self._pool:
                pooled = self._pool[agent_id]

                # Check if expired
                if self._is_expired(pooled):
                    await self._remove_agent(agent_id)
                    logger.info(f"Agent {agent_id} expired, will recreate")
                else:
                    # Update last used time
                    pooled.runtime.last_used_at = datetime.now()
                    pooled.runtime.status = AgentStatus.ACTIVE
                    return pooled

            # Check if config exists
            if agent_id not in self._configs:
                logger.warning(f"Agent config not found: {agent_id}")
                return None

            # Create new agent instance
            config = self._configs[agent_id]
            try:
                instance = await self.agent_factory(config)
                pooled = PooledAgent(config=config, instance=instance)
                self._pool[agent_id] = pooled
                logger.info(f"Created agent instance: {agent_id}")
                return pooled
            except Exception as e:
                logger.error(f"Failed to create agent {agent_id}: {e}")
                return None

    async def remove(self, agent_id: str) -> bool:
        """Remove an agent from the pool."""
        async with self._lock:
            return await self._remove_agent(agent_id)

    async def _remove_agent(self, agent_id: str) -> bool:
        """Internal method to remove agent without lock."""
        if agent_id in self._pool:
            del self._pool[agent_id]
            logger.info(f"Removed agent from pool: {agent_id}")
            return True
        return False

    async def clear(self) -> None:
        """Clear all agents from the pool."""
        async with self._lock:
            self._pool.clear()
            logger.info("Cleared agent pool")

    def increment_turn(self, agent_id: str) -> bool:
        """
        Increment the turn counter for an agent.

        Returns False if max turns exceeded.
        """
        if agent_id not in self._pool:
            return False

        pooled = self._pool[agent_id]
        pooled.runtime.current_turns += 1

        max_turns = pooled.config.max_turns or self.default_max_turns
        if pooled.runtime.current_turns >= max_turns:
            pooled.runtime.status = AgentStatus.EXPIRED
            logger.info(f"Agent {agent_id} reached max turns ({max_turns})")
            return False

        return True

    def _is_expired(self, pooled: PooledAgent) -> bool:
        """Check if an agent has expired based on TTL or turn limit."""
        # Check if agent is persistent (never destroy)
        if pooled.config.persistent:
            logger.debug(f"Agent {pooled.config.agent_id} is persistent, skipping expiration check")
            return False
        
        # Check turn limit
        max_turns = pooled.config.max_turns or self.default_max_turns
        if pooled.runtime.current_turns >= max_turns:
            return True

        # Check TTL
        ttl_minutes = pooled.config.ttl_minutes or self.default_ttl_minutes
        elapsed = (datetime.now() - pooled.runtime.last_used_at).total_seconds() / 60
        return elapsed >= ttl_minutes

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired agents."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval_seconds)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def _cleanup_expired(self) -> None:
        """Remove all expired agents from the pool."""
        async with self._lock:
            expired_ids = [
                agent_id for agent_id, pooled in self._pool.items()
                if self._is_expired(pooled)
            ]

            for agent_id in expired_ids:
                await self._remove_agent(agent_id)

            if expired_ids:
                logger.info(f"Cleaned up {len(expired_ids)} expired agents")

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        return {
            "total_configs": len(self._configs),
            "active_agents": len(self._pool),
            "agents": {
                agent_id: {
                    "status": pooled.runtime.status.value,
                    "turns": pooled.runtime.current_turns,
                    "last_used": pooled.runtime.last_used_at.isoformat(),
                }
                for agent_id, pooled in self._pool.items()
            },
        }

    def list_configs(self) -> list:
        """List all registered agent configurations."""
        return list(self._configs.values())
