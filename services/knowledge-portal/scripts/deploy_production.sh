#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_dir="$(cd "${script_dir}/.." && pwd)"
repository_dir="$(cd "${service_dir}/../.." && pwd)"
release_mode="${JIAOTANG_RELEASE_MODE:-}"
case "${release_mode}" in
    code|index) ;;
    *)
        echo "必须显式设置 JIAOTANG_RELEASE_MODE=code 或 index。" >&2
        exit 74
        ;;
esac
if [[ -n "${JIAOTANG_INDEX_ALREADY_DEPLOYED:-}" ]]; then
    echo "JIAOTANG_INDEX_ALREADY_DEPLOYED 已停用；请使用显式发布模式。" >&2
    exit 74
fi
index_rollback_enabled=0
if [[ "${release_mode}" == "index" ]]; then
    index_rollback_enabled=1
fi
if [[ "${JIAOTANG_DEPLOY_LOCK_HELD:-false}" != "true" ]]; then
    exec python3 "${script_dir}/with_deployment_lock.py" \
        --lock-file "${JIAOTANG_DEPLOY_LOCK_FILE:-${HOME}/.cache/jiaotang/deploy-production.lock}" \
        -- "$0" "$@"
fi

canonical_deploy_root="$(
    git -C "${repository_dir}" config --local --get jiaotang.deployWorktree \
        2>/dev/null || true
)"
if [[ -z "${canonical_deploy_root}" && "${JIAOTANG_ALLOW_NONCANONICAL_DEPLOY:-false}" != "true" ]]; then
    echo "拒绝部署：未配置唯一正式工作树 jiaotang.deployWorktree。" >&2
    exit 76
fi
if [[ -n "${canonical_deploy_root}" && "${JIAOTANG_ALLOW_NONCANONICAL_DEPLOY:-false}" != "true" ]]; then
    canonical_deploy_root="$(cd "${canonical_deploy_root}" && pwd -P)"
    current_deploy_root="$(cd "${repository_dir}" && pwd -P)"
    if [[ "${current_deploy_root}" != "${canonical_deploy_root}" ]]; then
        echo "拒绝从非正式工作树部署生产环境。" >&2
        echo "正式部署源：${canonical_deploy_root}" >&2
        echo "当前工作树：${current_deploy_root}" >&2
        exit 76
    fi
fi

if git -C "${repository_dir}" show-ref --verify --quiet refs/remotes/origin/main; then
    if ! git -C "${repository_dir}" merge-base --is-ancestor origin/main HEAD; then
        echo "拒绝部署：当前正式工作树尚未合入最新 origin/main。" >&2
        exit 77
    fi
fi

deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置 JIAOTANG_DEPLOY_HOST，例如 root@server.example.com}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"
wheelhouse_dir="${JIAOTANG_WHEELHOUSE_DIR:?请提供受控CI生成的生产wheelhouse目录}"
expected_wheelhouse_manifest_sha256="${JIAOTANG_EXPECTED_WHEELHOUSE_MANIFEST_SHA256:?请提供受控CI记录的wheelhouse manifest SHA-256}"
dependency_release_record="${JIAOTANG_DEPENDENCY_RELEASE_RECORD:?请提供main分支CI生成的依赖发布记录}"
legacy_app_dir="${JIAOTANG_REMOTE_APP_DIR:-/opt/jiaotang-kb}"
runtime_root="${JIAOTANG_REMOTE_RUNTIME_ROOT:-/opt/jiaotang-kb-runtime}"
release_root="${JIAOTANG_REMOTE_RELEASE_ROOT:-/opt/jiaotang-kb-release-slots}"
build_commit="$(git -C "${repository_dir}" rev-parse HEAD)"
skill_release_version="$(python3 - "${repository_dir}/skills/suite-manifest.json" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
version = str((manifest.get("release") or {}).get("version") or "")
if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
    raise SystemExit("skills/suite-manifest.json 缺少合法 release.version")
print(version)
PY
)"
build_created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
deployment_id="${timestamp}-${build_commit:0:12}-$(
    python3 -c 'import secrets; print(secrets.token_hex(4))'
)"
remote_release_dir="${release_root}/${deployment_id}"
echo "本轮应用部署编号：${deployment_id}"
echo "控制端中断后可用 scripts/resume_application_deployment.sh ${deployment_id} 续验。"
if [[ "${JIAOTANG_UPGRADE_INDEX:-false}" == "true" ]]; then
    echo "原地索引升级已停用；请构建、签名并发布新的不可变索引release。" >&2
    exit 78
fi
ssh_args=(
    -i "${deploy_key}"
    -o BatchMode=yes
    -o ConnectTimeout=15
    -o ConnectionAttempts=3
    -o ServerAliveInterval=15
    -o ServerAliveCountMax=4
)
transfer_stall_timeout_seconds="${JIAOTANG_DEPLOY_TRANSFER_STALL_TIMEOUT_SECONDS:-60}"
transfer_completion_timeout_seconds="${JIAOTANG_DEPLOY_TRANSFER_COMPLETION_TIMEOUT_SECONDS:-120}"

for command in ssh tar; do
    command -v "${command}" >/dev/null || {
        echo "缺少命令：${command}" >&2
        exit 1
    }
done

if [[ ! "${expected_wheelhouse_manifest_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "JIAOTANG_EXPECTED_WHEELHOUSE_MANIFEST_SHA256格式非法。" >&2
    exit 79
fi
wheelhouse_dir="$(cd "${wheelhouse_dir}" && pwd -P)"
dependency_release_record="$(
    cd "$(dirname "${dependency_release_record}")" \
        && printf '%s/%s\n' "$(pwd -P)" "$(basename "${dependency_release_record}")"
)"
if [[ ! -f "${dependency_release_record}" || -L "${dependency_release_record}" ]]; then
    echo "依赖发布记录必须是普通文件。" >&2
    exit 80
fi
if [[ "$(basename "${dependency_release_record}")" != \
    "portal-production-dependency-release-record.json" ]]; then
    echo "依赖发布记录文件名不符合受控CI协议。" >&2
    exit 81
fi
dependency_identity_json="$(
    python3 "${service_dir}/scripts/python_supply_chain.py" verify \
        --lock "${service_dir}/requirements.lock" \
        --build-lock "${service_dir}/requirements-build.lock" \
        --wheelhouse "${wheelhouse_dir}" \
        --expected-manifest-sha256 \
        "${expected_wheelhouse_manifest_sha256}" \
        --allow-foreign-runtime
)"
dependency_lock_sha256="$(
    python3 -c \
        'import json,sys; print(json.loads(sys.argv[1])["dependency_lock_sha256"])' \
        "${dependency_identity_json}"
)"
dependency_build_lock_sha256="$(
    python3 -c \
        'import json,sys; print(json.loads(sys.argv[1])["dependency_build_lock_sha256"])' \
        "${dependency_identity_json}"
)"
wheelhouse_install_lock_sha256="$(
    python3 -c \
        'import json,sys; print(json.loads(sys.argv[1])["wheelhouse_install_lock_sha256"])' \
        "${dependency_identity_json}"
)"
wheelhouse_content_identity_sha256="$(
    python3 -c \
        'import json,sys; print(json.loads(sys.argv[1])["wheelhouse_content_identity_sha256"])' \
        "${dependency_identity_json}"
)"
dependency_identity_sha256="$(
    python3 -c \
        'import json,sys; print(json.loads(sys.argv[1])["dependency_identity_sha256"])' \
        "${dependency_identity_json}"
)"
dependency_release_record_sha256="$(
    python3 - "${dependency_release_record}" "${build_commit}" \
        "${expected_wheelhouse_manifest_sha256}" \
        "${dependency_identity_json}" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SystemExit(f"依赖发布记录包含重复字段：{key}")
        result[key] = value
    return result


path = Path(sys.argv[1])
payload = path.read_bytes()
record = json.loads(payload, object_pairs_hook=reject_duplicates)
identity = json.loads(sys.argv[4], object_pairs_hook=reject_duplicates)
expected = {
    "schema_version": 1,
    "artifact_type": "jiaotang-python-dependency-release-record",
    "source_commit": sys.argv[2],
    "source_event": "push",
    "source_ref": "refs/heads/main",
    "dependency_identity": identity,
}
for key, value in expected.items():
    if record.get(key) != value:
        raise SystemExit(f"依赖发布记录字段不匹配：{key}")
if identity.get("wheelhouse_manifest_sha256") != sys.argv[3]:
    raise SystemExit("依赖发布记录与外部绑定的manifest摘要不一致")
if not re.fullmatch(r"[0-9]+", str(record.get("workflow_run_id") or "")):
    raise SystemExit("依赖发布记录缺少合法workflow_run_id")
if not re.fullmatch(r"[0-9]+", str(record.get("workflow_run_attempt") or "")):
    raise SystemExit("依赖发布记录缺少合法workflow_run_attempt")
allowed = {*expected, "workflow_run_id", "workflow_run_attempt"}
if set(record) != allowed:
    raise SystemExit("依赖发布记录字段集合不符合固定协议")
print(hashlib.sha256(payload).hexdigest())
PY
)"

python3 "${service_dir}/scripts/build_static_assets.py"

echo "[1/8] 校验本地技能签名和生产环境"
python3 "${service_dir}/scripts/python_supply_chain.py" \
    lock-metadata-verify --portal-dir "${service_dir}" >/dev/null
python3 "${service_dir}/scripts/verify_skill_signature_coverage.py" \
    --skills-root "${repository_dir}/skills" \
    --release-mode "${release_mode}"
ssh "${ssh_args[@]}" "${deploy_host}" "set -e
    SOURCE_ENV=/etc/jiaotang-kb-ops.env
    [ -f \"\${SOURCE_ENV}\" ] || SOURCE_ENV=/etc/jiaotang-kb.env
    [ -f \"\${SOURCE_ENV}\" ] || { echo '缺少生产环境文件' >&2; exit 1; }
    SOURCE_ENV=\"\${SOURCE_ENV}\" python3 - <<'PY'
import os
import platform
import sys
from pathlib import Path

if platform.python_implementation() != 'CPython' or sys.version_info[:2] != (3, 12):
    raise SystemExit(
        '生产主机必须提供CPython 3.12，当前为'
        f'{platform.python_implementation()} {platform.python_version()}'
    )
path = Path(os.environ['SOURCE_ENV'])
values = {}
for line in path.read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
required = {
    'JIAOTANG_DATA_DIR',
    'JIAOTANG_INDEX_DIR',
    'JIAOTANG_KNOWLEDGE_FILES_DIR',
    'JIAOTANG_SKILL_RELEASE_DIR',
    'JIAOTANG_MEMBER_COMPANY',
    'JIAOTANG_PUBLIC_HOST',
    'JIAOTANG_TOKEN_DERIVATION_SECRET',
    'JIAOTANG_SECURE_COOKIES',
    'JIAOTANG_OSS_ENDPOINT',
    'JIAOTANG_OSS_BUCKET',
}
missing = sorted(key for key in required if not values.get(key))
if missing:
    raise SystemExit('缺少生产环境变量：' + ', '.join(missing))
mode = values.get('JIAOTANG_OSS_AUTH_MODE', 'static').lower()
auth_required = {
    'static': {'JIAOTANG_OSS_ACCESS_KEY_ID', 'JIAOTANG_OSS_ACCESS_KEY_SECRET'},
    'sts': {
        'JIAOTANG_OSS_ACCESS_KEY_ID',
        'JIAOTANG_OSS_ACCESS_KEY_SECRET',
        'JIAOTANG_OSS_SECURITY_TOKEN',
    },
    'ram-role': {'JIAOTANG_OSS_RAM_ROLE_AUTH_HOST'},
}.get(mode)
if auth_required is None:
    raise SystemExit('JIAOTANG_OSS_AUTH_MODE仅支持static、sts或ram-role')
missing_auth = sorted(key for key in auth_required if not values.get(key))
if missing_auth:
    raise SystemExit('OSS认证配置缺失：' + ', '.join(missing_auth))
if values['JIAOTANG_SECURE_COOKIES'].lower() != 'true':
    raise SystemExit('生产环境必须设置 JIAOTANG_SECURE_COOKIES=true')
PY"

echo "[2/8] 创建唯一不可变应用release槽"
ssh "${ssh_args[@]}" "${deploy_host}" \
    "LEGACY_APP_DIR='${legacy_app_dir}' RUNTIME_ROOT='${runtime_root}' RELEASE_DIR='${remote_release_dir}' python3 - <<'PY'
import os
import secrets
from pathlib import Path

legacy = Path(os.environ['LEGACY_APP_DIR'])
runtime = Path(os.environ['RUNTIME_ROOT'])
release = Path(os.environ['RELEASE_DIR'])
runtime.mkdir(parents=True, exist_ok=True)
current = runtime / 'current'
if not current.is_symlink():
    if current.exists():
        raise SystemExit(f'运行时current存在但不是符号链接：{current}')
    if not (legacy / 'app' / 'main.py').is_file():
        raise SystemExit(f'首次槽位化缺少可用legacy-current：{legacy}')
    temporary = runtime / f'.current.{os.getpid()}.{secrets.token_hex(4)}.tmp'
    temporary.symlink_to(legacy)
    os.replace(temporary, current)
resolved = current.resolve(strict=True)
if not (resolved / 'app' / 'main.py').is_file():
    raise SystemExit(f'current不是有效应用release：{resolved}')
if release.exists() or release.is_symlink():
    raise SystemExit(f'不可变应用release已存在，拒绝覆盖：{release}')
release.mkdir(parents=True, mode=0o755)
PY"

COPYFILE_DISABLE=1 tar --no-xattrs -C "${service_dir}" -cf - \
    app references templates static installers deploy \
    scripts/build_knowledge_content_index.py \
    scripts/build_knowledge_inventory_from_manifest.py \
    scripts/build_cloud_upload_allowlist.py \
    scripts/run_acceptance_harness.py \
    scripts/oss_incremental_sync.py scripts/archive_index_snapshots.py \
    scripts/refresh_index_from_oss.py scripts/publish_index_to_oss.py \
    scripts/release_retention.py \
    scripts/oss_reconciliation.py \
    scripts/stream_to_command.py \
    scripts/release_progress.py \
    scripts/oss_auth.py scripts/verify_acceptance_receipt.py \
    scripts/verify_index_release_binding.py \
    scripts/verify_policy_increment_server.py \
    scripts/validate_operational_health.py scripts/report_systemd_failure.py \
    scripts/health_recovery_state.py \
    scripts/check_oss_governance.py scripts/deploy_index_delta_to_server.sh \
    scripts/verify_oss_mirror.py scripts/verify_authenticated_portal.py \
    scripts/verify_skill_signature_coverage.py \
    scripts/run_application_deployment.py \
    scripts/build_policy_version_links.py \
    scripts/manage_project_algorithm_packs.py \
    scripts/validate_project_algorithm_packs.py \
    scripts/upgrade_structured_knowledge_index.py \
    scripts/evaluate_structured_knowledge.py \
    scripts/project_catalog_matching.py \
    scripts/migrate_first_public_release.py scripts/publish_skill_release.py \
    scripts/reconcile_release_metadata.py \
    scripts/audit_release_locations.py \
    scripts/release_transaction.py scripts/smoke_test_production.sh \
    scripts/python_supply_chain.py \
    tests/fixtures/structured_knowledge_gold.jsonl \
    requirements.txt requirements.in requirements.lock \
    requirements-build.in requirements-build.lock \
    requirements-test.in requirements-test.lock \
    requirements-lock-metadata.json \
    -C "${repository_dir}" \
    skills \
    | python3 "${script_dir}/stream_to_command.py" \
        --label application-source \
        --stall-timeout-seconds "${transfer_stall_timeout_seconds}" \
        --completion-timeout-seconds "${transfer_completion_timeout_seconds}" \
        -- ssh "${ssh_args[@]}" "${deploy_host}" \
        "tar -C '${remote_release_dir}' -xf -"
ssh "${ssh_args[@]}" "${deploy_host}" \
    "mkdir '${remote_release_dir}/dependency-wheelhouse'"
COPYFILE_DISABLE=1 tar --no-xattrs -C "${wheelhouse_dir}" -cf - . \
    | python3 "${script_dir}/stream_to_command.py" \
        --label dependency-wheelhouse \
        --stall-timeout-seconds "${transfer_stall_timeout_seconds}" \
        --completion-timeout-seconds "${transfer_completion_timeout_seconds}" \
        -- ssh "${ssh_args[@]}" "${deploy_host}" \
        "tar -C '${remote_release_dir}/dependency-wheelhouse' -xf -"
COPYFILE_DISABLE=1 tar --no-xattrs \
    -C "$(dirname "${dependency_release_record}")" -cf - \
    "$(basename "${dependency_release_record}")" \
    | python3 "${script_dir}/stream_to_command.py" \
        --label dependency-release-record \
        --stall-timeout-seconds "${transfer_stall_timeout_seconds}" \
        --completion-timeout-seconds "${transfer_completion_timeout_seconds}" \
        -- ssh "${ssh_args[@]}" "${deploy_host}" \
        "tar -C '${remote_release_dir}' -xf -"

private_overlay_identity_sha256="$(
    ssh "${ssh_args[@]}" "${deploy_host}" \
        "RUNTIME_ROOT='${runtime_root}' RELEASE_DIR='${remote_release_dir}' python3 - <<'PY'
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

runtime = Path(os.environ['RUNTIME_ROOT'])
release = Path(os.environ['RELEASE_DIR'])
current = (runtime / 'current').resolve(strict=True)
allowlist = (
    Path('app/kindle_library.py'),
    Path('templates/admin_kindle.html'),
    Path('templates/kindle_public.html'),
    Path('templates/_private_admin_nav.html'),
    Path('static/kindle.css'),
)
files = []
for relative in allowlist:
    source = current / relative
    if not source.exists():
        continue
    source_stat = source.lstat()
    if not stat.S_ISREG(source_stat.st_mode) or source.is_symlink():
        raise SystemExit(f'私有覆盖层只接受普通文件：{source}')
    if source_stat.st_size > 2 * 1024 * 1024:
        raise SystemExit(f'私有覆盖层文件异常过大：{source}')
    destination = release / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o640)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    files.append(
        {
            'path': relative.as_posix(),
            'sha256': digest,
            'size': destination.stat().st_size,
        }
    )
guard = Path(
    '/etc/systemd/system/jiaotang-kb.service.d/90-private-admin.conf'
)
if guard.is_file() and not (release / 'app/kindle_library.py').is_file():
    raise SystemExit('私有管理员启动守卫已启用，但新release缺少Kindle覆盖层')
manifest = {
    'schema': 'jiaotang-private-overlay/v1',
    'files': files,
}
payload = (
    json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    + '\n'
).encode('utf-8')
(release / 'private-overlay-manifest.json').write_bytes(payload)
print(hashlib.sha256(payload).hexdigest())
PY"
)"

echo "[3/8] 离线校验新release并验证轻量指针回执（${release_mode}）"
ssh "${ssh_args[@]}" "${deploy_host}" "set -e
    python3 '${remote_release_dir}/scripts/python_supply_chain.py' \
        lock-metadata-verify --portal-dir '${remote_release_dir}' >/dev/null
    python3 -m venv '${remote_release_dir}/.venv'
    PIP_NO_INDEX=1 '${remote_release_dir}/.venv/bin/python' \
        '${remote_release_dir}/scripts/python_supply_chain.py' install \
        --lock '${remote_release_dir}/requirements.lock' \
        --build-lock '${remote_release_dir}/requirements-build.lock' \
        --wheelhouse '${remote_release_dir}/dependency-wheelhouse' \
        --expected-manifest-sha256 \
        '${expected_wheelhouse_manifest_sha256}'
    '${remote_release_dir}/.venv/bin/python' -m py_compile \
        '${remote_release_dir}/app/main.py'
    '${remote_release_dir}/.venv/bin/python' \
        '${remote_release_dir}/scripts/verify_skill_signature_coverage.py' \
        --skills-root '${remote_release_dir}/skills' \
        --release-mode '${release_mode}'
    SOURCE_ENV=/etc/jiaotang-kb-ops.env
    [ -f \"\${SOURCE_ENV}\" ] || SOURCE_ENV=/etc/jiaotang-kb.env
    set -a
    source \"\${SOURCE_ENV}\"
    set +a
    INDEX_STORAGE_MODE=\$(python3 - \"\${JIAOTANG_INDEX_DIR}\" <<'PY'
import json
import sys
from pathlib import Path

release = Path(sys.argv[1]) / 'current' / 'release.json'
payload = json.loads(release.resolve(strict=True).read_text(encoding='utf-8'))
print(str(payload.get('storage_mode') or 'full-index-release'))
PY
    )
    if [ \"\${INDEX_STORAGE_MODE}\" = 'signed-policy-delta-chain-v1' ]; then
        JIAOTANG_APP_DIR='${remote_release_dir}' \
            '${remote_release_dir}/.venv/bin/python' \
            '${remote_release_dir}/scripts/verify_policy_increment_server.py' \
            --index-root \"\${JIAOTANG_INDEX_DIR}\"
    else
        '${remote_release_dir}/.venv/bin/python' \
            '${remote_release_dir}/scripts/verify_index_release_binding.py' \
            --index-root \"\${JIAOTANG_INDEX_DIR}\" \
            --profile '${remote_release_dir}/references/acceptance-harness/knowledge-base.json'
    fi
    chmod -R a-w '${remote_release_dir}'
    find '${remote_release_dir}' -type d -exec chmod a+rx {} +
    find '${remote_release_dir}' -type f -exec chmod a+r {} +
    if [ -x /usr/local/sbin/jiaotang-kb-private-admin-guard ]; then
        JIAOTANG_APP_DIR='${remote_release_dir}' \
            /usr/local/sbin/jiaotang-kb-private-admin-guard
    fi"

echo "[4/8] 写入职责分离环境并安装release感知入口"
ssh "${ssh_args[@]}" "${deploy_host}" \
    "BUILD_COMMIT='${build_commit}' DEPLOYMENT_ID='${deployment_id}' \
    BUILD_CREATED_AT='${build_created_at}' RUNTIME_ROOT='${runtime_root}' \
    DEPENDENCY_LOCK_SHA256='${dependency_lock_sha256}' \
    DEPENDENCY_BUILD_LOCK_SHA256='${dependency_build_lock_sha256}' \
    WHEELHOUSE_INSTALL_LOCK_SHA256='${wheelhouse_install_lock_sha256}' \
    WHEELHOUSE_MANIFEST_SHA256='${expected_wheelhouse_manifest_sha256}' \
    WHEELHOUSE_CONTENT_IDENTITY_SHA256='${wheelhouse_content_identity_sha256}' \
    DEPENDENCY_IDENTITY_SHA256='${dependency_identity_sha256}' \
    DEPENDENCY_RELEASE_RECORD_SHA256='${dependency_release_record_sha256}' \
    PRIVATE_OVERLAY_IDENTITY_SHA256='${private_overlay_identity_sha256}' \
    RELEASE_DIR='${remote_release_dir}' python3 - <<'PY'
import grp
import json
import os
import secrets
import shutil
from pathlib import Path

legacy_env = Path('/etc/jiaotang-kb.env')
ops_env = Path('/etc/jiaotang-kb-ops.env')
app_env = Path('/etc/jiaotang-kb-app.env')
source = ops_env if ops_env.is_file() else legacy_env
lines = []
for line in source.read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        lines.append((key.strip(), value.strip()))
values = dict(lines)
if not values.get('JIAOTANG_OSS_RELEASE_SIGNING_SECRET'):
    lines.append(
        ('JIAOTANG_OSS_RELEASE_SIGNING_SECRET', secrets.token_urlsafe(48))
    )
overrides = {
    'JIAOTANG_APP_DIR': str(Path(os.environ['RUNTIME_ROOT']) / 'current'),
    'JIAOTANG_BUILD_COMMIT': os.environ['BUILD_COMMIT'],
    'JIAOTANG_DEPLOYMENT_ID': os.environ['DEPLOYMENT_ID'],
    'JIAOTANG_BUILD_CREATED_AT': os.environ['BUILD_CREATED_AT'],
    'JIAOTANG_DEPENDENCY_LOCK_SHA256': os.environ[
        'DEPENDENCY_LOCK_SHA256'
    ],
    'JIAOTANG_DEPENDENCY_BUILD_LOCK_SHA256': os.environ[
        'DEPENDENCY_BUILD_LOCK_SHA256'
    ],
    'JIAOTANG_WHEELHOUSE_INSTALL_LOCK_SHA256': os.environ[
        'WHEELHOUSE_INSTALL_LOCK_SHA256'
    ],
    'JIAOTANG_WHEELHOUSE_MANIFEST_SHA256': os.environ[
        'WHEELHOUSE_MANIFEST_SHA256'
    ],
    'JIAOTANG_WHEELHOUSE_CONTENT_IDENTITY_SHA256': os.environ[
        'WHEELHOUSE_CONTENT_IDENTITY_SHA256'
    ],
    'JIAOTANG_DEPENDENCY_IDENTITY_SHA256': os.environ[
        'DEPENDENCY_IDENTITY_SHA256'
    ],
    'JIAOTANG_DEPENDENCY_RELEASE_RECORD_SHA256': os.environ[
        'DEPENDENCY_RELEASE_RECORD_SHA256'
    ],
    'JIAOTANG_PRIVATE_OVERLAY_IDENTITY_SHA256': os.environ[
        'PRIVATE_OVERLAY_IDENTITY_SHA256'
    ],
}
deployment_state_dir = Path('/var/lib/jiaotang-kb/deployments')
deployment_state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
previous_build_path = deployment_state_dir / (
    os.environ['DEPLOYMENT_ID'] + '.previous-build.json'
)
previous_build = {
    'commit': values.get('JIAOTANG_BUILD_COMMIT'),
    'deployment_id': values.get('JIAOTANG_DEPLOYMENT_ID'),
    'built_at': values.get('JIAOTANG_BUILD_CREATED_AT'),
    'dependency_lock_sha256': values.get('JIAOTANG_DEPENDENCY_LOCK_SHA256'),
    'dependency_build_lock_sha256': values.get(
        'JIAOTANG_DEPENDENCY_BUILD_LOCK_SHA256'
    ),
    'wheelhouse_install_lock_sha256': values.get(
        'JIAOTANG_WHEELHOUSE_INSTALL_LOCK_SHA256'
    ),
    'wheelhouse_manifest_sha256': values.get(
        'JIAOTANG_WHEELHOUSE_MANIFEST_SHA256'
    ),
    'wheelhouse_content_identity_sha256': values.get(
        'JIAOTANG_WHEELHOUSE_CONTENT_IDENTITY_SHA256'
    ),
    'dependency_identity_sha256': values.get(
        'JIAOTANG_DEPENDENCY_IDENTITY_SHA256'
    ),
    'dependency_release_record_sha256': values.get(
        'JIAOTANG_DEPENDENCY_RELEASE_RECORD_SHA256'
    ),
    'private_overlay_identity_sha256': values.get(
        'JIAOTANG_PRIVATE_OVERLAY_IDENTITY_SHA256'
    ),
}
previous_build_temporary = previous_build_path.with_name(
    f'.{previous_build_path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp'
)
previous_build_temporary.write_text(
    json.dumps(previous_build, ensure_ascii=False, sort_keys=True) + '\n',
    encoding='utf-8',
)
os.chmod(previous_build_temporary, 0o600)
os.replace(previous_build_temporary, previous_build_path)
lines = [(key, value) for key, value in lines if key not in overrides]
lines.extend(overrides.items())
ops_text = ''.join(f'{key}={value}\n' for key, value in lines)
app_text = ''.join(
    f'{key}={value}\n'
    for key, value in lines
    if not key.startswith('JIAOTANG_OSS_')
    and not key.startswith('JIAOTANG_BACKUP_OSS_')
)
for target, content, mode in (
    (
        deployment_state_dir
        / (os.environ['DEPLOYMENT_ID'] + '.candidate-ops.env'),
        ops_text,
        0o600,
    ),
    (
        deployment_state_dir
        / (os.environ['DEPLOYMENT_ID'] + '.candidate-app.env'),
        app_text,
        0o600,
    ),
):
    temporary = target.with_name(
        f'.{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp'
    )
    temporary.write_text(content, encoding='utf-8')
    os.chmod(temporary, mode)
    os.replace(temporary, target)
if app_env.is_file():
    os.chown(app_env, 0, grp.getgrnam('jiaotang').gr_gid)
if legacy_env.is_file():
    os.chmod(legacy_env, 0o600)

runtime = Path(os.environ['RUNTIME_ROOT'])
release = Path(os.environ['RELEASE_DIR'])
legacy_entries = runtime / 'legacy-entrypoints'
unit_names = (
    'jiaotang-kb.service',
    'jiaotang-kb-health.service',
    'jiaotang-kb-health.timer',
    'jiaotang-kb-health-recovery@.service',
    'jiaotang-kb-backup.service',
    'jiaotang-kb-backup.timer',
    'jiaotang-kb-index-refresh.service',
    'jiaotang-kb-oss-verify.service',
    'jiaotang-kb-oss-verify.timer',
    'jiaotang-kb-failure-report@.service',
    'jiaotang-kb-oss-sync.service',
    'jiaotang-kb-oss-sync.timer',
    'jiaotang-kb-oss-sync.path',
)
wrapper_targets = {
    '/usr/local/sbin/jiaotang-kb-healthcheck': 'deploy/healthcheck.sh',
    '/usr/local/sbin/jiaotang-kb-health-recovery': 'deploy/health-recovery.sh',
    '/usr/local/sbin/jiaotang-kb-backup': 'deploy/backup.sh',
    '/usr/local/sbin/jiaotang-kb-oss-sync': 'deploy/oss-sync.sh',
    '/usr/local/sbin/jiaotang-kb-refresh-index': 'deploy/refresh-index.sh',
    '/usr/local/sbin/jiaotang-kb-smoke-test': 'scripts/smoke_test_production.sh',
    '/usr/local/sbin/jiaotang-kb-wait-ready': 'deploy/wait-ready.sh',
}
entries = {
    **{
        f'/etc/systemd/system/{name}': f'deploy/{name}'
        for name in unit_names
    },
    **wrapper_targets,
}
for target_value, relative in entries.items():
    target = Path(target_value)
    source_file = release / relative
    if not source_file.is_file():
        raise SystemExit(f'新release缺少运行入口：{source_file}')
    dynamic = runtime / 'current' / relative
    expected = str(dynamic)
    if target.is_symlink() and os.readlink(target) == expected:
        continue
    if target.exists() or target.is_symlink():
        preserved = legacy_entries / target.relative_to('/')
        if not preserved.exists() and not preserved.is_symlink():
            preserved.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                preserved.symlink_to(os.readlink(target))
            elif target.is_file():
                shutil.copy2(target, preserved)
    temporary = target.with_name(
        f'.{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp'
    )
    temporary.symlink_to(dynamic)
    os.replace(temporary, target)

stable_entries = {
    '/etc/systemd/system/jiaotang-kb-application-deploy@.service': (
        'deploy/jiaotang-kb-application-deploy@.service', 0o644
    ),
    '/usr/local/libexec/jiaotang-kb-application-deploy': (
        'scripts/run_application_deployment.py', 0o755
    ),
    '/usr/local/libexec/release_retention.py': (
        'scripts/release_retention.py', 0o644
    ),
    '/usr/local/libexec/jiaotang-policy-increment-verify': (
        'scripts/verify_policy_increment_server.py', 0o755
    ),
}
for target_value, (relative, mode) in stable_entries.items():
    target = Path(target_value)
    source_file = release / relative
    if not source_file.is_file() or source_file.is_symlink():
        raise SystemExit(f'新release缺少稳定部署入口：{source_file}')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f'.{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp'
    )
    shutil.copyfile(source_file, temporary)
    os.chmod(temporary, mode)
    os.replace(temporary, target)
PY
    systemctl disable --now \
        jiaotang-kb-oss-sync.timer jiaotang-kb-oss-sync.path \
        2>/dev/null || true"

echo "[5/8] 创建服务器持久化部署事务并脱离SSH执行"
launch_status=1
for launch_attempt in 1 2 3; do
    if ssh "${ssh_args[@]}" "${deploy_host}" \
        "DEPLOYMENT_ID='${deployment_id}' RELEASE_MODE='${release_mode}' \
        RUNTIME_ROOT='${runtime_root}' RELEASE_ROOT='${release_root}' \
        RELEASE_DIR='${remote_release_dir}' CREATED_AT='${build_created_at}' \
        BUILD_COMMIT='${build_commit}' \
        DEPENDENCY_LOCK_SHA256='${dependency_lock_sha256}' \
        DEPENDENCY_BUILD_LOCK_SHA256='${dependency_build_lock_sha256}' \
        WHEELHOUSE_INSTALL_LOCK_SHA256='${wheelhouse_install_lock_sha256}' \
        WHEELHOUSE_MANIFEST_SHA256='${expected_wheelhouse_manifest_sha256}' \
        WHEELHOUSE_CONTENT_IDENTITY_SHA256='${wheelhouse_content_identity_sha256}' \
        DEPENDENCY_IDENTITY_SHA256='${dependency_identity_sha256}' \
        DEPENDENCY_RELEASE_RECORD_SHA256='${dependency_release_record_sha256}' \
        PRIVATE_OVERLAY_IDENTITY_SHA256='${private_overlay_identity_sha256}' \
        python3 - <<'PY'
import json
import os
import secrets
from pathlib import Path

state_dir = Path('/var/lib/jiaotang-kb/deployments')
state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
deployment_id = os.environ['DEPLOYMENT_ID']
previous_build = json.loads(
    (state_dir / f'{deployment_id}.previous-build.json').read_text(
        encoding='utf-8'
    )
)
expected_build = {
    'commit': os.environ['BUILD_COMMIT'],
    'deployment_id': deployment_id,
    'built_at': os.environ['CREATED_AT'],
    'dependency_lock_sha256': os.environ['DEPENDENCY_LOCK_SHA256'],
    'dependency_build_lock_sha256': os.environ[
        'DEPENDENCY_BUILD_LOCK_SHA256'
    ],
    'wheelhouse_install_lock_sha256': os.environ[
        'WHEELHOUSE_INSTALL_LOCK_SHA256'
    ],
    'wheelhouse_manifest_sha256': os.environ['WHEELHOUSE_MANIFEST_SHA256'],
    'wheelhouse_content_identity_sha256': os.environ[
        'WHEELHOUSE_CONTENT_IDENTITY_SHA256'
    ],
    'dependency_identity_sha256': os.environ['DEPENDENCY_IDENTITY_SHA256'],
    'dependency_release_record_sha256': os.environ[
        'DEPENDENCY_RELEASE_RECORD_SHA256'
    ],
    'private_overlay_identity_sha256': os.environ[
        'PRIVATE_OVERLAY_IDENTITY_SHA256'
    ],
}
request = {
    'schema': 'jiaotang-application-deployment-request/v1',
    'deployment_id': deployment_id,
    'release_mode': os.environ['RELEASE_MODE'],
    'runtime_root': os.environ['RUNTIME_ROOT'],
    'release_root': os.environ['RELEASE_ROOT'],
    'release_dir': os.environ['RELEASE_DIR'],
    'previous_release_dir': str(
        (Path(os.environ['RUNTIME_ROOT']) / 'current').resolve(strict=True)
    ),
    'expected_build': expected_build,
    'previous_build': previous_build,
    'candidate_ops_env': str(
        state_dir / f'{deployment_id}.candidate-ops.env'
    ),
    'candidate_app_env': str(
        state_dir / f'{deployment_id}.candidate-app.env'
    ),
    'created_at': os.environ['CREATED_AT'],
}
path = state_dir / f'{deployment_id}.request.json'
payload = (json.dumps(request, ensure_ascii=False, sort_keys=True) + '\n').encode()
if path.is_file():
    if path.read_bytes() != payload:
        raise SystemExit('同一部署编号已存在不同请求')
else:
    temporary = path.with_name(
        f'.{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp'
    )
    temporary.write_bytes(payload)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
PY
        systemctl daemon-reload
        systemctl reset-failed 'jiaotang-kb-application-deploy@${deployment_id}.service' \
            >/dev/null 2>&1 || true
        systemctl start --no-block 'jiaotang-kb-application-deploy@${deployment_id}.service'"; then
        launch_status=0
        break
    fi
    echo "部署启动回执中断，第${launch_attempt}次重连确认。" >&2
done
if [[ "${launch_status}" -ne 0 ]]; then
    echo "启动SSH连续中断；仍进入服务器回执续验，不直接判定生产失败。" >&2
fi

echo "[6/8] 断线重连并续验服务器阶段回执"
if ! python3 "${script_dir}/wait_for_application_deployment.py" \
    --host "${deploy_host}" \
    --key "${deploy_key}" \
    --deployment-id "${deployment_id}" \
    --timeout-seconds "${JIAOTANG_DEPLOY_RECEIPT_TIMEOUT_SECONDS:-420}"; then
    ssh "${ssh_args[@]}" "${deploy_host}" \
        "systemctl --no-pager --full status \
            'jiaotang-kb-application-deploy@${deployment_id}.service' || true
         journalctl -u 'jiaotang-kb-application-deploy@${deployment_id}.service' \
            -n 100 --no-pager || true" || true
    echo "部署事务未返回成功回执；已保留服务器状态供续验。" >&2
    exit 1
fi

echo "[7/8] 刷新当前部署批次的签名门禁回执并对齐发布元数据"
if ! ssh "${ssh_args[@]}" "${deploy_host}" "set -e
    SOURCE_ENV=/etc/jiaotang-kb-ops.env
    [ -f \"\${SOURCE_ENV}\" ] || SOURCE_ENV=/etc/jiaotang-kb.env
    set -a
    source \"\${SOURCE_ENV}\"
    set +a
    '${remote_release_dir}/.venv/bin/python' \
        '${remote_release_dir}/scripts/verify_skill_signature_coverage.py' \
        --skills-root '${remote_release_dir}/skills' \
        --output \"\${JIAOTANG_DATA_DIR}/skill-deploy-gate-status.json\" \
        --deployment-id '${deployment_id}' \
        --scope production \
        --release-mode '${release_mode}' >/dev/null"
then
    echo "警告：生产部署已成功，但签名门禁状态回执刷新失败；请立即运行续验或手工补写回执。" >&2
fi
if ! ssh "${ssh_args[@]}" "${deploy_host}" "set -e
    SOURCE_ENV=/etc/jiaotang-kb-ops.env
    [ -f \"\${SOURCE_ENV}\" ] || SOURCE_ENV=/etc/jiaotang-kb.env
    set -a
    source \"\${SOURCE_ENV}\"
    set +a
    '${remote_release_dir}/.venv/bin/python' \
        '${remote_release_dir}/scripts/reconcile_release_metadata.py' \
        --version '${skill_release_version}' \
        --apply >/dev/null"
then
    echo "警告：生产部署已成功，但技能发布阶段元数据尚未完成根目录对齐；请运行 reconcile_release_metadata.py --apply。" >&2
fi

echo "[8/8] 部署完成：${deployment_id}"
echo "应用current：${remote_release_dir}"
echo "本轮未执行灾备恢复演练，也未处理历史对象、既有暂存或历史部署备份。"
