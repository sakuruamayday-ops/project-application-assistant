#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_dir="$(cd "${script_dir}/.." && pwd)"
root_dir="$(cd "${service_dir}/../.." && pwd)"
canonical_deploy_root="$(git -C "${root_dir}" config --local --get jiaotang.deployWorktree 2>/dev/null || true)"
if [[ -n "${canonical_deploy_root}" ]]; then
  canonical_deploy_root="$(cd "${canonical_deploy_root}" && pwd -P)"
  current_root="$(cd "${root_dir}" && pwd -P)"
  if [[ "${current_root}" != "${canonical_deploy_root}" ]]; then
    echo "六项发布门禁只能从唯一正式工作树执行：${canonical_deploy_root}" >&2
    exit 76
  fi
fi
if git -C "${root_dir}" show-ref --verify --quiet refs/remotes/origin/main; then
  if ! git -C "${root_dir}" merge-base --is-ancestor origin/main HEAD; then
    echo "六项发布门禁阻断：当前工作树尚未合入最新 origin/main。" >&2
    exit 77
  fi
fi
endpoint="${JIAOTANG_KB_ENDPOINT:?请设置 JIAOTANG_KB_ENDPOINT}"
token="${JIAOTANG_KB_TOKEN:?请设置 JIAOTANG_KB_TOKEN}"
device_id="${JIAOTANG_KB_DEVICE_ID:?请设置 JIAOTANG_KB_DEVICE_ID}"
device_name="${JIAOTANG_KB_DEVICE_NAME:-Release Gate Device}"
deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置 JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"
remote_online_gate="${JIAOTANG_REMOTE_ONLINE_GATE:-false}"
endpoint="${endpoint%/}"
auth=(
  -H "Authorization: Bearer ${token}"
  -H "X-Jiaotang-Device-ID: ${device_id}"
  -H "X-Jiaotang-Device-Name: ${device_name}"
)
curl_args=(--fail-with-body --silent --show-error --max-time 45)
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

echo "[1/6] 自动测试"
index_database="${JIAOTANG_INDEX_DATABASE:-/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3}"
if [[ -f "${index_database}" ]]; then
  python3 "${script_dir}/verify_structured_knowledge_tables.py" --database "${index_database}"
else
  echo "本地生产索引未挂载，改为校验服务器当前生产索引"
  {
    cat <<'REMOTE_INDEX_VERIFY'
set -e
set -a
source /etc/jiaotang-kb.env
set +a
python3 - "$JIAOTANG_INDEX_DIR/knowledge_content.sqlite3" <<'PY'
import json
import sqlite3
import sys

database = sys.argv[1]
required = {
    "list_coverage_matrix": 384,
    "list_entity_reconciliation": 1,
    "national_small_giant_master": 1,
    "three_first_project_awards": 1,
    "three_first_status_timeline": 1,
    "enterprise_product_graph_nodes": 1,
    "enterprise_product_graph_edges": 1,
}
with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = sorted(set(required) - existing)
    if missing:
        raise SystemExit("缺少结构化专表：" + "、".join(missing))
    counts = {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in required
    }
insufficient = {
    table: {"actual": counts[table], "minimum": minimum}
    for table, minimum in required.items()
    if counts[table] < minimum
}
if insufficient:
    raise SystemExit("结构化专表记录不足：" + json.dumps(insufficient, ensure_ascii=False))
print(json.dumps({"database": database, "tables": counts}, ensure_ascii=False))
PY
REMOTE_INDEX_VERIFY
  } | ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" bash
fi
(
  cd "${root_dir}"
  PYTHONPATH=src:. uv run --with pytest --with pyyaml pytest -q tests
)
(
  cd "${service_dir}"
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests -q
)
(
  cd "${service_dir}"
  .venv/bin/python scripts/manage_project_algorithm_packs.py generate-all
  .venv/bin/python scripts/validate_project_algorithm_packs.py
)
node_bin="${JIAOTANG_NODE_BIN:-$(command -v node || true)}"
node_modules="${JIAOTANG_NODE_MODULES:-}"
if [[ -z "${node_modules}" ]]; then
  bundled_node_root="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/node"
  if [[ -d "${bundled_node_root}/node_modules" ]]; then
    node_modules="${bundled_node_root}/node_modules"
    if [[ -x "${bundled_node_root}/bin/node" ]]; then
      node_bin="${bundled_node_root}/bin/node"
    fi
  fi
fi
if [[ -z "${node_bin}" || -z "${node_modules}" ]]; then
  echo "缺少 Node.js 或 Playwright 依赖，无法执行 Skills 浏览器视觉门禁" >&2
  exit 1
fi
python3 "${script_dir}/build_static_assets.py"
(
  cd "${service_dir}"
  NODE_PATH="${node_modules}" "${node_bin}" tests/skills_center_ux_regression.mjs
)

echo "[2/6] 高频项目检索金标准"
(
  cd "${service_dir}"
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_portal.py \
    -q -k 'high_frequency or municipal_projects or local_green_factory or knowledge_search_filters_cross_project'
)

echo "[3/6] REST API"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "set -e; source /etc/jiaotang-kb.env; \
  /opt/jiaotang-kb/.venv/bin/python /opt/jiaotang-kb/scripts/verify_authenticated_portal.py \
  --base-url http://127.0.0.1:8100"
if [[ "${remote_online_gate}" = "true" ]]; then
  {
    printf 'export JIAOTANG_KB_ENDPOINT=%q\n' "${endpoint}"
    printf 'export JIAOTANG_KB_TOKEN=%q\n' "${token}"
    printf 'export JIAOTANG_KB_DEVICE_ID=%q\n' "${device_id}"
    printf 'export JIAOTANG_KB_DEVICE_NAME=%q\n' "${device_name}"
    cat <<'REMOTE_REST'
export JIAOTANG_RESOLVE_IP=127.0.0.1
/opt/jiaotang-kb/scripts/smoke_test_production.sh
curl --fail-with-body --silent --show-error --max-time 45 \
  --resolve "zshjiaotang.cn:443:127.0.0.1" \
  -H "Authorization: Bearer ${JIAOTANG_KB_TOKEN}" \
  -H "X-Jiaotang-Device-ID: ${JIAOTANG_KB_DEVICE_ID}" \
  -H "X-Jiaotang-Device-Name: ${JIAOTANG_KB_DEVICE_NAME}" \
  "${JIAOTANG_KB_ENDPOINT}/v1/preferences"
REMOTE_REST
  } | ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" bash | tail -n 1 | python3 -c '
import json,sys
payload=json.load(sys.stdin)
assert payload.get("schema_version") == 1, "偏好API结构版本异常"
workflow=payload.get("preferences",{}).get("workflow",{})
assert workflow.get("knowledge_first") is True, "知识库优先核心规则异常"
assert workflow.get("four_question_review") is True, "四问复盘核心规则异常"
'
else
  JIAOTANG_KB_ENDPOINT="${endpoint}" JIAOTANG_KB_TOKEN="${token}" \
    JIAOTANG_KB_DEVICE_ID="${device_id}" JIAOTANG_KB_DEVICE_NAME="${device_name}" \
    "${script_dir}/smoke_test_production.sh"
  curl "${curl_args[@]}" "${auth[@]}" "${endpoint}/v1/preferences" | python3 -c '
import json,sys
payload=json.load(sys.stdin)
assert payload.get("schema_version") == 1, "偏好API结构版本异常"
workflow=payload.get("preferences",{}).get("workflow",{})
assert workflow.get("knowledge_first") is True, "知识库优先核心规则异常"
assert workflow.get("four_question_review") is True, "四问复盘核心规则异常"
'
fi

echo "[4/6] Streamable HTTP MCP"
if [[ "${remote_online_gate}" = "true" ]]; then
  {
    printf 'export JIAOTANG_KB_ENDPOINT=%q\n' "${endpoint}"
    printf 'export JIAOTANG_KB_TOKEN=%q\n' "${token}"
    printf 'export JIAOTANG_KB_DEVICE_ID=%q\n' "${device_id}"
    printf 'export JIAOTANG_KB_DEVICE_NAME=%q\n' "${device_name}"
    cat <<'REMOTE_MCP'
curl --fail-with-body --silent --show-error --max-time 45 \
  --resolve "zshjiaotang.cn:443:127.0.0.1" \
  -H "Authorization: Bearer ${JIAOTANG_KB_TOKEN}" \
  -H "X-Jiaotang-Device-ID: ${JIAOTANG_KB_DEVICE_ID}" \
  -H "X-Jiaotang-Device-Name: ${JIAOTANG_KB_DEVICE_NAME}" \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"knowledge_search","arguments":{"query":"小巨人","limit":1}}}' \
  "${JIAOTANG_KB_ENDPOINT}/mcp/"
REMOTE_MCP
  } | ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" bash | python3 -c 'import json,sys; payload=json.load(sys.stdin); assert payload.get("result",{}).get("structuredContent",{}).get("results"), "MCP检索未命中"'
else
  curl "${curl_args[@]}" "${auth[@]}" \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"knowledge_search","arguments":{"query":"小巨人","limit":1}}}' \
    "${endpoint}/mcp/" | python3 -c 'import json,sys; payload=json.load(sys.stdin); assert payload.get("result",{}).get("structuredContent",{}).get("results"), "MCP检索未命中"'
fi

echo "[5/6] 最新下载包"
release_archive="$(mktemp -t jiaotang-skills-release.XXXXXX.zip)"
trap 'rm -f "${release_archive}"' EXIT
if [[ "${remote_online_gate}" = "true" ]]; then
  {
    printf 'export JIAOTANG_KB_ENDPOINT=%q\n' "${endpoint}"
    printf 'export JIAOTANG_KB_TOKEN=%q\n' "${token}"
    printf 'export JIAOTANG_KB_DEVICE_ID=%q\n' "${device_id}"
    printf 'export JIAOTANG_KB_DEVICE_NAME=%q\n' "${device_name}"
    cat <<'REMOTE_DOWNLOAD'
curl --fail-with-body --silent --show-error --max-time 45 \
  --resolve "zshjiaotang.cn:443:127.0.0.1" \
  -H "Authorization: Bearer ${JIAOTANG_KB_TOKEN}" \
  -H "X-Jiaotang-Device-ID: ${JIAOTANG_KB_DEVICE_ID}" \
  -H "X-Jiaotang-Device-Name: ${JIAOTANG_KB_DEVICE_NAME}" \
  "${JIAOTANG_KB_ENDPOINT}/v1/skills/latest/download"
REMOTE_DOWNLOAD
  } | ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" bash > "${release_archive}"
else
  curl "${curl_args[@]}" "${auth[@]}" \
    "${endpoint}/v1/skills/latest/download" -o "${release_archive}"
fi
JIAOTANG_RELEASE_ARCHIVE="${release_archive}" python3 - <<'PY'
import json
import os
import zipfile
from pathlib import Path

payload = Path(os.environ["JIAOTANG_RELEASE_ARCHIVE"]).read_bytes()
assert payload, "下载包为空"
with zipfile.ZipFile(os.environ["JIAOTANG_RELEASE_ARCHIVE"]) as archive:
    assert archive.testzip() is None, "ZIP完整性失败"
    names = set(archive.namelist())
    manifest_name = next(
        (
            name
            for name in (
                "manifest.json",
                "suite-release-manifest.json",
                "jiaotang-skills/manifest.json",
                "jiaotang-skills/suite-release-manifest.json",
            )
            if name in names
        ),
        None,
    )
    assert manifest_name is not None, "下载包缺少套件清单"
    manifest = json.loads(archive.read(manifest_name))
    archive_prefix = (
        "jiaotang-skills/" if manifest_name.startswith("jiaotang-skills/") else ""
    )
    required = {
        archive_prefix + "skills/first-run-configuration/scripts/manage_preferences.py",
        archive_prefix + "skills/first-run-configuration/scripts/migrate_skill_preferences.py",
        archive_prefix + "skills/first-run-configuration/scripts/upgrade_inheritance.py",
    }
    assert required <= names, "下载包缺少偏好继承脚本"
    merge_scope = {
        "__name__": "release_gate_merge",
        "__file__": "skills/first-run-configuration/scripts/manage_preferences.py",
    }
    exec(
        archive.read(
            archive_prefix + "skills/first-run-configuration/scripts/manage_preferences.py"
        ),
        merge_scope,
    )
    merged, conflicts = merge_scope["merge_three_way"](
        {"output": {"tone": "professional"}, "region": {"city": "杭州"}},
        {"output": {"tone": "direct"}, "region": {"city": "杭州"}},
        {"output": {"tone": "professional"}, "region": {"city": "宁波"}},
    )
    assert not conflicts and merged["output"]["tone"] == "direct" and merged["region"]["city"] == "宁波", "三方合并门禁失败"
    upgrade_scope = {
        "__name__": "release_gate_upgrade",
        "__file__": "skills/first-run-configuration/scripts/upgrade_inheritance.py",
    }
    exec(
        archive.read(
            archive_prefix + "skills/first-run-configuration/scripts/upgrade_inheritance.py"
        ),
        upgrade_scope,
    )
    assert upgrade_scope["classify"]("old", "local", "new") == "用户直改与官方更新冲突", "直改检测门禁失败"
    migration_scope = {
        "__name__": "release_gate_migration",
        "__file__": "skills/first-run-configuration/scripts/migrate_skill_preferences.py",
    }
    exec(
        archive.read(
            archive_prefix
            + "skills/first-run-configuration/scripts/migrate_skill_preferences.py"
        ),
        migration_scope,
    )
    inferred = migration_scope["infer_global_preferences"]("默认政策地区为浙江省杭州市，输出使用详细版")
    assert inferred["region"]["city"] == "杭州市" and inferred["output"]["detail_level"] == "detailed", "旧Skill偏好迁移门禁失败"
PY

echo "[6/6] 最近备份"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
path = Path('/var/lib/jiaotang-kb/backup-status.json')
assert path.is_file(), '缺少备份状态文件'
payload = json.loads(path.read_text(encoding='utf-8'))
assert payload.get('status') == '正常', '最近备份状态异常'
completed = datetime.strptime(payload['completed_at'], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
assert (datetime.now(timezone.utc) - completed).total_seconds() <= 48 * 3600, '最近备份超过48小时'
assert any(Path('/var/backups/jiaotang-kb').glob('portal-*.sqlite3.gz')), '未找到门户数据库备份'
print('备份状态正常：' + payload['completed_at'])
PY"

echo "六项发布门禁全部通过。"
