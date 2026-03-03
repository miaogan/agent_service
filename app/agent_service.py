# agent_service.py
import json
import logging
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncGenerator, List, Literal, Optional
import httpx
import uvicorn
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware import SkillsMiddleware
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_experimental.tools import PythonREPLTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ────────────────────────────────────────────────
# 配置
# ────────────────────────────────────────────────

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    root_dir: Path = Path.cwd()
    litellm_api_base: str = "http://127.0.0.1:4000"
    mcp_default_url: str = "http://127.0.0.1:8000/mcp"
    agent_cache_size: int = 64
    default_thread_id: str = "conversation1"
    default_model: str = "glm-5"

    @property
    def skill_dir(self) -> Path:
        return self.root_dir / "skill"


settings = Settings()

os.makedirs(settings.skill_dir, exist_ok=True)

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("deepagent.service")

# 模式常量
AGENT_MODE_SKILL = "skill"
AGENT_MODE_MCP = "mcp"
AGENT_MODE_BOTH = "both"
VALID_MODES = {AGENT_MODE_SKILL, AGENT_MODE_MCP, AGENT_MODE_BOTH}

DEFAULT_MCP_CONFIG = {
    "my_fastmcp": {
        "transport": "http",
        "url": "http://127.0.0.1:8000/mcp",
    }
}
safe_python_tool = PythonREPLTool(
    name="safe_python",
    description="更安全的 Python 代码执行工具。适合执行数学、数据处理代码。"
)
# ────────────────────────────────────────────────
# Agent 池化管理
# ────────────────────────────────────────────────

from typing import Dict, List
import asyncio
from collections import deque
import time

# Agent 池配置
AGENT_POOL_SIZE = 3  # 每个 Agent 配置预创建的实例数
AGENT_POOL_TIMEOUT = 300  # 实例在池中最大空闲时间 (秒)


class AgentPool:
    """Agent 实例池，支持按配置隔离和自动回收"""
    
    def __init__(self):
        # pool_storage[key] = deque of (agent_instance, last_used_time)
        self.pool_storage: Dict[str, deque] = {}
        self._lock = asyncio.Lock()
    
    def _generate_pool_key(self, mode: str, model_name: str, mcp_config: dict) -> str:
        """生成池的键值，用于隔离不同配置的 Agent"""
        # 使用 mcp_config 的 JSON 指纹作为 key 的一部分
        config_fingerprint = json.dumps(mcp_config, sort_keys=True)
        return f"{mode}:{model_name}:{config_fingerprint}"
    
    async def acquire(
        self,
        mode: str,
        model_name: str,
        mcp_config: dict,
    ) -> Any:
        """从池中获取一个 Agent 实例，如果没有则创建新的"""
        pool_key = self._generate_pool_key(mode, model_name, mcp_config)
        
        async with self._lock:
            if pool_key not in self.pool_storage:
                # 初始化该配置的 Agent 池
                self.pool_storage[pool_key] = deque()
                logger.info(f"Initializing agent pool for {pool_key} with {AGENT_POOL_SIZE} instances")
                
                # 预创建 AGENT_POOL_SIZE 个实例
                for i in range(AGENT_POOL_SIZE):
                    try:
                        agent = await create_agent(mode, model_name, mcp_config)
                        self.pool_storage[pool_key].append((agent, time.time()))
                        logger.info(f"Created agent instance {i+1}/{AGENT_POOL_SIZE} for {pool_key}")
                    except Exception as e:
                        logger.error(f"Failed to create agent instance: {e}")
                        raise
            
            # 从池中取出最久未使用的实例
            if self.pool_storage[pool_key]:
                agent, last_used = self.pool_storage[pool_key].popleft()
                
                # 检查实例是否超时
                if time.time() - last_used > AGENT_POOL_TIMEOUT:
                    logger.warning(f"Agent instance expired, creating new one for {pool_key}")
                    try:
                        agent = await create_agent(mode, model_name, mcp_config)
                    except Exception as e:
                        logger.error(f"Failed to create replacement agent: {e}")
                        raise
                
                logger.debug(f"Acquired agent instance from pool {pool_key}")
                return agent
            else:
                # 池为空，创建新实例
                logger.info(f"Pool {pool_key} empty, creating new agent instance")
                return await create_agent(mode, model_name, mcp_config)
    
    async def release(
        self,
        mode: str,
        model_name: str,
        mcp_config: dict,
        agent: Any,
    ) -> None:
        """将 Agent 实例归还到池中"""
        pool_key = self._generate_pool_key(mode, model_name, mcp_config)
        
        async with self._lock:
            if pool_key in self.pool_storage:
                self.pool_storage[pool_key].append((agent, time.time()))
                logger.debug(f"Released agent instance back to pool {pool_key}")
    
    async def cleanup(self) -> None:
        """清理所有池中的超时实例"""
        async with self._lock:
            current_time = time.time()
            for pool_key, pool in list(self.pool_storage.items()):
                # 移除超时的实例
                expired_count = 0
                valid_instances = []
                for agent, last_used in pool:
                    if current_time - last_used > AGENT_POOL_TIMEOUT:
                        expired_count += 1
                        # 这里可以添加清理逻辑，比如关闭 agent 的资源
                    else:
                        valid_instances.append((agent, last_used))
                
                if expired_count > 0:
                    logger.info(f"Cleaned up {expired_count} expired instances from pool {pool_key}")
                
                pool.clear()
                pool.extend(valid_instances)


# 全局 Agent 池实例
agent_pool = AgentPool()


@lru_cache(maxsize=settings.agent_cache_size)
def get_checkpointer(thread_id: str) -> MemorySaver:
    """每个 thread_id 拥有独立的内存检查点"""
    return MemorySaver()


async def preload_litellm_models() -> None:
    global available_models
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{settings.litellm_api_base}/v1/models", timeout=8.0)
            if r.status_code == 200:
                data = r.json()
                available_models = [
                    m["id"] for m in data.get("data", []) if m.get("id")
                ]
                logger.info(f"Preloaded {len(available_models)} models from LiteLLM")
            else:
                logger.warning(f"LiteLLM models fetch failed: {r.status_code}")
    except Exception as e:
        logger.error(f"Cannot preload LiteLLM models: {e.__class__.__name__} {e}")


async def preload_mcp_tools() -> None:
    global mcp_tools_cache
    try:
        client = MultiServerMCPClient(DEFAULT_MCP_CONFIG)
        mcp_tools_cache = await client.get_tools()
        logger.info(f"Preloaded {len(mcp_tools_cache)} MCP tools")
    except Exception as e:
        logger.warning(f"MCP tools preload failed: {e.__class__.__name__} {e}")


# ────────────────────────────────────────────────
# Agent 工厂（带缓存）
# ────────────────────────────────────────────────


@lru_cache(maxsize=settings.agent_cache_size)
def agent_cache_key(mode: str, model: str, mcp_config_fingerprint: str) -> str:
    return f"{mode}:{model}:{mcp_config_fingerprint}"


async def create_agent(
        mode: str,
        model_name: str,
        mcp_config: dict,
) -> Any:
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode: {mode}")

    backend = FilesystemBackend(root_dir=str(settings.root_dir), virtual_mode=True)

    llm = ChatOpenAI(
        openai_api_base=settings.litellm_api_base,
        model=model_name,
        temperature=0.7,
    )

    common_kwargs = {
        "model": llm,
        "backend": backend,
        "checkpointer": None,  # 在 stream 时动态注入
    }

    if mode == AGENT_MODE_MCP:
        tools = mcp_tools_cache if mcp_tools_cache else await load_mcp_tools(mcp_config)
        system = "你是一个强大的助手，可以使用 MCP 工具。所有文件路径必须以 / 开头。"
        return create_deep_agent(
            **common_kwargs,
            system_prompt=system,
            tools=tools+[safe_python_tool],
        )

    skills_middleware = SkillsMiddleware(
        sources=[str(settings.skill_dir)],
        backend=backend,
    )

    if mode == AGENT_MODE_SKILL:
        system = """You are a helpful AI assistant with access to a virtual filesystem.
All file paths MUST start with / (e.g. /workspace/report.md, /skill/my-skill/SKILL.md).
Do NOT use Windows-style paths.
Use ls, read_file, write_file, etc. to interact with files."""
        return create_deep_agent(
            **common_kwargs,
            middleware=[skills_middleware],
            system_prompt=system,
        )

    # both
    tools = mcp_tools_cache if mcp_tools_cache else await load_mcp_tools(mcp_config)
    system = """You are a helpful AI assistant with access to a virtual filesystem and MCP tools.
All file paths MUST start with /. Use ls, read_file, write_file, etc."""
    return create_deep_agent(
        **common_kwargs,
        middleware=[skills_middleware],
        system_prompt=system,
        tools=tools+[safe_python_tool],
    )


async def load_mcp_tools(config: dict) -> List:
    try:
        client = MultiServerMCPClient(config)
        return await client.get_tools()
    except Exception as e:
        logger.error(f"Load MCP tools failed: {e}")
        return []


# ────────────────────────────────────────────────
# FastAPI 应用
# ────────────────────────────────────────────────

app = FastAPI(title="DeepAgent Service", version="0.2")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DeepAgent service...")
    await preload_litellm_models()
    await preload_mcp_tools()
    
    # 预初始化 Agent 池 - 为默认配置创建实例
    if available_models:
        default_model = available_models[0] if available_models else settings.default_model
        logger.info(f"Pre-initializing agent pool with default model: {default_model}")
        try:
            # 为每种模式预创建 AGENT_POOL_SIZE 个实例
            for mode in VALID_MODES:
                try:
                    # 预热 Agent 池（会创建 AGENT_POOL_SIZE 个实例）
                    await agent_pool.acquire(mode, default_model, DEFAULT_MCP_CONFIG)
                    logger.info(f"Pre-initialized {AGENT_POOL_SIZE} agents for mode: {mode}")
                except Exception as e:
                    logger.warning(f"Failed to pre-initialize agent for mode {mode}: {e}")
        except Exception as e:
            logger.warning(f"Agent pool pre-initialization failed: {e}")
    
    yield
    
    logger.info("Shutting down DeepAgent service...")
    # 清理 Agent 池
    await agent_pool.cleanup()
    logger.info("Agent pool cleaned up")


app.router.lifespan_context = lifespan


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    mode: Literal["skill", "mcp", "both"] = AGENT_MODE_SKILL
    model: str = settings.default_model
    thread_id: Optional[str] = settings.default_thread_id
    mcp_config: dict = Field(default_factory=lambda: DEFAULT_MCP_CONFIG.copy())


# ======================== 辅助函数：安全提取文本内容 ========================
def extract_text_content(msg) -> str:
    """
    从 LangChain 消息中安全提取纯文本内容

    Args:
        msg: LangChain 消息对象

    Returns:
        提取的文本内容
    """
    if not hasattr(msg, "content") or msg.content is None:
        return ""

    content = msg.content

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif "text" in block:
                    parts.append(block["text"])
            else:
                parts.append(str(block))
        return "".join(parts)

    return str(content)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    if request.model not in available_models and available_models:
        raise HTTPException(400, f"Unknown model: {request.model}")

    agent = None
    try:
        # 从 Agent 池获取实例
        agent = await agent_pool.acquire(
            request.mode,
            request.model,
            request.mcp_config,
        )
    except Exception as e:
        logger.exception("Failed to acquire agent from pool")
        raise HTTPException(500, "Failed to initialize agent")

    config = {
        "configurable": {"thread_id": request.thread_id},
        "checkpointer": get_checkpointer(request.thread_id),
    }

    async def event_generator() -> AsyncGenerator[str, None]:
        previous_content = ""
        tools_used: List[dict] = []

        try:
            async for event in agent.astream(
                    {"messages": [{"role": "user", "content": request.message}]},
                    config=config,
                    stream_mode="messages",   # ← 只改了这里
            ):
                # event 是 (chunk, metadata) 元组
                if not isinstance(event, tuple) or len(event) != 2:
                    continue

                chunk, metadata = event

                # 工具调用检测（尽量兼容原有风格）
                tool_calls = getattr(chunk, "tool_calls", None) or getattr(chunk, "tool_call_chunks", None)
                if tool_calls:
                    for tc in tool_calls:
                        # tool_call_chunks 可能是 list of dict，tool_calls 可能是 list of ToolCall
                        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                        args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                        id_  = tc.get("id")   if isinstance(tc, dict) else getattr(tc, "id", None)

                        if name:
                            tool_info = {
                                "type": "tool_call",
                                "tool": name,
                                "args": args,
                                "tool_call_id": id_
                            }
                            if tool_info not in tools_used:
                                tools_used.append(tool_info)
                                yield f"data: {json.dumps(tool_info, ensure_ascii=False)}\n\n"

                # 内容增量处理（核心改动在这里）
                delta = ""
                if hasattr(chunk, "content"):
                    content = chunk.content

                    if isinstance(content, str):
                        delta = content
                    elif isinstance(content, list):
                        # 处理 content = [{"type": "text", "text": "..."}, ...]
                        delta = "".join(
                            part.get("text", "") if isinstance(part, dict) else str(part)
                            for part in content
                        )

                if delta:
                    # 累加完整内容，用于 done 事件
                    previous_content += delta

                    # 发送本次增量
                    if delta.strip():
                        yield f"data: {json.dumps(
                            {'type': 'delta', 'content': delta},
                            ensure_ascii=False
                        )}\n\n"

            # 结束事件
            yield f"data: {json.dumps({
                'type': 'done',
                'content': previous_content,
                'tools_used': tools_used
            }, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"流式处理出错：{type(e).__name__} - {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': '处理过程中发生错误'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            # 将 Agent 实例归还到池中
            if agent is not None:
                try:
                    await agent_pool.release(
                        request.mode,
                        request.model,
                        request.mcp_config,
                        agent,
                    )
                    logger.debug("Agent instance returned to pool")
                except Exception as e:
                    logger.error(f"Failed to release agent back to pool: {e}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )


if __name__ == "__main__":
    uvicorn.run(
        "agent_service:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )
