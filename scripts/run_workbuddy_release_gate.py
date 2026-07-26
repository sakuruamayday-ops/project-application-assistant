#!/usr/bin/env python3
"""Run the released WorkBuddy package on a real macOS or Windows host."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_json(arguments: list[str]) -> object:
    completed = subprocess.run(arguments, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def download_release_asset(repository: str, release_tag: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for attempt in range(12):
        release = command_json(
            [
                "gh",
                "release",
                "view",
                release_tag,
                "--repo",
                repository,
                "--json",
                "assets,isPrerelease",
            ]
        )
        assets = [
            asset
            for asset in release.get("assets", [])
            if str(asset.get("name", "")).endswith("-WorkBuddy.zip")
        ]
        if len(assets) == 1:
            asset = assets[0]
            subprocess.run(
                [
                    "gh",
                    "release",
                    "download",
                    release_tag,
                    "--repo",
                    repository,
                    "--pattern",
                    str(asset["name"]),
                    "--dir",
                    str(destination),
                ],
                check=True,
            )
            archive = destination / str(asset["name"])
            expected = str(asset.get("digest") or "").removeprefix("sha256:")
            if expected and sha256(archive) != expected:
                raise RuntimeError("GitHub Release 资产摘要与下载文件不一致")
            return archive
        if attempt < 11:
            time.sleep(10)
    raise RuntimeError("GitHub 预发布中未找到唯一的 WorkBuddy ZIP")


def safe_extract(archive_path: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            name = info.filename
            normalized = PurePosixPath(name.replace("\\", "/"))
            key = normalized.as_posix().casefold()
            unix_type = (info.external_attr >> 16) & 0o170000
            if (
                normalized.is_absolute()
                or ".." in normalized.parts
                or ":" in name
                or key in seen
                or unix_type == 0o120000
            ):
                raise RuntimeError(f"WorkBuddy ZIP 包含不安全条目：{name}")
            seen.add(key)
            target = (destination / Path(*normalized.parts)).resolve()
            if target != destination_root and destination_root not in target.parents:
                raise RuntimeError(f"WorkBuddy ZIP 路径越界：{name}")
        archive.extractall(destination)


def locate_marketplace(extracted: Path) -> Path:
    matches = list(extracted.glob("*/.codebuddy-plugin/marketplace.json"))
    if len(matches) != 1:
        raise RuntimeError("发布包必须且只能包含一个 WorkBuddy 市场清单")
    return matches[0].parent.parent


def host_name() -> str:
    current = platform.system().lower()
    if current == "darwin":
        return "macos"
    if current == "windows":
        return "windows"
    raise RuntimeError(f"真实宿主门禁仅支持 macOS/Windows，当前为 {platform.system()}")


def system_details(host: str) -> dict[str, str]:
    if host == "macos":
        version = platform.mac_ver()[0] or platform.release()
        return {"system_name": "macOS", "system_version": version}
    version = platform.win32_ver()[1] or platform.version()
    return {"system_name": "Windows", "system_version": version}


def workbuddy_version(host: str, powershell: str | None = None) -> str:
    if host == "macos":
        plist = Path("/Applications/WorkBuddy.app/Contents/Info.plist")
        if plist.is_file():
            with plist.open("rb") as source:
                return str(plistlib.load(source).get("CFBundleShortVersionString") or "")
        return ""
    if not powershell:
        return ""
    script = r"""
$roots = @(
  "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
  "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
  "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
$item = Get-ItemProperty $roots -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -like "WorkBuddy*" } |
  Select-Object -First 1
if ($item) { [Console]::Write([string]$item.DisplayVersion) }
"""
    completed = subprocess.run(
        [powershell, "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def codebuddy_version(transcript: str) -> str:
    matches = re.findall(
        r"(?m)^(?:codebuddy\s+)?v?(\d+\.\d+\.\d+(?:[-+][^\s]+)?)\s*$",
        transcript,
        flags=re.IGNORECASE,
    )
    return matches[0] if matches else ""


def run_gate(archive: Path, output_dir: Path, expected_host: str) -> dict[str, object]:
    actual_host = host_name()
    if actual_host != expected_host:
        raise RuntimeError(f"Runner 标签为 {expected_host}，实际系统为 {actual_host}")
    output_dir.mkdir(parents=True, exist_ok=True)
    runner_temp = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    evidence_root = Path(tempfile.mkdtemp(prefix=f"jiaotang-{actual_host}-", dir=runner_temp))
    extracted = evidence_root / "marketplace"
    safe_extract(archive, extracted)
    marketplace = locate_marketplace(extracted)
    isolated_config = evidence_root / "codebuddy-config"
    install_root = evidence_root / "installed-marketplaces"
    environment = os.environ.copy()
    environment.update(
        {
            "CODEBUDDY_CONFIG_DIR": str(isolated_config),
            "JIAOTANG_WORKBUDDY_INSTALL_ROOT": str(install_root),
            "JIAOTANG_WORKBUDDY_INSTALL_CONFIRM": "INSTALL",
            "DISABLE_AUTOUPDATER": "1",
        }
    )
    powershell = None
    if actual_host == "macos":
        installer = marketplace / "install-jiaotang-workbuddy.command"
        command = ["/bin/zsh", str(installer)]
    else:
        installer = marketplace / "install-jiaotang-workbuddy.ps1"
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            raise RuntimeError("Windows Runner 未发现 PowerShell")
        command = [
            powershell,
            "-NoProfile",
            "-File",
            str(installer),
            "-InstallRoot",
            str(install_root),
        ]
    if not installer.is_file():
        raise RuntimeError(f"发布包缺少 {actual_host} 安装器")

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=25 * 60,
    )
    transcript = completed.stdout + completed.stderr
    (output_dir / "installer.log").write_text(transcript, encoding="utf-8")
    status = (
        "pass"
        if completed.returncode == 0 and "安装成功，且已真实触发技能" in transcript
        else "fail"
    )
    versions = system_details(actual_host)
    detected_workbuddy = workbuddy_version(actual_host, powershell)
    detected_codebuddy = codebuddy_version(transcript)
    if status == "pass" and (not detected_workbuddy or not detected_codebuddy):
        status = "fail"
        transcript += "\n安装失败：无法记录 WorkBuddy 或 CodeBuddy CLI 版本\n"
        (output_dir / "installer.log").write_text(transcript, encoding="utf-8")
    evidence = {
        "schema": "jiaotang-workbuddy-host-evidence/v1",
        "status": status,
        "host": actual_host,
        "runner": os.environ.get("RUNNER_NAME", ""),
        "os": os.environ.get("RUNNER_OS", platform.system()),
        **versions,
        "arch": os.environ.get("RUNNER_ARCH", platform.machine()),
        "workbuddy_version": detected_workbuddy,
        "codebuddy_version": detected_codebuddy,
        "release_tag": os.environ.get("JIAOTANG_RELEASE_TAG", ""),
        "commit": os.environ.get("GITHUB_SHA", ""),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "archive_sha256": sha256(archive),
        "installer": installer.name,
        "returncode": completed.returncode,
        "evidence_root": str(evidence_root),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "host-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if status != "pass":
        raise RuntimeError(f"{actual_host} WorkBuddy 实机门禁失败，详见 installer.log")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description="执行 WorkBuddy 正式发布包实机门禁")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--release-tag")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--host", choices=["macos", "windows"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    archive = arguments.archive
    if archive is None:
        if not arguments.repository:
            raise SystemExit("--release-tag 需要 --repository")
        archive = download_release_asset(
            arguments.repository,
            arguments.release_tag,
            arguments.output_dir / "release",
        )
    result = run_gate(archive.resolve(), arguments.output_dir.resolve(), arguments.host)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
