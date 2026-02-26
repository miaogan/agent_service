import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware import SkillsMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
ROOT_DIR = Path.cwd()  # 当前脚本所在目录
os.makedirs(ROOT_DIR / "skills", exist_ok=True)
checkpointer = MemorySaver()
os.environ["OPENAI_API_KEY"] = "sk-1234"
llm = ChatOpenAI(
    openai_api_base="http://127.0.0.1:4000",
    model="qwen3.5-plus"
)
system_prompt = """
You are a helpful AI assistant with access to a virtual filesystem.
All file paths MUST start with / (e.g. /workspace/report.md, /skills/my-skill/SKILL.md).
Do NOT use Windows-style paths like C:\\ or D:.
Use ls, read_file, write_file, etc. to interact with files.
"""
backend = FilesystemBackend(
    root_dir=str(ROOT_DIR),          # str 或 Path 都行
    virtual_mode=True,               # 必须！强制虚拟路径，防 Windows 路径 bug
)
skills_middleware = SkillsMiddleware(
    sources=["skills"],              # 相对 root_dir 的路径，用 / 分隔
    backend=backend,
)

# 修复 FilesystemBackend 警告，显式设置 virtual_mode
agent = create_deep_agent(
    model=llm,  # 直接传递配置好的模型实例
    backend=backend,
    system_prompt=system_prompt,
    middleware=[skills_middleware] if 'skills_middleware' in globals() else [],  # 如果用了 skills
    interrupt_on={
        "write_file": True,  # Default: approve, edit, reject
        "read_file": False,  # No interrupts needed
        "edit_file": True  # Default: approve, edit, reject
    },
    checkpointer=checkpointer,  # Required!
)

def run_agent():
    config = {"configurable": {"thread_id": "conversation1"}}  # 同一个 thread_id 保持会话连续

    print("Deep Agent 已启动！输入 'exit' 退出。")
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ["exit", "quit", "q"]:
            break

        # 流式输出
        print("Agent: ", end="", flush=True)
        for chunk in agent.stream(
            {"messages": [{"role": "user", "content": user_input}]},
            config=config,
            stream_mode="values",
        ):
            last_msg = chunk["messages"][-1]
            print(last_msg)
        print()  # 换行

if __name__ == "__main__":
    run_agent()