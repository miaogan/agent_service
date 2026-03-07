# agent_service.py
"""
DeepAgent 服务主程序
提供基于 LangGraph + LiteLLM + MCP + OpenSandbox 的智能代理流式对话接口
支持沙箱中生成的文件持久化到宿主机物理路径
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, List, Optional

import httpx
import uvicorn
from code_interpreter import CodeInterpreter, SupportedLanguage
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware import SkillsMiddleware
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from opensandbox import Sandbox
from opensandbox.api.lifecycle.models.volume import Volume
from opensandbox.models import Host
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ─── 配置加载 ────────────────────────────────────────────────

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    root_dir: Path = Path(__file__).resolve().parent.parent
    litellm_api_base: str = "http://127.0.0.1:4000"
    mcp_default_url: str = "http://127.0.0.1:8000/mcp"
    default_thread_id: str = "conversation1"
    default_model: str = "glm-5"

    # OpenSandbox 配置
    opensandbox_endpoint: str = "http://localhost:8000"
    opensandbox_api_key: Optional[str] = None

    # 沙箱持久化输出目录（宿主机路径）
    # 建议在 .env 中配置，例如：SANDBOX_OUTPUT_HOST_DIR=/data/agent_sandbox_output
    sandbox_output_host_dir: str = "D:/work_space/python_project/agents_service/workspace"

    @property
    def skill_dir(self) -> Path:
        return self.root_dir / "skill"


settings = Settings()

# 确保 skill 目录和沙箱输出目录存在
settings.skill_dir.mkdir(parents=True, exist_ok=True)
os.makedirs(settings.sandbox_output_host_dir, exist_ok=True)
logger = logging.getLogger("deepagent.service")
logger.info(f"沙箱持久化输出目录已准备：{settings.sandbox_output_host_dir}")

# ─── 日志配置 ─────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ─── 常量定义 ─────────────────────────────────────────────────

AGENT_MODE_SKILL = "skill"
AGENT_MODE_MCP = "mcp"
AGENT_MODE_BOTH = "both"
VALID_MODES = {AGENT_MODE_SKILL, AGENT_MODE_MCP, AGENT_MODE_BOTH}

DEFAULT_MCP_CONFIG = {
    "my_fastmcp": {
        "transport": "http",
        "url": settings.mcp_default_url,
    }
}

# 持久化目录在容器内的挂载路径（固定）
PERSISTENT_MOUNT_PATH = "/workspace"

# ─── 全局模型列表 ─────────────────────────────────────────────

available_models: List[str] = []


async def refresh_available_models() -> None:
    """从 LiteLLM 获取可用模型列表"""
    global available_models
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.litellm_api_base}/v1/models", timeout=8.0
            )
            if resp.status_code == 200:
                data = resp.json()
                available_models = [m["id"] for m in data.get("data", []) if m.get("id")]
                logger.info(f"成功加载 {len(available_models)} 个模型")
            else:
                logger.warning(f"获取模型列表失败：{resp.status_code}")
    except Exception as e:
        logger.error(f"无法获取 LiteLLM 模型列表：{type(e).__name__} {e}")


# ─── 安全沙箱 Python 执行工具（支持持久化输出） ────────────────


@tool
async def python_sandbox(
        code: str,
        timeout_seconds: Optional[int] = 180,
) -> str:
    """
    在隔离容器中安全执行 Python 代码（基于 OpenSandbox）

    重要说明：
    • 如果需要持久化文件（图表、CSV、报告、模型文件等），请保存到 {PERSISTENT_MOUNT_PATH} 目录
    • 这些文件会自动出现在宿主机的 {settings.sandbox_output_host_dir} 目录
    • 支持 numpy / pandas / matplotlib / sympy 等库
    • 每次执行为全新环境（除挂载的持久化目录外）
    """

    code = code.strip()
    if not code or len(code) < 5:
        return "代码太短或为空，无法执行"
    # 安全过滤（防止危险操作）
    blocked = [
        "sys.exit", "os.system", "subprocess", "exec(", "__import__",
        "shutil.rmtree", f"os.remove('{PERSISTENT_MOUNT_PATH}", f"rm -rf {PERSISTENT_MOUNT_PATH}"
    ]
    if any(kw.lower() in code.lower() for kw in blocked):
        return "拒绝执行：检测到不安全的关键字或路径操作"
    sandbox = None
    try:
        # 挂载宿主机目录 → 容器内持久化路径
        volumes = [
            Volume(
                name="workdir",
                host=Host(
                    path=settings.sandbox_output_host_dir
                ),
                mount_path=PERSISTENT_MOUNT_PATH,
                sub_path="task-001",
            ),

        ]
        sandbox = await Sandbox.create(
            image="sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter",
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
            env={"PYTHON_VERSION": "3.12"},
            volumes=volumes,
        )
        interpreter = await CodeInterpreter.create(sandbox)
        result = await interpreter.codes.run(
            code=code,
            language=SupportedLanguage.PYTHON,
        )
        parts = []
        if result.logs.stdout:
            stdout = "\n".join(l.text.strip() for l in result.logs.stdout if l.text.strip())
            if stdout:
                parts.append(f"=== stdout ===\n{stdout}")
        if result.logs.stderr:
            stderr = "\n".join(l.text.strip() for l in result.logs.stderr if l.text.strip())
            if stderr:
                parts.append(f"=== stderr ===\n{stderr}")
        output = "\n\n".join(parts) or "(执行完成，无标准输出)"
        # 简单提示是否有文件生成（生产环境可扫描目录列出具体文件）
        if os.listdir(settings.sandbox_output_host_dir):
            output += (
                f"\n\n注意：持久化文件已保存至宿主机目录：\n"
                f"  {settings.sandbox_output_host_dir}\n"
                f"  （容器内路径：{PERSISTENT_MOUNT_PATH}）"
            )
        return output
    except Exception as e:
        logger.exception("沙箱执行失败")
        return f"执行失败：{str(e)}"
    finally:
        if sandbox:
            try:
                await sandbox.kill()
            except Exception as exc:
                logger.warning(f"清理沙箱失败：{exc}")


# ─── Agent 工厂 ───────────────────────────────────────────────


async def create_agent(
        model_name: str,
) -> Any:
    """创建 DeepAgent 实例"""

    backend = FilesystemBackend(root_dir=str(settings.root_dir), virtual_mode=True)

    llm = ChatOpenAI(
        base_url=settings.litellm_api_base,
        model=model_name,
        temperature=0.7,
    )
    workspace_path = settings.root_dir / "workspace"
    skill_path_obj = settings.skill_dir
    composite_backend = lambda rt: CompositeBackend(
        default=backend,
        routes={
            "/workspace/": FilesystemBackend(root_dir=str(workspace_path), virtual_mode=True),
            "/skill/": FilesystemBackend(root_dir=str(skill_path_obj), virtual_mode=True)
        }
    )
    logger.info(f"配置复合后端：/workspace -> {workspace_path}, /skill -> {skill_path_obj}")
    tools = [python_sandbox]
    skills_middleware = SkillsMiddleware(
        sources=["/skill"],
        backend=backend,
    )
    common_kwargs = {
        "model": llm,
        "backend": composite_backend,
    }
    # 持久化说明（统一添加到所有模式的 system prompt）
    persistent_note = (
        f"\n重要：使用 python_sandbox 时，如果生成了需要保留的文件（如图表、CSV、报告等），"
        f"请保存到 {PERSISTENT_MOUNT_PATH} 目录。\n"
        f"这些文件会自动出现在宿主机的持久化目录：{settings.sandbox_output_host_dir}\n"
        "切勿删除或覆盖该目录内容。"
    )
    system = (
            "你是一个功能强大的助手，同时拥有虚拟文件系统和外部工具能力。\n"
            "所有文件路径必须以 / 开头。\n"
            "**绝对不要**在路径中使用 Windows 盘符（D:, C: 等），也不要输出任何真实物理路径。\n"
            "当你要引用 /skill 目录下的文件时，只使用相对路径，例如：\n"
            "  /skill/arxiv-search/SKILL.md\n"
            "  /skill/langgraph-docs/SKILL.md\n"
            "  arxiv-search/SKILL.md   （推荐，不带前导斜杠也可以）\n"
            "你可以通过写文件的方式将结果保存到 /workspace 目录下。\n"
            "可通过 python_sandbox 安全执行 Python 代码。"
            + persistent_note
    )
    return create_deep_agent(
        **common_kwargs,
        middleware=[skills_middleware],
        system_prompt=system,
        tools=tools,
    )


async def load_mcp_tools(config: dict) -> List:
    """加载 MCP 工具"""
    try:
        client = MultiServerMCPClient(config)
        tools = await client.get_tools()
        logger.debug(f"成功加载 {len(tools)} 个 MCP 工具")
        return tools
    except Exception as e:
        logger.error(f"加载 MCP 工具失败：{e}")
        return []


# ─── FastAPI 应用 ─────────────────────────────────────────────

app = FastAPI(title="DeepAgent Service", version="0.3")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("DeepAgent 服务启动中...")
    await refresh_available_models()
    yield
    logger.info("DeepAgent 服务正在关闭...")


app.router.lifespan_context = lifespan


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户消息")
    model: str = settings.default_model
    thread_id: str = settings.default_thread_id


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口"""
    if available_models and request.model not in available_models:
        raise HTTPException(400, f"未知模型：{request.model}")
    try:
        agent = await create_agent(
            request.model,
        )
    except Exception as e:
        logger.exception("创建 Agent 失败")
        raise HTTPException(500, "无法初始化 Agent")
    async def event_generator() -> AsyncGenerator[str, None]:
        content_acc = ""
        tools_used = []
        try:
            async for event in agent.astream(
                    {"messages": [{"role": "user", "content": request.message}]},
                    stream_mode="messages",
            ):
                if not isinstance(event, tuple) or len(event) != 2:
                    continue
                chunk, _ = event
                # 工具调用
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
                # 内容增量
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
            yield f"data: {json.dumps({
                'type': 'done',
                'content': content_acc,
                'tools_used': tools_used
            }, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"流式处理异常：{type(e).__name__} - {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': '处理错误'})}\n\n"
            yield "data: [DONE]\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(
        "agent_service:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info",
    )
