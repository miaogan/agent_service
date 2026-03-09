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
        self._pool = None

    @property
    def saver(self) -> Optional[AsyncPostgresSaver]:
        """Get the checkpointer instance."""
        return self._saver

    async def setup(self) -> None:
        """Initialize the PostgreSQL checkpointer."""
        # Check if PostgreSQL is configured
        if not self.settings.database_url and not self.settings.postgres_host:
            logger.info("No PostgreSQL configuration found, using in-memory checkpointer")
            return

        try:
            from psycopg_pool import AsyncConnectionPool

            # Use synchronous connection string format for psycopg3
            # psycopg_pool uses psycopg3, NOT asyncpg
            db_url = self.settings.effective_database_url

            # Mask password in log
            log_url = db_url
            if '@' in db_url:
                parts = db_url.split('@')
                log_url = parts[0].rsplit(':', 1)[0] + ':***@' + parts[1]

            logger.info(f"Connecting to PostgreSQL: {log_url}")

            # Create connection pool
            self._pool = AsyncConnectionPool(
                conninfo=db_url,
                max_size=10,
                open=False,
            )

            # Open the pool
            await self._pool.open()

            # Create checkpointer with pool
            self._saver = AsyncPostgresSaver(self._pool)

            # Setup tables (creates checkpoint_writes, checkpoint_blobs, checkpoints, checkpoint_blobs, checkpoint_migrations)
            await self._saver.setup()

            logger.info("PostgreSQL checkpointer initialized successfully")

        except ImportError as e:
            logger.error(f"Missing dependency for PostgreSQL: {e}. Install with: pip install psycopg[binary] psycopg_pool")
            self._saver = None
            self._pool = None
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL checkpointer: {type(e).__name__}: {e}")
            self._saver = None
            self._pool = None

    async def close(self) -> None:
        """Close the PostgreSQL connection pool."""
        if self._pool:
            try:
                await self._pool.close()
                logger.info("PostgreSQL connection pool closed")
            except Exception as e:
                logger.error(f"Error closing PostgreSQL connection: {e}")
            finally:
                self._pool = None
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
