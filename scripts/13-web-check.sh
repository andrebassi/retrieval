#!/usr/bin/env bash
# Canário do front: sobe o servidor, exercita todas as rotas, derruba.
#
# Reaproveita o servidor se já houver um na 8081 — assim dá para rodar o canário
# contra a tela que está aberta no browser, que é o caso em que ele mais serve.
set -euo pipefail
cd "$(dirname "$0")/.."

STARTED=""
cleanup() {
  if [ -n "$STARTED" ]; then
    kill "$STARTED" 2>/dev/null || true
    wait "$STARTED" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if lsof -nP -iTCP:8081 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "==> usando o servidor que já está na 8081"
else
  echo "==> subindo servidor efêmero"
  .venv/bin/python -m retrieval_poc.web.app >/tmp/retrieval-poc-web.log 2>&1 &
  STARTED=$!
  # O startup carrega o cross-encoder (~250 MB de pesos). Esperar por tempo fixo
  # daria flaky nos dois sentidos: cedo demais numa máquina fria, lento à toa
  # numa quente. Espera pela porta, com teto.
  for _ in $(seq 1 90); do
    if lsof -nP -iTCP:8081 -sTCP:LISTEN -t >/dev/null 2>&1; then break; fi
    if ! kill -0 "$STARTED" 2>/dev/null; then
      echo "🛑 servidor morreu no startup:" >&2
      tail -20 /tmp/retrieval-poc-web.log >&2
      exit 1
    fi
    sleep 1
  done
fi

.venv/bin/python tools/web_check.py "http://127.0.0.1:8081"
