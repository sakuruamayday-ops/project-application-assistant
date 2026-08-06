#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_dir="$(cd "${script_dir}/.." && pwd)"
root_dir="$(cd "${service_dir}/../.." && pwd)"
canonical_deploy_root="$(git -C "${root_dir}" config --local --get jiaotang.deployWorktree 2>/dev/null || true)"
if [[ -z "${canonical_deploy_root}" && "${JIAOTANG_ALLOW_NONCANONICAL_DEPLOY:-false}" != "true" ]]; then
  echo "四层发布门禁缺少唯一正式工作树 jiaotang.deployWorktree。" >&2
  exit 76
fi
if [[ -n "${canonical_deploy_root}" && "${JIAOTANG_ALLOW_NONCANONICAL_DEPLOY:-false}" != "true" ]]; then
  canonical_deploy_root="$(cd "${canonical_deploy_root}" && pwd -P)"
  current_root="$(cd "${root_dir}" && pwd -P)"
  if [[ "${current_root}" != "${canonical_deploy_root}" ]]; then
    echo "四层发布门禁只能从唯一正式工作树执行：${canonical_deploy_root}" >&2
    exit 76
  fi
fi
if git -C "${root_dir}" show-ref --verify --quiet refs/remotes/origin/main; then
  if ! git -C "${root_dir}" merge-base --is-ancestor origin/main HEAD; then
    echo "四层发布门禁阻断：当前工作树尚未合入最新 origin/main。" >&2
    exit 77
  fi
fi
endpoint="${JIAOTANG_KB_ENDPOINT:?请设置 JIAOTANG_KB_ENDPOINT}"
token="${JIAOTANG_KB_TOKEN:?请设置 JIAOTANG_KB_TOKEN}"
deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置 JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"
release_mode="${JIAOTANG_RELEASE_MODE:-}"
case "${release_mode}" in
  code|index) ;;
  *)
    echo "必须显式设置 JIAOTANG_RELEASE_MODE=code 或 index。" >&2
    exit 74
    ;;
esac
endpoint="${endpoint%/}"
auth=(
  -H "Authorization: Bearer ${token}"
)
curl_args=(--fail-with-body --silent --show-error --max-time 45)
gate_started_at="$(date +%s)"
phase_started_at="${gate_started_at}"

start_phase() {
  phase_started_at="$(date +%s)"
  echo "$1"
}

finish_phase() {
  local finished_at
  finished_at="$(date +%s)"
  echo "$1 通过，墙钟 $((finished_at - phase_started_at)) 秒。"
}
if [[ -n "${JIAOTANG_RESOLVE_IP:-}" ]]; then
  endpoint_authority="${endpoint#*://}"
  endpoint_authority="${endpoint_authority%%/*}"
  endpoint_host="${endpoint_authority%%:*}"
  endpoint_port="443"
  if [[ "${endpoint_authority}" == *:* ]]; then
    endpoint_port="${endpoint_authority##*:}"
  fi
  curl_args+=(--resolve "${endpoint_host}:${endpoint_port}:${JIAOTANG_RESOLVE_IP}")
fi

start_phase "[1/4] ${release_mode} 发布索引门禁"
if [[ "${release_mode}" == "index" ]]; then
  index_database="${JIAOTANG_INDEX_DATABASE:-/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3}"
  if [[ ! -f "${index_database}" ]]; then
    echo "索引发布需要挂载与发布目标一致的本地索引：${index_database}" >&2
    exit 78
  fi
  index_root="$(cd "$(dirname "${index_database}")" && pwd -P)"
  acceptance_receipt="${JIAOTANG_ACCEPTANCE_RECEIPT:-${index_root}/acceptance-harness.json}"
  if [[ ! -f "${acceptance_receipt}" ]]; then
    echo "索引发布缺少 Harness 收据：${acceptance_receipt}" >&2
    exit 79
  fi
  python3 "${script_dir}/verify_acceptance_receipt.py" \
    --receipt "${acceptance_receipt}" \
    --index-root "${index_root}" \
    --required-suite knowledge_base
else
  ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
    "set -e; set -a; source /etc/jiaotang-kb-ops.env; set +a; \
    \"\${JIAOTANG_APP_DIR}/.venv/bin/python\" \
    \"\${JIAOTANG_APP_DIR}/scripts/verify_index_release_binding.py\" \
    --index-root \"\${JIAOTANG_INDEX_DIR}\" \
    --profile \"\${JIAOTANG_APP_DIR}/references/acceptance-harness/knowledge-base.json\""
fi
finish_phase "${release_mode} 发布索引门禁"

start_phase "[2/4] 预发布运行时与远程 MCP"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "set -e; source /etc/jiaotang-kb-app.env; \
  \"\${JIAOTANG_APP_DIR}/.venv/bin/python\" \"\${JIAOTANG_APP_DIR}/scripts/verify_authenticated_portal.py\" \
  --base-url http://127.0.0.1:8100"
JIAOTANG_KB_ENDPOINT="${endpoint}" JIAOTANG_KB_TOKEN="${token}" \
  "${script_dir}/smoke_test_production.sh"
curl "${curl_args[@]}" "${auth[@]}" \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  "${endpoint}/mcp/" | python3 -c '
import json,sys
payload=json.load(sys.stdin)
tools={item.get("name") for item in payload.get("result",{}).get("tools",[])}
required={"knowledge_search","knowledge_document","knowledge_service_status"}
missing=sorted(required-tools)
assert not missing, "MCP 缺少必要工具："+"、".join(missing)
'
curl "${curl_args[@]}" "${auth[@]}" \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"knowledge_service_status","arguments":{}}}' \
  "${endpoint}/mcp/" | python3 -c '
import json,sys
payload=json.load(sys.stdin)
status=payload.get("result",{}).get("structuredContent",{})
assert status.get("connected") is True, "knowledge_service_status 未连接"
'
finish_phase "预发布运行时与远程 MCP"

start_phase "[3/4] 服务端发布产物"
release_workspace="$(mktemp -d -t jiaotang-release-evidence.XXXXXX)"
generic_archive="${release_workspace}/jiaotang-skills.zip"
workbuddy_archive="${release_workspace}/jiaotang-workbuddy.zip"
curl "${curl_args[@]}" "${auth[@]}" \
  "${endpoint}/v1/skills/latest/download" -o "${generic_archive}"
curl "${curl_args[@]}" "${auth[@]}" \
  "${endpoint}/v1/skills/latest/workbuddy/download" -o "${workbuddy_archive}"
JIAOTANG_RELEASE_ARCHIVE="${generic_archive}" python3 - <<'PY'
import os
import zipfile
from pathlib import Path

payload = Path(os.environ["JIAOTANG_RELEASE_ARCHIVE"]).read_bytes()
assert payload, "下载包为空"
with zipfile.ZipFile(os.environ["JIAOTANG_RELEASE_ARCHIVE"]) as archive:
    assert archive.testzip() is None, "ZIP完整性失败"
    names = set(archive.namelist())
    skill_manifests = {
        name for name in names
        if "/skills/" in f"/{name}" and name.endswith("/SKILL.md")
    }
    assert len(skill_manifests) == 49, f"Skills 数量异常：{len(skill_manifests)}"
    forbidden = (
        "jiaotang-agent.mjs",
        "run-node.cmd",
        "run-node",
        "bootstrap_url",
        "jiaotang_kb_setup",
    )
    hits = sorted(name for name in names if any(term in name for term in forbidden))
    assert not hits, "通用包仍包含旧安装组件：" + "、".join(hits)
PY
python3 "${root_dir}/tests/validate_workbuddy_release_candidate.py" \
  --suite-zip "${workbuddy_archive}" \
  --check server-release-contract
python3 "${root_dir}/tests/validate_workbuddy_release_candidate.py" \
  --suite-zip "${workbuddy_archive}" \
  --check all-skill-coverage
echo "产物证据保留于：${release_workspace}"
finish_phase "服务端发布产物"

start_phase "[4/4] 当前签名索引 release"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "python3 - <<'PY'
import json
from pathlib import Path
cache_path = Path('/var/lib/jiaotang-kb/oss-index-cache-status.json')
cache = json.loads(cache_path.read_text(encoding='utf-8'))
assert cache.get('status') == '正常', '索引缓存状态异常'
assert cache.get('current_release_id'), '索引缓存缺少current release身份'
assert cache.get('generation_consistent') is True, '索引世代不一致'
print('当前签名索引release正常：' + cache['current_release_id'])
PY"

finish_phase "当前签名索引 release"
gate_finished_at="$(date +%s)"
echo "四层发布门禁全部通过，总墙钟 $((gate_finished_at - gate_started_at)) 秒。"
