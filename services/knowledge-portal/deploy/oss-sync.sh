#!/usr/bin/env bash
set -euo pipefail

echo "旧式OSS同步单元已停用；OSS发布请使用不可变内容寻址中央发布流水线。本轮未启用任何存量快照、历史对象、暂存或部署备份处置流程。" >&2
exit 78
