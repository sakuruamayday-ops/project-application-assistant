from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require_text(path: Path, phrases: tuple[str, ...]) -> None:
    content = path.read_text(encoding="utf-8")
    missing = [phrase for phrase in phrases if phrase not in content]
    if missing:
        raise SystemExit(f"{path.relative_to(ROOT)} 缺少门禁语句：{missing}")


def main() -> None:
    manifest = json.loads(
        (ROOT / "skills/suite-manifest.json").read_text(encoding="utf-8")
    )
    services = manifest.get("external_services", [])
    if services.count("jiaotang-kb") != 1:
        raise SystemExit("团队知识库必须且只能声明一个 jiaotang-kb 外部服务")
    if any(
        "three_first" in str(service) or "三首" in str(service)
        for service in services
    ):
        raise SystemExit("三首分析不得声明为新的外部MCP服务")

    require_text(
        ROOT / "skills/first-run-configuration/references/first-startup-protocol.md",
        (
            "只允许配置一个名为 `jiaotang-kb` 的 MCP",
            "不得新增知识库 MCP",
        ),
    )
    require_text(
        ROOT / "skills/local-knowledge-retrieval/SKILL.md",
        (
            "MCP `three_first_analysis`",
            "不让用户新增第二个 MCP",
        ),
    )
    require_text(
        ROOT / "skills/project-task-router/SKILL.md",
        (
            "`three_first_analysis` 统一入口",
            "不得要求用户新增 MCP",
        ),
    )
    print(
        json.dumps(
            {
                "status": "pass",
                "knowledge_mcp": "jiaotang-kb",
                "three_first_entry": "three_first_analysis",
                "additional_mcp_required": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
