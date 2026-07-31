#!/usr/bin/env bash
set -euo pipefail

deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"

echo "差异块直写已停用；服务器将从OSS签名release刷新并原子切换current。"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "set -e
   source /etc/jiaotang-kb-ops.env
   index_before=\$(readlink \"\${JIAOTANG_INDEX_DIR}/current\" 2>/dev/null || true)
   systemctl start jiaotang-kb-index-refresh.service
   index_after=\$(readlink \"\${JIAOTANG_INDEX_DIR}/current\" 2>/dev/null || true)
   systemctl restart jiaotang-kb
   healthy=0
   for attempt in \$(seq 1 30); do
     if curl --fail --silent --show-error http://127.0.0.1:8100/health >/dev/null 2>&1; then
       healthy=1
       break
     fi
     sleep 2
   done
   if [ \"\${healthy}\" -ne 1 ]; then
     if [ \"\${index_before}\" != \"\${index_after}\" ]; then
       set -a
       source /etc/jiaotang-kb-ops.env
       set +a
       /usr/local/sbin/jiaotang-kb-refresh-index --rollback
       systemctl restart jiaotang-kb
       curl --fail --silent --show-error --retry 10 --retry-delay 2 \
         http://127.0.0.1:8100/health >/dev/null
       echo '新索引健康失败；已自动回滚previous并复检通过' >&2
     fi
     exit 1
   fi
   systemctl start jiaotang-kb-health.service"

echo "OSS签名release刷新、current切换与健康复检完成。"
