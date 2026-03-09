"""
Custom tools for the agent.

Provides secure code execution via OpenSandbox.
"""

import logging
import os
from typing import Optional

from langchain_core.tools import tool
from opensandbox import Sandbox
from opensandbox.api.lifecycle.models.volume import Volume
from opensandbox.models import Host
from code_interpreter import CodeInterpreter, SupportedLanguage

from app.core.config import Settings, PERSISTENT_MOUNT_PATH

logger = logging.getLogger("deepagent.service")


@tool
async def python_sandbox(
    code: str,
    settings: Settings,
    timeout_seconds: Optional[int] = 180,
) -> str:
    """
    Safely execute Python code in an isolated container (via OpenSandbox).

    Important:
    - If persistent files are needed (charts, CSV, reports, model files, etc.),
      save them to /workspace directory
    - These files will automatically appear in the host's sandbox_output_host_dir
    - Supports numpy / pandas / matplotlib / sympy libraries
    - Each execution is a fresh environment (except mounted persistent directory)
    """

    code = code.strip()
    if not code or len(code) < 5:
        return "Code is too short or empty, cannot execute"

    # Security filtering (prevent dangerous operations)
    blocked = [
        "sys.exit",
        "os.system",
        "subprocess",
        "exec(",
        "__import__",
        "shutil.rmtree",
        f"os.remove('{PERSISTENT_MOUNT_PATH}",
        f"rm -rf {PERSISTENT_MOUNT_PATH}",
    ]

    if any(kw.lower() in code.lower() for kw in blocked):
        return "Execution rejected: detected unsafe keyword or path operation"

    sandbox = None
    try:
        volumes = [
            Volume(
                name="/workspace",
                host=Host(path=settings.sandbox_output_host_dir),
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

        output = "\n\n".join(parts) or "(Execution completed, no standard output)"

        # Simple hint if files were generated
        if os.listdir(settings.sandbox_output_host_dir):
            output += (
                f"\n\nNote: Persistent files saved to host directory:\n"
                f"  {settings.sandbox_output_host_dir}\n"
                f"  (Container path: {PERSISTENT_MOUNT_PATH})"
            )

        return output

    except Exception as e:
        logger.exception("Sandbox execution failed")
        return f"Execution failed: {str(e)}"

    finally:
        if sandbox:
            try:
                await sandbox.kill()
            except Exception as exc:
                logger.warning(f"Failed to cleanup sandbox: {exc}")


def get_sandbox_tool(settings: Settings):
    """Get the sandbox tool with settings bound.

    Returns a wrapper that has settings pre-bound.
    """
    # Store settings in closure
    bound_settings = settings

    @tool
    async def python_sandbox_with_settings(code: str, timeout_seconds: Optional[int] = 180) -> str:
        """
        Safely execute Python code in an isolated container (via OpenSandbox).

        Important:
        - If persistent files are needed (charts, CSV, reports, model files, etc.),
          save them to /workspace directory
        - These files will automatically appear in the host's sandbox_output_host_dir
        - Supports numpy / pandas / matplotlib / sympy libraries
        - Each execution is a fresh environment (except mounted persistent directory)
        """
        # Call the original tool with bound settings
        return await python_sandbox.ainvoke({
            "code": code,
            "settings": bound_settings,
            "timeout_seconds": timeout_seconds,
        })

    # Override the name to match the expected tool name
    python_sandbox_with_settings.name = "python_sandbox"

    return python_sandbox_with_settings


# ─── Tool Registry ───────────────────────────────────────────────────────

# Registry mapping tool names to their factory functions
# Each factory takes Settings and returns a tool instance
TOOL_REGISTRY = {
    "python_sandbox": get_sandbox_tool,
}


def get_tools_by_names(tool_names: list[str], settings: Settings) -> list:
    """
    Get tool instances by their names from the registry.

    Args:
        tool_names: List of tool names to load
        settings: Application settings

    Returns:
        List of tool instances
    """
    tools = []
    for name in tool_names:
        if name in TOOL_REGISTRY:
            tool_factory = TOOL_REGISTRY[name]
            tools.append(tool_factory(settings))
            logger.info(f"Loaded tool: {name}")
        else:
            logger.warning(f"Tool not found in registry: {name}")
    return tools
