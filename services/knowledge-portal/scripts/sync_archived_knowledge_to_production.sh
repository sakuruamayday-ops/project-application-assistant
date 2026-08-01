#!/usr/bin/env bash
set -euo pipefail

path_config="${JIAOTANG_PATH_CONFIG:-/Users/zsh/JiaotangData/索引/config/paths.env}"
if [[ -f "${path_config}" ]]; then
  # shellcheck disable=SC1090
  source "${path_config}"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_dir="$(cd "${script_dir}/.." && pwd)"
manifest="${JIAOTANG_MANIFEST_PATH:-/Users/zsh/JiaotangData/索引/current/manifest.jsonl}"
index_dir="${JIAOTANG_INDEX_BUILD_DIR:-/Users/zsh/JiaotangData/索引/current}"
knowledge_root="${JIAOTANG_KNOWLEDGE_ROOT:-/Users/zsh/JiaotangData/知识库}"
structured_source_root="${JIAOTANG_STRUCTURED_SOURCE_ROOT:-${knowledge_root}/10_政策与目录/政策数据库/企策顾问/_结构化源}"
deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"
release_lock="${JIAOTANG_RELEASE_LOCK:-/Users/zsh/JiaotangData/索引/.locks/production-release.lock}"

if [[ "${JIAOTANG_RELEASE_LOCK_HELD:-0}" != "1" ]]; then
  mkdir -p "$(dirname "${release_lock}")"
  exec lockf -k -t "${JIAOTANG_RELEASE_LOCK_WAIT_SECONDS:-600}" \
    "${release_lock}" env JIAOTANG_RELEASE_LOCK_HELD=1 "$0" "$@"
fi

for required in "${manifest}" "${knowledge_root}" "${index_dir}"; do
  [[ -e "${required}" ]] || { echo "路径不存在：${required}" >&2; exit 1; }
done

echo "[1/10] 更新生产manifest并归并OCR伴生Markdown"
python3 "${script_dir}/update_cloud_policy_manifest.py"

echo "[2/10] 生成OCR结构抽检报告"
python3 "${script_dir}/audit_ocr_samples.py" \
  --extraction-report "${index_dir}/extraction_report.csv" \
  --knowledge-root "${knowledge_root}" \
  --priority-audit "/Users/zsh/JiaotangData/索引/priority_ocr_completion_2026-07-17.csv" \
  --list-audit "/Users/zsh/JiaotangData/索引/list_ocr_sequence_audit_2026-07-17.csv" \
  --output "${index_dir}/OCR资料抽检报告_2026-07-21.md"

echo "[3/10] 重建全文富索引"
python3 "${script_dir}/build_knowledge_content_index.py" --manifest "${manifest}" --output "${index_dir}"
python3 "${script_dir}/build_document_scopes.py" \
  --database "${index_dir}/knowledge_content.sqlite3"

echo "[4/10] 重建名单覆盖矩阵、官方分片、全国批次主表、身份图谱、浙江企业身份时间轴和三首跨年图谱"
python3 "${script_dir}/build_specialized_sme_coverage_matrix.py" \
  --database "${index_dir}/knowledge_content.sqlite3"
python3 "${script_dir}/build_small_giant_official_fragments.py" \
  --database "${index_dir}/knowledge_content.sqlite3"
python3 "${script_dir}/collect_small_giant_official_fragments.py"
small_giant_args=(--database "${index_dir}/knowledge_content.sqlite3")
if [[ -f "${structured_source_root}/企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json" ]]; then
  small_giant_args+=(--qice-dataset "${structured_source_root}/企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json")
fi
python3 "${script_dir}/build_national_small_giant_master.py" "${small_giant_args[@]}"
python3 "${script_dir}/build_small_giant_official_fragments.py" \
  --database "${index_dir}/knowledge_content.sqlite3"
if [[ -f "${structured_source_root}/企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json" ]]; then
  python3 "${script_dir}/build_qice_small_giant_snapshot_matrix.py" \
    --database "${index_dir}/knowledge_content.sqlite3" \
    --dataset "${structured_source_root}/企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json"
fi
python3 "${script_dir}/prepare_enterprise_identity_mapping.py" \
  --database "${index_dir}/knowledge_content.sqlite3"
python3 "${script_dir}/build_small_giant_identity_graph.py" \
  --database "${index_dir}/knowledge_content.sqlite3"
python3 "${script_dir}/build_zhejiang_enterprise_identity_timeline.py" \
  --database "${index_dir}/knowledge_content.sqlite3"
python3 "${script_dir}/audit_small_giant_weekly_delta.py" \
  --database "${index_dir}/knowledge_content.sqlite3" \
  --output "${index_dir}"
python3 "${script_dir}/extract_three_first_directory_status.py"
python3 "${script_dir}/collect_three_first_public_supplements.py" \
  --output "${knowledge_root}/50_名单与对标/三首项目/_结构化数据"
python3 "${script_dir}/collect_first_batch_material_directories.py" \
  --output "${knowledge_root}/10_政策与目录/三首项目/浙江省首批次新材料/应用示范指导目录"
three_first_args=(
  --history "${structured_source_root}/qice_three_first_history_full.json"
  --database "${index_dir}/knowledge_content.sqlite3"
  --guidance-directories "${knowledge_root}/10_政策与目录/三首项目/浙江省首批次新材料/应用示范指导目录/浙江省重点新材料首批次应用示范指导目录_结构化条目.jsonl"
)
latest_three_first_details="$(find "${structured_source_root}" -maxdepth 1 -type f \
  -name 'qice_three_first_product_details_merged_*.json' -print | sort | tail -1)"
if [[ -n "${latest_three_first_details}" ]]; then
  three_first_args+=(--details "${latest_three_first_details}")
elif [[ -f "${structured_source_root}/qice_three_first_product_details.json" ]]; then
  three_first_args+=(--details "${structured_source_root}/qice_three_first_product_details.json")
fi
python3 "${script_dir}/build_three_first_benchmark_graph.py" "${three_first_args[@]}"
python3 "${script_dir}/audit_three_first_directory_exit.py" \
  --database "${index_dir}/knowledge_content.sqlite3"
python3 "${script_dir}/audit_specialized_lists_and_three_first.py" \
  --database "${index_dir}/knowledge_content.sqlite3"
python3 "${script_dir}/verify_structured_knowledge_tables.py" \
  --database "${index_dir}/knowledge_content.sqlite3"

echo "[5/10] 将派生矩阵与图谱加入生产manifest"
python3 "${script_dir}/update_cloud_policy_manifest.py"

echo "[5/10] 校验manifest与本轮提取报告是否收敛"
set +e
python3 - "${manifest}" "${index_dir}/extraction_report.csv" <<'PY'
import csv
import json
import sys
from pathlib import Path

manifest_rows = {
    (str(row["relative_path"]), str(row["sha256"]))
    for row in (
        json.loads(line)
        for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
}
with Path(sys.argv[2]).open(encoding="utf-8-sig") as source:
    extraction_rows = {
        (str(row["relative_path"]), str(row["sha256"]))
        for row in csv.DictReader(source)
    }

missing = manifest_rows - extraction_rows
stale = extraction_rows - manifest_rows
manifest_paths = {path for path, _ in manifest_rows}
extraction_paths = {path for path, _ in extraction_rows}
path_delta = manifest_paths ^ extraction_paths
print(
    json.dumps(
        {
            "manifest_rows": len(manifest_rows),
            "extraction_rows": len(extraction_rows),
            "path_delta": len(path_delta),
            "missing_from_extraction": len(missing),
            "stale_in_extraction": len(stale),
        },
        ensure_ascii=False,
    )
)
if path_delta:
    raise SystemExit(2)
if missing or stale:
    raise SystemExit(3)
raise SystemExit(0)
PY
convergence_status="$?"
set -e

if (( convergence_status == 2 )); then
  convergence_pass="${JIAOTANG_RELEASE_CONVERGENCE_PASS:-0}"
  if (( convergence_pass >= 1 )); then
    echo "manifest路径集合连续两轮未收敛，停止发布" >&2
    exit 1
  fi
  echo "派生文件改变了路径集合，重新执行一次完整构建"
  exec env JIAOTANG_RELEASE_CONVERGENCE_PASS="$((convergence_pass + 1))" "$0" "$@"
elif (( convergence_status == 3 )); then
  echo "派生文件路径已收敛但内容哈希变化，暂存重建核心索引并保留结构化增强表"
  finalize_dir="$(mktemp -d /tmp/jiaotang-index-finalize.XXXXXX)"
  python3 "${script_dir}/build_knowledge_content_index.py" \
    --manifest "${manifest}" \
    --output "${finalize_dir}"
  python3 "${script_dir}/build_document_scopes.py" \
    --database "${finalize_dir}/knowledge_content.sqlite3"
  python3 "${script_dir}/merge_structured_tables.py" \
    --source "${index_dir}/knowledge_content.sqlite3" \
    --target "${finalize_dir}/knowledge_content.sqlite3"
  python3 "${script_dir}/verify_structured_knowledge_tables.py" \
    --database "${finalize_dir}/knowledge_content.sqlite3"
  for artifact in \
    documents.jsonl \
    extraction_report.csv \
    extraction_summary.json \
    knowledge_content.sqlite3
  do
    mv -f "${finalize_dir}/${artifact}" "${index_dir}/${artifact}"
  done
  rmdir "${finalize_dir}"
elif (( convergence_status != 0 )); then
  echo "manifest收敛检查异常退出：${convergence_status}" >&2
  exit "${convergence_status}"
fi

echo "[5/10] 依据已收敛的manifest与索引重建OSS白名单"
python3 "${script_dir}/build_cloud_upload_allowlist.py" \
  --index-root "${index_dir}"

echo "[5/10] 依据已收敛的manifest重建文件库存索引"
python3 "${script_dir}/build_knowledge_inventory_from_manifest.py" \
  --manifest "${manifest}" \
  --output "${index_dir}/knowledge_inventory.sqlite3"

echo "[6/10] 重建政策版本与替代关系"
python3 "${script_dir}/build_policy_version_links.py" \
  --manifest "${manifest}" \
  --content-db "${index_dir}/knowledge_content.sqlite3" \
  --output "${index_dir}"

echo "[7/10] 校验SQLite与服务端测试"
python3 - "${index_dir}/knowledge_content.sqlite3" <<'PY'
import sqlite3
import sys
connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    result = connection.execute("PRAGMA quick_check").fetchone()[0]
finally:
    connection.close()
if result != "ok":
    raise SystemExit(f"SQLite quick_check失败：{result}")
print("SQLite quick_check=ok")
PY
(
  cd "${service_dir}"
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_portal.py tests/test_structured_knowledge.py -q
)

echo "[8/10] 执行知识库Acceptance Harness"
python3 "${script_dir}/run_acceptance_harness.py" \
  --knowledge-root "${knowledge_root}" \
  --index-root "${index_dir}" \
  --suite knowledge_base \
  --output "${index_dir}/acceptance-harness.json"

echo "[发布1/5] 冻结manifest、OSS白名单和生产索引哈希"
frozen_manifest_sha="$(shasum -a 256 "${manifest}" | awk '{print $1}')"
frozen_allowlist_sha="$(shasum -a 256 "${index_dir}/upload_allowlist.csv" | awk '{print $1}')"
frozen_index_sha="$(shasum -a 256 "${index_dir}/knowledge_content.sqlite3" | awk '{print $1}')"
echo "manifest=${frozen_manifest_sha} allowlist=${frozen_allowlist_sha} index=${frozen_index_sha}"

echo "[发布1/5] 从服务器安全读取OSS运行凭据并执行容量预检"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "set -e
   env_file=/etc/jiaotang-kb-ops.env
   [ -f \"\${env_file}\" ] || env_file=/etc/jiaotang-kb.env
   [ -f \"\${env_file}\" ] || { echo '缺少OSS运维环境文件' >&2; exit 1; }
   if ! grep -q '^JIAOTANG_OSS_RELEASE_SIGNING_SECRET=' \"\${env_file}\"; then
     umask 077
     printf 'JIAOTANG_OSS_RELEASE_SIGNING_SECRET=%s\n' \"\$(openssl rand -hex 32)\" >>\"\${env_file}\"
   fi
   chmod 0600 \"\${env_file}\""
while IFS='=' read -r key value; do
  case "${key}" in
    JIAOTANG_OSS_ENDPOINT|JIAOTANG_OSS_BUCKET|JIAOTANG_OSS_ACCESS_KEY_ID|JIAOTANG_OSS_ACCESS_KEY_SECRET|JIAOTANG_OSS_PREFIX|JIAOTANG_OSS_AUTH_MODE|JIAOTANG_OSS_SECURITY_TOKEN|JIAOTANG_OSS_RAM_ROLE_AUTH_HOST|JIAOTANG_OSS_RELEASE_SIGNING_SECRET|JIAOTANG_OSS_RELEASE_VERIFY_SECRETS)
      export "${key}=${value}"
      ;;
  esac
done < <(ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "env_file=/etc/jiaotang-kb-ops.env; [ -f \"\${env_file}\" ] || env_file=/etc/jiaotang-kb.env; grep -E '^JIAOTANG_OSS_(ENDPOINT|BUCKET|ACCESS_KEY_ID|ACCESS_KEY_SECRET|PREFIX|AUTH_MODE|SECURITY_TOKEN|RAM_ROLE_AUTH_HOST|RELEASE_SIGNING_SECRET|RELEASE_VERIFY_SECRETS)=' \"\${env_file}\"")
JIAOTANG_OSS_ENDPOINT="${JIAOTANG_OSS_ENDPOINT/-internal/}"
export JIAOTANG_OSS_ENDPOINT
python3 "${script_dir}/check_oss_governance.py" \
  --mode "${JIAOTANG_OSS_GOVERNANCE_MODE:-warn}"
echo "[发布2/5] 执行SHA-256去重上传"
oss_upload_args=(
  --manifest "${manifest}"
  --allowlist "${index_dir}/upload_allowlist.csv"
  --object-layout sha256
  --workers "${JIAOTANG_OSS_UPLOAD_WORKERS:-4}"
)
if [[ -n "${JIAOTANG_OSS_RELATIVE_PREFIXES:-}" ]]; then
  IFS='|' read -r -a oss_relative_prefixes <<<"${JIAOTANG_OSS_RELATIVE_PREFIXES}"
  for relative_prefix in "${oss_relative_prefixes[@]}"; do
    [[ -n "${relative_prefix}" ]] && oss_upload_args+=(--relative-prefix "${relative_prefix}")
  done
fi
python3 "${script_dir}/upload_manifest_to_oss.py" "${oss_upload_args[@]}"
python3 "${script_dir}/upload_manifest_to_oss.py" \
  --manifest "${manifest}" \
  --allowlist "${index_dir}/upload_allowlist.csv" \
  --object-layout sha256 \
  --workers "${JIAOTANG_OSS_VERIFY_WORKERS:-8}" \
  --verify-only

echo "[发布2/5] 跳过既有历史对象、既有暂存和历史部署备份盘点（本轮明确排除）"

echo "[发布3/5] 复核冻结集合未变化且对象二次校验已经通过"
[[ "$(shasum -a 256 "${manifest}" | awk '{print $1}')" == "${frozen_manifest_sha}" ]] \
  || { echo "manifest冻结后发生变化，停止发布" >&2; exit 1; }
[[ "$(shasum -a 256 "${index_dir}/upload_allowlist.csv" | awk '{print $1}')" == "${frozen_allowlist_sha}" ]] \
  || { echo "OSS白名单冻结后发生变化，停止发布" >&2; exit 1; }
[[ "$(shasum -a 256 "${index_dir}/knowledge_content.sqlite3" | awk '{print $1}')" == "${frozen_index_sha}" ]] \
  || { echo "生产索引冻结后发生变化，停止发布" >&2; exit 1; }

echo "[发布4/5] 发布OSS索引并原子切换服务器查询索引"
JIAOTANG_DEPLOY_HOST="${deploy_host}" JIAOTANG_DEPLOY_KEY="${deploy_key}" \
  "${script_dir}/deploy_production.sh"
current_release_id="$(
  python3 - "${script_dir}" <<'PY'
import json
import os
import sys
sys.path.insert(0, sys.argv[1])
from oss_auth import build_bucket

prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
bucket = build_bucket()
try:
    payload = json.loads(bucket.get_object(f"{prefix}/index/current.json").read())
except Exception as error:
    if error.__class__.__name__ == "NoSuchKey":
        print("")
    else:
        raise
else:
    print(payload.get("release_id") or "")
PY
)"
index_publish_args=(
  --index-dir "${index_dir}"
  --index-policy always
  --prevalidated
  --capacity-budget-bytes "${JIAOTANG_OSS_CAPACITY_BUDGET_BYTES:-100000000000}"
)
if [[ -n "${current_release_id}" ]]; then
  index_publish_args+=(--expected-current-release-id "${current_release_id}")
else
  index_publish_args+=(--allow-initial-current)
fi
python3 "${script_dir}/publish_index_to_oss.py" "${index_publish_args[@]}"
JIAOTANG_INDEX_PATH="${index_dir}/knowledge_content.sqlite3" \
JIAOTANG_INDEX_PREVALIDATED=1 \
JIAOTANG_DEPLOY_HOST="${deploy_host}" \
JIAOTANG_DEPLOY_KEY="${deploy_key}" \
  "${script_dir}/deploy_index_delta_to_server.sh"

echo "[发布4/5] 运行生产冒烟测试"
if [[ -n "${JIAOTANG_KB_ENDPOINT:-}" && -n "${JIAOTANG_KB_TOKEN:-}" && -n "${JIAOTANG_KB_DEVICE_ID:-}" ]]; then
  "${script_dir}/smoke_test_production.sh"
else
  ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
    "set -e; source /etc/jiaotang-kb-app.env; curl --fail --silent http://127.0.0.1:8100/health >/dev/null; systemctl is-active --quiet jiaotang-kb"
  echo "未提供本地Token或设备标识，已完成服务健康与部署固定路由冒烟；带凭据REST/MCP冒烟由deploy_production.sh固定路由检查覆盖。"
fi

echo "[发布5/5] 容量熔断已由本次不可变release发布前后聚合校验完成；跳过历史对象与既有分片盘点"

echo "manifest冻结、去重上传、二次校验、索引发布和容量复核五步流水线完成。"
