import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel



from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware import SkillsMiddleware
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

# ======================== 配置 ========================
ROOT_DIR = Path.cwd()
os.makedirs(ROOT_DIR / "skill", exist_ok=True)

load_dotenv()

llm = ChatOpenAI(
    openai_api_base="http://127.0.0.1:4000",
    model="qwen3.5-plus"
)

backend = FilesystemBackend(
    root_dir=str(ROOT_DIR),
    virtual_mode=True,
)

checkpointer = MemorySaver()

# ======================== 全局变量 ========================
agents: Dict[str, any] = {}
mcp_tools: Optional[List] = None
skills_middleware: Optional[SkillsMiddleware] = None


# ======================== MCP Tools 加载 ========================
async def load_mcp_tools():
    client = MultiServerMCPClient({
        "my_fastmcp": {
            "transport": "http",
            "url": "http://127.0.0.1:8000/mcp",
        }
    })
    return await client.get_tools()


# ======================== 辅助函数：安全提取文本内容 ========================
def extract_text_content(msg) -> str:
    """从 LangChain 消息中安全提取纯文本内容"""
    if not hasattr(msg, "content") or msg.content is None:
        return ""

    content = msg.content

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                # 常见的几种 content block 格式
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif "text" in block:
                    parts.append(block["text"])
                # 忽略 tool_use / tool_result 等结构化块
            else:
                parts.append(str(block))
        return "".join(parts)

    # 其他意外类型，转字符串兜底
    return str(content)


# ======================== FastAPI Lifespan ========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_tools, skills_middleware, agents
    
    print("🚀 开始初始化服务...")
    print(f"📁 工作目录: {ROOT_DIR}")
    print(f"🔧 后端类型: {type(backend).__name__}")
    print(f"🧠 检查点器类型: {type(checkpointer).__name__}")

    # Skills Middleware
    print("🔄 初始化 Skills Middleware...")
    skills_middleware = SkillsMiddleware(
        sources=["skill"],
        backend=backend,
    )
    print("✅ Skills Middleware 初始化完成")

    # MCP Tools（启动时一次性加载，带容错）
    try:
        mcp_tools = await load_mcp_tools()
        mcp_available = len(mcp_tools) > 0 if mcp_tools else False
        if not mcp_available:
            print("⚠️  MCP工具不可用，将跳过MCP相关代理创建")
    except Exception as e:
        print(f"❌ MCP工具加载完全失败: {str(e)}")
        mcp_tools = []
        mcp_available = False

    # ======================== 创建三种模式的 Agent ========================
    base_system = """You are a helpful AI assistant with access to a virtual filesystem.
All file paths MUST start with / (e.g. /workspace/report.md, /skill/my-skill/SKILL.md).
Do NOT use Windows-style paths.
Use ls, read_file, write_file, etc. to interact with files."""

    # ---------- skill only ----------
    print("🔄 开始创建 Skill-only agent...")
    try:
        agents["skill"] = create_deep_agent(
            model=llm,
            backend=backend,
            system_prompt=base_system,
            middleware=[skills_middleware],
            interrupt_on={
                "write_file": False,
                "read_file": False,
                "edit_file": False,
            },
            checkpointer=checkpointer,
        )
        print("✅ Skill-only agent 创建成功")
        print(f"   - 使用模型: {llm.model}")
        print(f"   - 后端类型: {type(backend).__name__}")
        print(f"   - 中间件数量: {len([skills_middleware])}")
        print(f"   - 检查点器类型: {type(checkpointer).__name__}")
    except Exception as e:
        print(f"❌ Skill-only agent 创建失败: {str(e)}")
        raise

    # ---------- mcp only ----------
    if mcp_available:
        print("🔄 开始创建 MCP-only agent...")
        try:
            agents["mcp"] = create_deep_agent(
                model=llm,
                backend=backend,
                system_prompt="""你是一个强大的助手，可以使用 MCP 工具。
所有文件路径必须以 / 开头。""",
                tools=mcp_tools,
                checkpointer=checkpointer,
            )
            print("✅ MCP-only agent 创建成功")
            print(f"   - 使用模型: {llm.model}")
            print(f"   - 后端类型: {type(backend).__name__}")
            print(f"   - MCP工具数量: {len(mcp_tools)}")
            print(f"   - 检查点器类型: {type(checkpointer).__name__}")
        except Exception as e:
            print(f"❌ MCP-only agent 创建失败: {str(e)}")
            raise
    else:
        print("⚠️  跳过MCP-only agent创建（MCP工具不可用）")

    # ---------- both ----------
    if mcp_available:
        print("🔄 开始创建 Skills+MCP hybrid agent...")
        try:
            agents["both"] = create_deep_agent(
                model=llm,
                backend=backend,
                system_prompt=base_system + "\n你同时拥有 Skills Middleware 和 MCP 工具。",
                middleware=[skills_middleware],
                tools=mcp_tools,
                interrupt_on={
                    "write_file": False,
                    "read_file": False,
                    "edit_file": False,
                },
                checkpointer=checkpointer,
            )
            print("✅ Skills+MCP hybrid agent 创建成功")
            print(f"   - 使用模型: {llm.model}")
            print(f"   - 后端类型: {type(backend).__name__}")
            print(f"   - 中间件数量: {len([skills_middleware])}")
            print(f"   - MCP工具数量: {len(mcp_tools)}")
            print(f"   - 检查点器类型: {type(checkpointer).__name__}")
        except Exception as e:
            print(f"❌ Skills+MCP hybrid agent 创建失败: {str(e)}")
            raise
    else:
        print("⚠️  跳过Skills+MCP hybrid agent创建（MCP工具不可用）")

    # 总结
    print("\n📋 Agent 创建总结:")
    print(f"   - 成功创建的 Agent 数量: {len(agents)}")
    for mode in agents.keys():
        print(f"   - [{mode}] agent: ✅ 已就绪")
    print("🎉 服务初始化完成！")

    yield
    # 清理（可选）
    print("🧹 正在清理资源...")
    agents.clear()
    print("✅ 清理完成")


app = FastAPI(lifespan=lifespan, title="DeepAgent MCP/Skills Service")


# ======================== 请求模型 ========================
class ChatRequest(BaseModel):
    message: str
    mode: str = "skill"  # skill | mcp | both
    thread_id: Optional[str] = "conversation1"



# ======================== 流式接口（SSE） ========================
@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    if req.mode not in agents:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid mode. Use: skill, mcp, both"}
        )

    agent = agents[req.mode]
    config = {"configurable": {"thread_id": req.thread_id}}

    async def event_generator() -> AsyncGenerator[str, None]:
        previous_content = ""
        tools_used: List[dict] = []

        try:
            async for chunk in agent.astream(
                    {"messages": [{"role": "user", "content": req.message}]},
                    config=config,
                    stream_mode="values",
            ):
                messages = chunk.get("messages", [])
                if not messages:
                    continue

                last_msg = messages[-1]

                # 工具调用检测
                if hasattr(last_msg, "tool_calls") and getattr(last_msg, "tool_calls", None):
                    for tc in last_msg.tool_calls:
                        tool_info = {
                            "type": "tool_call",
                            "tool": tc.get("name"),
                            "args": tc.get("args", {}),
                            "tool_call_id": tc.get("id")
                        }
                        # 避免重复推送相同的 tool call
                        if tool_info not in tools_used:
                            tools_used.append(tool_info)
                            yield f"data: {json.dumps(tool_info, ensure_ascii=False)}\n\n"

                # 内容增量
                curr = extract_text_content(last_msg)

                if curr:
                    if curr.startswith(previous_content):
                        delta = curr[len(previous_content):]
                        if delta.strip():  # 避免推送纯空白
                            yield f"data: {json.dumps({'type': 'delta', 'content': delta}, ensure_ascii=False)}\n\n"
                        previous_content = curr
                    else:
                        # 内容被重置的情况（较少见）
                        yield f"data: {json.dumps({'type': 'delta', 'content': curr}, ensure_ascii=False)}\n\n"
                        previous_content = curr

            # 结束事件
            yield f"data: {json.dumps({
                'type': 'done',
                'content': previous_content,
                'tools_used': tools_used
            }, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )


# ======================== 健康检查 ========================
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "available_modes": list(agents.keys()),
        "mcp_tools_loaded": mcp_tools is not None,
        "mcp_tools_count": len(mcp_tools) if mcp_tools else 0,
        "mcp_available": len(mcp_tools) > 0 if mcp_tools else False
    }


if __name__ == '__main__':

    # 运行开发服务器
    uvicorn.run(
        "app.agent_service:app",
        host="0.0.0.0",
        port=8001,
        reload=True,  # 开发模式下启用热重载
        log_level="info"
    )
