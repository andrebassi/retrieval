#!/usr/bin/env bash
# Onde as estratégias discordam, com id de consulta e texto — não a média.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python tools/inspect_failures.py "$@"
