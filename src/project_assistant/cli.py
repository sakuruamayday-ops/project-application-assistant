from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .doctor import run_checks
from .guide import render_guide, write_guide
from .platforms import SUPPORTED_PLATFORMS, install_skills, platform_home


def project_root() -> Path:
    override = os.environ.get("PROJECT_ASSISTANT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="project-assistant")
    root.add_argument("--root", type=Path, default=None)
    subcommands = root.add_subparsers(dest="command", required=True)

    show = subcommands.add_parser("config", help="加载并显示脱敏配置")
    show.add_argument("--platform", choices=SUPPORTED_PLATFORMS, required=True)

    doctor = subcommands.add_parser("doctor", help="执行只读健康检查")
    doctor.add_argument("--platform", choices=SUPPORTED_PLATFORMS, required=True)
    doctor.add_argument("--json", action="store_true")

    install = subcommands.add_parser("install", help="安装技能到指定平台")
    install.add_argument("--platform", choices=SUPPORTED_PLATFORMS, required=True)
    install.add_argument("--mode", choices=("copy", "symlink"), default="copy")
    install.add_argument("--force", action="store_true")
    install.add_argument("--skip-guide", action="store_true")
    install.add_argument("--target", type=Path, default=None, help="覆盖技能安装目录")
    install.add_argument("--guide", type=Path, default=None, help="覆盖首次使用指南路径")

    guide = subcommands.add_parser("guide", help="生成详细使用指南")
    guide.add_argument("--platform", choices=SUPPORTED_PLATFORMS, required=True)
    guide.add_argument("--output", type=Path, default=None)

    setup = subcommands.add_parser("setup", help="运行统一首次配置向导")
    setup.add_argument("--config-dir", type=Path, default=None)
    setup.add_argument("--non-interactive", action="store_true")
    setup.add_argument("--skip-network", action="store_true")
    return root


def redact(value):
    if isinstance(value, dict):
        return {key: ("***" if any(part in key.lower() for part in ("secret", "token", "password", "key")) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def main() -> int:
    args = parser().parse_args()
    root = (args.root or project_root()).expanduser().resolve()
    try:
        if args.command == "setup":
            script = root / "skills" / "first-run-configuration" / "scripts" / "configure.py"
            command = [sys.executable, str(script)]
            if args.config_dir:
                command.extend(["--config-dir", str(args.config_dir.expanduser().resolve())])
            if args.non_interactive:
                command.append("--non-interactive")
            if args.skip_network:
                command.append("--skip-network")
            return subprocess.run(command, check=False).returncode

        config = load_config(root, args.platform)
        if args.command == "config":
            print(json.dumps(redact(config), ensure_ascii=False, indent=2))
            return 0

        checks = run_checks(args.platform, config, root)
        if args.command == "doctor":
            if args.json:
                print(json.dumps([item.__dict__ for item in checks], ensure_ascii=False, indent=2))
            else:
                for item in checks:
                    print(f"{item.status:8} {item.name:26} {item.detail}")
            return 1 if any(item.status == "error" for item in checks) else 0

        output = getattr(args, "output", None) or getattr(args, "guide", None)
        if not output:
            configured = config.get("onboarding", {}).get("guide_output_path")
            if configured and "${" not in str(configured):
                output = Path(os.path.expanduser(str(configured)))
            else:
                output = root / "用户使用指南.md"

        if args.command == "guide":
            print(write_guide(render_guide(args.platform, config, checks), output))
            return 0

        destination = args.target.expanduser().resolve() if args.target else platform_home(args.platform, config)
        installed = install_skills(root / "skills", destination, args.mode, args.force)
        print(f"已安装 {len(installed)} 个技能到 {destination}")
        if installed:
            print("\n".join(installed))
        if not args.skip_guide:
            print(write_guide(render_guide(args.platform, config, checks), output))
        return 0
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"错误：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
