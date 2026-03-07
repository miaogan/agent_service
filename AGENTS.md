# DeepAgent Service - Project Knowledge Base

**Generated:** 2026-03-07
**Language:** Python 3.12+
**Framework:** FastAPI + LangChain + DeepAgents + LangGraph
**Size:** Medium (~2000 lines)

---

## OVERVIEW

FastAPI 微服务，用于 AI Agent 编排，支持 MCP 协议、技能系统、Agent 池化管理、Human-in-the-Loop、PostgreSQL 会话持久化。

**核心功能：**
- Agent 池化管理（TTL、轮次限制、后台清理）
- 配置持久化（JSON 存储）
- Human-in-the-Loop（敏感工具人工确认）
- 会话持久化（PostgreSQL checkpointer）
- 流式聊天（SSE）
- Web UI（开箱即用）

**技术栈：** FastAPI, Uvicorn, LangChain, DeepAgents, LangGraph, PostgreSQL, asyncpg

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
│   │   ├── checkpoint.py    # PostgreSQL checkpointer 管理
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
├── Dockerfile
├── docker-compose.yml
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
| **会话持久化** | `app/core/checkpoint.py` | PostgreSQL checkpointer |
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

### 概述
Human-in-the-Loop (HITL) 允许敏感工具在执行前暂停，等待人工确认后再继续。这是通过 LangGraph 的 interrupt 机制和 checkpointer 实现的。

### 核心要求
⚠️ **重要：HITL 必须满足以下条件**
1. **Checkpointer 必需** - 必须配置 `checkpointer`（默认使用 MemorySaver）
2. **相同的 thread_id** - 中断和恢复必须使用相同的 `thread_id`
3. **interrupt_on 配置** - 在 AgentConfig 中指定需要确认的工具

### 配置方式

#### 基础配置
```python
AgentConfig(
    agent_id="safe-agent",
    name="Safe Agent",
    model="glm-5",
    tools=["python_sandbox"],
    interrupt_on={
        "python_sandbox": True,  # 需要人工确认
    }
)
```

#### 高级配置
```python
interrupt_on={
    # 方式1：简单配置（允许 approve, edit, reject）
    "delete_file": True,
    
    # 方式2：详细配置（限制允许的决策）
    "write_file": {"allowed_decisions": ["approve", "reject"]},
    
    # 方式3：禁用中断
    "read_file": False,
}
```

#### 决策类型
- **approve** - 批准执行（使用原始参数）
- **edit** - 修改参数后执行
- **reject** - 拒绝执行（跳过工具调用）

### 完整流程

#### 1. 创建支持 HITL 的 Agent
```bash
curl -X POST http://localhost:8001/agents \
-H "Content-Type: application/json" \
-d '{
  "agent_id": "safe-agent",
  "name": "Safe Agent",
  "model": "glm-5",
  "tools": ["python_sandbox"],
  "interrupt_on": {
    "python_sandbox": true
  },
  "max_turns": 50
}'
```

#### 2. 发送聊天消息（触发中断）
```bash
curl -X POST http://localhost:8001/chat/safe-agent/stream \
-H "Content-Type: application/json" \
-d '{
  "message": "Use python_sandbox to calculate 2+2",
  "thread_id": "conversation1"
}'
```

#### 3. 接收中断事件（SSE）
```javascript
// SSE 流事件
data: {
  "type": "interrupt",
  "interrupts": [
    {
      "tool_name": "python_sandbox",
      "tool_call_id": "call_abc123",
      "args": {"code": "result = 2+2; print(result)"},
      "description": "Tool 'python_sandbox' execution requires approval",
      "allowed_decisions": ["approve", "edit", "reject"]
    }
  ]
}
data: [DONE]
```

#### 4. 用户决策并恢复

**批准执行：**
```bash
curl -X POST http://localhost:8001/chat/safe-agent/resume \
-H "Content-Type: application/json" \
-d '{
  "decision": "approve",
  "tool_call_id": "call_abc123",
  "thread_id": "conversation1"
}'
```

**拒绝执行：**
```bash
curl -X POST http://localhost:8001/chat/safe-agent/resume \
-H "Content-Type: application/json" \
-d '{
  "decision": "reject",
  "tool_call_id": "call_abc123",
  "thread_id": "conversation1"
}'
```

**编辑参数后执行：**
```bash
curl -X POST http://localhost:8001/chat/safe-agent/resume \
-H "Content-Type: application/json" \
-d '{
  "decision": "edit",
  "tool_call_id": "call_abc123",
  "edited_args": {"code": "result = 3+3; print(result)"},
  "thread_id": "conversation1"
}'
```

#### 5. 接收执行结果
```javascript
// SSE 流事件（批准后继续）
data: {"type": "tool_call", "tool": "python_sandbox", "args": {...}}
data: {"type": "delta", "content": "The result is 4"}
data: {"type": "done", "content": "The result is 4", "tools_used": [...]}
data: [DONE]
```

### 多工具中断

当 Agent 同时调用多个需要确认的工具时，所有中断会批量返回：

```javascript
data: {
  "type": "interrupt",
  "interrupts": [
    {
      "tool_name": "delete_file",
      "tool_call_id": "call_001",
      "args": {"path": "/tmp/file1.txt"}
    },
    {
      "tool_name": "send_email",
      "tool_call_id": "call_002",
      "args": {"to": "user@example.com", "subject": "Test"}
    }
  ]
}
```

**注意：** resume 时只需提供 `decision`，系统会自动处理所有中断。

### 最佳实践

#### 1. 根据风险等级配置
```python
interrupt_on = {
    # 高风险：完全控制
    "execute_command": {"allowed_decisions": ["approve", "edit", "reject"]},
    "delete_file": {"allowed_decisions": ["approve", "edit", "reject"]},
    
    # 中风险：批准或拒绝
    "write_file": {"allowed_decisions": ["approve", "reject"]},
    "send_email": {"allowed_decisions": ["approve", "reject"]},
    
    # 低风险：无需中断
    "read_file": False,
    "list_files": False,
}
```

#### 2. 始终使用相同的 thread_id
```python
# 错误：中断和恢复使用不同的 thread_id
config1 = {"thread_id": "conv-1"}  # 中断时
config2 = {"thread_id": "conv-2"}  # 恢复时 ❌

# 正确：使用相同的 thread_id
config = {"thread_id": "conv-1"}  # 中断和恢复都用 ✅
```

#### 3. 配置持久化会话（生产环境）
```bash
# PostgreSQL 配置（推荐生产环境）
DATABASE_URL=postgresql://user:password@host:5432/deepagent

# 内存模式（开发环境，服务重启会话丢失）
# 不配置 PostgreSQL 即使用内存模式
```

### 技术实现细节

#### Stream 模式
```python
# 使用双模式流式传输
stream_mode=["messages", "updates"]

# messages 模式：传输内容增量
# updates 模式：检测中断事件
```

#### 中断数据结构
```python
{
    "__interrupt__": [
        Interrupt(
            value={
                "action_requests": [
                    {
                        "name": "tool_name",
                        "args": {...},
                        "id": "call_xxx"
                    }
                ],
                "review_configs": [
                    {
                        "action_name": "tool_name",
                        "allowed_decisions": ["approve", "edit", "reject"]
                    }
                ]
            }
        )
    ]
}
```

#### Resume 命令格式
```python
from langgraph.types import Command

# 批准
Command(resume={"decisions": [{"type": "approve"}]})

# 拒绝
Command(resume={"decisions": [{"type": "reject"}]})

# 编辑
Command(resume={
    "decisions": [{
        "type": "edit",
        "edited_action": {
            "name": "tool_name",
            "args": {"new": "args"}
        }
    }]
})
```

### 常见问题

**Q: 为什么工具没有触发中断？**
A: 检查以下几点：
1. AgentConfig 中是否正确配置了 `interrupt_on`
2. 是否使用了 checkpointer（必需）
3. 是否使用了正确的 stream_mode（`["messages", "updates"]`）
4. 工具名称是否匹配

**Q: 如何处理多个中断？**
A: 系统会批量返回所有中断，resume 时只需提供一个 `decision`，系统会应用到所有中断。

**Q: 中断后会话会丢失吗？**
A: 不会。checkpointer 会保存会话状态。使用内存模式时，服务重启才会丢失；使用 PostgreSQL 时，会话会持久化到数据库。

**Q: 可以动态修改 interrupt_on 配置吗？**
A: 可以。更新 Agent 配置后，下次创建 Agent 实例时会使用新配置。已运行的 Agent 实例不受影响。

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
# API Keys
OPENAI_API_KEY=your-key
LITELLM_API_BASE=http://127.0.0.1:4000
DEFAULT_MODEL=glm-5

# MCP Server
MCP_SERVER_URL=http://127.0.0.1:8000/mcp
MCP_LOAD_FAIL_CONTINUE=true

# PostgreSQL (会话持久化)
DATABASE_URL=postgresql://user:password@host:5432/database
# 或单独配置：
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=deepagent
POSTGRES_PASSWORD=secret
POSTGRES_DB=deepagent
```

---

## SESSION PERSISTENCE

Agent 会话使用 PostgreSQL `langgraph-checkpoint-postgres` 存储。

### 自动建表
启动时自动创建：
- `checkpoints` - 检查点数据
- `checkpoint_blobs` - 二进制数据
- `checkpoint_writes` - 写入记录
- `checkpoint_channels` - 通道状态

### 配置方式
```python
# 方式1：完整 URL
DATABASE_URL=postgresql://user:pass@host:5432/db

# 方式2：单独配置
POSTGRES_HOST=localhost
POSTGRES_USER=deepagent
POSTGRES_PASSWORD=secret
```

### 降级策略
- PostgreSQL 未配置 → 使用内存 checkpointer
- 连接失败 → 自动降级 + 日志警告

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
