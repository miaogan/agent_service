from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from contextlib import asynccontextmanager

from app.api.routes import router
from app.services.agent_service import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    print("正在初始化Agent服务...")
    try:
        from app.services.agent_service import get_agent_service
        agent_service = await get_agent_service()
        print("✅ Agent服务初始化完成!")
        print(f"- MCP Agent状态: {agent_service.agent_statuses['mcp']['status']}")
        print(f"- Skills Agent状态: {agent_service.agent_statuses['skills']['status']}")
        if agent_service.agent_statuses['mcp'].get('tools_count'):
            print(f"- MCP工具数量: {agent_service.agent_statuses['mcp']['tools_count']}")
    except Exception as e:
        print(f"❌ Agent服务初始化失败: {e}")
        # 即使初始化失败也继续启动，让服务可以处理错误情况
        pass
    
    yield
    
    # 关闭时清理
    print("正在关闭服务...")


# 创建FastAPI应用
app = FastAPI(
    title="Agents Service API",
    description="基于FastAPI的Agent服务，支持MCP和Skills两种Agent类型",
    version="1.0.0",
    lifespan=lifespan
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境中应该限制具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 包含路由
app.include_router(router)


@app.get("/")
async def root():
    """根路径欢迎信息"""
    return {
        "message": "欢迎使用 Agents Service API",
        "docs": "/docs",
        "redoc": "/redoc",
        "api_version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """详细的健康检查"""
    try:
        from app.services.agent_service import get_agent_service
        agent_service = await get_agent_service()
        
        # 检查各组件状态
        mcp_status = agent_service.agent_statuses["mcp"]["status"]
        skills_status = agent_service.agent_statuses["skills"]["status"]
        
        overall_status = "healthy" if (
            mcp_status == "initialized" and 
            skills_status == "initialized"
        ) else "degraded"
        
        return {
            "status": overall_status,
            "service": "agents-service",
            "components": {
                "mcp_agent": mcp_status,
                "skills_agent": skills_status
            },
            "initialized": agent_service._initialized,
            "initialization_error": agent_service._initialization_error
        }
    except Exception as e:
        return {
            "status": "unhealthy", 
            "service": "agents-service",
            "error": str(e)
        }

@app.get("/initialization-status")
async def initialization_status():
    """获取初始化状态详情"""
    try:
        from app.services.agent_service import get_agent_service
        agent_service = await get_agent_service()
        
        return {
            "initialized": agent_service._initialized,
            "initialization_error": agent_service._initialization_error,
            "agent_statuses": agent_service.agent_statuses,
            "agents_ready": len([status for status in agent_service.agent_statuses.values() 
                                if status["status"] == "initialized"])
        }
    except Exception as e:
        return {
            "initialized": False,
            "initialization_error": str(e),
            "agent_statuses": {},
            "agents_ready": 0
        }


if __name__ == "__main__":
    # 运行开发服务器
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,  # 开发模式下启用热重载
        log_level="info"
    )