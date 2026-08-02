#!/bin/zsh
set -euo pipefail

if [[ -z "${SME_SCORE_NODE_BIN:-}" || -z "${SME_SCORE_NODE_MODULES:-}" ]]; then
  print -u2 "请先通过工作区依赖加载器取得 Node 与 node_modules 路径，并设置 SME_SCORE_NODE_BIN、SME_SCORE_NODE_MODULES。"
  exit 2
fi

script_dir="${0:A:h}"
skill_dir="${script_dir:h}"
run_dir="$(mktemp -d "${TMPDIR:-/tmp}/sme-score.XXXXXX")"
ln -s "$SME_SCORE_NODE_MODULES" "$run_dir/node_modules"
cp "$script_dir/score_engine.mjs" "$run_dir/score_engine.mjs"
exec "$SME_SCORE_NODE_BIN" "$run_dir/score_engine.mjs" --skill-dir "$skill_dir" "$@"
