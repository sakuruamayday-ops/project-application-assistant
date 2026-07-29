#!/usr/bin/env bash
set -euo pipefail

app_dir="${JIAOTANG_APP_DIR:-/opt/jiaotang-kb}"
mode="${1:-}"
if [[ "${mode}" == "--if-missing" ]]; then
    index_dir="${JIAOTANG_INDEX_DIR:-/srv/jiaotang/knowledge-index}"
    if [[ -s "${index_dir}/knowledge_content.sqlite3" ]]; then
        exit 0
    fi
elif [[ -n "${mode}" ]]; then
    echo "未知参数：${mode}" >&2
    exit 2
fi
exec "${app_dir}/.venv/bin/python" "${app_dir}/scripts/refresh_index_from_oss.py"
