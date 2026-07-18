#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_dir="$(cd "${script_dir}/.." && pwd)"
repository_dir="$(cd "${service_dir}/../.." && pwd)"
deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置 JIAOTANG_DEPLOY_HOST，例如 root@server.example.com}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"
remote_app_dir="${JIAOTANG_REMOTE_APP_DIR:-/opt/jiaotang-kb}"
timestamp="$(date +%Y%m%d%H%M%S)"
remote_backup_dir="/opt/jiaotang-kb-backups/${timestamp}"
ssh_args=(
    -i "${deploy_key}"
    -o BatchMode=yes
    -o ConnectTimeout=15
    -o ConnectionAttempts=3
    -o ServerAliveInterval=15
    -o ServerAliveCountMax=4
)

for command in ssh tar; do
    command -v "${command}" >/dev/null || { echo "缺少命令：${command}" >&2; exit 1; }
done

echo "[1/6] 校验服务器环境变量"
ssh "${ssh_args[@]}" "${deploy_host}" "python3 - <<'PY'
from pathlib import Path

path = Path('/etc/jiaotang-kb.env')
values = {}
for line in path.read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
required = {
    'JIAOTANG_DATA_DIR',
    'JIAOTANG_INDEX_DIR',
    'JIAOTANG_KNOWLEDGE_FILES_DIR',
    'JIAOTANG_SKILL_RELEASE_DIR',
    'JIAOTANG_INDEX_SNAPSHOT_DIR',
    'JIAOTANG_MEMBER_COMPANY',
    'JIAOTANG_PUBLIC_HOST',
    'JIAOTANG_SECURE_COOKIES',
}
missing = sorted(key for key in required if not values.get(key))
if missing:
    raise SystemExit('缺少生产环境变量：' + ', '.join(missing))
if values['JIAOTANG_SECURE_COOKIES'].lower() != 'true':
    raise SystemExit('生产环境必须设置 JIAOTANG_SECURE_COOKIES=true')
print('环境变量校验通过')
PY"

echo "[2/6] 创建不可覆盖的部署备份"
ssh "${ssh_args[@]}" "${deploy_host}" \
    "install -d '${remote_backup_dir}' && cp -a '${remote_app_dir}/app' '${remote_app_dir}/templates' '${remote_app_dir}/static' '${remote_app_dir}/requirements.txt' '${remote_backup_dir}/' && if [ -d '${remote_app_dir}/docs' ]; then cp -a '${remote_app_dir}/docs' '${remote_backup_dir}/'; fi"

echo "[3/6] 上传应用与运维文件"
deployment_failed=0
COPYFILE_DISABLE=1 tar --no-xattrs -C "${service_dir}" -cf - \
    app templates static deploy scripts/build_knowledge_content_index.py \
    scripts/smoke_test_production.sh requirements.txt \
    -C "${repository_dir}" docs/user-guide/项目申报助手用户使用手册.md \
    | ssh "${ssh_args[@]}" "${deploy_host}" "tar -C '${remote_app_dir}' -xf -" \
    || deployment_failed=1

echo "[4/6] 校验并重启服务"
if [[ "${deployment_failed}" -eq 0 ]]; then
    ssh "${ssh_args[@]}" "${deploy_host}" "set -e
        systemctl stop jiaotang-kb-health.timer jiaotang-kb-backup.timer
        REMOTE_APP_DIR='${remote_app_dir}' METADATA_QUARANTINE='/opt/jiaotang-kb-quarantine/macos-metadata-${timestamp}' python3 - <<'PY'
import os
from pathlib import Path

root = Path(os.environ['REMOTE_APP_DIR'])
quarantine = Path(os.environ['METADATA_QUARANTINE'])
for path in sorted(root.rglob('*')):
    if path.is_file() and (path.name.startswith('._') or path.name == '.DS_Store'):
        target = quarantine / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
PY
        install -m 0755 '${remote_app_dir}/deploy/healthcheck.sh' '/usr/local/sbin/jiaotang-kb-healthcheck.${timestamp}'
        install -m 0755 '${remote_app_dir}/deploy/backup.sh' '/usr/local/sbin/jiaotang-kb-backup.${timestamp}'
        install -m 0755 '${remote_app_dir}/scripts/smoke_test_production.sh' '/usr/local/sbin/jiaotang-kb-smoke-test.${timestamp}'
        mv '/usr/local/sbin/jiaotang-kb-healthcheck.${timestamp}' /usr/local/sbin/jiaotang-kb-healthcheck
        mv '/usr/local/sbin/jiaotang-kb-backup.${timestamp}' /usr/local/sbin/jiaotang-kb-backup
        mv '/usr/local/sbin/jiaotang-kb-smoke-test.${timestamp}' /usr/local/sbin/jiaotang-kb-smoke-test
        cp '${remote_app_dir}/deploy/jiaotang-kb-health.service' '${remote_app_dir}/deploy/jiaotang-kb-backup.service' /etc/systemd/system/
        chown -R jiaotang:jiaotang '${remote_app_dir}/app' '${remote_app_dir}/templates' '${remote_app_dir}/static' '${remote_app_dir}/docs'
        SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt '${remote_app_dir}/.venv/bin/pip' install -r '${remote_app_dir}/requirements.txt'
        '${remote_app_dir}/.venv/bin/python' -m py_compile '${remote_app_dir}/app/main.py'
        systemctl daemon-reload
        systemctl restart jiaotang-kb
        systemctl enable --now jiaotang-kb-health.timer jiaotang-kb-backup.timer
        sleep 2
        curl --fail --silent --show-error http://127.0.0.1:8100/health >/dev/null
        systemctl start jiaotang-kb-health.service
        systemctl start jiaotang-kb-backup.service" || deployment_failed=1
fi

if [[ "${deployment_failed}" -ne 0 ]]; then
    echo "部署失败，正在恢复 ${remote_backup_dir}" >&2
    ssh "${ssh_args[@]}" "${deploy_host}" \
        "cp -a '${remote_backup_dir}/app/.' '${remote_app_dir}/app/' && cp -a '${remote_backup_dir}/templates/.' '${remote_app_dir}/templates/' && cp -a '${remote_backup_dir}/static/.' '${remote_app_dir}/static/' && cp -a '${remote_backup_dir}/requirements.txt' '${remote_app_dir}/requirements.txt' && if [ -d '${remote_backup_dir}/docs' ]; then install -d '${remote_app_dir}/docs' && cp -a '${remote_backup_dir}/docs/.' '${remote_app_dir}/docs/'; fi && SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt '${remote_app_dir}/.venv/bin/pip' install -r '${remote_app_dir}/requirements.txt' && systemctl restart jiaotang-kb"
    exit 1
fi

echo "[5/6] 检查固定路由"
ssh "${ssh_args[@]}" "${deploy_host}" "set -e
    source /etc/jiaotang-kb.env
    resolve=(--resolve \"\${JIAOTANG_PUBLIC_HOST}:443:127.0.0.1\")
    test \"\$(curl -sS -o /dev/null -w '%{http_code}' \"\${resolve[@]}\" \"https://\${JIAOTANG_PUBLIC_HOST}/login\")\" = 200
    test \"\$(curl -sS -o /dev/null -w '%{http_code}' \"\${resolve[@]}\" \"https://\${JIAOTANG_PUBLIC_HOST}/setup\")\" = 303
    test \"\$(curl -sS -o /dev/null -w '%{http_code}' \"\${resolve[@]}\" \"https://\${JIAOTANG_PUBLIC_HOST}/v1/me\")\" = 401
    test \"\$(curl -sS -o /dev/null -w '%{http_code}' \"\${resolve[@]}\" \"https://\${JIAOTANG_PUBLIC_HOST}/mcp/\")\" = 401"

ssh "${ssh_args[@]}" "${deploy_host}" "set -e; source /etc/jiaotang-kb.env; curl --fail --silent --show-error --resolve \"\${JIAOTANG_PUBLIC_HOST}:443:127.0.0.1\" \"https://\${JIAOTANG_PUBLIC_HOST}/guide\" >/dev/null"

echo "[6/6] 部署完成：${timestamp}"
echo "备份目录：${remote_backup_dir}"
