# deep_agent_example.py
import asyncio
import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
# 新增：MCP 适配器
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

# ========================
# 1. FilesystemBackend（保持你原来的 Windows 配置）
# ========================
ROOT_DIR = Path.cwd()
backend = FilesystemBackend(root_dir=str(ROOT_DIR), virtual_mode=True)
os.environ["OPENAI_API_KEY"] = "sk-1234"

# ========================
# 2. 加载 FastMCP 的工具（关键部分）
# ========================
async def get_mcp_tools():
    client = MultiServerMCPClient({
        "my_fastmcp": {  # 给这个 server 起个名字
            "transport": "http",
            "url": "http://127.0.0.1:8000/mcp",  # 对应上面 server 的地址

        }
    })
    tools = await client.get_tools()  # 自动转换成 LangChain Tool
    return tools


# ========================
# 3. LLM + DeepAgent
# ========================
llm = ChatOpenAI(
    openai_api_base="http://127.0.0.1:4000",
    model="qwen3.5-plus"
)

system_prompt = """
你是一个强大的助手，可以使用 MCP 工具。
所有文件路径必须以 / 开头。
"""

checkpointer = MemorySaver()


async def main():
    # 异步加载 MCP tools
    mcp_tools = await get_mcp_tools()

    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        backend=backend,
        tools=mcp_tools,  # ← 直接传入！
        checkpointer=checkpointer,
    )

    config = {"configurable": {"thread_id": "mcp_test"}}

    print("DeepAgent + FastMCP 已就绪！输入 'exit' 退出。")
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ["exit", "quit", "q"]:
            break

        print("Agent: ", end="", flush=True)
        async for chunk in agent.astream(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
                stream_mode="values",
        ):
            last_msg = chunk["messages"][-1]
            print(last_msg)
        print()


if __name__ == "__main__":
    asyncio.run(main())
