from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    from scripts.oss_auth import build_bucket
except ImportError:  # direct script execution
    from oss_auth import build_bucket


SECRET_NAMES = {
    "JIAOTANG_OSS_ACCESS_KEY_ID",
    "JIAOTANG_OSS_ACCESS_KEY_SECRET",
    "JIAOTANG_OSS_SECURITY_TOKEN",
    "JIAOTANG_OSS_RELEASE_SIGNING_SECRET",
    "JIAOTANG_BACKUP_OSS_ACCESS_KEY_ID",
    "JIAOTANG_BACKUP_OSS_ACCESS_KEY_SECRET",
    "JIAOTANG_BACKUP_OSS_SECURITY_TOKEN",
}


def environment_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.split("=", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }


def nonempty_collection(result: object, *attributes: str) -> bool:
    for name in attributes:
        value = getattr(result, name, None)
        if value:
            return True
    return False


def audit_bucket(bucket: object, *, auth_mode: str) -> dict[str, object]:
    checks: dict[str, object] = {"auth_mode": auth_mode, "query_errors": {}}

    def query(name: str, function, transform) -> None:
        try:
            checks[name] = transform(function())
        except Exception as error:
            checks[name] = "unknown"
            query_errors = checks["query_errors"]
            assert isinstance(query_errors, dict)
            query_errors[name] = f"{type(error).__name__}:{error}"[:500]

    query(
        "versioning",
        bucket.get_bucket_versioning,
        lambda result: str(getattr(result, "status", "")),
    )
    query(
        "encryption",
        bucket.get_bucket_encryption,
        lambda result: str(
            getattr(result, "sse_algorithm", "")
            or getattr(result, "algorithm", "")
        ),
    )
    query(
        "access_logging",
        bucket.get_bucket_logging,
        lambda result: bool(
            getattr(result, "target_bucket", "")
            and getattr(result, "target_prefix", "")
        ),
    )
    query(
        "inventory",
        bucket.list_bucket_inventory_configurations,
        lambda result: nonempty_collection(
            result,
            "inventory_configurations",
            "inventory_configuration_list",
        ),
    )
    query(
        "cross_region_replication",
        bucket.get_bucket_replication,
        lambda result: nonempty_collection(result, "rule_list", "rules"),
    )
    return checks


def evaluate(
    checks: dict[str, object],
    *,
    app_environment_keys: set[str],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    leaked = sorted(app_environment_keys & SECRET_NAMES)
    if leaked:
        errors.append("门户主进程环境仍包含发布凭据：" + ", ".join(leaked))
    if checks.get("versioning") != "Enabled":
        warnings.append("OSS版本控制未启用或无法读取")
    if not checks.get("encryption"):
        warnings.append("OSS服务端加密未启用")
    elif checks.get("encryption") == "unknown":
        warnings.append("OSS服务端加密配置无法读取")
    if checks.get("auth_mode") == "static":
        warnings.append("OSS运维仍使用静态AccessKey，建议迁移STS或RAM Role")
    if checks.get("access_logging") is not True:
        warnings.append("OSS访问日志未启用")
    if checks.get("inventory") is not True:
        warnings.append("OSS Inventory未启用")
    if checks.get("cross_region_replication") is not True:
        warnings.append("OSS跨区域复制未配置")
    query_errors = checks.get("query_errors")
    if isinstance(query_errors, dict) and query_errors:
        warnings.append(
            "部分OSS治理配置无法读取：" + ", ".join(sorted(query_errors))
        )
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="只读检查OSS职责分离、版本、加密、访问日志、Inventory和CRR"
    )
    parser.add_argument(
        "--mode",
        choices=("warn", "enforce"),
        default=os.environ.get("JIAOTANG_OSS_GOVERNANCE_MODE", "warn"),
    )
    parser.add_argument(
        "--app-environment-file",
        type=Path,
        default=Path("/etc/jiaotang-kb-app.env"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    auth_mode = os.environ.get("JIAOTANG_OSS_AUTH_MODE", "static").strip().lower()
    checks = audit_bucket(build_bucket(), auth_mode=auth_mode)
    errors, warnings = evaluate(
        checks,
        app_environment_keys=environment_keys(args.app_environment_file),
    )
    if args.mode == "enforce":
        errors.extend(warnings)
        warnings = []
    report = {
        "status": "fail" if errors else ("warn" if warnings else "pass"),
        "mode": args.mode,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "note": "本门禁只读，不创建访问日志、Inventory、RAM Role或CRR资源。",
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(
            f".{args.output.name}.{os.getpid()}.tmp"
        )
        temporary.write_text(encoded + "\n", encoding="utf-8")
        os.replace(temporary, args.output)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
