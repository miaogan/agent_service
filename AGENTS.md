# AGENTS SERVICE - PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-07
**Language:** Python 3.13+
**Framework:** FastAPI + LangChain
**Size:** Medium (modular architecture, ~1000 lines)

---

## OVERVIEW

FastAPI microservice for AI agent orchestration with MCP (Model Context Protocol) support. Features:
- **Agent Pool Management**: Create, configure, and reuse agents with TTL and turn limits
- **Persistent Configuration**: Agent configs saved to JSON, loaded on startup
- **Streaming Chat**: SSE-based chat with tool calling capabilities
- **Secure Sandbox**: Code execution via OpenSandbox with persistent output

**Core Stack:** FastAPI, Uvicorn, LangChain, Pydantic, OpenSandbox, LiteLLM

---

## STRUCTURE

```
agents_service/
├── app/
│   ├── main.py              # ✅ FastAPI entry point
│   ├── api/
│   │   └── routes.py        # API endpoints (chat, agents CRUD)
│   ├── core/
│   │   ├── config.py        # Settings & constants
│   │   ├── tools.py         # python_sandbox tool
│   │   └── storage.py       # JSON persistence for agent configs
│   ├── models/
│   │   └── schemas.py       # Pydantic models (AgentConfig, ChatRequest)
│   ├── services/
│   │   ├── agent_service.py # Agent factory
│   │   └── agent_pool.py    # Agent pool with TTL & turn limits
│   └── __init__.py
├── tests/                   # Test files
│   ├── test_agent_pool.py
│   ├── test_storage.py
│   └── test_api.py
├── skill/                   # Skill modules (self-documenting)
│   ├── arxiv-search/
│   └── langgraph-docs/
├── data/                    # Runtime data (auto-created)
│   └── agent_configs.json   # Persisted agent configurations
├── workspace/               # Sandbox output files
├── pyproject.toml
└── .env
```

---

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| **Main entry** | `app/main.py` | `python -m app.main` |
| **API routes** | `app/api/routes.py` | Chat + Agent CRUD |
| **Agent pool** | `app/services/agent_pool.py` | TTL, turn limits, cleanup |
| **Agent config** | `app/models/schemas.py` | `AgentConfig`, `ChatRequest` |
| **Settings** | `app/core/config.py` | `Settings` class |
| **Storage** | `app/core/storage.py` | JSON persistence |

---

## API ENDPOINTS

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat/stream` | Streaming chat (default agent) |
| POST | `/chat/{agent_id}/stream` | Chat with specific pooled agent |

### Agent Configuration
| Method | Path | Description |
|--------|------|-------------|
| POST | `/agents` | Create agent configuration |
| GET | `/agents` | List all configurations |
| GET | `/agents/{agent_id}` | Get specific configuration |
| PUT | `/agents/{agent_id}` | Update configuration |
| DELETE | `/agents/{agent_id}` | Delete configuration |

### Monitoring
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/models` | List available models |
| GET | `/pool/stats` | Agent pool statistics |

---

## AGENT POOL FEATURES

### Default Agent
服务启动时自动创建 ID 为 `default` 的默认 Agent，具有以下配置：
- **Skills**: 加载 `/skill` 目录下的所有技能
- **MCP Server**: `http://127.0.0.1:8000/mcp` (可通过环境变量修改)
- **Tools**: `python_sandbox` 安全代码执行工具
- **Max Turns**: 100 轮
- **TTL**: 60 分钟

### Lifecycle Management
- **Lazy initialization**: Agents created on first request
- **TTL expiration**: Removed after 30 minutes idle (configurable)
- **Turn limits**: Max 50 turns per agent (configurable)
- **Background cleanup**: Runs every 60 seconds

### Configuration Example
```json
{
  "agent_id": "research-assistant",
  "name": "Research Assistant",
  "model": "glm-5",
  "system_prompt": "You are a research assistant...",
  "tools": ["python_sandbox"],
  "max_turns": 50,
  "ttl_minutes": 30
}
```

---

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `AgentPool` | Class | `services/agent_pool.py` | Pool manager with TTL |
| `AgentConfig` | Model | `models/schemas.py` | Agent configuration schema |
| `AgentConfigStorage` | Class | `core/storage.py` | JSON persistence |
| `create_agent` | Async Fn | `services/agent_service.py` | DeepAgent factory |
| `python_sandbox` | Tool | `core/tools.py` | Secure code execution |

---

## CONVENTIONS

### Virtual Filesystem Paths
- Skills: `/skill/arxiv-search/SKILL.md`
- Workspace: `/workspace` (container mount)
- **NEVER** use Windows paths (D:, C:) in code

### Agent Configuration
- Agent IDs must be unique
- Configs persist to `data/agent_configs.json`
- Pool reloads configs on startup

---

## ANTI-PATTERNS (AVOID)

### Sandbox Execution
- **NEVER** use: `sys.exit`, `os.system`, `subprocess`, `exec(`, `__import__`, `shutil.rmtree`
- **NEVER** delete `/workspace` mount path
- **ALWAYS** save persistent files to `/workspace`

### Agent Pool
- **NEVER** skip `agent_pool.start()` in lifespan
- **NEVER** create agents directly - use pool
- **ALWAYS** call `agent_pool.stop()` on shutdown

---

## COMMANDS

```bash
# Install
uv sync

# Development
python -m app.main

# Run tests
uv run pytest tests/

# Linting
uv run ruff check app/
uv run ruff format app/
```

---

## ENVIRONMENT VARIABLES

```bash
OPENAI_API_KEY=your-key
LITELLM_API_BASE=http://127.0.0.1:4000
MCP_SERVER_URL=http://127.0.0.1:8000/mcp
MCP_LOAD_FAIL_CONTINUE=true
SANDBOX_OUTPUT_HOST_DIR=/path
```

---

## QUICK START

1. `uv sync`
2. Copy `.env.example` → `.env`, set `OPENAI_API_KEY`
3. `python -m app.main`
4. Open http://localhost:8001/docs

### Create an Agent
```bash
curl -X POST http://localhost:8001/agents \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my-agent", "name": "My Agent", "model": "glm-5"}'
```

### Chat with Agent
```bash
curl -X POST http://localhost:8001/chat/my-agent/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```
