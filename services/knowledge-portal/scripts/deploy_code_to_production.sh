#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${JIAOTANG_RELEASE_MODE:-}" && "${JIAOTANG_RELEASE_MODE}" != "code" ]]; then
  echo "纯代码发布入口不接受非 code 模式：${JIAOTANG_RELEASE_MODE}" >&2
  exit 74
fi

export JIAOTANG_RELEASE_MODE=code
echo "已固定为 code 模式：只验签回执与当前指针，不扫描、不发布、不刷新索引。"
exec "${script_dir}/deploy_production.sh" "$@"
