#!/usr/bin/env python3
"""One-command grounded-citations registry, fixture, impact and host gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "grounded-citations"
REAL = FIXTURE_ROOT / "real"


def first_existing(env_name: str, patterns: list[str], fallback: str | None = None) -> Path:
    explicit = os.environ.get(env_name, "").strip()
    if explicit and Path(explicit).exists():
        return Path(explicit).resolve()
    for pattern in patterns:
        matches = sorted(Path.home().glob(pattern), reverse=True)
        if matches:
            return matches[0].resolve()
    if fallback:
        located = shutil.which(fallback)
        if located:
            return Path(located).resolve()
    raise RuntimeError(f"cannot locate runtime for {env_name}")


def runtime_paths() -> dict[str, Path]:
    paths = {
        "python": first_existing(
            "GROUNDED_FIXTURE_PYTHON",
            [".cache/codex-runtimes/*/dependencies/python/bin/python3"],
            "python3",
        ),
        "node": first_existing(
            "GROUNDED_FIXTURE_NODE",
            [".cache/codex-runtimes/*/dependencies/node/bin/node"],
            "node",
        ),
        "artifact": first_existing(
            "GROUNDED_ARTIFACT_TOOL_MODULE",
            [".cache/codex-runtimes/*/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs"],
        ),
        "render_docx": first_existing(
            "GROUNDED_RENDER_DOCX",
            [".codex/plugins/cache/openai-primary-runtime/documents/*/skills/documents/render_docx.py"],
        ),
        "soffice_bin": first_existing(
            "GROUNDED_SOFFICE_BIN",
            [".cache/codex-runtimes/*/dependencies/bin/override/soffice"],
            "soffice",
        ),
        "go": first_existing(
            "JIAOTANG_GO",
            [],
            "go",
        ),
    }
    pytest_candidates = [
        os.environ.get("GROUNDED_PYTEST_PYTHON", "").strip(),
        shutil.which("python3") or "",
        sys.executable,
        str(paths["python"]),
    ]
    for candidate in dict.fromkeys(item for item in pytest_candidates if item):
        probe = subprocess.run(
            [candidate, "-c", "import pytest"],
            text=True,
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            paths["pytest_python"] = Path(candidate).resolve()
            break
    else:
        raise RuntimeError("cannot locate a Python runtime with pytest")
    return paths


def run_step(name: str, command: list[str], *, env: dict[str, str], required: bool = True) -> dict[str, object]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    return {
        "name": name,
        "status": "pass" if result.returncode == 0 else ("fail" if required else "degraded"),
        "required": required,
        "returncode": result.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "command": [Path(item).name if index == 0 else item for index, item in enumerate(command)],
        "stdout_tail": stdout[-3000:],
        "stderr_tail": stderr[-2000:],
    }


def host_adapter_receipt(python: Path, env: dict[str, str]) -> dict[str, object]:
    fixture = ROOT / "skills" / "evidence-ledger" / "examples" / "normal-grounded-report.json"
    outputs: dict[str, bytes] = {}
    details: dict[str, object] = {}
    for host in ("codex", "workbuddy"):
        adapter = ROOT / "skills" / "_runtime" / "grounded-citations" / f"{host}_adapter.py"
        result = subprocess.run(
            [str(python), str(adapter), "render-profile", str(fixture), "--profile", "analysis-report", "--artifact", "pdf"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            check=False,
        )
        outputs[host] = result.stdout
        details[host] = {
            "status": "pass" if result.returncode == 0 else "fail",
            "returncode": result.returncode,
            "sha256": hashlib.sha256(result.stdout).hexdigest(),
            "bytes": len(result.stdout),
            "stderr_tail": result.stderr.decode("utf-8", errors="replace")[-1000:],
        }
    identical = outputs.get("codex") == outputs.get("workbuddy") and bool(outputs.get("codex"))
    return {"status": "pass" if identical and all(item["status"] == "pass" for item in details.values()) else "fail", "identical_output": identical, "hosts": details}


def parse_json_tail(text: str) -> dict[str, object] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def write_receipt(output_dir: Path, receipt: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "product-configuration-acceptance.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Grounded Citations 产品配置验收回执",
        "",
        f"- 批次：`{receipt['run_id']}`",
        f"- 总状态：`{receipt['status']}`",
        f"- 分支：`{receipt['git']['branch']}`",
        f"- 提交：`{receipt['git']['commit']}`",
        f"- 稳定通道：Windows `{receipt['product_baseline']['channels']['workbuddy_windows_stable']}` / macOS `{receipt['product_baseline']['channels']['workbuddy_macos_stable']}`",
        f"- 隔离候选：`{receipt['product_baseline']['channels']['candidate']}`",
        f"- Skills 契约：`{receipt['product_baseline']['skills_contract']}`",
        f"- 双适配器输出一致：`{receipt['host_adapters']['identical_output']}`",
        "",
        "## 执行步骤",
        "",
        "| 步骤 | 状态 | 秒 |",
        "|---|---:|---:|",
    ]
    for item in receipt["steps"]:
        lines.append(f"| {item['name']} | {item['status']} | {item['duration_seconds']} |")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 本回执是候选分支技术验收，不是正式发布证明。",
            "- Bash 权限策略和外部 MCP 均不属于本产品配置门禁。",
            "- 标准正文不含报告式来源章节；来源说明为独立文件。",
            "- DOCX/PDF 结构往返使用真实文件；当前自动夹具使用拉丁正文验证渲染健康。缺少 Word 或中文字体的宿主只能记录待设备验收，不能把文本提取成功写成中文视觉通过。",
            "",
        ]
    )
    (output_dir / "product-configuration-acceptance.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--release-manager-root",
        type=Path,
        default=Path.home() / ".codex" / "skills" / "skill-release-manager",
        help="发布管理器源码或候选根目录；默认检查当前已安装版本",
    )
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (args.output_dir or ROOT / ".project-assistant" / "grounded-citations" / run_id).resolve()
    paths = runtime_paths()
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["ARTIFACT_TOOL_MODULE"] = paths["artifact"].as_uri()
    env["PATH"] = str(paths["soffice_bin"].parent) + os.pathsep + str(paths["node"].parent) + os.pathsep + env.get("PATH", "")

    steps: list[dict[str, object]] = []
    steps.append(run_step("registry-and-call-graph", [str(paths["python"]), "scripts/generate_grounded_registry.py"], env=env))
    product_step = run_step(
        "product-configuration",
        [
            str(paths["python"]),
            "scripts/validate_grounded_product_config.py",
            "--release-manager-root",
            str(args.release_manager_root.expanduser().resolve()),
        ],
        env=env,
    )
    steps.append(product_step)
    manager_root = args.release_manager_root.expanduser().resolve()
    env["JIAOTANG_RELEASE_MANAGER_SCRIPTS"] = str(manager_root / "scripts")
    steps.append(
        run_step(
            "release-manager-pytest",
            [
                str(paths["pytest_python"]),
                "-m",
                "pytest",
                "-q",
                str(manager_root / "tests" / "test_release_security.py"),
            ],
            env=env,
        )
    )
    steps.append(
        run_step(
            "windows-hook-go-test",
            [
                str(paths["go"]),
                "-C",
                str(manager_root / "scripts" / "windows_hook"),
                "test",
                "./...",
            ],
            env=env,
        )
    )
    steps.append(run_step("docx-fixtures", [str(paths["python"]), "tests/fixtures/grounded-citations/build_document_fixtures.py"], env=env))
    for name, file_name, render_dir in (
        ("render-report", "grounded-analysis-report.docx", "render-report"),
        ("render-standard", "Q-JT-001-2026-grounded-standard.docx", "render-standard"),
        ("render-standard-source", "Q-JT-001-2026-grounded-standard-source-explanation.docx", "render-standard-source"),
    ):
        steps.append(
            run_step(
                name,
                [str(paths["python"]), str(paths["render_docx"]), str(REAL / file_name), "--output_dir", str(REAL / render_dir), "--emit_pdf"],
                env=env,
            )
        )
    steps.append(run_step("xlsx-roundtrip", [str(paths["node"]), "tests/fixtures/grounded-citations/build_spreadsheet_fixture.mjs", str(REAL / "xlsx")], env=env))
    steps.append(run_step("pptx-roundtrip", [str(paths["node"]), "tests/fixtures/grounded-citations/build_presentation_fixture.mjs", str(REAL / "pptx")], env=env))
    artifact_step = run_step("artifact-contracts", [str(paths["python"]), "tests/validate_grounded_artifacts.py"], env=env)
    steps.append(artifact_step)
    steps.append(
        run_step(
            "grounded-pytest",
            [
                str(paths["pytest_python"]),
                "-m",
                "pytest",
                "-q",
                "tests/test_grounded_evidence.py",
                "tests/test_grounded_delivery_profiles.py",
                "tests/test_grounded_delivery_receipts.py",
                "tests/test_grounded_product_configuration.py",
            ],
            env=env,
        )
    )
    steps.append(
        run_step(
            "full-suite-pytest",
            [str(paths["pytest_python"]), "-m", "pytest", "-q", "tests"],
            env=env,
        )
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    steps.append(
        run_step(
            "impact-graph",
            [
                str(paths["python"]),
                "skills/skill-curator/scripts/build_impact_graph.py",
                "--root",
                str(ROOT),
                "--changed",
                "config/grounded-citations.json",
                "--changed",
                "skills/evidence-ledger",
                "--changed",
                "skills/standard-drafting",
                "--changed",
                "tests/fixtures/grounded-citations",
                "--output-dir",
                str(output_dir / "impact"),
            ],
            env=env,
        )
    )

    adapters = host_adapter_receipt(paths["python"], env)
    required_failed = any(item["required"] and item["status"] != "pass" for item in steps) or adapters["status"] != "pass"
    git_branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "fail" if required_failed else "pass",
        "git": {"branch": git_branch, "commit": git_commit, "dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True).stdout)},
        "runtimes": {key: str(value) for key, value in paths.items()},
        "registry": "skills/report-skill-registry.json",
        "call_graph": "skills/skill-call-graph.json",
        "impact_graph": str((output_dir / "impact" / "skill-impact-graph.json").relative_to(ROOT)) if (output_dir / "impact" / "skill-impact-graph.json").is_relative_to(ROOT) else str(output_dir / "impact" / "skill-impact-graph.json"),
        "product_baseline": parse_json_tail(str(product_step["stdout_tail"])),
        "artifact_validation": parse_json_tail(str(artifact_step["stdout_tail"])),
        "host_adapters": adapters,
        "excluded_from_scope": ["bash-permission-policy", "external-mcp", "qcc", "paddleocr"],
        "verification_scope": {
            "host_adapters": "deterministic grounded contract output",
            "product_configuration": "V1.6.1.4 双端本地修复候选；Stop 当前 turn validator receipt 消费待实机复验；企业数字身份证与索引不在插件构建输入",
            "docx_pdf": "real OOXML/PDF round trip with Latin visual text; Chinese semantic contract covered by pytest",
        },
        "known_limits": [
            {
                "id": "headless-docx-cjk-font",
                "status": "known",
                "effect": "bundled LibreOffice renders CJK glyphs as boxes",
                "mitigation": "keep structural round-trip fixture Latin and run Chinese semantic contract tests",
            }
        ],
        "steps": steps,
        "release_authorized": False,
    }
    write_receipt(output_dir, receipt)
    print(json.dumps({"status": receipt["status"], "receipt": str(output_dir / "product-configuration-acceptance.json"), "impact_graph": str(output_dir / "impact" / "skill-impact-graph.json")}, ensure_ascii=False))
    return 2 if required_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
