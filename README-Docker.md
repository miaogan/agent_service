# 部署指南

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/miaogan/agent_service.git
cd agent_service
git checkout open_claw
```

### 2. 配置环境变量

```bash
cp .env.production .env
# 编辑 .env 设置 API Keys 和密码
```

### 3. 启动服务

```bash
# 启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f agent-service

# 查看服务状态
docker compose ps
```

### 4. 访问服务

- **Web UI**: http://localhost:8001/
- **API 文档**: http://localhost:8001/docs
- **LiteLLM**: http://localhost:4000/

## 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| agent-service | 8001 | 主 API 服务 |
| mcp-server | 8000 | MCP 工具服务 |
| litellm | 4000 | LLM 代理服务 |
| postgres | 5432 | PostgreSQL 数据库（会话持久化）|
| redis | 6379 | Redis 缓存 |

> **PostgreSQL 用途**：存储 Agent 会话状态，支持对话历史持久化和中断恢复。

## 生产部署

### 环境变量

关键配置项：

```bash
# 数据库密码（必须修改）
POSTGRES_PASSWORD=your-secure-password

# LiteLLM 密钥（必须修改）
LITELLM_MASTER_KEY=your-litellm-key

# API Keys
OPENAI_API_KEY=your-openai-key
GLM_API_KEY=your-glm-key
```

### 健康检查

```bash
# Agent Service
curl http://localhost:8001/health

# PostgreSQL
docker compose exec postgres pg_isready

# Redis
docker compose exec redis redis-cli ping
```

### 数据备份

```bash
# 备份 PostgreSQL
docker compose exec postgres pg_dump -U deepagent deepagent > backup.sql

# 恢复
docker compose exec -T postgres psql -U deepagent deepagent < backup.sql
```

### 日志管理

```bash
# 查看所有日志
docker compose logs

# 查看特定服务日志
docker compose logs agent-service

# 实时日志
docker compose logs -f --tail=100 agent-service
```

## 仅启动必要服务

```bash
# 最小化部署（无 LiteLLM）
docker compose up -d postgres redis mcp-server agent-service

# 仅数据库
docker compose up -d postgres
```

## 更新部署

```bash
# 拉取最新代码
git pull

# 重新构建并启动
docker compose up -d --build agent-service
```

## 故障排查

### 容器无法启动

```bash
# 查看容器日志
docker compose logs agent-service

# 检查容器状态
docker compose ps
```

### 数据库连接失败

```bash
# 检查数据库是否就绪
docker compose exec postgres pg_isready

# 检查网络
docker compose exec agent-service ping postgres
```

### 端口冲突

修改 `.env` 中的端口配置：

```bash
APP_PORT=8002
POSTGRES_PORT=5433
REDIS_PORT=6380
```
