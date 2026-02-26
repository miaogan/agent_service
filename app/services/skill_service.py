"""技能服务模块"""
import os
from pathlib import Path
from typing import List, Dict, Any
import yaml
from datetime import datetime

from app.models.schemas import SkillInfo, SkillListResponse


class SkillService:
    """技能服务类"""
    
    def __init__(self):
        self.skills_dir = Path("skills")
        self._ensure_skills_directory()
    
    def _ensure_skills_directory(self):
        """确保skills目录存在"""
        if not self.skills_dir.exists():
            self.skills_dir.mkdir(parents=True, exist_ok=True)
    
    def _parse_skill_metadata(self, skill_path: Path) -> Dict[str, Any]:
        """解析技能的元数据文件"""
        metadata = {
            "name": skill_path.name,
            "description": "暂无描述",
            "features": [],
            "usage_examples": [],
            "dependencies": []
        }
        
        # 查找SKILL.md文件
        skill_md_path = skill_path / "SKILL.md"
        if skill_md_path.exists():
            try:
                content = skill_md_path.read_text(encoding='utf-8')
                
                # 解析YAML头部
                if content.startswith("---"):
                    lines = content.split('\n')
                    yaml_end = 0
                    for i, line in enumerate(lines[1:], 1):
                        if line.strip() == "---":
                            yaml_end = i
                            break
                    
                    if yaml_end > 0:
                        yaml_content = '\n'.join(lines[1:yaml_end])
                        try:
                            yaml_data = yaml.safe_load(yaml_content)
                            if isinstance(yaml_data, dict):
                                metadata.update({
                                    "name": yaml_data.get("name", skill_path.name),
                                    "description": yaml_data.get("description", "暂无描述")
                                })
                        except yaml.YAMLError:
                            pass
                
                # 提取特性、示例和依赖信息
                lines = content.split('\n')
                current_section = None
                
                for line in lines:
                    line = line.strip()
                    if line.startswith("## Features"):
                        current_section = "features"
                    elif line.startswith("## Examples") or line.startswith("## Usage"):
                        current_section = "examples"
                    elif line.startswith("## Dependencies"):
                        current_section = "dependencies"
                    elif line.startswith("- ") and current_section:
                        item = line[2:].strip()
                        if current_section == "features":
                            metadata["features"].append(item)
                        elif current_section == "examples":
                            metadata["usage_examples"].append(item)
                        elif current_section == "dependencies":
                            metadata["dependencies"].append(item)
                            
            except Exception as e:
                print(f"解析技能元数据时出错 {skill_path}: {e}")
        
        return metadata
    
    def get_skill_list(self) -> SkillListResponse:
        """获取技能列表"""
        skills = []
        
        if self.skills_dir.exists():
            for skill_dir in self.skills_dir.iterdir():
                if skill_dir.is_dir():
                    metadata = self._parse_skill_metadata(skill_dir)
                    
                    # 处理路径，避免相对路径问题
                    try:
                        skill_path = str(skill_dir.relative_to(Path.cwd()))
                    except ValueError:
                        # 如果不在子路径中，使用绝对路径
                        skill_path = str(skill_dir)
                    
                    try:
                        readme_path = str((skill_dir / "SKILL.md").relative_to(Path.cwd())) if (skill_dir / "SKILL.md").exists() else None
                    except ValueError:
                        readme_path = str(skill_dir / "SKILL.md") if (skill_dir / "SKILL.md").exists() else None
                    
                    skill_info = SkillInfo(
                        name=metadata["name"],
                        description=metadata["description"],
                        path=skill_path,
                        readme_path=readme_path,
                        features=metadata["features"],
                        usage_examples=metadata["usage_examples"],
                        dependencies=metadata["dependencies"]
                    )
                    skills.append(skill_info)
        
        return SkillListResponse(
            skills=skills,
            total_count=len(skills),
            timestamp=datetime.now().isoformat()
        )


# 全局技能服务实例
_skill_service_instance = None


def get_skill_service() -> SkillService:
    """获取技能服务实例"""
    global _skill_service_instance
    if _skill_service_instance is None:
        _skill_service_instance = SkillService()
    return _skill_service_instance