# Agents Service API

基于FastAPI构建的Agent服务，支持MCP和Skills两种Agent类型，提供流式和非流式调用接口。

## 功能特性

- ✅ 支持MCP协议Agent（工具调用）
- ✅ 支持Skills Agent（文件系统操作）
- ✅ 流式响应（Server-Sent Events）
- ✅ 非流式响应
- ✅ 会话管理（thread_id）
- ✅ 统一API接口
- ✅ 自动生成API文档

## 项目结构

```
agents_service/
├── app/
│   ├── agents/              # 原始Agent实现
│   │   ├── mcp_agents.py
│   │   └── skills_agents.py
│   ├── api/
│   │   └── routes.py        # API路由定义
│   ├── models/
│   │   └── schemas.py       # 数据模型
│   ├── services/
│   │   └── agent_service.py # Agent服务封装
│   └── main.py              # FastAPI主应用
├── skills/                  # 技能目录
├── test_api.py             # API测试脚本
└── pyproject.toml          # 项目配置
```

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 启动服务

```bash
python -m app.main
```

服务将在 `http://localhost:8001` 启动

### 3. 访问API文档

- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## API接口说明

### 健康检查

```bash
GET /health
GET /api/v1/health
```

### 列出可用Agents

```bash
GET /api/v1/agents/list
```

### 非流式聊天（推荐用于简单场景）

```bash
POST /api/v1/chat/completion
Content-Type: application/json

{
    "message": "你好，请介绍一下你自己",
    "agent_type": "mcp",        # "mcp" 或 "skills"
    "thread_id": "my_thread",   # 会话ID，相同ID保持对话历史
    "stream": false             # 必须为false
}
```

### 流式聊天（推荐用于实时交互）

```bash
POST /api/v1/chat/completion/stream
Content-Type: application/json

{
    "message": "列出当前目录的文件",
    "agent_type": "skills",
    "thread_id": "my_thread",
    "stream": true              # 必须为true
}
```

### 统一聊天接口（自动识别流式/非流式）

```bash
POST /api/v1/chat/completion/unified
Content-Type: application/json

{
    "message": "你的消息",
    "agent_type": "mcp",
    "thread_id": "my_thread",
    "stream": true/false        # 根据此参数自动选择响应格式
}
```

## 使用示例

### Python客户端示例

```python
import requests

# 非流式调用
response = requests.post(
    "http://localhost:8001/api/v1/chat/completion",
    json={
        "message": "你好",
        "agent_type": "mcp",
        "thread_id": "test_thread",
        "stream": False
    }
)
print(response.json())

# 流式调用
response = requests.post(
    "http://localhost:8001/api/v1/chat/completion/stream",
    json={
        "message": "列出文件",
        "agent_type": "skills",
        "thread_id": "test_thread",
        "stream": True
    },
    stream=True
)

# 处理SSE流
for line in response.iter_lines():
    if line:
        line_str = line.decode('utf-8')
        if line_str.startswith('data: '):
            import json
            data = json.loads(line_str[6:])
            print(data['content'])
```

### JavaScript客户端示例

```javascript
// 非流式调用
fetch('http://localhost:8001/api/v1/chat/completion', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        message: '你好',
        agent_type: 'mcp',
        thread_id: 'test_thread',
        stream: false
    })
})
.then(response => response.json())
.then(data => console.log(data));

// 流式调用（使用EventSource）
const eventSource = new EventSource('http://localhost:8001/api/v1/chat/completion/stream', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        message: '列出文件',
        agent_type: 'skills',
        thread_id: 'test_thread',
        stream: true
    })
});

eventSource.addEventListener('message', function(event) {
    const data = JSON.parse(event.data);
    console.log('收到:', data.content);
});

eventSource.addEventListener('end', function(event) {
    console.log('流结束');
    eventSource.close();
});
```

## Agent类型说明

### MCP Agent
- **用途**: 支持外部工具调用
- **特点**: 通过MCP协议与外部服务通信
- **适用场景**: 需要调用外部API、工具的复杂任务

### Skills Agent
- **用途**: 文件系统操作
- **特点**: 提供虚拟文件系统访问能力
- **适用场景**: 文件读写、目录操作、技能执行

## 配置说明

### 环境变量

```bash
OPENAI_API_KEY=sk-1234  # 在代码中硬编码，实际使用时应从环境变量读取
```

### 服务配置

在 `app/main.py` 中修改：

```python
uvicorn.run(
    "app.main:app",
    host="0.0.0.0",      # 监听地址
    port=8001,           # 端口号
    reload=True,         # 开发模式热重载
    log_level="info"     # 日志级别
)
```

## 测试

运行内置测试脚本：

```bash
python test_api.py
```

这将测试：
1. 健康检查
2. Agent列表查询
3. 非流式调用
4. 流式调用

## 部署建议

### 生产环境部署

```bash
# 使用Gunicorn + Uvicorn workers
pip install gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8001
```

### Docker部署

```dockerfile
FROM python:3.11
WORKDIR /app
COPY . .
RUN pip install uv
RUN uv sync
CMD ["uv", "run", "python", "-m", "app.main"]
```

## 故障排除

### 常见问题

1. **依赖安装失败**
   ```bash
   uv sync --refresh  # 清除缓存重新安装
   ```

2. **端口被占用**
   ```bash
   # 修改app/main.py中的端口号
   port=8002  # 改为其他端口
   ```

3. **Agent初始化失败**
   - 检查MCP服务是否在 `http://127.0.0.1:8000/mcp` 运行
   - 确认LiteLLM服务在 `http://127.0.0.1:4000` 运行

## 许可证

MIT License