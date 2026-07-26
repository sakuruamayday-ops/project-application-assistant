#!/usr/bin/env bash
set -euo pipefail

app_dir="${JIAOTANG_APP_DIR:-/opt/jiaotang-kb}"
data_dir="${JIAOTANG_DATA_DIR:-/var/lib/jiaotang-kb}"
knowledge_dir="${JIAOTANG_KNOWLEDGE_FILES_DIR:-/srv/jiaotang/knowledge-files}"
index_dir="${JIAOTANG_INDEX_DIR:-/srv/jiaotang/knowledge-index}"
snapshot_dir="${JIAOTANG_INDEX_SNAPSHOT_DIR:-/srv/jiaotang/index-snapshots}"
backup_dir="${JIAOTANG_BACKUP_DIR:-/var/backups/jiaotang-kb}"

"${app_dir}/.venv/bin/python" "${app_dir}/scripts/archive_index_snapshots.py" \
    --snapshot-dir "${snapshot_dir}" \
    --archive-dir "${backup_dir}/index-snapshot-archive" \
    --status-file "${data_dir}/snapshot-retention-status.json" \
    --portal-database "${data_dir}/knowledge.db" \
    --keep-latest "${JIAOTANG_SNAPSHOT_KEEP_LATEST:-3}"

"${app_dir}/.venv/bin/python" "${app_dir}/scripts/oss_incremental_sync.py" \
    --knowledge-dir "${knowledge_dir}" \
    --index-dir "${index_dir}" \
    --state-database "${data_dir}/oss-sync.sqlite3" \
    --status-file "${data_dir}/oss-sync-status.json"
