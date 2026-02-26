from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import json
import asyncio
from datetime import datetime
from typing import AsyncGenerator, List

from app.models.schemas import (
    AgentRequest, AgentResponse, StreamChunk, HealthResponse,
    SkillListResponse, MCPListResponse, SessionHistoryResponse,
    SessionInfo, AgentStatusResponse
)
from app.services.agent_service import get_agent_service, AgentService
from app.services.skill_service import get_skill_service, SkillService

router = APIRouter(prefix="/api/v1", tags=["agents"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点"""
    return HealthResponse()


@router.post("/chat/completion", response_model=AgentResponse)
async def chat_completion(
    request: AgentRequest,
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    非流式聊天完成
    
    Args:
        request: 聊天请求
        agent_service: Agent服务实例
        
    Returns:
        AgentResponse: 完整的响应结果
    """
    try:
        # 如果请求要求流式但访问了非流式端点，返回错误
        if request.stream:
            raise HTTPException(
                status_code=400, 
                detail="请使用流式端点 /chat/completion/stream 进行流式调用"
            )
            
        response_content, tools_used = await agent_service.chat_completion(request)
        
        return AgentResponse(
            message=response_content,
            thread_id=request.thread_id,
            agent_type=request.agent_type,
            tools_used=tools_used,
            usage_stats={
                "response_length": len(response_content),
                "tools_count": len(tools_used)
            },
            metadata={"stream": False}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理请求时出错: {str(e)}")


@router.post("/chat/completion/stream")
async def chat_completion_stream(
    request: AgentRequest,
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    流式聊天完成
    
    Args:
        request: 聊天请求
        agent_service: Agent服务实例
        
    Returns:
        EventSourceResponse: SSE流式响应
    """
    try:
        # 设置流式标志
        request.stream = True
        
        async def event_generator() -> AsyncGenerator[dict, None]:
            """事件生成器"""
            try:
                async for chunk in agent_service.chat_completion_stream(request):
                    # 根据chunk类型处理
                    if chunk.chunk_type == "final":
                        # 结束标记
                        yield {
                            "event": "end",
                            "data": json.dumps(chunk.model_dump(), ensure_ascii=False)
                        }
                        break
                    else:
                        # 普通文本块
                        yield {
                            "event": "message",
                            "data": json.dumps(chunk.model_dump(), ensure_ascii=False)
                        }
                        
            except asyncio.CancelledError:
                # 客户端断开连接
                pass
            except Exception as e:
                # 错误处理
                error_chunk = StreamChunk(
                    content=f"Error: {str(e)}",
                    chunk_type="final",
                    thread_id=request.thread_id,
                    agent_type=request.agent_type
                )
                yield {
                    "event": "error",
                    "data": json.dumps(error_chunk.model_dump(), ensure_ascii=False)
                }
        
        return EventSourceResponse(event_generator())
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理流式请求时出错: {str(e)}")


@router.get("/agents/list")
async def list_agents():
    """列出所有可用的Agent类型"""
    return {
        "agents": [
            {
                "type": "mcp",
                "description": "MCP协议Agent，支持外部工具调用",
                "features": ["工具调用", "HTTP传输"]
            },
            {
                "type": "skills",
                "description": "Skills Agent，支持文件系统操作",
                "features": ["文件读写", "虚拟文件系统", "技能中间件"]
            }
        ]
    }


@router.post("/chat/completion/unified")
async def unified_chat_completion(
    request: AgentRequest,
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    统一聊天端点，根据stream参数自动选择响应格式
    
    Args:
        request: 聊天请求
        agent_service: Agent服务实例
        
    Returns:
        根据stream参数返回不同的响应格式
    """
    if request.stream:
        # 流式响应
        return await chat_completion_stream(request, agent_service)
    else:
        # 非流式响应
        return await chat_completion(request, agent_service)


@router.get("/skills/list", response_model=SkillListResponse)
async def list_skills(
    skill_service: SkillService = Depends(get_skill_service)
):
    """
    获取技能列表
    
    Returns:
        SkillListResponse: 技能列表响应
    """
    try:
        return skill_service.get_skill_list()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取技能列表时出错: {str(e)}")


@router.get("/sessions/{thread_id}", response_model=SessionHistoryResponse)
async def get_session_history(
    thread_id: str,
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    获取指定会话的历史记录
    
    Args:
        thread_id: 会话ID
        agent_service: Agent服务实例
        
    Returns:
        SessionHistoryResponse: 会话历史响应
    """
    try:
        return agent_service.get_session_history(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话历史时出错: {str(e)}")


@router.get("/sessions", response_model=List[SessionInfo])
async def list_sessions(
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    列出所有会话
    
    Args:
        agent_service: Agent服务实例
        
    Returns:
        List[SessionInfo]: 会话列表
    """
    try:
        return agent_service.list_sessions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"列出会话时出错: {str(e)}")


@router.get("/agents/{agent_type}/status", response_model=AgentStatusResponse)
async def get_agent_status(
    agent_type: str,
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    获取指定Agent的状态
    
    Args:
        agent_type: Agent类型
        agent_service: Agent服务实例
        
    Returns:
        AgentStatusResponse: Agent状态响应
    """
    try:
        return agent_service.get_agent_status(agent_type)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取Agent状态时出错: {str(e)}")


@router.get("/agents/status", response_model=List[AgentStatusResponse])
async def get_all_agents_status(
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    获取所有Agent的状态
    
    Args:
        agent_service: Agent服务实例
        
    Returns:
        List[AgentStatusResponse]: 所有Agent状态列表
    """
    try:
        return agent_service.get_all_agent_statuses()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取Agent状态时出错: {str(e)}")


@router.delete("/sessions/{thread_id}")
async def delete_session(
    thread_id: str,
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    删除指定会话
    
    Args:
        thread_id: 会话ID
        agent_service: Agent服务实例
        
    Returns:
        dict: 删除结果
    """
    try:
        if thread_id in agent_service.sessions:
            del agent_service.sessions[thread_id]
            return {"message": f"会话 {thread_id} 已删除", "deleted": True}
        else:
            raise HTTPException(status_code=404, detail=f"会话不存在: {thread_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除会话时出错: {str(e)}")


@router.get("/mcp/tools", response_model=MCPListResponse)
async def list_mcp_tools(
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    获取MCP工具列表
    
    Returns:
        MCPListResponse: MCP工具列表响应
    """
    try:
        # 确保MCP agent已初始化
        if "mcp" not in agent_service.agents:
            await agent_service._initialize_mcp_agent()
        
        # 获取MCP工具信息
        mcp_tools = await agent_service.get_mcp_tools_for_api()
        
        tools_info = []
        for tool in mcp_tools:
            # 提取工具信息 - LangChain StructuredTool格式
            tool_info = {
                "tool_name": getattr(tool, 'name', 'unknown'),
                "description": getattr(tool, 'description', '暂无描述'),
                "functions": [],
                "server_url": "http://127.0.0.1:8000/mcp"
            }
            
            # 从args_schema提取参数信息
            args_schema = getattr(tool, 'args_schema', {})
            if isinstance(args_schema, dict) and 'properties' in args_schema:
                # 构造函数信息
                func_info = {
                    "name": getattr(tool, 'name', 'unknown'),
                    "description": getattr(tool, 'description', '暂无描述'),
                    "tool_type": "function",
                    "parameters": args_schema,
                    "required_parameters": args_schema.get('required', [])
                }
                tool_info["functions"].append(func_info)
            
            tools_info.append(tool_info)
        
        return MCPListResponse(
            tools=tools_info,
            total_count=len(tools_info),
            server_status="connected" if tools_info else "disconnected",
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取MCP工具列表时出错: {str(e)}")