"""
FastAPI application entry point.

Main module that initializes and runs the DeepAgent service.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ─── Windows Event Loop Fix ───────────────────────────────────────────────────

# On Windows, psycopg/asyncpg requires SelectorEventLoop instead of ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.api.routes import register_routes
from app.core.config import Settings, get_settings, ensure_directories
from app.core.checkpoint import get_checkpoint_manager
from app.core.storage import AgentConfigStorage
from app.models.schemas import AgentConfig
from app.services.agent_pool import AgentPool
from app.services.agent_service import AgentService

# ─── Load environment variables ──────────────────────────────────────────────

load_dotenv()

# ─── Logging configuration ───────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("deepagent.service")

# ─── Constants ───────────────────────────────────────────────────────────────

DEFAULT_AGENT_ID = "default"


def create_default_agent_config(settings: Settings) -> AgentConfig:
    """Create the default agent configuration."""
    return AgentConfig(
        agent_id=DEFAULT_AGENT_ID,
        name="Default Agent",
        model=settings.default_model,
        system_prompt=None,  # Use default system prompt
        tools=["python_sandbox"],
        mcp_servers=[
            {
                "name": "default_mcp",
                "transport": "http",
                "url": settings.mcp_default_url,
            }
        ],
        interrupt_on={
            "execute": True,  # Require approval for shell commands
        },
        max_turns=100,  # Higher limit for default agent
        ttl_minutes=60,  # Longer TTL for default agent
        persistent=True,  # Never destroy default agent
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


# ─── Application factory ─────────────────────────────────────────────────────


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()

    # Ensure directories exist
    ensure_directories(settings)

    # Create agent service
    agent_service = AgentService(settings)

    # Create storage for agent configurations
    storage_path = settings.root_dir / "data" / "agent_configs.json"
    storage = AgentConfigStorage(storage_path)

    # Create agent pool
    agent_pool = AgentPool(
        agent_factory=lambda config: agent_service.create_agent_from_config(config),
        default_ttl_minutes=30,
        default_max_turns=50,
        cleanup_interval_seconds=60,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan manager."""
        logger.info("DeepAgent service starting...")

        # Initialize PostgreSQL checkpointer
        checkpoint_manager = get_checkpoint_manager()
        await checkpoint_manager.setup()

        if checkpoint_manager.saver:
            logger.info("PostgreSQL checkpointer ready for conversation persistence")
        else:
            logger.warning("Using in-memory checkpointer (conversations will not persist across restarts)")

        # Load available models
        await agent_service.refresh_available_models()

        # Start agent pool
        await agent_pool.start()

        # Ensure default agent exists
        default_config = create_default_agent_config(settings)
        if not storage.exists(DEFAULT_AGENT_ID):
            storage.save(default_config)
            logger.info(f"Created default agent configuration: {DEFAULT_AGENT_ID}")
        else:
            # Update default agent config (to sync with settings)
            storage.save(default_config)
            logger.info(f"Updated default agent configuration: {DEFAULT_AGENT_ID}")

        # Load saved agent configurations into pool
        configs = storage.load_all()
        for config in configs:
            agent_pool.register_config(config)
        logger.info(f"Loaded {len(configs)} agent configurations into pool")

        # Pre-create default agent instance (eager initialization)
        try:
            await agent_pool.get(DEFAULT_AGENT_ID)
            logger.info(f"Default agent instance created and ready in pool")
        except Exception as e:
            logger.error(f"Failed to create default agent instance: {e}")

        yield

        # Cleanup
        logger.info("DeepAgent service shutting down...")
        await agent_pool.stop()
        await checkpoint_manager.close()

    # Create FastAPI app
    app = FastAPI(
        title="DeepAgent Service",
        version="0.5.0",
        description="AI agent orchestration service with MCP, Skills, and Agent Pool support",
        lifespan=lifespan,
    )

    # Add CORS middleware for frontend access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 允许所有来源，生产环境应限制
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    register_routes(app, agent_service, agent_pool, storage)

    # Store services in app state for access in routes
    app.state.agent_service = agent_service
    app.state.agent_pool = agent_pool
    app.state.storage = storage
    app.state.settings = settings

    return app


# ─── Create application instance ─────────────────────────────────────────────

app = create_app()

# ─── Development server entry point ─────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info",
    )
