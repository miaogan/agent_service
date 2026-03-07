"""
FastAPI application entry point.

Main module that initializes and runs the DeepAgent service.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import register_routes
from app.core.config import Settings, get_settings, ensure_directories
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

        yield

        # Cleanup
        logger.info("DeepAgent service shutting down...")
        await agent_pool.stop()

    # Create FastAPI app
    app = FastAPI(
        title="DeepAgent Service",
        version="0.5.0",
        description="AI agent orchestration service with MCP, Skills, and Agent Pool support",
        lifespan=lifespan,
    )

    # Register routes
    register_routes(app, agent_service, agent_pool, storage)

    # Mount static files for web UI
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        logger.info(f"Static files mounted from {static_dir}")

    # Serve index.html at root
    @app.get("/", include_in_schema=False)
    async def root():
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"message": "DeepAgent API", "docs": "/docs"}

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
