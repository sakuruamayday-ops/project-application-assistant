#!/usr/bin/env bash
set -euo pipefail

app_dir="${JIAOTANG_APP_DIR:-/opt/jiaotang-kb}"
exec "${app_dir}/.venv/bin/python" "${app_dir}/scripts/refresh_index_from_oss.py"
