from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .doctor import Check


def render_guide(config: dict[str, Any], checks: Iterable[Check]) -> str:
    status_rows = "\n".join(f"| {item.name} | {item.status} | {item.detail} |" for item in checks)
    providers = config.get("providers", {})
    enabled = [name for name, value in providers.items() if isinstance(value, dict) and value.get("enabled")]
    disabled = [name for name, value in providers.items() if isinstance(value, dict) and not value.get("enabled")]
    return f"""# 企业全生命周期助手首次使用指南

## 当前环境

- 已启用能力：{', '.join(enabled) or '暂无外部能力'}
- 未启用能力：{', '.join(disabled) or '无'}

## 配置状态

| 检查项 | 状态 | 说明 |
|---|---|---|
{status_rows}

## 推荐使用流程

1. 提供企业名称、所在地和企业材料。
2. 说“帮我判断这家企业能申报哪些政府项目”。
3. 选择目标项目后执行政策检索和可行性分析。
4. 补齐财务、知识产权和证明材料。
5. 前期分析完成后再撰写正式申报文本。
6. 提交前执行一致性检查和版本对比。
7. 任务完成后自动整理到用户工作区的项目归档目录。

## API与MCP

首次使用先运行 `project-assistant setup`，或执行 `skills/first-run-configuration/scripts/configure.py`。向导统一检测团队云端、企查查、专利数据、浏览器MCP、本地OCR和文档能力，并生成不含密钥的能力报告。其他Skill读取该报告，不再重复索要凭据。完整说明见 `docs/user-guide/api-mcp-configuration.md`。

## 常用说法

- 帮我查今年浙江省这个项目的管理办法和申报通知。
- 帮我判断这家企业能申报哪些项目。
- 对照官方政策做完整可行性分析。
- 检查财务指标和知识产权是否满足申报口径。
- 根据分析结果撰写申报材料。
- 提交前做一致性检查。

## 安全边界

- 模型API、MCP、企查查、OCR和企策顾问均由用户自行配置。
- 任何外部发送、云端上传和技能替换均需用户确认；本地归档不得覆盖原文件。
- 未配置外部能力时自动降级，不补造企业数据或政策事实。
- 本指南不包含密钥、密码、Cookie、Token或客户敏感原文。

## 排查

先运行 `project-assistant setup`，再运行 `project-assistant doctor` 查看统一能力状态。
"""


def write_guide(content: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return output
