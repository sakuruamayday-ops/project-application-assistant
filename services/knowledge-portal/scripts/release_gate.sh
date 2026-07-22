#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_dir="$(cd "${script_dir}/.." && pwd)"
root_dir="$(cd "${service_dir}/../.." && pwd)"
endpoint="${JIAOTANG_KB_ENDPOINT:?请设置 JIAOTANG_KB_ENDPOINT}"
token="${JIAOTANG_KB_TOKEN:?请设置 JIAOTANG_KB_TOKEN}"
deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置 JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"
endpoint="${endpoint%/}"
auth=(-H "Authorization: Bearer ${token}")
curl_args=(--fail-with-body --silent --show-error --max-time 45)

echo "[1/6] 自动测试"
(
  cd "${root_dir}"
  PYTHONPATH=src:. uv run --with pytest --with pyyaml pytest -q tests
)
(
  cd "${service_dir}"
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_portal.py tests/test_structured_knowledge.py -q
)

echo "[2/6] 高频项目检索金标准"
(
  cd "${service_dir}"
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_portal.py \
    -q -k 'high_frequency or municipal_projects or local_green_factory or knowledge_search_filters_cross_project'
)

echo "[3/6] REST API"
JIAOTANG_KB_ENDPOINT="${endpoint}" JIAOTANG_KB_TOKEN="${token}" \
  "${script_dir}/smoke_test_production.sh"
curl "${curl_args[@]}" "${auth[@]}" "${endpoint}/v1/preferences" | python3 -c '
import json,sys
payload=json.load(sys.stdin)
assert payload.get("schema_version") == 1, "偏好API结构版本异常"
workflow=payload.get("preferences",{}).get("workflow",{})
assert workflow.get("knowledge_first") is True, "知识库优先核心规则异常"
assert workflow.get("four_question_review") is True, "四问复盘核心规则异常"
'

echo "[4/6] Streamable HTTP MCP"
curl "${curl_args[@]}" "${auth[@]}" \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"knowledge_search","arguments":{"query":"小巨人","limit":1}}}' \
  "${endpoint}/mcp/" | python3 -c 'import json,sys; payload=json.load(sys.stdin); assert payload.get("result",{}).get("structuredContent",{}).get("results"), "MCP检索未命中"'

echo "[5/6] 最新下载包"
JIAOTANG_KB_ENDPOINT="${endpoint}" JIAOTANG_KB_TOKEN="${token}" python3 - <<'PY'
import io
import json
import os
import urllib.request
import zipfile

request = urllib.request.Request(
    os.environ["JIAOTANG_KB_ENDPOINT"].rstrip("/") + "/v1/skills/latest/download",
    headers={"Authorization": "Bearer " + os.environ["JIAOTANG_KB_TOKEN"]},
)
with urllib.request.urlopen(request, timeout=45) as response:
    payload = response.read()
assert payload, "下载包为空"
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    assert archive.testzip() is None, "ZIP完整性失败"
    names = set(archive.namelist())
    manifest = json.loads(archive.read("manifest.json"))
    required = {
        "skills/first-run-configuration/scripts/manage_preferences.py",
        "skills/first-run-configuration/scripts/migrate_skill_preferences.py",
        "skills/first-run-configuration/scripts/upgrade_inheritance.py",
    }
    assert required <= names, "下载包缺少偏好继承脚本"
    includes = manifest.get("includes", {})
    for flag in (
        "personal_preference_overlay",
        "cross_device_preference_sync",
        "three_way_upgrade_inheritance",
        "direct_skill_edit_detection",
        "legacy_skill_preference_migration",
    ):
        assert includes.get(flag) is True, "发布包偏好门禁缺失：" + flag
    merge_scope = {"__name__": "release_gate_merge"}
    exec(archive.read("skills/first-run-configuration/scripts/manage_preferences.py"), merge_scope)
    merged, conflicts = merge_scope["merge_three_way"](
        {"output": {"tone": "professional"}, "region": {"city": "杭州"}},
        {"output": {"tone": "direct"}, "region": {"city": "杭州"}},
        {"output": {"tone": "professional"}, "region": {"city": "宁波"}},
    )
    assert not conflicts and merged["output"]["tone"] == "direct" and merged["region"]["city"] == "宁波", "三方合并门禁失败"
    upgrade_scope = {"__name__": "release_gate_upgrade"}
    exec(archive.read("skills/first-run-configuration/scripts/upgrade_inheritance.py"), upgrade_scope)
    assert upgrade_scope["classify"]("old", "local", "new") == "用户直改与官方更新冲突", "直改检测门禁失败"
    migration_scope = {"__name__": "release_gate_migration"}
    exec(archive.read("skills/first-run-configuration/scripts/migrate_skill_preferences.py"), migration_scope)
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
