#!/usr/bin/env bash
set -euo pipefail

mode="${1:-deploy}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_dir="$(cd "${script_dir}/.." && pwd)"
deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"
prepared_path="${JIAOTANG_POLICY_PREPARED_RELEASE:-}"
remote_index_root="${JIAOTANG_REMOTE_INDEX_ROOT:-/srv/jiaotang/knowledge-index}"
receipt_path="${JIAOTANG_POLICY_DEPLOY_RECEIPT:-}"

ssh_base=(ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}")

pause_verifiers() {
  "${ssh_base[@]}" \
    "systemctl disable --now jiaotang-kb-oss-verify.timer >/dev/null 2>&1 || true; \
     systemctl disable --now jiaotang-kb-policy-increment-verify.timer >/dev/null 2>&1 || true"
}

restore_legacy_verifier() {
  "${ssh_base[@]}" \
    "set -e; \
     systemctl disable --now jiaotang-kb-policy-increment-verify.timer >/dev/null 2>&1 || true; \
     if ! systemctl cat jiaotang-kb-oss-verify.timer >/dev/null 2>&1; then \
       install -m 0644 /opt/jiaotang-kb-runtime/current/deploy/jiaotang-kb-oss-verify.service /etc/systemd/system/; \
       install -m 0644 /opt/jiaotang-kb-runtime/current/deploy/jiaotang-kb-oss-verify.timer /etc/systemd/system/; \
       systemctl daemon-reload; \
     fi; \
     systemctl enable --now jiaotang-kb-oss-verify.timer >/dev/null"
}

install_verifier() {
  [[ -n "${prepared_path}" ]] || { echo "install-verifier需要JIAOTANG_POLICY_PREPARED_RELEASE" >&2; exit 64; }
  public_key="$(python3 - "${prepared_path}" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))["trusted_public_key"])
PY
)"
  verifier="${script_dir}/verify_policy_increment_server.py"
  service="${service_dir}/deploy/jiaotang-kb-policy-increment-verify.service"
  timer="${service_dir}/deploy/jiaotang-kb-policy-increment-verify.timer"
  verifier_sha="$(shasum -a 256 "${verifier}" | awk '{print $1}')"
  tar -C "${service_dir}" -cf - \
    scripts/verify_policy_increment_server.py \
    deploy/jiaotang-kb-policy-increment-verify.service \
    deploy/jiaotang-kb-policy-increment-verify.timer \
    | "${ssh_base[@]}" "set -e
      staging=\$(mktemp -d /var/lib/jiaotang-kb/policy-increment-install.XXXXXX)
      trap 'mv \"\${staging}\" /var/lib/jiaotang-kb/policy-increment-install-failed-\$(date +%s) 2>/dev/null || true' EXIT
      tar -C \"\${staging}\" -xf -
      actual=\$(sha256sum \"\${staging}/scripts/verify_policy_increment_server.py\" | awk '{print \$1}')
      [ \"\${actual}\" = '${verifier_sha}' ]
      install -m 0755 \"\${staging}/scripts/verify_policy_increment_server.py\" /usr/local/libexec/jiaotang-policy-increment-verify
      install -m 0644 \"\${staging}/deploy/jiaotang-kb-policy-increment-verify.service\" /etc/systemd/system/
      install -m 0644 \"\${staging}/deploy/jiaotang-kb-policy-increment-verify.timer\" /etc/systemd/system/
      mkdir -p /etc/jiaotang-kb
      systemctl daemon-reload
      trap - EXIT
      install_target=/var/lib/jiaotang-kb/policy-increment-install-${verifier_sha}
      if [ -e \"\${install_target}\" ]; then
        existing=\$(sha256sum \"\${install_target}/scripts/verify_policy_increment_server.py\" | awk '{print \$1}')
        [ \"\${existing}\" = '${verifier_sha}' ]
        mv \"\${staging}\" \"\${install_target}-repeat-\$(date +%s)-\$\$\"
      else
        mv \"\${staging}\" \"\${install_target}\"
      fi"
  remote_public_sha="$("${ssh_base[@]}" \
    "if [ -f /etc/jiaotang-kb/policy-increment-public.pem ]; then sha256sum /etc/jiaotang-kb/policy-increment-public.pem | awk '{print \$1}'; fi")"
  local_public_sha="$(shasum -a 256 "${public_key}" | awk '{print $1}')"
  if [[ -n "${remote_public_sha}" && "${remote_public_sha}" != "${local_public_sha}" ]]; then
    echo "服务器已存在不同政策增量链公钥，拒绝覆盖" >&2
    exit 1
  fi
  if [[ -z "${remote_public_sha}" ]]; then
    scp -i "${deploy_key}" -o BatchMode=yes "${public_key}" "${deploy_host}:/etc/jiaotang-kb/policy-increment-public.pem.tmp"
    "${ssh_base[@]}" \
      "install -m 0644 /etc/jiaotang-kb/policy-increment-public.pem.tmp /etc/jiaotang-kb/policy-increment-public.pem; \
       mv /etc/jiaotang-kb/policy-increment-public.pem.tmp /var/lib/jiaotang-kb/policy-increment-public-installed.pem"
  fi
  "${ssh_base[@]}" \
    "set -e; \
     systemctl disable --now jiaotang-kb-oss-verify.timer >/dev/null 2>&1 || true; \
     systemctl enable jiaotang-kb-policy-increment-verify.timer >/dev/null; \
     systemctl start jiaotang-kb-policy-increment-verify.service; \
     systemctl start jiaotang-kb-policy-increment-verify.timer"
}

rollback_release() {
  "${ssh_base[@]}" \
    "set -e; set -a; source /etc/jiaotang-kb-ops.env; set +a; \
     /opt/jiaotang-kb-runtime/current/.venv/bin/python \
       /opt/jiaotang-kb-runtime/current/scripts/refresh_index_from_oss.py --rollback; \
     systemctl restart jiaotang-kb; \
     curl --fail --silent --show-error --retry 20 --retry-delay 2 http://127.0.0.1:8100/health >/dev/null"
}

case "${mode}" in
  pause-verifiers)
    pause_verifiers
    exit 0
    ;;
  restore-legacy-verifier)
    restore_legacy_verifier
    exit 0
    ;;
  install-verifier)
    install_verifier
    exit 0
    ;;
  rollback)
    rollback_release
    exit 0
    ;;
  deploy)
    ;;
  *)
    echo "未知模式：${mode}" >&2
    exit 2
    ;;
esac

[[ -n "${prepared_path}" ]] || { echo "deploy需要JIAOTANG_POLICY_PREPARED_RELEASE" >&2; exit 64; }
[[ -n "${receipt_path}" ]] || receipt_path="$(dirname "${prepared_path}")/server-deploy-receipt.json"

IFS=$'\t' read -r candidate_dir release_id previous_release_id chain_sha index_sha manifest_sha < <(
  python3 - "${prepared_path}" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
print("\t".join(str(p[k]) for k in (
    "candidate_index_dir","release_id","previous_release_id","chain_sha256",
    "candidate_index_sha256","candidate_manifest_sha256",
)))
PY
)

for path in "${candidate_dir}/release.json" "${candidate_dir}/knowledge_content.sqlite3" "${candidate_dir}/manifest.jsonl"; do
  [[ -f "${path}" ]] || { echo "候选release缺少文件：${path}" >&2; exit 1; }
done

python3 - "${candidate_dir}" "${release_id}" "${index_sha}" "${manifest_sha}" <<'PY'
import hashlib,json,sqlite3,sys
from pathlib import Path
root=Path(sys.argv[1])
release=json.loads((root/"release.json").read_text())
if release.get("release_id") != sys.argv[2]: raise SystemExit("候选release_id不一致")
for name,expected in (("knowledge_content.sqlite3",sys.argv[3]),("manifest.jsonl",sys.argv[4])):
    h=hashlib.sha256()
    with (root/name).open("rb") as f:
        for block in iter(lambda:f.read(8*1024*1024),b""): h.update(block)
    if h.hexdigest()!=expected: raise SystemExit(f"候选{name}摘要不一致")
with sqlite3.connect(f"file:{root/'knowledge_content.sqlite3'}?mode=ro",uri=True) as db:
    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok": raise SystemExit("候选SQLite quick_check失败")
PY

readarray_output="$("${ssh_base[@]}" \
  "set -e; current=\$(readlink -f '${remote_index_root}/current'); previous=\$(readlink -f '${remote_index_root}/previous'); \
   printf '%s\t%s\n' \"\${current}\" \"\${previous}\"")"
IFS=$'\t' read -r remote_current remote_inactive <<<"${readarray_output}"
case "${remote_current}" in "${remote_index_root}"/releases/*) ;; *) echo "服务器current路径越界" >&2; exit 1;; esac
case "${remote_inactive}" in "${remote_index_root}"/releases/*) ;; *) echo "服务器previous路径越界" >&2; exit 1;; esac
[[ "${remote_current}" != "${remote_inactive}" ]] || { echo "服务器current与previous指向同一目录" >&2; exit 1; }

remote_target="${remote_index_root}/releases/${release_id}"
remote_current_relative="${remote_current#${remote_index_root}/}"
remote_target_relative="${remote_target#${remote_index_root}/}"
rsync_stats="$(dirname "${receipt_path}")/rsync-stats.txt"
mkdir -p "$(dirname "${receipt_path}")"

if [[ "$(basename "${remote_current}")" != "${release_id}" ]]; then
  if [[ "$(basename "${remote_inactive}")" == "${release_id}" ]]; then
    deployment_action="switched-existing"
    : > "${rsync_stats}"
  else
    deployment_action="switched"
    rsync --archive --no-owner --no-group --no-whole-file --checksum \
      --block-size=4096 --stats --partial-dir=.policy-rsync-partial \
      -e "ssh -i ${deploy_key} -o BatchMode=yes" \
      "${candidate_dir}/" "${deploy_host}:${remote_inactive}/" | tee "${rsync_stats}"
  fi
  "${ssh_base[@]}" "set -e
    activated=0
    atomic_link() {
      link_name=\"\$1\"
      link_target=\"\$2\"
      temporary='${remote_index_root}/.'\"\${link_name}\"'.policy-link-'\"\$\$\"
      ln -s \"\${link_target}\" \"\${temporary}\"
      mv -Tf \"\${temporary}\" '${remote_index_root}/'\"\${link_name}\"
    }
    rollback_on_error() {
      code=\"\$?\"
      trap - EXIT
      if [ \"\${activated}\" = 1 ]; then
        atomic_link current '${remote_current_relative}'
        atomic_link previous '${remote_target_relative}'
        systemctl restart jiaotang-kb || true
        curl --fail --silent --retry 20 --retry-delay 2 http://127.0.0.1:8100/health >/dev/null || true
        echo '政策增量release执行异常，已恢复切换前current' >&2
      fi
      exit \"\${code}\"
    }
    trap rollback_on_error EXIT
    python3 - '${remote_inactive}' '${release_id}' <<'PY'
import hashlib,json,sqlite3,sys
from pathlib import Path
root=Path(sys.argv[1])
release=json.loads((root/'release.json').read_text())
if release.get('release_id') != sys.argv[2]: raise SystemExit('服务器候选release_id不一致')
for row in release['files']:
    p=root/row['name']
    if not p.is_file() or p.stat().st_size != int(row['size']): raise SystemExit('服务器候选文件大小不一致:'+row['name'])
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''): h.update(block)
    if h.hexdigest()!=row['sha256']: raise SystemExit('服务器候选SHA-256不一致:'+row['name'])
with sqlite3.connect(f\"file:{root/'knowledge_content.sqlite3'}?mode=ro\",uri=True) as db:
    if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok': raise SystemExit('服务器候选SQLite校验失败')
PY
    if [ '${remote_inactive}' != '${remote_target}' ]; then
      [ ! -e '${remote_target}' ] || { echo '同名服务器release已存在，拒绝覆盖' >&2; exit 1; }
      mv '${remote_inactive}' '${remote_target}'
    fi
    activated=1
    atomic_link previous '${remote_current_relative}'
    atomic_link current '${remote_target_relative}'
    chown -R root:jiaotang '${remote_target}'
    find '${remote_target}' -type d -exec chmod 0750 {} +
    find '${remote_target}' -type f -exec chmod 0640 {} +
    systemctl restart jiaotang-kb
    healthy=0
    for attempt in \$(seq 1 30); do
      if curl --fail --silent http://127.0.0.1:8100/health >/dev/null 2>&1; then healthy=1; break; fi
      sleep 2
    done
    if [ \"\${healthy}\" -ne 1 ]; then
      echo '政策增量release健康失败，已自动回滚' >&2
      exit 1
    fi
    activated=0
    trap - EXIT"
else
  deployment_action="already-current"
  : > "${rsync_stats}"
fi

python3 - "${receipt_path}" "${release_id}" "${previous_release_id}" "${chain_sha}" \
  "${index_sha}" "${manifest_sha}" "${rsync_stats}" "${deployment_action}" <<'PY'
import json,re,sys
from datetime import datetime,timezone
from pathlib import Path
stats=Path(sys.argv[7]).read_text(errors='replace')
def value(labels):
    for label in labels:
        m=re.search(rf"^{re.escape(label)}:\s*([0-9,]+)",stats,re.M)
        if m:return int(m.group(1).replace(',',''))
    return 0
payload={
 'schema':'jiaotang-policy-increment-server-receipt/v1',
 'completed_at':datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),
 'release_id':sys.argv[2],'previous_release_id':sys.argv[3],'chain_sha256':sys.argv[4],
 'candidate_index_sha256':sys.argv[5],'candidate_manifest_sha256':sys.argv[6],
 'server_status':'healthy','deployment_action':sys.argv[8],
 'rsync_literal_bytes':value(('Literal data','Unmatched data')),
 'rsync_total_sent_bytes':value(('Total bytes sent','Total sent')),
 'rsync_total_received_bytes':value(('Total bytes received','Total received')),
}
Path(sys.argv[1]).write_text(json.dumps(payload,ensure_ascii=False,indent=2))
print(json.dumps(payload,ensure_ascii=False))
PY
