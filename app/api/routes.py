"""
API routes module.

Defines all HTTP endpoints for the agent service.

Stream Event Types (compatible with DeerFlow):
- delta: Content increment
- tool_call: Tool invocation
- tool_result: Tool execution result
- task_started: Subtask started
- task_running: Subtask running (with AI message)
- task_completed: Subtask completed
- task_failed: Subtask failed
- task_timed_out: Subtask timed out
- interrupt: Human-in-the-loop approval required
- done: Stream completed
- error: Error occurred
"""

import json
import logging
import uuid
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
    ChatRequest,
    ResumeRequest,
    HistoryRequest,
    HistoryResponse,
    MessageItem,
)
from app.services.agent_pool import AgentPool
from app.services.agent_service import AgentService

logger = logging.getLogger("deepagent.service")

# ─── Default Agent ID ────────────────────────────────────────────────────────

DEFAULT_AGENT_ID = "default"


# ─── Chat Endpoints ─────────────────────────────────────────────────────────


async def get_history(
    request: HistoryRequest,
    agent_service: AgentService,
):
    """Get conversation history for a thread from PostgreSQL checkpointer."""
    from app.core.checkpoint import get_checkpoint_manager

    checkpoint_manager = get_checkpoint_manager()
    messages = []
    total_checkpoints = 0

    if not checkpoint_manager.saver:
        logger.warning("No checkpointer available, returning empty history")
        return HistoryResponse(
            thread_id=request.thread_id,
            messages=[],
            total_checkpoints=0,
            has_more=False,
        )

    try:
        config = {"configurable": {"thread_id": request.thread_id}}

        # Get all checkpoints for this thread
        checkpoints = []
        async for cp_tuple in checkpoint_manager.saver.alist(config, limit=request.limit + 1):
            checkpoints.append(cp_tuple)
            total_checkpoints += 1

        has_more = len(checkpoints) > request.limit
        if has_more:
            checkpoints = checkpoints[:request.limit]

        # Extract messages from checkpoints
        # Checkpoints are returned in reverse chronological order (newest first)
        # We need to process them in chronological order (oldest first)
        seen_message_ids = set()

        for cp_tuple in reversed(checkpoints):
            checkpoint = cp_tuple.checkpoint
            channel_values = checkpoint.get("channel_values", {})

            # Get messages from channel_values
            checkpoint_messages = channel_values.get("messages", [])

            for msg in checkpoint_messages:
                # Get message ID to avoid duplicates
                msg_id = getattr(msg, "id", None) or id(msg)

                if msg_id in seen_message_ids:
                    continue
                seen_message_ids.add(msg_id)

                # Extract role and content
                msg_type = type(msg).__name__
                role = "assistant"
                content = ""
                tool_calls = None
                tool_call_id = None

                # Determine role based on message type
                if "Human" in msg_type or "User" in msg_type:
                    role = "user"
                elif "Tool" in msg_type:
                    role = "tool"
                    tool_call_id = getattr(msg, "tool_call_id", None)
                elif "System" in msg_type:
                    role = "system"

                # Extract content
                if hasattr(msg, "content"):
                    c = msg.content
                    if isinstance(c, str):
                        content = c
                    elif isinstance(c, list):
                        content = "".join(
                            p.get("text", "") if isinstance(p, dict) else str(p)
                            for p in c
                        )
                    else:
                        content = str(c) if c else ""
                else:
                    content = str(msg)

                # Extract tool calls if present
                tcalls = getattr(msg, "tool_calls", None)
                if tcalls:
                    tool_calls = []
                    for tc in tcalls:
                        if isinstance(tc, dict):
                            # Convert to frontend expected format
                            tool_calls.append({
                                "tool": tc.get("name", ""),
                                "args": tc.get("args", {}),
                                "tool_call_id": tc.get("id", ""),
                            })
                        else:
                            # Handle object-style tool calls
                            tool_calls.append({
                                "tool": getattr(tc, "name", ""),
                                "args": getattr(tc, "args", {}),
                                "tool_call_id": getattr(tc, "id", ""),
                            })

                # Skip empty messages
                if not content and not tool_calls:
                    continue

                messages.append(MessageItem(
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                    tool_call_id=tool_call_id,
                ))

        logger.info(
            f"Retrieved {len(messages)} messages from {total_checkpoints} checkpoints for thread {request.thread_id}")

        return HistoryResponse(
            thread_id=request.thread_id,
            messages=messages,
            total_checkpoints=total_checkpoints,
            has_more=has_more,
        )

    except Exception as e:
        logger.error(f"Failed to get history: {type(e).__name__}: {e}")
        return HistoryResponse(
            thread_id=request.thread_id,
            messages=[],
            total_checkpoints=0,
            has_more=False,
        )


async def chat_stream(
    request: ChatRequest,
    agent_service: AgentService,
    agent_pool: Optional[AgentPool] = None,
):
    """Streaming chat endpoint handler with agent pool support and human-in-the-loop.

    Output format is compatible with DeerFlow's stream events:
    - delta: Content increment
    - tool_call: Tool invocation
    - tool_result: Tool execution result
    - interrupt: Human-in-the-loop approval required
    - task_started/task_running/task_completed/task_failed: Subtask events
    - done: Stream completed
    - error: Error occurred
    """
    agent = None
    agent_id = request.agent_id or DEFAULT_AGENT_ID
    # Generate thread_id if not provided
    thread_id = request.thread_id or str(uuid.uuid4())

    # Try to get agent from pool
    if agent_pool:
        pooled_agent = await agent_pool.get(agent_id)
        if pooled_agent:
            agent = pooled_agent.instance
            if not agent_pool.increment_turn(agent_id):
                raise HTTPException(410, f"Agent {agent_id} has reached max turns")
            logger.info(f"Using pooled agent: {agent_id}")
        else:
            # Check if config exists to provide better error message
            if agent_id not in agent_pool._configs:
                logger.warning(f"Agent config not found: {agent_id}")
                # If using default agent and it doesn't exist, try to create directly
                if agent_id == DEFAULT_AGENT_ID:
                    logger.info("Default agent not found in pool, will create directly")
                else:
                    raise HTTPException(404, f"Agent configuration not found: {agent_id}")
            else:
                # Config exists but agent creation failed
                logger.error(f"Failed to create agent instance: {agent_id}")
                raise HTTPException(500, f"Failed to initialize agent: {agent_id}")

    # Fallback: create agent directly (for default agent or when pool is not available)
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
    config = {"configurable": {"thread_id": thread_id}}

    async def event_generator() -> AsyncGenerator[str, None]:
        content_acc = ""
        tools_used = []
        tool_results = []
        event_count = 0
        message_index = 0
        current_messages = []  # Track all messages for values event

        try:
            # Use multiple stream modes to get rich event types (DeerFlow compatible)
            # Note: 'events' mode requires LangChain callback system and is handled
            # separately through tool detection in messages mode
            async for event in agent.astream(
                {"messages": [{"role": "user", "content": request.message}]},
                config=config,
                stream_mode=["values", "messages", "updates", "custom", ],
            ):
                event_count += 1
                # Event format: (mode, value) with 2 elements
                if not isinstance(event, tuple) or len(event) != 2:
                    logger.warning(
                        f"Unexpected event format: {type(event)}, len={len(event) if isinstance(event, tuple) else 'not tuple'}")
                    continue

                mode, value = event

                # Handle values mode - full state snapshot (DeerFlow format)
                if mode == "values":
                    if isinstance(value, dict):
                        # Extract messages from state
                        messages = value.get("messages", [])
                        current_messages = messages

                        # Build values event
                        values_event = {
                            "messages": [
                                {
                                    "role": "user" if getattr(m, 'type', '') == "human" else "assistant",
                                    "content": str(m.content) if hasattr(m, 'content') and m.content else ""
                                }
                                for m in messages
                            ],
                            "thread_id": thread_id,
                        }

                        # Include any additional state fields (title, todos, artifacts)
                        for key in ["title", "todos", "artifacts"]:
                            if key in value:
                                values_event[key] = value[key]

                        yield f"event: values\ndata: {json.dumps(values_event, ensure_ascii=False, default=str)}\n\n"
                    continue

                # Handle custom mode - for task/subagent events (DeerFlow compatible)
                if mode == "custom":
                    if isinstance(value, dict):
                        event_type = value.get("type")
                        # Pass through task events directly (task_started, task_running, etc.)
                        if event_type in ("task_started", "task_running", "task_completed", "task_failed",
                                          "task_timed_out"):
                            logger.info(f"Task event: {event_type} - task_id: {value.get('task_id')}")
                            # Use standard SSE format with event type
                            yield f"event: custom\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"
                    continue

                # Handle updates mode - check for interrupts and state updates
                if mode == "updates":
                    if isinstance(value, dict):
                        # Check for interrupt (human-in-the-loop)
                        if "__interrupt__" in value:
                            interrupt_data = value["__interrupt__"]
                            if interrupt_data and len(interrupt_data) > 0:
                                # Extract interrupt info from Interrupt object
                                interrupt_obj = interrupt_data[0]
                                interrupt_value = interrupt_obj.value if hasattr(interrupt_obj,
                                                                                 'value') else interrupt_obj

                                # Build interrupt event for client (DeerFlow format)
                                interrupt_info = {
                                    "type": "interrupt",
                                    "thread_id": thread_id,
                                    "interrupts": []
                                }

                                # Extract action_requests and review_configs
                                action_requests = interrupt_value.get("action_requests", [])
                                review_configs = interrupt_value.get("review_configs", [])

                                # Create lookup map
                                config_map = {cfg["action_name"]: cfg for cfg in review_configs}

                                # Build interrupt list
                                for action in action_requests:
                                    tool_name = action.get("name", "unknown")
                                    review_config = config_map.get(tool_name, {})

                                    interrupt_info["interrupts"].append({
                                        "tool_name": tool_name,
                                        "tool_call_id": action.get("id", ""),
                                        "args": action.get("args", {}),
                                        "description": f"Tool '{tool_name}' execution requires approval",
                                        "allowed_decisions": review_config.get("allowed_decisions",
                                                                               ["approve", "reject"])
                                    })

                                logger.info(
                                    f"Interrupt detected for tools: {[intr['tool_name'] for intr in interrupt_info['interrupts']]}")
                                # Use standard SSE format
                                yield f"event: updates\ndata: {json.dumps({'__interrupt__': interrupt_info}, ensure_ascii=False)}\n\n"
                                yield "event: end\ndata: {}\n\n"
                                return

                        # Handle other update events (like title updates, todo updates, etc.)
                        # Pass through as update events
                        for key, val in value.items():
                            if key != "__interrupt__" and val is not None:
                                update_event = {
                                    "type": "update",
                                    "thread_id": thread_id,
                                    "key": key,
                                    "value": val,
                                }
                                # Use standard SSE format
                                yield f"event: updates\ndata: {json.dumps(update_event, ensure_ascii=False, default=str)}\n\n"
                    continue

                # Handle messages mode - stream content
                elif mode == "messages":
                    # value is (message_chunk, metadata_dict)
                    if not isinstance(value, tuple) or len(value) != 2:
                        logger.warning(
                            f"Messages mode: unexpected value format: {type(value)}, len={len(value) if isinstance(event, tuple) else 'not tuple'}")
                        continue

                    msg, msg_metadata = value
                    message_index += 1
                    
                    # Get message type
                    msg_type = getattr(msg, 'type', '')
                    
                    # Handle ToolMessage - tool execution result (on_tool_end)
                    if msg_type == 'tool':
                        tool_call_id = getattr(msg, 'tool_call_id', '')
                        tool_content = ""
                        if hasattr(msg, 'content'):
                            c = msg.content
                            if isinstance(c, str):
                                tool_content = c
                            elif isinstance(c, list):
                                tool_content = "".join(
                                    p.get("text", "") if isinstance(p, dict) else str(p)
                                    for p in c
                                )
                        
                        # Emit on_tool_end event
                        tool_end_event = {
                            "event": "on_tool_end",
                            "thread_id": thread_id,
                            "name": "",  # Tool name not available in ToolMessage
                            "run_id": tool_call_id,
                            "outputs": {"content": tool_content[:500]},  # Truncate for display
                            "tags": [],
                            "metadata": {
                                "langgraph_node": msg_metadata.get("langgraph_node", ""),
                                "langgraph_step": msg_metadata.get("langgraph_step", 0),
                            }
                        }
                        yield f"event: events\ndata: {json.dumps(tool_end_event, ensure_ascii=False, default=str)}\n\n"
                        continue

                    # Build message event in DeerFlow format
                    msg_event = {
                        "role": "assistant",
                        "content": "",
                        "thread_id": thread_id,
                    }

                    # Tool calls - also emit events for on_tool_start
                    tcalls = (
                        getattr(msg, "tool_calls", None)
                        or getattr(msg, "tool_call_chunks", None)
                    )

                    if tcalls:
                        logger.info(f"Tool calls detected: {len(tcalls)} calls")
                        tool_call_events = []
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
                                tool_call_events.append({
                                    "name": name,
                                    "args": args,
                                    "id": tid,
                                    "type": "tool_call",
                                })
                                info = {
                                    "type": "tool_call",
                                    "thread_id": thread_id,
                                    "tool": name,
                                    "args": args,
                                    "tool_call_id": tid,
                                    "message_index": message_index,
                                }
                                if info not in tools_used:
                                    tools_used.append(info)

                                    # Emit on_tool_start event
                                    tool_start_event = {
                                        "event": "on_tool_start",
                                        "thread_id": thread_id,
                                        "name": name,
                                        "run_id": tid,
                                        "inputs": args,
                                        "tags": [],
                                        "metadata": {
                                            "langgraph_node": msg_metadata.get("langgraph_node", ""),
                                            "langgraph_step": msg_metadata.get("langgraph_step", 0),
                                        }
                                    }
                                    yield f"event: events\ndata: {json.dumps(tool_start_event, ensure_ascii=False, default=str)}\n\n"

                        if tool_call_events:
                            msg_event["tool_calls"] = tool_call_events

                    # Content delta
                    delta = ""
                    reasoning_content = ""

                    if hasattr(msg, "content"):
                        c = msg.content
                        if isinstance(c, str):
                            delta = c
                        elif isinstance(c, list):
                            delta = "".join(
                                p.get("text", "") if isinstance(p, dict) else str(p)
                                for p in c
                            )
                        else:
                            # Handle other content types (e.g., None, empty)
                            if c is not None:
                                delta = str(c)

                    # Check for reasoning_content (used by some models like qwen/deepseek)
                    if hasattr(msg, "additional_kwargs"):
                        reasoning_content = msg.additional_kwargs.get("reasoning_content", "")
                        if reasoning_content:
                            msg_event["reasoning_content"] = reasoning_content

                    if delta:
                        content_acc += delta
                        msg_event["content"] = delta

                    # Send message event in standard SSE format
                    if delta or tcalls or reasoning_content:
                        yield f"event: messages\ndata: {json.dumps(msg_event, ensure_ascii=False)}\n\n"


            # Send final values event (DeerFlow format)
            result = {
                "messages": [{"role": "assistant", "content": content_acc}],
                "thread_id": thread_id,
                "tools_used": tools_used,
            }
            if agent_id:
                result["agent_id"] = agent_id

            yield f"event: values\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"
            yield "event: end\ndata: {}\n\n"

        except Exception as e:
            import traceback
            logger.error(f"Streaming error: {type(e).__name__} - {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            error_event = {
                "type": "error",
                "thread_id": thread_id,
                "message": str(e),
                "error_type": type(e).__name__,
            }
            yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            yield "event: end\ndata: {}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def resume_stream(
    agent_id: str,
    request: ResumeRequest,
    agent_service: AgentService,
    agent_pool: Optional[AgentPool] = None,
):
    """Resume an interrupted agent with a decision.

    Output format is compatible with DeerFlow's stream events.
    """
    agent = None
    thread_id = request.thread_id

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
    config = {"configurable": {"thread_id": thread_id}}

    # Build decision based on user choice
    # According to deepagents docs, decisions format is:
    # [{"type": "approve"}] or [{"type": "reject"}] or [{"type": "edit", "edited_action": {...}}]
    if request.decision == "approve":
        decision = {"type": "approve"}
    elif request.decision == "reject":
        decision = {"type": "reject"}
    elif request.decision == "edit":
        if not request.edited_args:
            raise HTTPException(400, "edited_args required for edit decision")
        if not request.tool_name:
            raise HTTPException(400, "tool_name required for edit decision")
        decision = {
            "type": "edit",
            "edited_action": {
                "name": request.tool_name,
                "args": request.edited_args
            }
        }
    else:
        raise HTTPException(400, f"Invalid decision: {request.decision}")

    # Resume command must use {"decisions": [decision1, decision2, ...]}
    resume_value = {"decisions": [decision]}
    logger.info(f"Resuming agent with decision: {request.decision} for tool_call_id: {request.tool_call_id}")

    async def event_generator() -> AsyncGenerator[str, None]:
        content_acc = ""
        tools_used = []
        message_index = 0
        current_messages = []

        try:
            # Resume with Command - use multiple stream modes (DeerFlow compatible)
            # Note: events are emitted from tool detection in messages mode
            async for event in agent.astream(
                Command(resume=resume_value),
                config=config,
                stream_mode=["values", "messages", "updates", "custom"],
            ):
                # Event format: (mode, value)
                if not isinstance(event, tuple) or len(event) != 2:
                    continue

                mode, value = event

                # Handle values mode - full state snapshot
                if mode == "values":
                    if isinstance(value, dict):
                        messages = value.get("messages", [])
                        current_messages = messages

                        values_event = {
                            "messages": [
                                {
                                    "role": "user" if getattr(m, 'type', '') == "human" else "assistant",
                                    "content": str(m.content) if hasattr(m, 'content') and m.content else ""
                                }
                                for m in messages
                            ],
                            "thread_id": thread_id,
                        }

                        for key in ["title", "todos", "artifacts"]:
                            if key in value:
                                values_event[key] = value[key]

                        yield f"event: values\ndata: {json.dumps(values_event, ensure_ascii=False, default=str)}\n\n"
                    continue

                # Handle custom mode - for task/subagent events
                if mode == "custom":
                    if isinstance(value, dict):
                        event_type = value.get("type")
                        if event_type in ("task_started", "task_running", "task_completed", "task_failed",
                                          "task_timed_out"):
                            yield f"event: custom\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"
                    continue

                # Handle updates mode - check for interrupts
                if mode == "updates":
                    if isinstance(value, dict):
                        # Check for interrupt (human-in-the-loop)
                        if "__interrupt__" in value:
                            interrupt_data = value["__interrupt__"]
                            if interrupt_data and len(interrupt_data) > 0:
                                interrupt_obj = interrupt_data[0]
                                interrupt_value = interrupt_obj.value if hasattr(interrupt_obj,
                                                                                 'value') else interrupt_obj

                                interrupt_info = {
                                    "type": "interrupt",
                                    "thread_id": thread_id,
                                    "interrupts": []
                                }

                                action_requests = interrupt_value.get("action_requests", [])
                                review_configs = interrupt_value.get("review_configs", [])
                                config_map = {cfg["action_name"]: cfg for cfg in review_configs}

                                for action in action_requests:
                                    tool_name = action.get("name", "unknown")
                                    review_config = config_map.get(tool_name, {})

                                    interrupt_info["interrupts"].append({
                                        "tool_name": tool_name,
                                        "tool_call_id": action.get("id", ""),
                                        "args": action.get("args", {}),
                                        "description": f"Tool '{tool_name}' execution requires approval",
                                        "allowed_decisions": review_config.get("allowed_decisions",
                                                                               ["approve", "reject"])
                                    })

                                logger.info(f"Another interrupt detected during resume")
                                yield f"event: updates\ndata: {json.dumps({'__interrupt__': interrupt_info}, ensure_ascii=False)}\n\n"
                                yield "event: end\ndata: {}\n\n"
                                return

                        # Handle other update events
                        for key, val in value.items():
                            if key != "__interrupt__" and val is not None:
                                update_event = {
                                    "type": "update",
                                    "thread_id": thread_id,
                                    "key": key,
                                    "value": val,
                                }
                                yield f"event: updates\ndata: {json.dumps(update_event, ensure_ascii=False, default=str)}\n\n"
                    continue

                # Handle messages mode - stream content
                elif mode == "messages":
                    if not isinstance(value, tuple) or len(value) != 2:
                        continue

                    msg, msg_metadata = value
                    message_index += 1
                    
                    # Get message type
                    msg_type = getattr(msg, 'type', '')
                    
                    # Handle ToolMessage - tool execution result (on_tool_end)
                    if msg_type == 'tool':
                        tool_call_id = getattr(msg, 'tool_call_id', '')
                        tool_content = ""
                        if hasattr(msg, 'content'):
                            c = msg.content
                            if isinstance(c, str):
                                tool_content = c
                            elif isinstance(c, list):
                                tool_content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
                        
                        # Emit on_tool_end event
                        tool_end_event = {
                            "event": "on_tool_end",
                            "thread_id": thread_id,
                            "name": "",
                            "run_id": tool_call_id,
                            "outputs": {"content": tool_content[:500]},
                            "tags": [],
                            "metadata": {
                                "langgraph_node": msg_metadata.get("langgraph_node", "") if msg_metadata else "",
                                "langgraph_step": msg_metadata.get("langgraph_step", 0) if msg_metadata else 0,
                            }
                        }
                        yield f"event: events\ndata: {json.dumps(tool_end_event, ensure_ascii=False, default=str)}\n\n"
                        continue

                    # Build message event in DeerFlow format
                    msg_event = {
                        "role": "assistant",
                        "content": "",
                        "thread_id": thread_id,
                    }

                    # Tool calls - also emit events for on_tool_start
                    tcalls = getattr(msg, "tool_calls", None) or getattr(msg, "tool_call_chunks", None)
                    if tcalls:
                        tool_call_events = []
                        for tc in tcalls:
                            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                            tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                            if name:
                                tool_call_events.append({
                                    "name": name,
                                    "args": args,
                                    "id": tid,
                                    "type": "tool_call",
                                })
                                info = {
                                    "type": "tool_call",
                                    "thread_id": thread_id,
                                    "tool": name,
                                    "args": args,
                                    "tool_call_id": tid,
                                    "message_index": message_index,
                                }
                                if info not in tools_used:
                                    tools_used.append(info)

                                    # Emit on_tool_start event
                                    tool_start_event = {
                                        "event": "on_tool_start",
                                        "thread_id": thread_id,
                                        "name": name,
                                        "run_id": tid,
                                        "inputs": args,
                                        "tags": [],
                                        "metadata": {
                                            "langgraph_node": msg_metadata.get("langgraph_node", "") if msg_metadata else "",
                                            "langgraph_step": msg_metadata.get("langgraph_step", 0) if msg_metadata else 0,
                                        }
                                    }
                                    yield f"event: events\ndata: {json.dumps(tool_start_event, ensure_ascii=False, default=str)}\n\n"

                        if tool_call_events:
                            msg_event["tool_calls"] = tool_call_events

                    # Content delta
                    delta = ""
                    if hasattr(msg, "content"):
                        c = msg.content
                        if isinstance(c, str):
                            delta = c
                        elif isinstance(c, list):
                            delta = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)

                    # Check for reasoning_content
                    reasoning_content = ""
                    if hasattr(msg, "additional_kwargs"):
                        reasoning_content = msg.additional_kwargs.get("reasoning_content", "")
                        if reasoning_content:
                            msg_event["reasoning_content"] = reasoning_content

                    if delta:
                        content_acc += delta
                        msg_event["content"] = delta

                    # Send message event in standard SSE format
                    if delta or tcalls or reasoning_content:
                        yield f"event: messages\ndata: {json.dumps(msg_event, ensure_ascii=False)}\n\n"


            result = {
                "messages": [{"role": "assistant", "content": content_acc}],
                "thread_id": thread_id,
                "tools_used": tools_used,
                "agent_id": agent_id,
            }
            yield f"event: values\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"
            yield "event: end\ndata: {}\n\n"

        except Exception as e:
            logger.error(f"Resume streaming error: {type(e).__name__} - {e}")
            error_event = {
                "type": "error",
                "thread_id": thread_id,
                "message": str(e),
                "error_type": type(e).__name__,
            }
            yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            yield "event: end\ndata: {}\n\n"

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
        persistent=config_create.persistent,
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


async def update_agent_config(
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
    await agent_pool.remove(agent_id)

    logger.info(f"Updated agent config: {agent_id}")
    return existing


async def delete_agent_config(
    agent_id: str, storage: AgentConfigStorage, agent_pool: AgentPool
) -> dict:
    """Delete an agent configuration."""
    if not storage.delete(agent_id):
        raise HTTPException(404, f"Agent not found: {agent_id}")

    await agent_pool.remove(agent_id)

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

    @app.post("/chat/history", response_model=HistoryResponse)
    async def _get_history(request: HistoryRequest):
        """Get conversation history for a thread."""
        return await get_history(request, agent_service)

    @app.post("/chat/stream")
    async def _chat_stream(request: ChatRequest):
        """Streaming chat endpoint. Use agent_id in request body to specify agent."""
        return await chat_stream(request, agent_service, agent_pool)

    @app.post("/chat/resume")
    async def _resume_agent(request: ResumeRequest):
        """Resume an interrupted agent with a decision. Use agent_id in request body."""
        return await resume_stream(request.agent_id, request, agent_service, agent_pool)

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
        return await update_agent_config(agent_id, config_update, storage, agent_pool)

    @app.delete("/agents/{agent_id}")
    async def delete_agent(agent_id: str):
        """Delete an agent configuration."""
        return await delete_agent_config(agent_id, storage, agent_pool)

    @app.get("/pool/stats")
    async def pool_stats():
        """Get agent pool statistics."""
        return get_agent_pool_stats(agent_pool)
