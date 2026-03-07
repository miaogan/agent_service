# DeepAgent Service - Project Knowledge Base

**Generated:** 2026-03-07
**Language:** Python 3.12+
**Framework:** FastAPI + LangChain + DeepAgents
**Size:** Medium (~1500 lines)

---

## OVERVIEW

FastAPI 微服务，用于 AI Agent 编排，支持 MCP 协议、技能系统、Agent 池化管理、Human-in-the-Loop。

**核心功能：**
- Agent 池化管理（TTL、轮次限制、后台清理）
- 配置持久化（JSON 存储）
- Human-in-the-Loop（敏感工具人工确认）
- 流式聊天（SSE）
- Web UI（开箱即用）

**技术栈：** FastAPI, Uvicorn, LangChain, DeepAgents, Pydantic, LiteLLM

---

## STRUCTURE

```
agent_service/
├── app/
│   ├── main.py              # ✅ FastAPI 入口，生命周期管理
│   ├── api/
│   │   └── routes.py        # API 路由（chat, agents CRUD, resume）
│   ├── core/
│   │   ├── config.py        # Settings 配置类
│   │   ├── tools.py         # python_sandbox 工具
│   │   └── storage.py       # AgentConfigStorage JSON 持久化
│   ├── models/
│   │   └── schemas.py       # AgentConfig, ChatRequest, ResumeRequest
│   ├── services/
│   │   ├── agent_service.py # Agent 工厂，创建 DeepAgent
│   │   └── agent_pool.py    # AgentPool 池管理
│   └── static/
│       └── index.html       # Web UI
├── skill/                   # 技能模块（自描述）
├── tests/                   # 测试文件
├── data/                    # 运行时数据
│   └── agent_configs.json   # Agent 配置持久化
└── pyproject.toml
```

---

## KEY FILES

| 任务 | 文件 | 说明 |
|------|------|------|
| **入口** | `app/main.py` | `python -m app.main` |
| **API 路由** | `app/api/routes.py` | chat, agents, resume |
| **Agent 池** | `app/services/agent_pool.py` | TTL, 轮次限制, 清理 |
| **Agent 工厂** | `app/services/agent_service.py` | 创建 DeepAgent |
| **配置模型** | `app/models/schemas.py` | AgentConfig, ChatRequest |
| **设置** | `app/core/config.py` | Settings 类 |
| **存储** | `app/core/storage.py` | JSON 持久化 |

---

## API ENDPOINTS

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat/stream` | 流式聊天（默认 Agent）|
| POST | `/chat/{agent_id}/stream` | 指定 Agent 聊天 |
| POST | `/chat/{agent_id}/resume` | 恢复中断的 Agent |

### Agent Configuration
| Method | Path | Description |
|--------|------|-------------|
| POST | `/agents` | 创建 Agent 配置 |
| GET | `/agents` | 列出所有配置 |
| GET | `/agents/{agent_id}` | 获取配置 |
| PUT | `/agents/{agent_id}` | 更新配置 |
| DELETE | `/agents/{agent_id}` | 删除配置 |

### Monitoring
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | 健康检查 |
| GET | `/models` | 可用模型 |
| GET | `/pool/stats` | 池状态 |

---

## HUMAN-IN-THE-LOOP

### 配置
在 AgentConfig 中设置 `interrupt_on`：
```python
AgentConfig(
    agent_id="safe-agent",
    interrupt_on={
        "execute": True,      # Shell 命令需确认
        "write_file": True,   # 写文件需确认
    }
)
```

### 流程
1. Agent 执行 `interrupt_on` 中的工具
2. 流中断，返回 `type: "interrupt"` 事件
3. 用户发送 approve/reject/edit 决策
4. 调用 `/chat/{agent_id}/resume` 继续

### Resume 请求
```json
{
    "decision": "approve",
    "tool_call_id": "call_xxx",
    "thread_id": "conversation1"
}
```

---

## AGENT POOL

### 默认 Agent
服务启动自动创建 `default` Agent：
- **Model**: `glm-5`（可配置）
- **Tools**: `python_sandbox`
- **MCP**: 配置的 MCP 服务器
- **Interrupt**: `{"execute": true}`
- **Max Turns**: 100
- **TTL**: 60 分钟

### 生命周期
- **Lazy initialization** - 首次请求时创建
- **TTL expiration** - 空闲 30 分钟后过期
- **Turn limits** - 最大轮次限制
- **Background cleanup** - 每 60 秒清理过期 Agent

---

## SSE EVENTS

| Type | Description |
|------|-------------|
| `delta` | 内容增量 |
| `tool_call` | 工具调用 |
| `interrupt` | 等待人工确认 |
| `done` | 完成 |
| `error` | 错误 |

---

## ENVIRONMENT VARIABLES

```bash
OPENAI_API_KEY=your-key
LITELLM_API_BASE=http://127.0.0.1:4000
MCP_SERVER_URL=http://127.0.0.1:8000/mcp
MCP_LOAD_FAIL_CONTINUE=true
DEFAULT_MODEL=glm-5
```

---

## COMMANDS

```bash
# 安装
uv sync

# 开发
uv run python -m app.main

# 测试
uv run pytest tests/

# 检查
uv run ruff check app/
```

---

## CONVENTIONS

- 虚拟文件系统：`/skill/`, `/workspace`
- **禁止** Windows 路径（D:, C:）
- Agent ID 必须唯一
- 配置持久化到 `data/agent_configs.json`
