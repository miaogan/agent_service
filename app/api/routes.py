"""
API routes module.

Defines all HTTP endpoints for the agent service.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import AsyncGenerator, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from app.core.storage import AgentConfigStorage
from app.models.schemas import (
    AgentConfig,
    AgentConfigCreate,
    AgentConfigUpdate,
    AgentInfo,
    ChatRequest,
    ResumeRequest,
    InterruptInfo,
)
from app.services.agent_pool import AgentPool
from app.services.agent_service import AgentService

logger = logging.getLogger("deepagent.service")

# ─── Default Agent ID ────────────────────────────────────────────────────────

DEFAULT_AGENT_ID = "default"


# ─── Chat Endpoints ─────────────────────────────────────────────────────────


async def chat_stream(
    request: ChatRequest,
    agent_service: AgentService,
    agent_pool: Optional[AgentPool] = None,
):
    """Streaming chat endpoint handler with agent pool support and human-in-the-loop."""
    agent = None
    agent_id = request.agent_id or DEFAULT_AGENT_ID

    # Try to get agent from pool
    if agent_pool:
        pooled_agent = await agent_pool.get(agent_id)
        if pooled_agent:
            agent = pooled_agent.instance
            if not agent_pool.increment_turn(agent_id):
                raise HTTPException(410, f"Agent {agent_id} has reached max turns")
            logger.info(f"Using pooled agent: {agent_id}")
        else:
            raise HTTPException(404, f"Agent not found: {agent_id}")

    # Fallback: create agent directly
    if agent is None:
        if not agent_service.validate_model(request.model):
            raise HTTPException(400, f"Unknown model: {request.model}")
        try:
            agent = await agent_service.create_agent(request.model)
            logger.info(f"Created new agent with model: {request.model}")
        except Exception as e:
            logger.exception("Failed to create Agent")
            raise HTTPException(500, "Cannot initialize Agent")

    # Thread config for checkpointing
    config = {"configurable": {"thread_id": request.thread_id}}

    async def event_generator() -> AsyncGenerator[str, None]:
        content_acc = ""
        tools_used = []
        try:
            async for event in agent.astream(
                {"messages": [{"role": "user", "content": request.message}]},
                config=config,
                stream_mode="messages",
                interrupt_before=[],  # We handle interrupts via interrupt_on
            ):
                if not isinstance(event, tuple) or len(event) != 2:
                    continue

                chunk, metadata = event

                # Check for interrupt
                if hasattr(chunk, "__interrupt__"):
                    interrupt_data = chunk.__interrupt__
                    if interrupt_data:
                        # Send interrupt event to client
                        interrupt_info = {
                            "type": "interrupt",
                            "interrupts": []
                        }
                        for intr in interrupt_data if isinstance(interrupt_data, list) else [interrupt_data]:
                            if isinstance(intr, dict):
                                interrupt_info["interrupts"].append({
                                    "tool_name": intr.get("name", "unknown"),
                                    "tool_call_id": intr.get("id", ""),
                                    "args": intr.get("args", {}),
                                    "description": intr.get("description", "Tool execution requires approval"),
                                    "allowed_decisions": intr.get("allowed_decisions", ["approve", "reject"])
                                })
                        yield f"data: {json.dumps(interrupt_info, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                # Tool calls
                tcalls = (
                    getattr(chunk, "tool_calls", None)
                    or getattr(chunk, "tool_call_chunks", None)
                )
                if tcalls:
                    for tc in tcalls:
                        name = (
                            tc.get("name")
                            if isinstance(tc, dict)
                            else getattr(tc, "name", None)
                        )
                        args = (
                            tc.get("args")
                            if isinstance(tc, dict)
                            else getattr(tc, "args", {})
                        )
                        tid = (
                            tc.get("id")
                            if isinstance(tc, dict)
                            else getattr(tc, "id", None)
                        )
                        if name:
                            info = {
                                "type": "tool_call",
                                "tool": name,
                                "args": args,
                                "tool_call_id": tid,
                            }
                            if info not in tools_used:
                                tools_used.append(info)
                                yield f"data: {json.dumps(info, ensure_ascii=False)}\n\n"

                # Content delta
                delta = ""
                if hasattr(chunk, "content"):
                    c = chunk.content
                    if isinstance(c, str):
                        delta = c
                    elif isinstance(c, list):
                        delta = "".join(
                            p.get("text", "") if isinstance(p, dict) else str(p)
                            for p in c
                        )

                if delta:
                    content_acc += delta
                    if delta.strip():
                        yield f"data: {json.dumps({'type': 'delta', 'content': delta}, ensure_ascii=False)}\n\n"

            result = {
                "type": "done",
                "content": content_acc,
                "tools_used": tools_used,
            }
            if agent_id:
                result["agent_id"] = agent_id

            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Streaming error: {type(e).__name__} - {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def resume_stream(
    agent_id: str,
    request: ResumeRequest,
    agent_service: AgentService,
    agent_pool: Optional[AgentPool] = None,
):
    """Resume an interrupted agent with a decision."""
    agent = None

    # Try to get agent from pool
    if agent_pool:
        pooled_agent = await agent_pool.get(agent_id)
        if pooled_agent:
            agent = pooled_agent.instance
        else:
            raise HTTPException(404, f"Agent not found: {agent_id}")

    if agent is None:
        raise HTTPException(404, f"Agent not found: {agent_id}")

    # Thread config for checkpointing
    config = {"configurable": {"thread_id": request.thread_id}}

    # Build resume command based on decision
    if request.decision == "approve":
        resume_value = {request.tool_call_id: {"decision": "approve"}}
    elif request.decision == "reject":
        resume_value = {request.tool_call_id: {"decision": "reject"}}
    elif request.decision == "edit":
        resume_value = {request.tool_call_id: {"decision": "edit", "args": request.edited_args or {}}}
    else:
        raise HTTPException(400, f"Invalid decision: {request.decision}")

    async def event_generator() -> AsyncGenerator[str, None]:
        content_acc = ""
        tools_used = []
        try:
            # Resume with Command
            async for event in agent.astream(
                Command(resume=resume_value),
                config=config,
                stream_mode="messages",
            ):
                if not isinstance(event, tuple) or len(event) != 2:
                    continue

                chunk, metadata = event

                # Check for another interrupt
                if hasattr(chunk, "__interrupt__"):
                    interrupt_data = chunk.__interrupt__
                    if interrupt_data:
                        interrupt_info = {
                            "type": "interrupt",
                            "interrupts": []
                        }
                        for intr in interrupt_data if isinstance(interrupt_data, list) else [interrupt_data]:
                            if isinstance(intr, dict):
                                interrupt_info["interrupts"].append({
                                    "tool_name": intr.get("name", "unknown"),
                                    "tool_call_id": intr.get("id", ""),
                                    "args": intr.get("args", {}),
                                    "description": intr.get("description", "Tool execution requires approval"),
                                    "allowed_decisions": intr.get("allowed_decisions", ["approve", "reject"])
                                })
                        yield f"data: {json.dumps(interrupt_info, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                # Tool calls
                tcalls = getattr(chunk, "tool_calls", None) or getattr(chunk, "tool_call_chunks", None)
                if tcalls:
                    for tc in tcalls:
                        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                        args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                        tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                        if name:
                            info = {"type": "tool_call", "tool": name, "args": args, "tool_call_id": tid}
                            if info not in tools_used:
                                tools_used.append(info)
                                yield f"data: {json.dumps(info, ensure_ascii=False)}\n\n"

                # Content delta
                delta = ""
                if hasattr(chunk, "content"):
                    c = chunk.content
                    if isinstance(c, str):
                        delta = c
                    elif isinstance(c, list):
                        delta = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)

                if delta:
                    content_acc += delta
                    if delta.strip():
                        yield f"data: {json.dumps({'type': 'delta', 'content': delta}, ensure_ascii=False)}\n\n"

            result = {"type": "done", "content": content_acc, "tools_used": tools_used, "agent_id": agent_id}
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Resume streaming error: {type(e).__name__} - {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ─── Agent Configuration Endpoints ──────────────────────────────────────────


def create_agent_config(
    config_create: AgentConfigCreate, storage: AgentConfigStorage, agent_pool: AgentPool
) -> AgentConfig:
    """Create a new agent configuration."""
    if storage.exists(config_create.agent_id):
        raise HTTPException(400, f"Agent already exists: {config_create.agent_id}")

    config = AgentConfig(
        agent_id=config_create.agent_id,
        name=config_create.name,
        model=config_create.model,
        system_prompt=config_create.system_prompt,
        tools=config_create.tools,
        mcp_servers=config_create.mcp_servers,
        interrupt_on=config_create.interrupt_on,
        max_turns=config_create.max_turns,
        ttl_minutes=config_create.ttl_minutes,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    storage.save(config)
    agent_pool.register_config(config)
    logger.info(f"Created agent config: {config.agent_id}")

    return config


def get_agent_config(agent_id: str, storage: AgentConfigStorage) -> AgentConfig:
    """Get an agent configuration by ID."""
    config = storage.load(agent_id)
    if not config:
        raise HTTPException(404, f"Agent not found: {agent_id}")
    return config


def list_agent_configs(storage: AgentConfigStorage) -> list[AgentConfig]:
    """List all agent configurations."""
    return storage.load_all()


def update_agent_config(
    agent_id: str,
    config_update: AgentConfigUpdate,
    storage: AgentConfigStorage,
    agent_pool: AgentPool,
) -> AgentConfig:
    """Update an existing agent configuration."""
    existing = storage.load(agent_id)
    if not existing:
        raise HTTPException(404, f"Agent not found: {agent_id}")

    update_data = config_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(existing, key, value)

    existing.updated_at = datetime.now()
    storage.save(existing)
    agent_pool.register_config(existing)
    asyncio.get_event_loop().run_until_complete(agent_pool.remove(agent_id))

    logger.info(f"Updated agent config: {agent_id}")
    return existing


def delete_agent_config(
    agent_id: str, storage: AgentConfigStorage, agent_pool: AgentPool
) -> dict:
    """Delete an agent configuration."""
    if not storage.delete(agent_id):
        raise HTTPException(404, f"Agent not found: {agent_id}")

    asyncio.get_event_loop().run_until_complete(agent_pool.remove(agent_id))

    logger.info(f"Deleted agent config: {agent_id}")
    return {"status": "deleted", "agent_id": agent_id}


def get_agent_pool_stats(agent_pool: AgentPool) -> dict:
    """Get agent pool statistics."""
    return agent_pool.get_stats()


# ─── Route Registration ──────────────────────────────────────────────────────


def register_routes(
    app,
    agent_service: AgentService,
    agent_pool: AgentPool,
    storage: AgentConfigStorage,
):
    """Register all routes with the FastAPI app."""

    @app.post("/chat/stream")
    async def _chat_stream(request: ChatRequest):
        """Streaming chat endpoint."""
        return await chat_stream(request, agent_service, agent_pool)

    @app.post("/chat/{agent_id}/stream")
    async def _chat_with_agent(agent_id: str, request: ChatRequest):
        """Streaming chat with a specific agent from the pool."""
        request.agent_id = agent_id
        return await chat_stream(request, agent_service, agent_pool)

    @app.post("/chat/{agent_id}/resume")
    async def _resume_agent(agent_id: str, request: ResumeRequest):
        """Resume an interrupted agent with a decision."""
        return await resume_stream(agent_id, request, agent_service, agent_pool)

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "DeepAgent"}

    @app.get("/models")
    async def list_models():
        """List available models."""
        return {"models": agent_service.available_models}

    @app.post("/agents", response_model=AgentConfig, status_code=201)
    async def create_agent(config_create: AgentConfigCreate):
        """Create a new agent configuration."""
        return create_agent_config(config_create, storage, agent_pool)

    @app.get("/agents", response_model=list[AgentConfig])
    async def list_agents():
        """List all agent configurations."""
        return list_agent_configs(storage)

    @app.get("/agents/{agent_id}", response_model=AgentConfig)
    async def get_agent(agent_id: str):
        """Get an agent configuration by ID."""
        return get_agent_config(agent_id, storage)

    @app.put("/agents/{agent_id}", response_model=AgentConfig)
    async def update_agent(agent_id: str, config_update: AgentConfigUpdate):
        """Update an existing agent configuration."""
        return update_agent_config(agent_id, config_update, storage, agent_pool)

    @app.delete("/agents/{agent_id}")
    async def delete_agent(agent_id: str):
        """Delete an agent configuration."""
        return delete_agent_config(agent_id, storage, agent_pool)

    @app.get("/pool/stats")
    async def pool_stats():
        """Get agent pool statistics."""
        return get_agent_pool_stats(agent_pool)
