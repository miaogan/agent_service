import asyncio
import os
import json
from pathlib import Path
from typing import AsyncGenerator, Generator, Dict, Any, Optional, List
from contextlib import asynccontextmanager
from datetime import datetime

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware import SkillsMiddleware
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from app.models.schemas import (
    AgentRequest, StreamChunk, ToolCallInfo, 
    SessionInfo, SessionMessage, SessionHistoryResponse,
    AgentStatusResponse
)


class AgentService:
    """统一的Agent服务类，封装MCP和Skills两种Agent"""
    
    def __init__(self):
        self.root_dir = Path.cwd()
        self.backend = FilesystemBackend(root_dir=str(self.root_dir), virtual_mode=True)
        os.environ["OPENAI_API_KEY"] = "sk-1234"
        
        # 初始化LLM
        self.llm = ChatOpenAI(
            openai_api_base="http://127.0.0.1:4000",
            model="qwen3.5-plus"
        )
        
        # 初始化检查点
        self.checkpointer = MemorySaver()
        
        # 存储不同类型的agents
        self.agents: Dict[str, Any] = {}
        self.configs: Dict[str, Dict] = {}
        
        # Agent状态跟踪
        self.agent_statuses: Dict[str, Dict] = {
            "mcp": {"status": "uninitialized", "error": None, "initialized_at": None, "tools_count": 0},
            "skills": {"status": "uninitialized", "error": None, "initialized_at": None, "tools_count": 0}
        }
        
        # 会话存储
        self.sessions: Dict[str, Dict] = {}
        
        # 工具调用监控
        self.tool_call_history: List[ToolCallInfo] = []
        
        # 初始化标志
        self._initialized = False
        self._initialization_error = None
        
        # 缓存MCP工具信息
        self._cached_mcp_tools = None
        
    async def initialize_agents(self):
        """异步初始化所有agents"""
        if self._initialized:
            return
            
        try:
            print("开始初始化Agent服务...")
            # 初始化MCP Agent
            await self._initialize_mcp_agent()
            
            # 初始化Skills Agent
            self._initialize_skills_agent()
            
            self._initialized = True
            print("✅ Agent服务初始化成功完成")
            
        except Exception as e:
            self._initialization_error = str(e)
            print(f"❌ Agent服务初始化失败: {e}")
            raise
        
    async def _initialize_mcp_agent(self):
        """初始化MCP Agent"""
        try:
            print("正在初始化MCP Agent...")
            self.agent_statuses["mcp"]["status"] = "initializing"
            
            # 获取MCP工具
            client = MultiServerMCPClient({
                "my_fastmcp": {
                    "transport": "http",
                    "url": "http://127.0.0.1:8000/mcp",
                }
            })
            mcp_tools = await client.get_tools()
            print(f"✅ 成功加载 {len(mcp_tools)} 个MCP工具")
            # 缓存MCP工具信息用于API接口
            self._cached_mcp_tools = mcp_tools
            system_prompt = """
            你是一个强大的助手，可以使用 MCP 工具。
            所有文件路径必须以 / 开头。
            """
            
            mcp_agent = create_deep_agent(
                model=self.llm,
                system_prompt=system_prompt,
                backend=self.backend,
                tools=mcp_tools,
                checkpointer=self.checkpointer,
            )
            
            self.agents["mcp"] = mcp_agent
            self.configs["mcp"] = {"configurable": {"thread_id": "mcp_default"}}
            self.agent_statuses["mcp"]["status"] = "initialized"
            self.agent_statuses["mcp"]["initialized_at"] = datetime.now().isoformat()
            self.agent_statuses["mcp"]["tools_count"] = len(mcp_tools)
            print("✅ MCP Agent初始化完成")
            
        except Exception as e:
            self.agent_statuses["mcp"]["status"] = "error"
            self.agent_statuses["mcp"]["error"] = str(e)
            print(f"❌ MCP Agent初始化失败: {e}")
            raise
        
    def _initialize_skills_agent(self):
        """初始化Skills Agent"""
        try:
            print("正在初始化Skills Agent...")
            self.agent_statuses["skills"]["status"] = "initializing"
            
            system_prompt = """
            You are a helpful AI assistant with access to a virtual filesystem.
            All file paths MUST start with / (e.g. /workspace/report.md, /skills/my-skill/SKILL.md).
            Do NOT use Windows-style paths like C:\\ or D:.
            Use ls, read_file, write_file, etc. to interact with files.
            """
            
            skills_middleware = SkillsMiddleware(
                sources=["skills"],
                backend=self.backend,
            )
            
            skills_agent = create_deep_agent(
                model=self.llm,
                backend=self.backend,
                system_prompt=system_prompt,
                middleware=[skills_middleware],
                interrupt_on={
                    "write_file": True,
                    "read_file": False,
                    "edit_file": True
                },
                checkpointer=self.checkpointer,
            )
            
            self.agents["skills"] = skills_agent
            self.configs["skills"] = {"configurable": {"thread_id": "skills_default"}}
            self.agent_statuses["skills"]["status"] = "initialized"
            self.agent_statuses["skills"]["initialized_at"] = datetime.now().isoformat()
            self.agent_statuses["skills"]["tools_count"] = 1  # Skills middleware算作一个工具
            print("✅ Skills Agent初始化完成")
            
        except Exception as e:
            self.agent_statuses["skills"]["status"] = "error"
            self.agent_statuses["skills"]["error"] = str(e)
            print(f"❌ Skills Agent初始化失败: {e}")
            raise
        
    def get_agent(self, agent_type: str):
        """获取指定类型的agent"""
        if agent_type not in self.agents:
            raise ValueError(f"不支持的agent类型: {agent_type}")
        return self.agents[agent_type]
        
    def get_config(self, agent_type: str, thread_id: str):
        """获取配置，支持自定义thread_id"""
        base_config = self.configs.get(agent_type, {}).copy()
        if "configurable" in base_config:
            base_config["configurable"]["thread_id"] = thread_id
        return base_config
        
    def _record_session_message(self, thread_id: str, agent_type: str, role: str, content: str, tool_calls: Optional[List[ToolCallInfo]] = None):
        """记录会话消息"""
        if thread_id not in self.sessions:
            self.sessions[thread_id] = {
                "agent_type": agent_type,
                "created_at": datetime.now().isoformat(),
                "messages": []
            }
        
        message = SessionMessage(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            tool_calls=tool_calls
        )
        
        self.sessions[thread_id]["messages"].append(message.dict())
        self.sessions[thread_id]["last_active"] = datetime.now().isoformat()
        
    async def chat_completion(self, request: AgentRequest) -> tuple[str, List[ToolCallInfo]]:
        """非流式聊天完成"""
        agent = self.get_agent(request.agent_type)
        config = self.get_config(request.agent_type, request.thread_id)
        
        # 记录用户消息
        self._record_session_message(request.thread_id, request.agent_type, "user", request.message)
        
        # 构造消息
        messages = {"messages": [{"role": "user", "content": request.message}]}
        
        # 收集所有响应和工具调用
        response_chunks = []
        tools_used = []
        
        if asyncio.iscoroutinefunction(agent.astream):
            # 异步流式处理
            async for chunk in agent.astream(messages, config=config, stream_mode="values"):
                if chunk.get("messages"):
                    last_msg = chunk["messages"][-1]
                    if hasattr(last_msg, 'content'):
                        content = str(last_msg.content)
                        response_chunks.append(content)
                    else:
                        content = str(last_msg)
                        response_chunks.append(content)
                    
                    # 记录助手回复
                    self._record_session_message(request.thread_id, request.agent_type, "assistant", content)
        else:
            # 同步流式处理
            for chunk in agent.stream(messages, config=config, stream_mode="values"):
                if chunk.get("messages"):
                    last_msg = chunk["messages"][-1]
                    if hasattr(last_msg, 'content'):
                        content = str(last_msg.content)
                        response_chunks.append(content)
                    else:
                        content = str(last_msg)
                        response_chunks.append(content)
                    
                    # 记录助手回复
                    self._record_session_message(request.thread_id, request.agent_type, "assistant", content)
                        
        return "".join(response_chunks), tools_used
        
    async def chat_completion_stream(self, request: AgentRequest) -> AsyncGenerator[StreamChunk, None]:
        """流式聊天完成"""
        agent = self.get_agent(request.agent_type)
        config = self.get_config(request.agent_type, request.thread_id)
        
        # 记录用户消息
        self._record_session_message(request.thread_id, request.agent_type, "user", request.message)
        
        # 构造消息
        messages = {"messages": [{"role": "user", "content": request.message}]}
        
        try:
            if asyncio.iscoroutinefunction(agent.astream):
                # 异步流式处理
                async for chunk in agent.astream(messages, config=config, stream_mode="values"):
                    if chunk.get("messages"):
                        last_msg = chunk["messages"][-1]
                        content = str(last_msg.content) if hasattr(last_msg, 'content') else str(last_msg)
                        
                        # 记录助手回复
                        self._record_session_message(request.thread_id, request.agent_type, "assistant", content)
                        
                        yield StreamChunk(
                            content=content,
                            chunk_type="text",
                            thread_id=request.thread_id,
                            agent_type=request.agent_type,
                            timestamp=datetime.now().isoformat()
                        )
            else:
                # 同步流式处理需要在异步上下文中运行
                loop = asyncio.get_event_loop()
                for chunk in await loop.run_in_executor(None, lambda: list(agent.stream(messages, config=config, stream_mode="values"))):
                    if chunk.get("messages"):
                        last_msg = chunk["messages"][-1]
                        content = str(last_msg.content) if hasattr(last_msg, 'content') else str(last_msg)
                        
                        # 记录助手回复
                        self._record_session_message(request.thread_id, request.agent_type, "assistant", content)
                        
                        yield StreamChunk(
                            content=content,
                            chunk_type="text",
                            thread_id=request.thread_id,
                            agent_type=request.agent_type,
                            timestamp=datetime.now().isoformat()
                        )
                        
            # 发送结束标记
            yield StreamChunk(
                content="",
                chunk_type="final",
                thread_id=request.thread_id,
                agent_type=request.agent_type,
                timestamp=datetime.now().isoformat()
            )
            
        except Exception as e:
            # 错误处理
            yield StreamChunk(
                content=f"Error: {str(e)}",
                chunk_type="final",
                thread_id=request.thread_id,
                agent_type=request.agent_type,
                timestamp=datetime.now().isoformat()
            )
    def get_session_history(self, thread_id: str) -> SessionHistoryResponse:
        """获取会话历史"""
        if thread_id not in self.sessions:
            raise ValueError(f"会话不存在: {thread_id}")
            
        session_data = self.sessions[thread_id]
        messages = [SessionMessage(**msg) for msg in session_data["messages"]]
        
        session_info = SessionInfo(
            thread_id=thread_id,
            agent_type=session_data["agent_type"],
            created_at=session_data["created_at"],
            last_active=session_data.get("last_active", session_data["created_at"]),
            message_count=len(messages),
            tools_used_count=sum(1 for msg in messages if msg.tool_calls)
        )
        
        return SessionHistoryResponse(
            session_info=session_info,
            messages=messages,
            total_messages=len(messages)
        )
        
    def list_sessions(self) -> List[SessionInfo]:
        """列出所有会话"""
        sessions_info = []
        for thread_id, session_data in self.sessions.items():
            messages = [SessionMessage(**msg) for msg in session_data["messages"]]
            session_info = SessionInfo(
                thread_id=thread_id,
                agent_type=session_data["agent_type"],
                created_at=session_data["created_at"],
                last_active=session_data.get("last_active", session_data["created_at"]),
                message_count=len(messages),
                tools_used_count=sum(1 for msg in messages if msg.tool_calls)
            )
            sessions_info.append(session_info)
        
        return sessions_info
        
    def get_agent_status(self, agent_type: str) -> AgentStatusResponse:
        """获取Agent状态"""
        if agent_type not in self.agent_statuses:
            raise ValueError(f"不支持的agent类型: {agent_type}")
            
        status_info = self.agent_statuses[agent_type]
        sessions_count = sum(1 for session in self.sessions.values() if session["agent_type"] == agent_type)
        
        return AgentStatusResponse(
            agent_type=agent_type,
            status=status_info["status"],
            error_message=status_info.get("error"),
            initialized_at=status_info.get("initialized_at"),
            tools_available=status_info.get("tools_count", 0),
            sessions_count=sessions_count
        )
        
    def get_all_agent_statuses(self) -> List[AgentStatusResponse]:
        """获取所有Agent状态"""
        return [self.get_agent_status(agent_type) for agent_type in self.agent_statuses.keys()]
        
    async def get_mcp_tools_for_api(self) -> List[Any]:
        """获取MCP工具列表用于API接口"""
        if self._cached_mcp_tools is not None:
            return self._cached_mcp_tools
        
        # 如果缓存为空，重新获取
        try:
            client = MultiServerMCPClient({
                "my_fastmcp": {
                    "transport": "http",
                    "url": "http://127.0.0.1:8000/mcp",
                }
            })
            mcp_tools = await client.get_tools()
            self._cached_mcp_tools = mcp_tools
            return mcp_tools
        except Exception as e:
            print(f"获取MCP工具时出错: {e}")
            return []


# 全局agent服务实例
_agent_service_instance: Optional[AgentService] = None


async def get_agent_service():
    """获取agent服务实例"""
    global _agent_service_instance
    if _agent_service_instance is None:
        _agent_service_instance = AgentService()
        await _agent_service_instance.initialize_agents()
    return _agent_service_instance