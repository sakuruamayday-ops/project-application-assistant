#!/usr/bin/env bash
set -euo pipefail

handoff_dir="${1:?用法：release_policy_increment.sh /path/to/frozen-handoff}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_dir="$(cd "${script_dir}/.." && pwd)"
root_dir="$(cd "${service_dir}/../.." && pwd)"
canonical_root="$(git -C "${root_dir}" config --local --get jiaotang.deployWorktree 2>/dev/null || true)"
if [[ -n "${canonical_root}" && "$(cd "${canonical_root}" && pwd -P)" != "$(cd "${root_dir}" && pwd -P)" ]]; then
  echo "政策增量正式发布只能从唯一正式工作树执行：${canonical_root}" >&2
  exit 76
fi
if [[ -n "$(git -C "${root_dir}" status --porcelain)" ]]; then
  echo "正式发布工作树不干净，拒绝执行政策自动发布" >&2
  exit 77
fi
if ! git -C "${root_dir}" merge-base --is-ancestor origin/main HEAD; then
  echo "正式发布工作树尚未包含最新origin/main" >&2
  exit 78
fi

deploy_host="${JIAOTANG_DEPLOY_HOST:-root@101.37.169.250}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-/Users/zsh/.ssh/jiaotang_kb_aliyun}"
state_root="${JIAOTANG_POLICY_CHAIN_ROOT:-/Users/zsh/JiaotangData/索引/policy-increment-chain}"
private_key="${JIAOTANG_POLICY_PRIVATE_KEY:-/Users/zsh/.config/project-assistant/policy-increment-chain/ed25519-private.pem}"
public_key="${JIAOTANG_POLICY_PUBLIC_KEY:-/Users/zsh/.config/project-assistant/policy-increment-chain/ed25519-public.pem}"
baseline_source="${JIAOTANG_POLICY_BASELINE_SOURCE:-/Users/zsh/JiaotangData/索引/candidates/identity-reverse-lookup.RtlTpt/index}"
python_bin="${JIAOTANG_POLICY_PYTHON:-/Users/zsh/Documents/分析/项目申报助手/services/knowledge-portal/.venv/bin/python}"
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$(basename "${handoff_dir}")"
run_dir="${state_root}/runs/${run_id}"
prepared="${run_dir}/prepared-release.json"
server_receipt="${run_dir}/server-deploy-receipt.json"
final_receipt="${run_dir}/production-deployment-receipt.json"
deploy_lock="/Users/zsh/.cache/jiaotang/deploy-production.lock"
release_lock="/Users/zsh/JiaotangData/索引/.locks/production-release.lock"

if [[ "${JIAOTANG_DEPLOY_LOCK_HELD:-false}" != "true" ]]; then
  exec python3 "${script_dir}/with_deployment_lock.py" \
    --lock-file "${deploy_lock}" -- "$0" "$@"
fi
if [[ "${JIAOTANG_RELEASE_LOCK_HELD:-0}" != "1" ]]; then
  mkdir -p "$(dirname "${release_lock}")"
  exec lockf -k -t 600 "${release_lock}" \
    env JIAOTANG_RELEASE_LOCK_HELD=1 "$0" "$@"
fi

server_deployed=0
pointer_switched=0
verifiers_paused=0
release_completed=0
rollback_on_failure() {
  exit_code="$?"
  trap - EXIT
  if [[ "${release_completed}" == "1" ]]; then
    exit "${exit_code}"
  fi
  set +e
  if [[ "${pointer_switched}" == "1" && -f "${prepared}" ]]; then
    "${python_bin}" "${script_dir}/policy_increment_release.py" rollback-pointer \
      --prepared "${prepared}" >>"${run_dir}/rollback.log" 2>&1
  fi
  if [[ "${server_deployed}" == "1" && -f "${prepared}" ]]; then
    JIAOTANG_DEPLOY_HOST="${deploy_host}" JIAOTANG_DEPLOY_KEY="${deploy_key}" \
      JIAOTANG_POLICY_PREPARED_RELEASE="${prepared}" \
      "${script_dir}/deploy_policy_increment_to_server.sh" rollback \
      >>"${run_dir}/rollback.log" 2>&1
  fi
  if [[ "${verifiers_paused}" == "1" ]]; then
    JIAOTANG_DEPLOY_HOST="${deploy_host}" JIAOTANG_DEPLOY_KEY="${deploy_key}" \
      "${script_dir}/deploy_policy_increment_to_server.sh" restore-legacy-verifier \
      >>"${run_dir}/rollback.log" 2>&1
  fi
  exit "${exit_code}"
}
trap rollback_on_failure EXIT

[[ -d "${handoff_dir}" ]] || { echo "冻结交接包目录不存在：${handoff_dir}" >&2; exit 1; }
[[ -f "${deploy_key}" ]] || { echo "SSH发布密钥不存在：${deploy_key}" >&2; exit 1; }
[[ -x "${python_bin}" ]] || { echo "政策增量Python运行时不可用：${python_bin}" >&2; exit 1; }

while IFS='=' read -r key value; do
  case "${key}" in
    JIAOTANG_OSS_ENDPOINT|JIAOTANG_OSS_BUCKET|JIAOTANG_OSS_ACCESS_KEY_ID|JIAOTANG_OSS_ACCESS_KEY_SECRET|JIAOTANG_OSS_PREFIX|JIAOTANG_OSS_AUTH_MODE|JIAOTANG_OSS_SECURITY_TOKEN|JIAOTANG_OSS_RAM_ROLE_AUTH_HOST)
      export "${key}=${value}"
      ;;
  esac
done < <(ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  'env_file=/etc/jiaotang-kb-ops.env; grep -E "^JIAOTANG_OSS_(ENDPOINT|BUCKET|ACCESS_KEY_ID|ACCESS_KEY_SECRET|PREFIX|AUTH_MODE|SECURITY_TOKEN|RAM_ROLE_AUTH_HOST)=" "${env_file}"')
export JIAOTANG_OSS_ENDPOINT="${JIAOTANG_OSS_ENDPOINT/oss-cn-hangzhou-internal/oss-cn-hangzhou}"

if [[ ! -f "${state_root}/state.json" ]]; then
  base_release_json="$(mktemp -t jiaotang-policy-base-release.XXXXXX.json)"
  remote_base_id="$(ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
    'basename "$(readlink -f /srv/jiaotang/knowledge-index/current)"')"
  ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
    'cat "$(readlink -f /srv/jiaotang/knowledge-index/current)/release.json"' \
    >"${base_release_json}"
  "${python_bin}" "${script_dir}/policy_increment_release.py" initialize \
    --baseline-index-dir "${baseline_source}" \
    --base-release-json "${base_release_json}" \
    --base-release-id "${remote_base_id}" \
    --state-root "${state_root}" \
    --private-key "${private_key}" \
    --public-key "${public_key}"
  mv "${base_release_json}" "${state_root}/baselines/${remote_base_id}/source-release.json"
fi

"${python_bin}" "${script_dir}/policy_increment_release.py" prepare \
  --handoff-dir "${handoff_dir}" \
  --run-dir "${run_dir}" \
  --state-root "${state_root}" \
  --private-key "${private_key}"

echo "[1/7] 仅上传冻结交接包中的SHA-256内容寻址对象"
"${python_bin}" "${script_dir}/upload_manifest_to_oss.py" \
  --manifest "${run_dir}/delta-upload-manifest.jsonl" \
  --allowlist "${run_dir}/delta-upload-allowlist.csv" \
  --object-layout sha256 \
  --workers 4 \
  --verify-after-upload | tee "${run_dir}/knowledge-object-upload.log"

echo "[2/7] 上传完整基线锚点、受信公钥和不可变签名增量包"
"${python_bin}" "${script_dir}/policy_increment_release.py" upload-immutable \
  --prepared "${prepared}" | tee "${run_dir}/immutable-upload.log"

echo "[3/7] 暂停旧OSS完整release校验器，准备双槽差异切换"
JIAOTANG_DEPLOY_HOST="${deploy_host}" JIAOTANG_DEPLOY_KEY="${deploy_key}" \
  "${script_dir}/deploy_policy_increment_to_server.sh" pause-verifiers
verifiers_paused=1

echo "[4/7] rsync仅传输变化数据库页并原子切换服务器current"
JIAOTANG_DEPLOY_HOST="${deploy_host}" JIAOTANG_DEPLOY_KEY="${deploy_key}" \
JIAOTANG_POLICY_PREPARED_RELEASE="${prepared}" \
JIAOTANG_POLICY_DEPLOY_RECEIPT="${server_receipt}" \
  "${script_dir}/deploy_policy_increment_to_server.sh" deploy
server_deployed=1

echo "[5/7] CAS切换Ed25519增量链current并启用每小时链验证"
"${python_bin}" "${script_dir}/policy_increment_release.py" switch-pointer \
  --prepared "${prepared}" | tee "${run_dir}/pointer-switch.log"
pointer_switched=1
JIAOTANG_DEPLOY_HOST="${deploy_host}" JIAOTANG_DEPLOY_KEY="${deploy_key}" \
JIAOTANG_POLICY_PREPARED_RELEASE="${prepared}" \
  "${script_dir}/deploy_policy_increment_to_server.sh" install-verifier

echo "[6/7] OSS二次校验、服务器深度验签、REST/MCP固定路由和新增文档命中"
"${python_bin}" "${script_dir}/policy_increment_release.py" verify-cloud \
  --prepared "${prepared}" >"${run_dir}/cloud-verification.json"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  'set -e; source /etc/jiaotang-kb-ops.env; /opt/jiaotang-kb-runtime/current/.venv/bin/python /usr/local/libexec/jiaotang-policy-increment-verify --deep' \
  >"${run_dir}/server-chain-verification.json"

document_paths_base64="$(python3 - "${prepared}" <<'PY'
import base64,json,sys
p=json.load(open(sys.argv[1]))
payload=json.load(open(p["package_dir"]+"/delta_payload.json"))
body=json.dumps([row["source_path"] for row in payload["documents"]],ensure_ascii=False).encode()
print(base64.b64encode(body).decode())
PY
)"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "python3 - '${document_paths_base64}' /srv/jiaotang/knowledge-index/current/knowledge_content.sqlite3" <<'PY' \
  >"${run_dir}/new-document-smoke.json"
import base64,json,sqlite3,sys
paths=json.loads(base64.b64decode(sys.argv[1]))
with sqlite3.connect(f"file:{sys.argv[2]}?mode=ro",uri=True) as db:
    hits=sum(db.execute("SELECT COUNT(*) FROM documents WHERE source_path=?",(path,)).fetchone()[0] for path in paths)
if hits != len(paths): raise SystemExit(f"新增文档命中不完整：{hits}/{len(paths)}")
print(json.dumps({"expected":len(paths),"hits":hits,"status":"pass"},ensure_ascii=False))
PY

ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  'set -e
   source /etc/jiaotang-kb-app.env
   curl --fail --silent http://127.0.0.1:8100/health >/dev/null
   systemctl is-active --quiet jiaotang-kb
   resolve=(--resolve "${JIAOTANG_PUBLIC_HOST}:443:127.0.0.1")
   test "$(curl -sS -o /dev/null -w "%{http_code}" "${resolve[@]}" "https://${JIAOTANG_PUBLIC_HOST}/login")" = 200
   test "$(curl -sS -o /dev/null -w "%{http_code}" "${resolve[@]}" "https://${JIAOTANG_PUBLIC_HOST}/v1/me")" = 401
   test "$(curl -sS -o /dev/null -w "%{http_code}" "${resolve[@]}" "https://${JIAOTANG_PUBLIC_HOST}/mcp/")" = 401' \
  >"${run_dir}/route-smoke.log"

"${python_bin}" "${script_dir}/audit_oss_capacity.py" >"${run_dir}/oss-capacity.json"

echo "[7/7] 冻结生产回执并提交本地链状态"
python3 - "${prepared}" "${server_receipt}" "${run_dir}/cloud-verification.json" "${final_receipt}" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
p=json.load(open(sys.argv[1])); server=json.load(open(sys.argv[2])); cloud=json.load(open(sys.argv[3]))
receipt={
 "schema":"jiaotang-policy-increment-deployment-receipt/v1",
 "completed_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),
 "release_id":p["release_id"],"chain_sha256":p["chain_sha256"],
 "candidate_index_sha256":p["candidate_index_sha256"],
 "candidate_manifest_sha256":p["candidate_manifest_sha256"],
 "server_status":server["server_status"],"cloud_status":cloud["status"],
 "rest_status":"pass","mcp_status":"pass",
 "rsync_literal_bytes":server.get("rsync_literal_bytes",0),
 "rsync_total_sent_bytes":server.get("rsync_total_sent_bytes",0),
 "rsync_total_received_bytes":server.get("rsync_total_received_bytes",0),
}
Path(sys.argv[4]).write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
print(json.dumps(receipt,ensure_ascii=False))
PY
"${python_bin}" "${script_dir}/policy_increment_release.py" finalize \
  --prepared "${prepared}" --receipt "${final_receipt}" \
  >"${run_dir}/finalization-output.json"

release_completed=1
trap - EXIT
echo "政策冻结交接包增量正式发布完成：${run_dir}"
