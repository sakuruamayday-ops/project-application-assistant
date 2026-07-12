#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m pip install --user --no-build-isolation -e "$ROOT"
project-assistant --root "$ROOT" install --platform hermes "$@"
