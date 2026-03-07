# DeepAgent Service

基于 FastAPI 构建的 Agent 服务，支持 MCP 协议、Skills 技能系统、Agent 池化管理，以及 Human-in-the-Loop 人工干预。

## 功能特性

- ✅ **Agent 池化管理** - 创建、复用、TTL 过期、轮次限制
- ✅ **MCP 协议支持** - 动态加载 MCP 工具
- ✅ **Skills 技能系统** - 文件系统操作与技能执行
- ✅ **Human-in-the-Loop** - 敏感工具执行需人工确认
- ✅ **流式响应** - SSE 实时输出
- ✅ **Web UI** - 开箱即用的聊天界面
- ✅ **配置持久化** - Agent 配置自动保存

## 项目结构

```
agent_service/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── api/
│   │   └── routes.py        # API 路由
│   ├── core/
│   │   ├── config.py        # 配置管理
│   │   ├── tools.py         # python_sandbox 工具
│   │   └── storage.py       # JSON 持久化
│   ├── models/
│   │   └── schemas.py       # Pydantic 模型
│   ├── services/
│   │   ├── agent_service.py # Agent 工厂
│   │   └── agent_pool.py    # Agent 池管理
│   └── static/
│       └── index.html       # Web UI
├── skill/                   # 技能模块目录
├── tests/                   # 测试文件
├── data/                    # 运行时数据
└── pyproject.toml
```

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 设置 OPENAI_API_KEY
```

### 3. 启动服务

```bash
uv run python -m app.main
```

服务启动后：
- **Web UI**: http://localhost:8001/
- **API 文档**: http://localhost:8001/docs

## API 接口

### 聊天

```bash
# 流式聊天
POST /chat/{agent_id}/stream
{
    "message": "你好",
    "thread_id": "conversation1",
    "model": "glm-5"
}

# 恢复中断（Human-in-the-Loop）
POST /chat/{agent_id}/resume
{
    "decision": "approve",       # "approve" | "reject" | "edit"
    "tool_call_id": "call_xxx",
    "thread_id": "conversation1"
}
```

### Agent 配置管理

```bash
# 创建 Agent
POST /agents
{
    "agent_id": "my-agent",
    "name": "My Agent",
    "model": "glm-5",
    "interrupt_on": {"execute": true}   # 需人工确认的工具
}

# 列出所有 Agent
GET /agents

# 获取/更新/删除 Agent
GET /agents/{agent_id}
PUT /agents/{agent_id}
DELETE /agents/{agent_id}
```

### 监控

```bash
GET /health           # 健康检查
GET /models           # 可用模型列表
GET /pool/stats       # Agent 池状态
```

## Human-in-the-Loop

配置 Agent 时，通过 `interrupt_on` 指定需要人工确认的工具：

```json
{
    "agent_id": "safe-agent",
    "name": "Safe Agent",
    "interrupt_on": {
        "execute": true,      // Shell 命令需确认
        "write_file": true    // 写文件需确认
    }
}
```

当 Agent 执行这些工具时，会中断并等待用户决策：
- **approve** - 批准执行
- **reject** - 拒绝执行
- **edit** - 修改参数后执行

## SSE 事件格式

```javascript
// 内容增量
data: {"type": "delta", "content": "Hello"}

// 工具调用
data: {"type": "tool_call", "tool": "execute", "args": {...}, "tool_call_id": "xxx"}

// 等待确认
data: {"type": "interrupt", "interrupts": [{"tool_name": "execute", ...}]}

// 完成
data: {"type": "done", "content": "...", "tools_used": [...]}
```

## 配置说明

```bash
# .env
OPENAI_API_KEY=your-key
LITELLM_API_BASE=http://127.0.0.1:4000
MCP_SERVER_URL=http://127.0.0.1:8000/mcp
DEFAULT_MODEL=glm-5
```

## 开发

```bash
# 运行测试
uv run pytest tests/

# 代码检查
uv run ruff check app/
uv run ruff format app/
```

## 部署

### Docker

```dockerfile
FROM python:3.12
WORKDIR /app
COPY . .
RUN pip install uv && uv sync
CMD ["uv", "run", "python", "-m", "app.main"]
```

### 生产环境

```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8001
```

## 许可证

MIT License
