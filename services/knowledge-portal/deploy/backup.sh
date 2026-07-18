#!/usr/bin/env bash
set -euo pipefail

data_dir="${JIAOTANG_DATA_DIR:-/var/lib/jiaotang-kb}"
index_dir="${JIAOTANG_INDEX_DIR:-/srv/jiaotang/knowledge-index}"
backup_dir="${JIAOTANG_BACKUP_DIR:-/var/backups/jiaotang-kb}"
archive_dir="${backup_dir}/archive"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

install -d -m 0700 -o root -g root "${backup_dir}"
install -d -m 0700 -o root -g root "${archive_dir}"

backup_database() {
    local source_path="$1"
    local label="$2"
    local temporary_database="${backup_dir}/${label}-${timestamp}.sqlite3.tmp"
    local final_database="${backup_dir}/${label}-${timestamp}.sqlite3"
    [[ -f "${source_path}" ]] || return 0
    sqlite3 "${source_path}" ".timeout 10000" ".backup '${temporary_database}'"
    sqlite3 "${temporary_database}" "PRAGMA integrity_check;" | grep -qx "ok"
    mv "${temporary_database}" "${final_database}"
    chmod 0600 "${final_database}"
    gzip -6 "${final_database}"
}

backup_database "${data_dir}/knowledge.db" "portal"
if [[ "${JIAOTANG_BACKUP_INDEX:-false}" == "true" || "$(date +%u)" == "7" ]]; then
    backup_database "${index_dir}/knowledge_content.sqlite3" "content-index"
fi

find "${backup_dir}" -maxdepth 1 -type f -name '*.sqlite3.gz' -mtime +35 \
    -exec mv -n -t "${archive_dir}" {} +

python3 - "${data_dir}/backup-status.json" "${timestamp}" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
temporary = path.with_suffix(".json.tmp")
temporary.write_text(
    json.dumps({"status": "正常", "completed_at": sys.argv[2]}, ensure_ascii=False),
    encoding="utf-8",
)
os.chmod(temporary, 0o644)
os.replace(temporary, path)
PY
