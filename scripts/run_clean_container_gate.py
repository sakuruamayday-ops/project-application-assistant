#!/usr/bin/env python3
"""Run the packaged tax-report E2E test in an isolated OCI container."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


IMAGE = "jiaotang-portable-report-test:1.0.0"


def engine_binary(requested: str | None) -> str:
    candidates = [requested] if requested else ["docker", "podman"]
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return candidate
    raise RuntimeError("未找到Docker或Podman；stable发布必须在干净OCI容器中通过")


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--engine", choices=["docker", "podman"])
    parser.add_argument("--audit-json", type=Path)
    parser.add_argument("--rebuild-image", action="store_true")
    args = parser.parse_args()

    package = args.package.resolve()
    if not package.is_file():
        raise FileNotFoundError(package)
    engine = engine_binary(args.engine)
    repository = Path(__file__).resolve().parents[1]
    dockerfile = repository / "containers" / "portable-report-test.Dockerfile"

    inspect = subprocess.run(
        [engine, "image", "inspect", IMAGE],
        text=True,
        capture_output=True,
    )
    if args.rebuild_image or inspect.returncode:
        run(
            [
                engine,
                "build",
                "-f",
                str(dockerfile),
                "-t",
                IMAGE,
                str(dockerfile.parent),
            ]
        )

    with tempfile.TemporaryDirectory(prefix="jiaotang-container-audit-") as directory:
        audit_directory = Path(directory)
        run(
            [
                engine,
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=256m",
                "--tmpfs",
                "/work:rw,exec,nosuid,size=512m",
                "-v",
                f"{package}:/input/release.zip:ro",
                "-v",
                f"{audit_directory}:/output:rw",
                IMAGE,
                "sh",
                "-lc",
                "unzip -q /input/release.zip -d /work/package && "
                "python /work/package/skills/manufacturing-tax-risk-analysis/"
                "scripts/verify_e2e.py "
                "--skills-root /work/package/skills "
                "--output-dir /work/artifacts "
                "--audit-json /output/container-audit.json",
            ]
        )
        container_audit = json.loads(
            (audit_directory / "container-audit.json").read_text(encoding="utf-8")
        )

    result = {
        "status": "passed",
        "engine": engine,
        "image": IMAGE,
        "package": str(package),
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "network_disabled_during_test": True,
        "read_only_container_root": True,
        "e2e": container_audit,
    }
    if args.audit_json:
        args.audit_json.parent.mkdir(parents=True, exist_ok=True)
        args.audit_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
