#!/usr/bin/env bash
set -euo pipefail

endpoint="${JIAOTANG_KB_ENDPOINT:?请设置 JIAOTANG_KB_ENDPOINT}"
token="${JIAOTANG_KB_TOKEN:?请设置 JIAOTANG_KB_TOKEN}"
device_id="${JIAOTANG_KB_DEVICE_ID:?请设置 JIAOTANG_KB_DEVICE_ID}"
device_name="${JIAOTANG_KB_DEVICE_NAME:-Production Smoke Device}"
query="${JIAOTANG_SMOKE_QUERY:-小巨人}"
endpoint="${endpoint%/}"
curl_args=(--fail-with-body --silent --show-error --max-time 30)

if [[ -n "${JIAOTANG_RESOLVE_IP:-}" ]]; then
    authority="${endpoint#*://}"
    authority="${authority%%/*}"
    host="${authority%%:*}"
    port="443"
    if [[ "${authority}" == *:* ]]; then
        port="${authority##*:}"
    fi
    curl_args+=(--resolve "${host}:${port}:${JIAOTANG_RESOLVE_IP}")
fi

auth=(
    -H "Authorization: Bearer ${token}"
    -H "X-Jiaotang-Device-ID: ${device_id}"
    -H "X-Jiaotang-Device-Name: ${device_name}"
)
header_file="$(mktemp)"
trap 'rm -f "${header_file}"' EXIT
unauthorized_status="$(curl --silent --show-error --max-time 30 -D "${header_file}" -o /dev/null -w '%{http_code}' "${curl_args[@]:1}" "${endpoint}/mcp/")"
[[ "${unauthorized_status}" = "401" ]] || { echo "MCP未认证请求未返回401" >&2; exit 1; }
me="$(curl "${curl_args[@]}" "${auth[@]}" "${endpoint}/v1/me")"
search_payload="$(JIAOTANG_SMOKE_QUERY_VALUE="${query}" python3 -c 'import json,os; print(json.dumps({"query": os.environ["JIAOTANG_SMOKE_QUERY_VALUE"], "limit": 3}, ensure_ascii=False))')"
search="$(curl "${curl_args[@]}" "${auth[@]}" -H 'Content-Type: application/json' -X POST \
    -d "${search_payload}" \
    "${endpoint}/v1/search")"
document_id="$(printf '%s' "${search}" | python3 -c 'import json,sys; rows=json.load(sys.stdin)["results"]; print(rows[0]["document_id"] if rows else "")')"
[[ -n "${document_id}" ]] || { echo "检索未命中文档" >&2; exit 1; }
document="$(curl "${curl_args[@]}" "${auth[@]}" "${endpoint}/v1/documents/${document_id}")"
usage="$(curl "${curl_args[@]}" "${auth[@]}" "${endpoint}/v1/usage")"
skills="$(curl "${curl_args[@]}" "${auth[@]}" "${endpoint}/v1/skills/latest")"

ME="${me}" SEARCH="${search}" DOCUMENT="${document}" USAGE="${usage}" SKILLS="${skills}" python3 - <<'PY'
import json
import os

me = json.loads(os.environ["ME"])
search = json.loads(os.environ["SEARCH"])
document = json.loads(os.environ["DOCUMENT"])
usage = json.loads(os.environ["USAGE"])
skills = json.loads(os.environ["SKILLS"])
print("生产冒烟测试通过")
print("用户：" + me["username"])
print("检索命中：" + str(len(search["results"])))
print("文档：" + document["title"])
print("累计调用：" + str(usage["total_calls"]))
print("Skills：" + (skills.get("version") or "尚未发布"))
PY
