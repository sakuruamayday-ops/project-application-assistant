#!/usr/bin/env bash
set -euo pipefail

deploy_host="${JIAOTANG_DEPLOY_HOST:?请设置JIAOTANG_DEPLOY_HOST}"
deploy_key="${JIAOTANG_DEPLOY_KEY:-${HOME}/.ssh/jiaotang_kb_aliyun}"
progress_interval="${JIAOTANG_INDEX_REFRESH_PROGRESS_INTERVAL_SECONDS:-15}"
if [[ ! "${progress_interval}" =~ ^[1-9][0-9]{0,2}$ ]]; then
  echo "JIAOTANG_INDEX_REFRESH_PROGRESS_INTERVAL_SECONDS必须为1至999的整数" >&2
  exit 64
fi

echo "差异块直写已停用；服务器将从OSS签名release刷新并原子切换current。"
ssh -i "${deploy_key}" -o BatchMode=yes "${deploy_host}" \
  "set -e
   source /etc/jiaotang-kb-ops.env
   progress_interval=${progress_interval}
   index_before=\$(readlink \"\${JIAOTANG_INDEX_DIR}/current\" 2>/dev/null || true)
   refresh_state=\$(systemctl show jiaotang-kb-index-refresh.service -p ActiveState --value)
   if [ \"\${refresh_state}\" = active ] || [ \"\${refresh_state}\" = activating ]; then
     echo '已有服务器索引刷新任务在运行，拒绝并发加入' >&2
     exit 75
   fi
   refresh_started=\$(date +%s)
   systemctl reset-failed jiaotang-kb-index-refresh.service >/dev/null 2>&1 || true
   systemctl start --no-block jiaotang-kb-index-refresh.service
   while true; do
     refresh_state=\$(systemctl show jiaotang-kb-index-refresh.service -p ActiveState --value)
     refresh_substate=\$(systemctl show jiaotang-kb-index-refresh.service -p SubState --value)
     refresh_result=\$(systemctl show jiaotang-kb-index-refresh.service -p Result --value)
     elapsed=\$((\$(date +%s) - refresh_started))
     latest_progress=\$(journalctl -u jiaotang-kb-index-refresh.service \
       --since \"@\${refresh_started}\" --no-pager -o cat 2>/dev/null \
       | grep '^\\[release-progress\\]' | tail -1 || true)
     echo \"[index-refresh] elapsed_seconds=\${elapsed} state=\${refresh_state}/\${refresh_substate} result=\${refresh_result:-pending} \${latest_progress}\"
     if [ \"\${refresh_state}\" = failed ]; then
       journalctl -u jiaotang-kb-index-refresh.service \
         --since \"@\${refresh_started}\" --no-pager -n 80 >&2 || true
       exit 1
     fi
     if [ \"\${refresh_state}\" = inactive ]; then
       if [ \"\${refresh_result}\" != success ]; then
         journalctl -u jiaotang-kb-index-refresh.service \
           --since \"@\${refresh_started}\" --no-pager -n 80 >&2 || true
         exit 1
       fi
       break
     fi
     sleep \"\${progress_interval}\"
   done
   index_after=\$(readlink \"\${JIAOTANG_INDEX_DIR}/current\" 2>/dev/null || true)
   # OnFailure 恢复器可能接管首次启动并让 restart 瞬时返回非零；最终结果仍由下面的健康复检和回滚决定。
   systemctl restart jiaotang-kb || true
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
       systemctl restart jiaotang-kb || true
       curl --fail --silent --show-error --retry 10 --retry-delay 2 \
         http://127.0.0.1:8100/health >/dev/null
       echo '新索引健康失败；已自动回滚previous并复检通过' >&2
     fi
     exit 1
   fi
   systemctl start jiaotang-kb-health.service"

echo "OSS签名release刷新、current切换与健康复检完成。"
