#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deployment_id="${1:?用法：resume_application_deployment.sh DEPLOYMENT_ID}"
deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"

ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
    "systemctl reset-failed \
        'jiaotang-kb-application-deploy@${deployment_id}.service' \
        >/dev/null 2>&1 || true
     systemctl start --no-block \
        'jiaotang-kb-application-deploy@${deployment_id}.service'"

exec python3 "${script_dir}/wait_for_application_deployment.py" \
    --host "${deploy_host}" \
    --key "${deploy_key}" \
    --deployment-id "${deployment_id}" \
    --timeout-seconds "${JIAOTANG_DEPLOY_RECEIPT_TIMEOUT_SECONDS:-420}"
