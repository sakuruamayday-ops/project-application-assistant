#!/usr/bin/env bash
set -euo pipefail

index_path="${JIAOTANG_INDEX_PATH:?请设置JIAOTANG_INDEX_PATH}"
deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"
remote_index="${JIAOTANG_REMOTE_INDEX_PATH:-/srv/jiaotang/knowledge-index/knowledge_content.sqlite3}"
remote_previous="${remote_index}.previous"
remote_swap="${remote_index}.swap"

[[ -f "${index_path}" ]] || { echo "索引不存在：${index_path}" >&2; exit 1; }

python3 - "${index_path}" "${JIAOTANG_INDEX_PREVALIDATED:-0}" <<'PY'
import sqlite3
import sys

prevalidated = sys.argv[2] == "1"
connection = sqlite3.connect(
    f"file:{sys.argv[1]}?mode={'ro' if prevalidated else 'rw'}",
    uri=True,
)
try:
    if not prevalidated:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    result = "ok" if prevalidated else connection.execute("PRAGMA quick_check").fetchone()[0]
finally:
    connection.close()
if result != "ok":
    raise SystemExit(f"本地索引校验失败：{result}")
PY

expected_sha="$(shasum -a 256 "${index_path}" | awk '{print $1}')"
remote_dir="$(dirname "${remote_index}")"
remote_sha="$(ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "if [ -f '${remote_index}' ]; then sha256sum '${remote_index}' | awk '{print \$1}'; fi")"
if [[ "${remote_sha}" == "${expected_sha}" ]]; then
  ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
    "python3 - '${expected_sha}' <<'PY'
import json
import sys
from pathlib import Path

path = Path('/var/lib/jiaotang-kb/oss-index-cache-status.json')
payload = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
payload['index_sha256'] = sys.argv[1]
payload['mode'] = '服务器差异索引 + OSS周期完整快照'
payload['source'] = 'rsync差异块'
temporary = path.with_suffix('.json.tmp')
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
temporary.replace(path)
PY"
  echo "服务器索引与本地一致，差异同步跳过。"
  exit 0
fi

ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "set -e; mkdir -p '${remote_dir}'; \
   if [ ! -f '${remote_previous}' ]; then \
     if [ -f '${remote_index}' ]; then cp --reflink=auto '${remote_index}' '${remote_previous}'; \
     else : > '${remote_previous}'; fi; \
   fi"

rsync --archive --stats --partial \
  -e "ssh -i ${deploy_key} -o BatchMode=yes" \
  "${index_path}" "${deploy_host}:${remote_previous}"

ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "set -e; \
   actual_sha=\$(sha256sum '${remote_previous}' | awk '{print \$1}'); \
   [ \"\${actual_sha}\" = '${expected_sha}' ] || { echo '服务器差异索引SHA-256不一致' >&2; exit 1; }; \
   [ \"\$(sqlite3 '${remote_previous}' 'PRAGMA quick_check;')\" = 'ok' ] || { echo '服务器差异索引SQLite校验失败' >&2; exit 1; }; \
   chown jiaotang:jiaotang '${remote_previous}'; chmod 0640 '${remote_previous}'; \
   systemctl stop jiaotang-kb; \
   if [ -f '${remote_index}' ]; then \
     mv '${remote_index}' '${remote_swap}'; \
     mv '${remote_previous}' '${remote_index}'; \
     mv '${remote_swap}' '${remote_previous}'; \
   else mv '${remote_previous}' '${remote_index}'; fi; \
   checked_at=\$(date -u +%Y-%m-%dT%H:%M:%SZ); \
   printf '{\n  \"status\": \"正常\",\n  \"mode\": \"服务器差异索引领先于 OSS\",\n  \"checked_at\": \"%s\",\n  \"cache_updated_at\": \"%s\",\n  \"source\": \"rsync差异块\",\n  \"index_sha256\": \"%s\",\n  \"cache_updated\": true\n}\n' \"\${checked_at}\" \"\${checked_at}\" '${expected_sha}' > /var/lib/jiaotang-kb/oss-index-cache-status.json.tmp; \
   chown jiaotang:jiaotang /var/lib/jiaotang-kb/oss-index-cache-status.json.tmp; chmod 0640 /var/lib/jiaotang-kb/oss-index-cache-status.json.tmp; \
   mv /var/lib/jiaotang-kb/oss-index-cache-status.json.tmp /var/lib/jiaotang-kb/oss-index-cache-status.json; \
   systemctl start jiaotang-kb; \
   for attempt in \$(seq 1 30); do curl --fail --silent http://127.0.0.1:8100/health >/dev/null && exit 0; sleep 2; done; \
   echo '服务器索引切换后健康检查失败' >&2; exit 1"

echo "服务器SQLite差异块同步与原子切换完成。"
