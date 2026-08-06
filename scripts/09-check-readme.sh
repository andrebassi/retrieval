#!/usr/bin/env bash
# Canário da documentação: acusa número do README que não bate com o medido.
# Complementa o `07-verify.sh`, que é o canário do índice.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python tools/check_readme.py "$@"
