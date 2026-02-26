"""测试技能列表和MCP功能列表接口"""
import requests
import json
from typing import Dict, Any


class SkillMCPAPITest:
    """技能和MCP API测试类"""
    
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
    
    def test_health_check(self) -> Dict[str, Any]:
        """测试健康检查"""
        print("=== 健康检查测试 ===")
        response = requests.get(f"{self.base_url}/api/v1/health")
        result = response.json()
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
        print()
        return result
    
    def test_list_skills(self) -> Dict[str, Any]:
        """测试技能列表接口"""
        print("=== 技能列表接口测试 ===")
        response = requests.get(f"{self.base_url}/api/v1/skills/list")
        result = response.json()
        print(f"状态码: {response.status_code}")
        print(f"技能总数: {result.get('total_count', 0)}")
        print("技能详情:")
        for skill in result.get('skills', []):
            print(f"  - 名称: {skill['name']}")
            print(f"    描述: {skill['description']}")
            print(f"    路径: {skill['path']}")
            if skill['features']:
                print(f"    特性: {', '.join(skill['features'])}")
            if skill['dependencies']:
                print(f"    依赖: {', '.join(skill['dependencies'])}")
            print()
        return result
    
    def test_list_mcp_tools(self) -> Dict[str, Any]:
        """测试MCP工具列表接口"""
        print("=== MCP工具列表接口测试 ===")
        response = requests.get(f"{self.base_url}/api/v1/mcp/tools")
        result = response.json()
        print(f"状态码: {response.status_code}")
        print(f"MCP工具总数: {result.get('total_count', 0)}")
        print(f"服务器状态: {result.get('server_status', 'unknown')}")
        print("工具详情:")
        for tool in result.get('tools', []):
            print(f"  - 工具名称: {tool['tool_name']}")
            print(f"    描述: {tool['description']}")
            print(f"    服务器URL: {tool['server_url']}")
            print(f"    功能数量: {len(tool['functions'])}")
            for func in tool['functions']:
                print(f"      * 功能: {func['name']} - {func['description']}")
            print()
        return result
    
    def run_all_tests(self):
        """运行所有测试"""
        print("开始测试技能列表和MCP功能列表接口...\n")
        
        try:
            # 测试健康检查
            self.test_health_check()
            
            # 测试技能列表
            self.test_list_skills()
            
            # 测试MCP工具列表
            self.test_list_mcp_tools()
            
            print("所有测试完成!")
            
        except requests.exceptions.ConnectionError:
            print("错误: 无法连接到服务，请确保服务已在端口8001上运行")
        except Exception as e:
            print(f"测试过程中出现错误: {e}")


if __name__ == "__main__":
    # 创建测试实例并运行测试
    tester = SkillMCPAPITest()
    tester.run_all_tests()