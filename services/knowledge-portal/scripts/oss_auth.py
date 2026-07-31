from __future__ import annotations

import os
from collections.abc import Mapping

import oss2


def _required(values: Mapping[str, str], name: str) -> str:
    value = str(values.get(name, "")).strip()
    if not value:
        raise RuntimeError(f"缺少OSS配置：{name}")
    return value


def build_auth(
    values: Mapping[str, str] | None = None,
    *,
    namespace: str = "JIAOTANG_OSS",
) -> object:
    """Build an OSS auth object without silently falling back to static keys."""

    environment = values if values is not None else os.environ
    mode = str(
        environment.get(f"{namespace}_AUTH_MODE", "static")
    ).strip().lower()
    if mode == "static":
        return oss2.Auth(
            _required(environment, f"{namespace}_ACCESS_KEY_ID"),
            _required(environment, f"{namespace}_ACCESS_KEY_SECRET"),
        )
    if mode == "sts":
        return oss2.StsAuth(
            _required(environment, f"{namespace}_ACCESS_KEY_ID"),
            _required(environment, f"{namespace}_ACCESS_KEY_SECRET"),
            _required(environment, f"{namespace}_SECURITY_TOKEN"),
        )
    if mode == "ram-role":
        auth_host = _required(environment, f"{namespace}_RAM_ROLE_AUTH_HOST")
        return oss2.ProviderAuth(
            oss2.EcsRamRoleCredentialsProvider(auth_host)
        )
    raise RuntimeError(
        f"{namespace}_AUTH_MODE仅支持static、sts或ram-role，当前为：{mode}"
    )


def build_bucket(
    values: Mapping[str, str] | None = None,
    *,
    namespace: str = "JIAOTANG_OSS",
) -> oss2.Bucket:
    environment = values if values is not None else os.environ
    return oss2.Bucket(
        build_auth(environment, namespace=namespace),
        _required(environment, f"{namespace}_ENDPOINT").rstrip("/"),
        _required(environment, f"{namespace}_BUCKET"),
    )
