#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
service_dir="$(cd "${script_dir}/.." && pwd)"
manifest="${JIAOTANG_MANIFEST_PATH:-/Volumes/知识库/_云端迁移索引/cloud_package_index/manifest.jsonl}"
index_dir="${JIAOTANG_INDEX_BUILD_DIR:-/Volumes/知识库/_云端迁移索引/cloud_package_index}"
knowledge_root="${JIAOTANG_KNOWLEDGE_ROOT:-/Volumes/知识库/_云端知识库}"
deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"

for required in "${manifest}" "${knowledge_root}" "${index_dir}"; do
  [[ -e "${required}" ]] || { echo "路径不存在：${required}" >&2; exit 1; }
done

echo "[1/10] 更新生产manifest并归并OCR伴生Markdown"
python3 "${script_dir}/update_cloud_policy_manifest.py"

echo "[2/10] 生成OCR结构抽检报告"
python3 "${script_dir}/audit_ocr_samples.py" \
  --extraction-report "${index_dir}/extraction_report.csv" \
  --knowledge-root "${knowledge_root}" \
  --priority-audit "/Volumes/知识库/_云端迁移索引/priority_ocr_completion_2026-07-17.csv" \
  --list-audit "/Volumes/知识库/_云端迁移索引/list_ocr_sequence_audit_2026-07-17.csv" \
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
if [[ -f "${HOME}/Downloads/企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json" ]]; then
  small_giant_args+=(--qice-dataset "${HOME}/Downloads/企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json")
fi
python3 "${script_dir}/build_national_small_giant_master.py" "${small_giant_args[@]}"
python3 "${script_dir}/build_small_giant_official_fragments.py" \
  --database "${index_dir}/knowledge_content.sqlite3"
if [[ -f "${HOME}/Downloads/企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json" ]]; then
  python3 "${script_dir}/build_qice_small_giant_snapshot_matrix.py" \
    --database "${index_dir}/knowledge_content.sqlite3" \
    --dataset "${HOME}/Downloads/企策顾问_国家专精特新小巨人_2019年至今_2026-07-22.json"
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
three_first_args=(
  --history "${HOME}/Downloads/qice_three_first_history_full.json"
  --database "${index_dir}/knowledge_content.sqlite3"
)
if [[ -f "${HOME}/Downloads/qice_three_first_product_details_merged_20260724.json" ]]; then
  three_first_args+=(--details "${HOME}/Downloads/qice_three_first_product_details_merged_20260724.json")
elif [[ -f "${HOME}/Downloads/qice_three_first_product_details.json" ]]; then
  three_first_args+=(--details "${HOME}/Downloads/qice_three_first_product_details.json")
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

echo "[8/10] 从服务器安全读取OSS运行凭据并增量同步"
while IFS='=' read -r key value; do
  case "${key}" in
    JIAOTANG_OSS_ENDPOINT|JIAOTANG_OSS_BUCKET|JIAOTANG_OSS_ACCESS_KEY_ID|JIAOTANG_OSS_ACCESS_KEY_SECRET|JIAOTANG_OSS_PREFIX)
      export "${key}=${value}"
      ;;
  esac
done < <(ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "grep -E '^JIAOTANG_OSS_(ENDPOINT|BUCKET|ACCESS_KEY_ID|ACCESS_KEY_SECRET|PREFIX)=' /etc/jiaotang-kb.env")
JIAOTANG_OSS_ENDPOINT="${JIAOTANG_OSS_ENDPOINT/-internal/}"
export JIAOTANG_OSS_ENDPOINT
python3 "${script_dir}/upload_manifest_to_oss.py" \
  --manifest "${manifest}" \
  --relative-prefix "10_政策与目录/政策数据库/企策顾问/" \
  --relative-prefix "10_政策与目录/研究院/杭州市企业研究院/" \
  --relative-prefix "10_政策与目录/综合政策/法律法规底库/公司法/" \
  --relative-prefix "10_政策与目录/政策检索分层说明.md" \
  --relative-prefix "50_名单与对标/优质中小企业梯度培育/_省级专精特新/" \
  --relative-prefix "50_名单与对标/优质中小企业梯度培育/_覆盖矩阵/" \
  --relative-prefix "50_名单与对标/优质中小企业梯度培育/_全国小巨人批次主表/" \
  --relative-prefix "50_名单与对标/优质中小企业梯度培育/企策顾问动态索引/" \
  --relative-prefix "50_名单与对标/三首项目/_结构化数据/" \
  --relative-prefix "50_名单与对标/企业身份时间轴/" \
  --relative-prefix "90_方法与复盘/" \
  --workers "${JIAOTANG_OSS_UPLOAD_WORKERS:-4}"
python3 "${script_dir}/publish_index_to_oss.py" \
  --index-dir "${index_dir}" \
  --snapshot-current \
  --prevalidated

echo "[9/10] 刷新服务器只读索引缓存并部署应用"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "set -e; set -a; source /etc/jiaotang-kb.env; set +a; /usr/local/sbin/jiaotang-kb-refresh-index; systemctl restart jiaotang-kb"
JIAOTANG_DEPLOY_HOST="${deploy_host}" JIAOTANG_DEPLOY_KEY="${deploy_key}" \
  "${script_dir}/deploy_production.sh"

echo "[10/10] 运行生产冒烟测试"
if [[ -n "${JIAOTANG_KB_ENDPOINT:-}" && -n "${JIAOTANG_KB_TOKEN:-}" && -n "${JIAOTANG_KB_DEVICE_ID:-}" ]]; then
  "${script_dir}/smoke_test_production.sh"
else
  ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
    "set -e; source /etc/jiaotang-kb.env; curl --fail --silent http://127.0.0.1:8100/health >/dev/null; systemctl is-active --quiet jiaotang-kb"
  echo "未提供本地Token或设备标识，已完成服务健康与部署固定路由冒烟；带凭据REST/MCP冒烟由deploy_production.sh固定路由检查覆盖。"
fi

echo "本地归档、富索引、OSS增量同步和生产冒烟流水线完成。"
