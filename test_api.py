import requests
import json
import time
from typing import Iterator


class AgentsAPIClient:
    """Agents API测试客户端"""
    
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        
    def health_check(self):
        """健康检查"""
        response = requests.get(f"{self.base_url}/health")
        return response.json()
        
    def list_agents(self):
        """列出可用的agents"""
        response = requests.get(f"{self.base_url}/api/v1/agents/list")
        return response.json()
        
    def chat_completion_sync(self, message: str, agent_type: str = "mcp", thread_id: str = "test_thread"):
        """同步（非流式）聊天"""
        payload = {
            "message": message,
            "agent_type": agent_type,
            "thread_id": thread_id,
            "stream": False
        }
        
        response = requests.post(
            f"{self.base_url}/api/v1/chat/completion",
            json=payload
        )
        return response.json()
        
    def chat_completion_stream(self, message: str, agent_type: str = "mcp", thread_id: str = "test_thread"):
        """流式聊天"""
        payload = {
            "message": message,
            "agent_type": agent_type,
            "thread_id": thread_id,
            "stream": True
        }
        
        response = requests.post(
            f"{self.base_url}/api/v1/chat/completion/stream",
            json=payload,
            stream=True
        )
        
        # 解析SSE流
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    data = line_str[6:]  # 移除 'data: ' 前缀
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        print(f"JSON解析错误: {data}")


def test_api():
    """测试API功能"""
    client = AgentsAPIClient()
    
    print("=== Agents API 测试 ===\n")
    
    # 1. 健康检查
    print("1. 健康检查:")
    try:
        health = client.health_check()
        print(f"   状态: {health}")
    except Exception as e:
        print(f"   错误: {e}")
        return
    
    print("\n" + "="*50 + "\n")
    
    # 2. 列出agents
    print("2. 可用Agents:")
    try:
        agents = client.list_agents()
        for agent in agents['agents']:
            print(f"   类型: {agent['type']}")
            print(f"   描述: {agent['description']}")
            print(f"   功能: {', '.join(agent['features'])}")
            print()
    except Exception as e:
        print(f"   错误: {e}")
        return
    
    print("="*50 + "\n")
    
    # 3. 测试非流式调用
    print("3. 非流式调用测试 (MCP Agent):")
    try:
        response = client.chat_completion_sync("你好，请介绍一下你自己")
        print(f"   响应: {response['message']}")
        print(f"   线程ID: {response['thread_id']}")
        print(f"   Agent类型: {response['agent_type']}")
    except Exception as e:
        print(f"   错误: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # 4. 测试流式调用
    print("4. 流式调用测试 (Skills Agent):")
    try:
        print("   流式响应:")
        for chunk in client.chat_completion_stream("列出当前目录的文件", "skills"):
            if chunk.get('chunk_type') == 'final':
                print(f"\n   [结束] 线程: {chunk['thread_id']}")
                break
            else:
                print(chunk['content'], end='', flush=True)
        print()  # 换行
    except Exception as e:
        print(f"   错误: {e}")


if __name__ == "__main__":
    test_api()