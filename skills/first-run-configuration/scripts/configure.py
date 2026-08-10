#!/usr/bin/env python3
"""Platform-neutral first-run configuration and capability detector."""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


DEFAULT_ENDPOINT = ""
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "project-assistant"
STARTUP_PROTOCOL_VERSION = 2
PREFERENCE_PROTOCOL_VERSION = 1
KNOWLEDGE_CONNECTION_CHECK_PROMPT = "检查下知识库连接状态"
HOST_SKILL_INSTALL_PROMPT = "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills"
SECRET_NAMES = {
    "GONGCHUANG_KB_TOKEN",
    "QCC_API_KEY",
    "PATENT_API_KEY",
    "PADDLE_OCR_API_KEY",
}
SYSTEM_CREDENTIAL_ONLY_NAMES = {
    "GONGCHUANG_KB_TOKEN",
}
PLAINTEXT_CREDENTIAL_NAMES = SECRET_NAMES - SYSTEM_CREDENTIAL_ONLY_NAMES
BOOLEAN_NAMES = {
    "GONGCHUANG_KB_MCP_READY",
    "TYC_MCP_READY",
    "QCC_MCP_READY",
    "PATENT_MCP_READY",
    "PROJECT_ASSISTANT_BROWSER_READY",
    "PROJECT_ASSISTANT_DOCUMENT_TOOLS_READY",
    "PROJECT_ASSISTANT_OCR_READY",
}
REGION_PROFILE_PATH = Path.home() / ".project-application-assistant" / "profile.json"


def initialize_preferences(
    config_dir: Path,
    values: dict[str, str],
    *,
    network: bool,
) -> tuple[str, str]:
    preference_file = config_dir / "preferences.json"
    if preference_file.is_file():
        return "ready", f"保留现有个人覆盖层：{preference_file}"
    script = Path(__file__).with_name("manage_preferences.py")
    spec = importlib.util.spec_from_file_location("project_assistant_preferences", script)
    if spec is None or spec.loader is None:
        return "warning", "未能加载个人偏好管理器"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    endpoint = values.get("GONGCHUANG_KB_ENDPOINT", "").strip()
    token = values.get("GONGCHUANG_KB_TOKEN", "").strip()
    if network and endpoint and token:
        try:
            remote = module.request_json(
                "GET",
                endpoint,
                token,
                "/v1/preferences",
            )
            module.write_local(preference_file, module.local_from_remote(remote))
            return "synced", f"已从云端同步个人偏好R{remote.get('revision', 0)}"
        except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as error:
            detail = f"云端偏好暂未同步：{type(error).__name__}"
    else:
        detail = "未配置云端凭据，已创建本地覆盖层"
    module.write_local(
        preference_file,
        {
            "schema_version": 1,
            "revision": 0,
            "preferences": {},
            "_meta": {"dirty": False, "base_revision": 0, "base_preferences": {}},
        },
    )
    return "local", detail


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "ready", "enabled"}


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        try:
            parts = shlex.split(raw_value.strip(), posix=True)
            value = parts[0] if len(parts) == 1 else raw_value.strip()
        except ValueError:
            value = raw_value.strip()
        values[key] = value
    return values


def effective_values(credentials_file: Path, environment: dict[str, str] | None = None) -> dict[str, str]:
    values = read_env_file(credentials_file)
    values.update({key: value for key, value in (environment or os.environ).items() if value})
    return values


def write_credentials(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 企业全生命周期助手统一凭据；禁止提交到Git或发送到对话。"]
    for key in sorted(values):
        if key in SYSTEM_CREDENTIAL_ONLY_NAMES:
            continue
        value = values[key].strip()
        if value:
            lines.append(f"{key}={shlex.quote(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def scrub_system_credentials_from_plaintext(path: Path) -> list[str]:
    values = read_env_file(path)
    removed = sorted(
        key for key in SYSTEM_CREDENTIAL_ONLY_NAMES if values.get(key, "").strip()
    )
    if removed:
        write_credentials(path, values)
    return removed


def write_region_profile(region: str, path: Path = REGION_PROFILE_PATH) -> None:
    normalized = "".join(region.split())
    if not normalized:
        return
    parts = list(
        dict.fromkeys(
            re.findall(r"[^省市区县]{2,12}(?:自治区|省|市|区|县)", normalized)
        )
    )
    province = next((part for part in parts if part.endswith(("省", "自治区"))), None)
    city = next((part for part in parts if part.endswith("市")), None)
    selected = [part for part in (province, city) if part]
    normalized = "".join(selected) or normalized
    scope = list(reversed(selected or parts))
    if "全国" not in scope:
        scope.append("全国")
    payload = {
        "default_region": normalized,
        "scope": scope,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def probe_cloud(
    endpoint: str,
    token: str,
    timeout: float = 10.0,
) -> tuple[str, str]:
    if not endpoint or not token:
        return "missing", "缺少地址或个人Token"
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/me",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "project-assistant-onboarding/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        username = str(payload.get("username") or "").strip()
        return ("ready", f"身份验证通过：{username}" if username else "身份验证通过")
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return "error", "Token无效、已吊销或无访问权限"
        return "warning", f"云端返回HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return "warning", f"联网验证未完成：{type(exc).__name__}"


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def capability_report(
    values: dict[str, str], *, network: bool = True, startup_required: bool = True
) -> dict[str, object]:
    endpoint = values.get("GONGCHUANG_KB_ENDPOINT", DEFAULT_ENDPOINT).strip()
    token = values.get("GONGCHUANG_KB_TOKEN", "").strip()
    knowledge_mcp_ready = truthy(values.get("GONGCHUANG_KB_MCP_READY"))
    if knowledge_mcp_ready:
        cloud_status, cloud_detail = "ready", "jiaotang-kb MCP运行时连接已验证"
    elif network and token:
        cloud_status, cloud_detail = probe_cloud(endpoint, token)
    elif token:
        cloud_status, cloud_detail = "configured", "已配置，尚未联网验证"
    else:
        cloud_status, cloud_detail = "missing", "未配置个人Token"

    qcc_mcp = truthy(values.get("QCC_MCP_READY"))
    qcc_key = bool(values.get("QCC_API_KEY"))
    tyc_mcp = truthy(values.get("TYC_MCP_READY"))
    patent_mcp = truthy(values.get("PATENT_MCP_READY"))
    patent_provider = bool(values.get("PATENT_DATA_PROVIDER"))
    patent_key = bool(values.get("PATENT_API_KEY"))
    browser_ready = truthy(values.get("PROJECT_ASSISTANT_BROWSER_READY"))
    ocr_ready = (
        truthy(values.get("PROJECT_ASSISTANT_OCR_READY"))
        or bool(values.get("PADDLE_OCR_API_KEY"))
        or module_available("paddleocr")
    )
    documents_ready = (
        truthy(values.get("PROJECT_ASSISTANT_DOCUMENT_TOOLS_READY"))
        or module_available("fitz")
        or shutil.which("libreoffice") is not None
    )

    knowledge_connection_verified = knowledge_mcp_ready
    show_host_skill_prompt = startup_required and knowledge_connection_verified
    return {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "onboarding": {
            "startup_protocol_version": STARTUP_PROTOCOL_VERSION,
            "preference_protocol_version": PREFERENCE_PROTOCOL_VERSION,
            "startup_protocol_executed": True,
            "startup_protocol_completed": knowledge_connection_verified,
            "startup_prompt_required": startup_required,
            "controlled_evolution_enabled": True,
            "four_question_review_enabled": True,
            "knowledge_connection_check_required": (
                startup_required and not knowledge_connection_verified
            ),
            "knowledge_connection_check_prompt": (
                KNOWLEDGE_CONNECTION_CHECK_PROMPT
                if startup_required and not knowledge_connection_verified
                else ""
            ),
            "host_skill_install_prompt": (
                HOST_SKILL_INSTALL_PROMPT if show_host_skill_prompt else ""
            ),
        },
        "credentials": {
            "stored_values_are_redacted": True,
            "detected_names": sorted(key for key in SECRET_NAMES if values.get(key)),
        },
        "project_region": {
            "default_region": values.get("PROJECT_ASSISTANT_DEFAULT_REGION", "").strip(),
            "configured": bool(values.get("PROJECT_ASSISTANT_DEFAULT_REGION", "").strip()),
        },
        "capabilities": {
            "team_knowledge": {
                "status": cloud_status,
                "detail": cloud_detail,
                "endpoint": endpoint,
                "required": True,
            },
            "tyc": {
                "status": "ready" if tyc_mcp else "optional",
                "detail": "MCP已标记连接" if tyc_mcp else "未配置，使用企查查或公开来源降级",
                "required": False,
            },
            "qcc": {
                "status": "ready" if qcc_mcp or qcc_key else "optional",
                "detail": "MCP已标记连接" if qcc_mcp else ("API Key已配置" if qcc_key else "未配置，使用公开来源降级"),
                "required": False,
            },
            "patent_data": {
                "status": "ready" if patent_mcp or (patent_provider and patent_key) else "optional",
                "detail": "MCP已标记连接" if patent_mcp else ("供应商与API Key已配置" if patent_provider and patent_key else "未完整配置，专利检索受限"),
                "required": False,
            },
            "browser": {
                "status": "ready" if browser_ready else "optional",
                "detail": "宿主浏览器或MCP已确认" if browser_ready else "未确认，动态网页任务需人工配置",
                "required": False,
            },
            "ocr": {
                "status": "ready" if ocr_ready else "optional",
                "detail": "本地Agent具备OCR能力" if ocr_ready else "未检测到OCR，扫描件需另行处理",
                "required": False,
            },
            "documents": {
                "status": "ready" if documents_ready else "optional",
                "detail": "宿主文档或PDF能力可用" if documents_ready else "未检测到，降级为Markdown或HTML",
                "required": False,
            },
        },
    }


def render_markdown(report: dict[str, object], credentials_file: Path) -> str:
    rows = []
    capabilities = report["capabilities"]
    assert isinstance(capabilities, dict)
    for name, item in capabilities.items():
        assert isinstance(item, dict)
        rows.append(f"| {name} | {item['status']} | {item['detail']} |")
    lines = [
            "# 企业全生命周期助手首次配置检测报告",
            "",
            f"检测时间：{report['checked_at']}",
            "",
            "| 能力 | 状态 | 说明 |",
            "|---|---|---|",
            *rows,
            "",
            "## 统一凭据",
            "",
            f"凭据文件：`{credentials_file}`",
            "",
            "团队知识库个人Token只写入当前用户的宿主MCP配置，不写入该文件；其他第三方凭据优先保存在宿主安全环境。该报告不包含Token、API Key、密码、Cookie或认证Header；不要把凭据文件发送给他人。",
            "",
            "## 后续规则",
            "",
            "- 其他Skill先读取本报告，不再分别询问已经配置的凭据。",
            "- 团队云端知识对成员只读；成员政策规则写入本地 `project-rules/`。",
            "- 可选能力不可用时执行降级，不补造企业、政策、专利或OCR结果。",
            "- 受控自进化已启用：自动记录脱敏经验、执行四问复盘并生成改进候选；正式Skill修改和发布仍需审批。",
            "",
        ]
    onboarding = report.get("onboarding", {})
    if (
        isinstance(onboarding, dict)
        and onboarding.get("knowledge_connection_check_required")
    ):
        lines.extend(
            [
                "## 请先完成知识库连接检查",
                "",
                f"`{KNOWLEDGE_CONNECTION_CHECK_PROMPT}`",
                "",
                "当前首次配置尚未结束。请先让当前Agent检查并完成 `jiaotang-kb` 运行时连接；只有知识库状态工具调用成功后，才继续安装通用能力。",
                "",
            ]
        )
    elif (
        isinstance(onboarding, dict)
        and onboarding.get("host_skill_install_prompt")
    ):
        lines.extend(
            [
                "## 请在当前Agent对话框继续输入",
                "",
                f"`{HOST_SKILL_INSTALL_PROMPT}`",
                "",
                "这些通用能力由当前Agent安装，企业全生命周期助手不重复打包。若已经具备这些能力，可忽略本提示。",
                "",
            ]
        )
    return "\n".join(lines)


def startup_protocol_required(profile_file: Path) -> bool:
    if not profile_file.is_file():
        return True
    try:
        profile = json.loads(profile_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    onboarding = profile.get("onboarding", {})
    if not isinstance(onboarding, dict):
        return True
    if int(onboarding.get("startup_protocol_version", 0)) < STARTUP_PROTOCOL_VERSION:
        return True
    return not bool(onboarding.get("startup_protocol_completed"))


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{marker}]: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "1", "true"}


def configure_interactively(values: dict[str, str]) -> dict[str, str]:
    configured = dict(values)
    configured["PROJECT_ASSISTANT_DEFAULT_REGION"] = ask(
        "默认政策地区，请填写到省、市",
        configured.get("PROJECT_ASSISTANT_DEFAULT_REGION", ""),
    )
    configured["GONGCHUANG_KB_ENDPOINT"] = ask(
        "团队云端知识API地址",
        configured.get("GONGCHUANG_KB_ENDPOINT", DEFAULT_ENDPOINT),
    )
    if not configured.get("GONGCHUANG_KB_TOKEN"):
        print(
            "团队知识库凭据不再通过首次配置脚本录入；"
            "请在登录门户生成一次性安装引导，由本地Agent保存到系统凭据库。"
        )

    if ask_yes_no("天眼查是否已经通过MCP连接", truthy(configured.get("TYC_MCP_READY"))):
        configured["TYC_MCP_READY"] = "true"

    if ask_yes_no("是否配置企查查API或确认企查查MCP", bool(configured.get("QCC_API_KEY") or truthy(configured.get("QCC_MCP_READY")))):
        if ask_yes_no("企查查是否已经通过MCP连接", truthy(configured.get("QCC_MCP_READY"))):
            configured["QCC_MCP_READY"] = "true"
        elif not configured.get("QCC_API_KEY"):
            key = getpass.getpass("企查查API Key；暂不配置可直接回车: ").strip()
            if key:
                configured["QCC_API_KEY"] = key

    if ask_yes_no("是否配置专利数据API或确认专利MCP", bool(configured.get("PATENT_DATA_PROVIDER") or truthy(configured.get("PATENT_MCP_READY")))):
        if ask_yes_no("专利数据是否已经通过MCP连接", truthy(configured.get("PATENT_MCP_READY"))):
            configured["PATENT_MCP_READY"] = "true"
        else:
            configured["PATENT_DATA_PROVIDER"] = ask("专利数据供应商标识", configured.get("PATENT_DATA_PROVIDER", ""))
            configured["PATENT_API_ENDPOINT"] = ask("专利数据REST地址", configured.get("PATENT_API_ENDPOINT", ""))
            if not configured.get("PATENT_API_KEY"):
                key = getpass.getpass("专利数据API Key；暂不配置可直接回车: ").strip()
                if key:
                    configured["PATENT_API_KEY"] = key

    configured["PROJECT_ASSISTANT_BROWSER_READY"] = str(
        ask_yes_no("宿主浏览器或浏览器MCP是否已经可用", truthy(configured.get("PROJECT_ASSISTANT_BROWSER_READY")))
    ).lower()
    configured["PROJECT_ASSISTANT_OCR_READY"] = str(
        ask_yes_no("本地Agent是否已经具备OCR能力", truthy(configured.get("PROJECT_ASSISTANT_OCR_READY")) or module_available("paddleocr"))
    ).lower()
    configured["PROJECT_ASSISTANT_DOCUMENT_TOOLS_READY"] = str(
        ask_yes_no("宿主是否已经具备PDF、Word或Excel能力", truthy(configured.get("PROJECT_ASSISTANT_DOCUMENT_TOOLS_READY")))
    ).lower()
    return configured


def run(
    config_dir: Path,
    *,
    non_interactive: bool,
    network: bool,
    environment: dict[str, str] | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> tuple[dict[str, object], Path, Path]:
    del input_fn
    credentials_file = config_dir / "credentials.env"
    profile_file = config_dir / "capabilities.json"
    report_file = config_dir / "首次配置检测报告.md"
    needs_startup = startup_protocol_required(profile_file)
    values = effective_values(credentials_file, environment)
    removed_plaintext_credentials = scrub_system_credentials_from_plaintext(
        credentials_file
    )
    if not non_interactive:
        values = configure_interactively(values)
        if ask_yes_no("是否保存到仅当前用户可读的统一凭据文件", True):
            allowed = {
                key: value
                for key, value in values.items()
                if key in PLAINTEXT_CREDENTIAL_NAMES
                or key in BOOLEAN_NAMES
                or key in {
                    "GONGCHUANG_KB_ENDPOINT",
                    "PATENT_DATA_PROVIDER",
                    "PATENT_API_ENDPOINT",
                    "PROJECT_ASSISTANT_DEFAULT_REGION",
                }
            }
            write_credentials(credentials_file, allowed)

    report = capability_report(values, network=network, startup_required=needs_startup)
    report["credentials"]["system_store_only_names"] = sorted(
        SYSTEM_CREDENTIAL_ONLY_NAMES
    )
    report["credentials"]["removed_from_plaintext_file"] = (
        removed_plaintext_credentials
    )
    write_region_profile(values.get("PROJECT_ASSISTANT_DEFAULT_REGION", ""))
    config_dir.mkdir(parents=True, exist_ok=True)
    preference_status, preference_detail = initialize_preferences(
        config_dir, values, network=network
    )
    report["personal_preferences"] = {
        "status": preference_status,
        "detail": preference_detail,
        "file": str(config_dir / "preferences.json"),
    }
    profile_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_file.write_text(render_markdown(report, credentials_file), encoding="utf-8")
    return report, profile_file, report_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--skip-network", action="store_true")
    args = parser.parse_args()
    report, profile_file, report_file = run(
        args.config_dir.expanduser().resolve(),
        non_interactive=args.non_interactive,
        network=not args.skip_network,
    )
    capabilities = report["capabilities"]
    assert isinstance(capabilities, dict)
    missing_required = [
        name
        for name, item in capabilities.items()
        if isinstance(item, dict) and item.get("required") and item.get("status") not in {"ready", "configured"}
    ]
    print(f"能力配置：{profile_file}")
    print(f"检测报告：{report_file}")
    print("凭据内容未写入报告。")
    print("受控自进化和四问复盘已启用。")
    preferences = report.get("personal_preferences", {})
    if isinstance(preferences, dict):
        print(f"个人偏好：{preferences.get('detail', '已初始化')}")
    onboarding = report.get("onboarding", {})
    if (
        isinstance(onboarding, dict)
        and onboarding.get("knowledge_connection_check_required")
    ):
        print(f"请先在当前Agent中执行：{KNOWLEDGE_CONNECTION_CHECK_PROMPT}")
    elif (
        isinstance(onboarding, dict)
        and onboarding.get("host_skill_install_prompt")
    ):
        print(f"请在当前Agent对话框输入：{HOST_SKILL_INSTALL_PROMPT}")
    if missing_required:
        print("仍需配置：" + "、".join(missing_required))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
