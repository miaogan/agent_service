"""
PostgreSQL checkpointer module.

Provides persistent conversation state storage using PostgreSQL.
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings

logger = logging.getLogger("deepagent.service")


class CheckpointManager:
    """Manages PostgreSQL checkpointer lifecycle."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._saver: Optional[AsyncPostgresSaver] = None
        self._connection = None

    @property
    def saver(self) -> Optional[AsyncPostgresSaver]:
        """Get the checkpointer instance."""
        return self._saver

    async def setup(self) -> None:
        """Initialize the PostgreSQL checkpointer."""
        if not self.settings.database_url and not self.settings.postgres_host:
            logger.info("No PostgreSQL configuration found, using in-memory checkpointer")
            return

        try:
            from psycopg_pool import AsyncConnectionPool

            # Create connection pool
            db_url = self.settings.async_database_url
            logger.info(f"Connecting to PostgreSQL: {db_url.split('@')[-1] if '@' in db_url else db_url}")

            self._connection = AsyncConnectionPool(
                conninfo=self.settings.effective_database_url,
                max_size=10,
                open=False,
            )

            # Open the pool
            await self._connection.open()

            # Create checkpointer
            self._saver = AsyncPostgresSaver(self._connection)

            # Setup tables
            await self._saver.setup()

            logger.info("PostgreSQL checkpointer initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL checkpointer: {e}")
            # Fall back to in-memory
            self._saver = None
            self._connection = None
            raise

    async def close(self) -> None:
        """Close the PostgreSQL connection pool."""
        if self._connection:
            try:
                await self._connection.close()
                logger.info("PostgreSQL connection pool closed")
            except Exception as e:
                logger.error(f"Error closing PostgreSQL connection: {e}")
            finally:
                self._connection = None
                self._saver = None

    @asynccontextmanager
    async def lifespan(self):
        """Context manager for checkpointer lifecycle."""
        await self.setup()
        try:
            yield self._saver
        finally:
            await self.close()


# Global instance
_checkpoint_manager: Optional[CheckpointManager] = None


def get_checkpoint_manager() -> CheckpointManager:
    """Get or create the global checkpoint manager."""
    global _checkpoint_manager
    if _checkpoint_manager is None:
        from app.core.config import get_settings
        _checkpoint_manager = CheckpointManager(get_settings())
    return _checkpoint_manager
