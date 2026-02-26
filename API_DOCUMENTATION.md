# Agents Service API 文档

## 基础信息
- **基础URL**: `http://localhost:8001`
- **API版本**: v1
- **文档格式**: JSON

## 新增接口

### 1. 获取技能列表
**GET** `/api/v1/skills/list`

获取系统中所有可用技能的详细信息。

#### 响应示例
```json
{
  "skills": [
    {
      "name": "arxiv-search",
      "description": "Search arXiv preprint repository for papers...",
      "path": "skills\\arxiv-search",
      "readme_path": "skills\\arxiv-search\\SKILL.md",
      "features": [
        "**Relevance sorting**: Results ordered by relevance to query",
        "**Fast retrieval**: Direct API access with no authentication required"
      ],
      "usage_examples": [],
      "dependencies": [
        "arXiv is particularly strong for:",
        "Computer science (cs.LG, cs.AI, cs.CV)"
      ]
    }
  ],
  "total_count": 2,
  "timestamp": "2026-02-26T23:09:23.294254"
}
```

#### 响应字段说明
- `skills`: 技能列表数组
  - `name`: 技能名称
  - `description`: 技能描述
  - `path`: 技能目录路径
  - `readme_path`: README文件路径
  - `features`: 技能特性列表
  - `usage_examples`: 使用示例
  - `dependencies`: 依赖包列表
- `total_count`: 技能总数
- `timestamp`: 响应时间戳

---

### 2. 获取MCP工具列表
**GET** `/api/v1/mcp/tools`

获取MCP服务器上所有可用工具的详细信息。

#### 响应示例
```json
{
  "tools": [
    {
      "tool_name": "fetch_url",
      "description": "从URL获取内容",
      "functions": [
        {
          "name": "fetch_url",
          "description": "获取指定URL的内容",
          "tool_type": "function",
          "parameters": {
            "type": "object",
            "properties": {
              "url": {
                "type": "string",
                "description": "要获取的URL"
              }
            },
            "required": ["url"]
          },
          "required_parameters": ["url"]
        }
      ],
      "server_url": "http://127.0.0.1:8000/mcp"
    }
  ],
  "total_count": 1,
  "server_status": "connected",
  "timestamp": "2026-02-26T23:10:00.675250"
}
```

#### 响应字段说明
- `tools`: MCP工具列表数组
  - `tool_name`: 工具名称
  - `description`: 工具描述
  - `functions`: 包含的功能列表
    - `name`: 功能名称
    - `description`: 功能描述
    - `tool_type`: 工具类型
    - `parameters`: 参数信息
    - `required_parameters`: 必需参数列表
  - `server_url`: 服务器URL
- `total_count`: 工具总数
- `server_status`: 服务器状态 (connected/disconnected)
- `timestamp`: 响应时间戳

---

## 现有接口

### 3. 健康检查
**GET** `/api/v1/health`

检查服务运行状态。

#### 响应示例
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "agents_available": ["mcp", "skills"]
}
```

---

### 4. 列出可用Agents
**GET** `/api/v1/agents/list`

列出所有可用的Agent类型及其基本信息。

#### 响应示例
```json
{
  "agents": [
    {
      "type": "mcp",
      "description": "MCP协议Agent，支持外部工具调用",
      "features": ["工具调用", "HTTP传输"]
    },
    {
      "type": "skills",
      "description": "Skills Agent，支持文件系统操作",
      "features": ["文件读写", "虚拟文件系统", "技能中间件"]
    }
  ]
}
```

---

### 5. 聊天完成 (非流式)
**POST** `/api/v1/chat/completion`

进行非流式的聊天对话。

#### 请求体
```json
{
  "message": "你好",
  "agent_type": "mcp",
  "thread_id": "my_thread",
  "stream": false
}
```

#### 响应示例
```json
{
  "message": "你好！有什么我可以帮助你的吗？",
  "thread_id": "my_thread",
  "agent_type": "mcp",
  "metadata": {
    "stream": false
  }
}
```

---

### 6. 聊天完成 (流式)
**POST** `/api/v1/chat/completion/stream`

进行流式的聊天对话，返回SSE (Server-Sent Events) 流。

#### 请求体
```json
{
  "message": "列出当前目录的文件",
  "agent_type": "skills",
  "thread_id": "my_thread",
  "stream": true
}
```

#### 响应格式
SSE流格式，每个事件包含：
```json
{
  "event": "message",
  "data": "{\"content\":\"当前目录包含以下文件：\",\"chunk_type\":\"text\",\"thread_id\":\"my_thread\",\"agent_type\":\"skills\"}"
}
```

---

### 7. 统一聊天接口
**POST** `/api/v1/chat/completion/unified`

根据stream参数自动选择响应格式的统一接口。

#### 请求体
```json
{
  "message": "你的消息",
  "agent_type": "mcp",
  "thread_id": "my_thread",
  "stream": true/false
}
```

---

## 错误响应格式

所有接口在出错时都会返回标准的错误格式：

```json
{
  "detail": "错误描述信息"
}
```

常见HTTP状态码：
- `200`: 成功
- `400`: 请求参数错误
- `404`: 资源未找到
- `500`: 服务器内部错误

---

## 测试脚本

项目提供了测试脚本 `test_skill_mcp_api.py` 来验证所有接口功能：

```bash
python test_skill_mcp_api.py
```

该脚本会依次测试：
1. 健康检查接口
2. 技能列表接口
3. MCP工具列表接口

---

## 使用示例

### Python客户端示例

```python
import requests

# 获取技能列表
response = requests.get("http://localhost:8001/api/v1/skills/list")
skills_data = response.json()
print(f"发现 {skills_data['total_count']} 个技能")

# 获取MCP工具列表
response = requests.get("http://localhost:8001/api/v1/mcp/tools")
mcp_data = response.json()
print(f"MCP服务器状态: {mcp_data['server_status']}")

# 非流式聊天
response = requests.post(
    "http://localhost:8001/api/v1/chat/completion",
    json={
        "message": "你好",
        "agent_type": "mcp",
        "thread_id": "test_thread",
        "stream": False
    }
)
print(response.json()['message'])
```

### cURL示例

```bash
# 获取技能列表
curl -X GET "http://localhost:8001/api/v1/skills/list" -H "accept: application/json"

# 获取MCP工具列表
curl -X GET "http://localhost:8001/api/v1/mcp/tools" -H "accept: application/json"

# 健康检查
curl -X GET "http://localhost:8001/api/v1/health" -H "accept: application/json"
```

---

## 注意事项

1. **技能列表接口**会自动扫描`skills`目录下的所有技能
2. **MCP工具列表接口**需要MCP服务器正常运行才能获取完整信息
3. 所有接口都支持跨域请求
4. 时间戳采用ISO 8601格式
5. 路径分隔符在Windows系统下显示为反斜杠`\`