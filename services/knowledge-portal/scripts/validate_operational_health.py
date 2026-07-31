from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.refresh_index_from_oss import (
        local_generation_metadata_valid,
        release_id_from_link,
        runtime_binding_mode,
    )
except ImportError:  # direct script execution
    from refresh_index_from_oss import (
        local_generation_metadata_valid,
        release_id_from_link,
        runtime_binding_mode,
    )


def parse_timestamp(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z") and "T" in value and "-" in value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.endswith("Z") and len(value) == 16:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    raise ValueError(f"不支持的时间格式：{value}")


def age_seconds(value: str, now: datetime) -> float:
    return (now - parse_timestamp(value)).total_seconds()


def read_json(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"缺少{label}状态：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{label}状态不可读：{path}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label}状态格式非法")
    return payload


def validate_fresh_status(
    path: Path,
    *,
    label: str,
    timestamp_field: str,
    max_age_seconds: int,
    accepted_statuses: set[str],
    now: datetime,
) -> dict[str, object]:
    payload, age = read_valid_status_with_age(
        path,
        label=label,
        timestamp_field=timestamp_field,
        accepted_statuses=accepted_statuses,
        now=now,
    )
    if age > max_age_seconds:
        raise RuntimeError(
            f"{label}状态过期：{int(age)}秒 > {max_age_seconds}秒"
        )
    return payload


def read_valid_status_with_age(
    path: Path,
    *,
    label: str,
    timestamp_field: str,
    accepted_statuses: set[str],
    now: datetime,
) -> tuple[dict[str, object], float]:
    payload = read_json(path, label)
    if str(payload.get("status") or "") not in accepted_statuses:
        raise RuntimeError(f"{label}状态异常：{payload.get('status')}")
    value = str(payload.get(timestamp_field) or "")
    if not value:
        raise RuntimeError(f"{label}缺少时间字段：{timestamp_field}")
    age = age_seconds(value, now)
    if age < -300:
        raise RuntimeError(f"{label}时间位于未来：{value}")
    return payload, age


def validate_generation(
    index_dir: Path,
    cache_status: dict[str, object],
) -> dict[str, str | None]:
    current = release_id_from_link(index_dir / "current")
    previous = release_id_from_link(index_dir / "previous")
    if not current:
        raise RuntimeError("本地current不是release符号链接")
    if cache_status.get("current_release_id") != current:
        raise RuntimeError("缓存状态current_release_id与文件系统不一致")
    if not cache_status.get("generation_consistent"):
        raise RuntimeError("缓存状态标记世代不一致")
    if not local_generation_metadata_valid(index_dir, current):
        raise RuntimeError("current release本地元数据复检失败")
    if previous and not local_generation_metadata_valid(index_dir, previous):
        raise RuntimeError("previous release本地元数据复检失败")
    runtime_mode = runtime_binding_mode(index_dir, current)
    if not runtime_mode:
        raise RuntimeError("运行时根索引与current release不一致")
    return {
        "current_release_id": current,
        "previous_release_id": previous,
        "runtime_mode": runtime_mode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="聚合焦糖门户运维健康门禁")
    parser.add_argument("--response-json", required=True)
    parser.add_argument("--disk-percent", type=int, required=True)
    parser.add_argument("--certificate-expires", default="")
    parser.add_argument("--failed-unit", action="append", default=[])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, object] = {}
    try:
        response = json.loads(args.response_json)
        if response.get("status") != "ok":
            errors.append("应用/health未返回status=ok")
    except json.JSONDecodeError:
        errors.append("应用/health响应不是有效JSON")
    if args.failed_unit:
        errors.append("systemd失败单元：" + ", ".join(sorted(args.failed_unit)))
    fail_disk = int(os.environ.get("JIAOTANG_DISK_FAIL_PERCENT", "90"))
    warn_disk = int(os.environ.get("JIAOTANG_DISK_WARN_PERCENT", "80"))
    if args.disk_percent >= fail_disk:
        errors.append(f"磁盘使用率{args.disk_percent}%达到失败阈值{fail_disk}%")
    elif args.disk_percent >= warn_disk:
        warnings.append(f"磁盘使用率{args.disk_percent}%达到告警阈值{warn_disk}%")
    certificate_status = "待检查"
    if args.certificate_expires:
        try:
            certificate_time = datetime.strptime(
                args.certificate_expires,
                "%b %d %H:%M:%S %Y %Z",
            ).replace(tzinfo=timezone.utc)
            remaining = (certificate_time - now).total_seconds()
            if remaining <= 0:
                errors.append("TLS证书已经过期")
                certificate_status = "已过期"
            elif remaining <= int(
                os.environ.get(
                    "JIAOTANG_CERTIFICATE_WARN_SECONDS",
                    str(14 * 86400),
                )
            ):
                warnings.append("TLS证书将在14天告警窗口内到期")
                certificate_status = "即将到期"
            else:
                certificate_status = "有效"
        except ValueError:
            warnings.append("TLS证书到期时间无法解析")
    else:
        warnings.append("未取得TLS证书到期时间")
    try:
        cache, cache_age = read_valid_status_with_age(
            args.data_dir / "oss-index-cache-status.json",
            label="索引缓存",
            timestamp_field="checked_at",
            accepted_statuses={"正常"},
            now=now,
        )
        generation = validate_generation(args.index_dir, cache)
        details.update(generation)
        max_cache_age = int(
            os.environ.get("JIAOTANG_INDEX_STATUS_MAX_AGE_SECONDS", "7200")
        )
        if cache_age > max_cache_age:
            warnings.append(
                "索引缓存上次OSS验证已超过"
                f"{max_cache_age}秒；本地release元数据与运行时绑定复检通过"
            )
        if generation.get("runtime_mode") == "legacy-root-readonly":
            warnings.append(
                "根索引处于只读兼容模式；本轮未迁移或处置既有文件，"
                "不同release切换将保持失败关闭"
            )
    except Exception as error:
        errors.append(str(error))
    payload: dict[str, object] = {
        "status": "异常" if errors else ("告警" if warnings else "正常"),
        "checked_at": now.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "disk_percent": args.disk_percent,
        "certificate_status": certificate_status,
        "certificate_expires": args.certificate_expires,
        "failed_units": sorted(args.failed_unit),
        "errors": errors,
        "warnings": warnings,
        **details,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o644)
    os.replace(temporary, args.output)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
