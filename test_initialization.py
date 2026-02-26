#!/usr/bin/env python3
"""
Agent服务初始化测试脚本
验证服务启动时的完整初始化流程
"""

import requests
import time
import json

BASE_URL = "http://localhost:8001"

def test_service_initialization():
    """测试服务初始化状态"""
    print("🔍 测试服务初始化状态...")
    
    # 测试根路径
    response = requests.get(f"{BASE_URL}/")
    assert response.status_code == 200
    print("✅ 根路径访问正常")
    
    # 测试健康检查
    response = requests.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    health_data = response.json()
    assert health_data["status"] == "healthy"
    assert health_data["initialized"] == True
    print("✅ 健康检查通过")
    print(f"   - MCP Agent状态: {health_data['components']['mcp_agent']}")
    print(f"   - Skills Agent状态: {health_data['components']['skills_agent']}")
    
    # 测试初始化状态
    response = requests.get(f"{BASE_URL}/initialization-status")
    assert response.status_code == 200
    init_data = response.json()
    assert init_data["initialized"] == True
    assert init_data["agents_ready"] == 2
    print("✅ 初始化状态检查通过")
    print(f"   - 已准备Agent数量: {init_data['agents_ready']}")
    print(f"   - MCP工具数量: {init_data['agent_statuses']['mcp']['tools_count']}")
    
def test_agent_functionality():
    """测试Agent功能"""
    print("\n🤖 测试Agent功能...")
    
    # 测试MCP Agent聊天
    chat_data = {
        "agent_type": "mcp",
        "message": "请告诉我今天的日期",
        "thread_id": "test_init_" + str(int(time.time()))
    }
    
    response = requests.post(
        f"{BASE_URL}/api/v1/chat/completion",
        json=chat_data
    )
    assert response.status_code == 200
    chat_result = response.json()
    print("✅ MCP Agent聊天功能正常")
    print(f"   - 响应长度: {chat_result['usage_stats']['response_length']} 字符")
    
    # 测试Agent状态查询
    response = requests.get(f"{BASE_URL}/api/v1/agents/status")
    assert response.status_code == 200
    agents_status = response.json()
    assert len(agents_status) == 2
    print("✅ Agent状态查询正常")
    
    # 测试会话列表
    response = requests.get(f"{BASE_URL}/api/v1/sessions")
    assert response.status_code == 200
    sessions = response.json()
    print(f"✅ 会话列表查询正常，当前有 {len(sessions)} 个会话")

def test_error_handling():
    """测试错误处理"""
    print("\n⚠️  测试错误处理...")
    
    # 测试无效Agent类型
    chat_data = {
        "agent_type": "invalid_agent",
        "message": "test",
        "thread_id": "test_error"
    }
    
    response = requests.post(
        f"{BASE_URL}/api/v1/chat/completion",
        json=chat_data
    )
    assert response.status_code == 422 or response.status_code == 500  # 应该返回错误
    print("✅ 无效Agent类型错误处理正常")
    
    # 测试不存在的会话
    response = requests.get(f"{BASE_URL}/api/v1/sessions/nonexistent")
    assert response.status_code == 404
    print("✅ 不存在会话的错误处理正常")

def main():
    """主测试函数"""
    print("🚀 开始Agent服务初始化测试\n")
    
    try:
        # 等待服务完全启动
        print("⏳ 等待服务启动...")
        time.sleep(2)
        
        # 执行各项测试
        test_service_initialization()
        test_agent_functionality()
        test_error_handling()
        
        print("\n🎉 所有测试通过！Agent服务初始化成功完成！")
        print("\n📊 测试总结:")
        print("   ✓ 服务启动时自动完成Agent初始化")
        print("   ✓ MCP Agent和Skills Agent均已就绪")
        print("   ✓ 健康检查和状态监控接口正常")
        print("   ✓ 核心功能接口工作正常")
        print("   ✓ 错误处理机制有效")
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        return False
    except Exception as e:
        print(f"\n💥 测试过程中发生错误: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)