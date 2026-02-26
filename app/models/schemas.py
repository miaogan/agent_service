from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    """Agent调用请求模型"""
    message: str = Field(..., description="用户输入的消息")
    thread_id: str = Field(default="default_thread", description="会话线程ID")
    agent_type: Literal["mcp", "skills"] = Field(default="mcp", description="Agent类型")
    stream: bool = Field(default=False, description="是否启用流式响应")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int = Field(default=1000, ge=1, le=4096, description="最大token数")
    tools_enabled: bool = Field(default=True, description="是否启用工具调用")
    system_prompt_override: Optional[str] = Field(default=None, description="覆盖默认系统提示词")


class ToolCallInfo(BaseModel):
    """工具调用信息"""
    tool_name: str = Field(..., description="工具名称")
    arguments: Dict[str, Any] = Field(..., description="调用参数")
    result: Optional[Any] = Field(default=None, description="调用结果")
    error: Optional[str] = Field(default=None, description="错误信息")
    timestamp: str = Field(..., description="调用时间戳")


class AgentResponse(BaseModel):
    """Agent调用响应模型"""
    message: str = Field(..., description="Agent回复的内容")
    thread_id: str = Field(..., description="会话线程ID")
    agent_type: str = Field(..., description="使用的Agent类型")
    tools_used: List[ToolCallInfo] = Field(default=[], description="使用的工具列表")
    usage_stats: Optional[Dict[str, Any]] = Field(default=None, description="使用统计信息")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="额外元数据")


class StreamChunk(BaseModel):
    """流式响应的数据块"""
    content: str = Field(..., description="当前块的内容")
    chunk_type: Literal["text", "tool_call", "thinking", "final"] = Field(..., description="块类型")
    thread_id: str = Field(..., description="会话线程ID")
    agent_type: str = Field(..., description="使用的Agent类型")
    tool_call_info: Optional[ToolCallInfo] = Field(default=None, description="工具调用详情")
    timestamp: str = Field(..., description="时间戳")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(default="healthy", description="服务状态")
    version: str = Field(default="1.0.0", description="API版本")
    agents_available: List[str] = Field(default=["mcp", "skills"], description="可用的Agent类型")


class SkillInfo(BaseModel):
    """技能信息模型"""
    name: str = Field(..., description="技能名称")
    description: str = Field(..., description="技能描述")
    path: str = Field(..., description="技能路径")
    readme_path: Optional[str] = Field(default=None, description="README文件路径")
    features: List[str] = Field(default=[], description="技能特性列表")
    usage_examples: List[str] = Field(default=[], description="使用示例")
    dependencies: List[str] = Field(default=[], description="依赖包列表")


class SkillListResponse(BaseModel):
    """技能列表响应模型"""
    skills: List[SkillInfo] = Field(..., description="技能列表")
    total_count: int = Field(..., description="技能总数")
    timestamp: str = Field(..., description="响应时间戳")


class MCPFunctionInfo(BaseModel):
    """MCP功能信息模型"""
    name: str = Field(..., description="功能名称")
    description: str = Field(..., description="功能描述")
    tool_type: str = Field(..., description="工具类型")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="参数信息")
    required_parameters: List[str] = Field(default=[], description="必需参数")


class MCPToolInfo(BaseModel):
    """MCP工具信息模型"""
    tool_name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    functions: List[MCPFunctionInfo] = Field(default=[], description="包含的功能列表")
    server_url: str = Field(..., description="服务器URL")


class MCPListResponse(BaseModel):
    """MCP功能列表响应模型"""
    tools: List[MCPToolInfo] = Field(..., description="MCP工具列表")
    total_count: int = Field(..., description="工具总数")
    server_status: str = Field(..., description="服务器状态")
    timestamp: str = Field(..., description="响应时间戳")


class SessionMessage(BaseModel):
    """会话消息模型"""
    role: Literal["user", "assistant", "system", "tool"] = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")
    timestamp: str = Field(..., description="时间戳")
    tool_calls: Optional[List[ToolCallInfo]] = Field(default=None, description="工具调用信息")


class SessionInfo(BaseModel):
    """会话信息模型"""
    thread_id: str = Field(..., description="会话ID")
    agent_type: str = Field(..., description="Agent类型")
    created_at: str = Field(..., description="创建时间")
    last_active: str = Field(..., description="最后活跃时间")
    message_count: int = Field(..., description="消息数量")
    tools_used_count: int = Field(default=0, description="使用的工具数量")


class SessionHistoryResponse(BaseModel):
    """会话历史响应模型"""
    session_info: SessionInfo = Field(..., description="会话基本信息")
    messages: List[SessionMessage] = Field(..., description="消息历史")
    total_messages: int = Field(..., description="总消息数")


class AgentStatusResponse(BaseModel):
    """Agent状态响应模型"""
    agent_type: str = Field(..., description="Agent类型")
    status: Literal["initialized", "initializing", "error"] = Field(..., description="状态")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    initialized_at: Optional[str] = Field(default=None, description="初始化时间")
    tools_available: int = Field(default=0, description="可用工具数量")
    sessions_count: int = Field(default=0, description="活跃会话数")