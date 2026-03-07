"""
Agent service module.

Provides agent creation, MCP tool loading, and model management.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.middleware import SkillsMiddleware
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from app.core.config import Settings, PERSISTENT_MOUNT_PATH, DEFAULT_MCP_CONFIG
from app.core.checkpoint import get_checkpoint_manager
from app.core.tools import python_sandbox
from app.models.schemas import AgentConfig

logger = logging.getLogger("deepagent.service")


class AgentService:
    """Service for managing agent lifecycle and operations."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._available_models: List[str] = []

    @property
    def available_models(self) -> List[str]:
        """Get list of available models."""
        return self._available_models

    async def refresh_available_models(self) -> None:
        """Fetch available models from LiteLLM."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.settings.litellm_api_base}/v1/models",
                    timeout=8.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._available_models = [
                        m["id"] for m in data.get("data", []) if m.get("id")
                    ]
                    logger.info(f"Successfully loaded {len(self._available_models)} models")
                else:
                    logger.warning(f"Failed to fetch model list: {resp.status_code}")
        except Exception as e:
            logger.error(f"Cannot fetch LiteLLM model list: {type(e).__name__} {e}")

    async def load_mcp_tools(self, mcp_servers: Optional[List[dict]] = None) -> List:
        """Load MCP tools from configuration."""
        # Build MCP config from server list
        if mcp_servers:
            mcp_config = {}
            for server in mcp_servers:
                name = server.get("name", "mcp_server")
                mcp_config[name] = {
                    "transport": server.get("transport", "http"),
                    "url": server.get("url", self.settings.mcp_default_url),
                }
        else:
            # Use default MCP config
            mcp_config = DEFAULT_MCP_CONFIG.copy()
            mcp_config["my_fastmcp"]["url"] = self.settings.mcp_default_url

        try:
            client = MultiServerMCPClient(mcp_config)
            tools = await client.get_tools()
            logger.info(f"Successfully loaded {len(tools)} MCP tools from {list(mcp_config.keys())}")
            return tools
        except Exception as e:
            logger.error(f"Failed to load MCP tools: {e}")
            if not self.settings.mcp_load_fail_continue:
                raise
            return []

    async def create_agent(
        self,
        model_name: str,
        mcp_servers: Optional[List[dict]] = None,
        system_prompt: Optional[str] = None,
        enable_skills: bool = True,
        enable_mcp: bool = True,
        interrupt_on: Optional[Dict[str, bool]] = None,
    ) -> Any:
        """
        Create a DeepAgent instance.

        Args:
            model_name: Model to use for the agent
            mcp_servers: List of MCP server configurations
            system_prompt: Custom system prompt (optional)
            enable_skills: Whether to enable skills middleware
            enable_mcp: Whether to load MCP tools
            interrupt_on: Tools that require human approval (e.g., {"execute": True})
        """
        backend = FilesystemBackend(
            root_dir=str(self.settings.root_dir),
            virtual_mode=True,
        )

        llm = ChatOpenAI(
            base_url=self.settings.litellm_api_base,
            model=model_name,
            temperature=0.7,
        )

        workspace_path = self.settings.workspace_dir
        skill_path_obj = self.settings.skill_dir

        def composite_backend(rt):
            return CompositeBackend(
                default=backend,
                routes={
                    "/workspace/": FilesystemBackend(
                        root_dir=str(workspace_path),
                        virtual_mode=True,
                    ),
                    "/skill/": FilesystemBackend(
                        root_dir=str(skill_path_obj),
                        virtual_mode=True,
                    ),
                },
            )

        logger.info(
            f"Configuring composite backend: /workspace -> {workspace_path}, "
            f"/skill -> {skill_path_obj}"
        )

        # Build tools list
        tools = [python_sandbox]

        # Load MCP tools if enabled
        if enable_mcp:
            mcp_tools = await self.load_mcp_tools(mcp_servers)
            tools.extend(mcp_tools)

        # Setup skills middleware if enabled
        middleware = []
        if enable_skills:
            skills_middleware = SkillsMiddleware(
                sources=["/skill"],
                backend=backend,
            )
            middleware.append(skills_middleware)
            logger.info("Skills middleware enabled for /skill directory")

        # Build system prompt
        persistent_note = (
            f"\nImportant: When using python_sandbox, if you generate files that need to be kept "
            f"(such as charts, CSV, reports, etc.), save them to {PERSISTENT_MOUNT_PATH} directory.\n"
            f"These files will automatically appear in the host's persistent directory: "
            f"{self.settings.sandbox_output_host_dir}\n"
            "Never delete or overwrite this directory's contents."
        )

        default_system = (
            "You are a powerful assistant with both virtual filesystem and external tool capabilities.\n"
            "All file paths must start with /.\n"
            "**NEVER** use Windows drive letters (D:, C:, etc.) in paths, and never output any real physical paths.\n"
            "When referencing files in /skill directory, use relative paths only, for example:\n"
            "  /skill/arxiv-search/SKILL.md\n"
            "  /skill/langgraph-docs/SKILL.md\n"
            "  arxiv-search/SKILL.md (recommended, leading slash is optional)\n"
            "You can save results to /workspace directory by writing files.\n"
            "You can safely execute Python code via python_sandbox."
            + persistent_note
        )

        system = system_prompt if system_prompt else default_system

        # Configure interrupt_on for human-in-the-loop
        interrupt_config = None
        if interrupt_on:
            interrupt_config = interrupt_on
            logger.info(f"Human-in-the-loop enabled for tools: {list(interrupt_on.keys())}")

        # Get PostgreSQL checkpointer if available
        checkpointer = None
        checkpoint_manager = get_checkpoint_manager()
        if checkpoint_manager.saver:
            checkpointer = checkpoint_manager.saver
            logger.info("Using PostgreSQL checkpointer for conversation persistence")
        else:
            # Use MemorySaver for in-memory checkpointer
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
            logger.info("Using in-memory checkpointer")

        return create_deep_agent(
            model=llm,
            backend=composite_backend,
            middleware=middleware,
            system_prompt=system,
            tools=tools,
            interrupt_on=interrupt_config,
            checkpointer=checkpointer,
        )

    async def create_agent_from_config(self, config: AgentConfig) -> Any:
        """
        Create an agent from an AgentConfig object.

        This is the main factory method for the agent pool.
        """
        # Determine if MCP should be enabled
        enable_mcp = bool(config.mcp_servers) if config.mcp_servers else True

        return await self.create_agent(
            model_name=config.model,
            mcp_servers=config.mcp_servers,
            system_prompt=config.system_prompt,
            enable_skills=True,  # Always enable skills
            enable_mcp=enable_mcp,
            interrupt_on=config.interrupt_on,
        )

    def validate_model(self, model_name: str) -> bool:
        """Validate if model is available."""
        if not self._available_models:
            return True  # Skip validation if model list not loaded
        return model_name in self._available_models
