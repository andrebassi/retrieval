#!/usr/bin/env bash
# Reinicia a tela em segundo plano.
#
# O servidor sobe SEM reload (uvicorn com reload recarregaria os índices a cada
# toque em arquivo, e a carga leva alguns segundos). Consequência: toda edição em
# `app.py` só chega ao navegador depois de reiniciar — e conferir a tela contra um
# processo antigo é o jeito mais rápido de "provar" que um defeito foi corrigido
# quando ele nem chegou a ser servido.
#
# Espera o `/` responder 200 antes de sair: o `task web:check` logo em seguida
# falharia com conexão recusada enquanto o modelo ainda carrega.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8081}"
LOG="${LOG:-/tmp/retrieval-poc-web.log}"

echo "==> derrubando o processo anterior, se houver"
pkill -f "retrieval_poc.web.app" 2>/dev/null || true
sleep 1

echo "==> subindo em http://127.0.0.1:${PORT} (log em ${LOG})"
nohup .venv/bin/python -m retrieval_poc.web.app > "${LOG}" 2>&1 &

for _ in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/" 2>/dev/null || echo 000)
  if [ "${code}" = "200" ]; then
    echo "==> de pé (pid $(pgrep -f 'retrieval_poc.web.app' | head -1))"
    exit 0
  fi
  sleep 2
done

echo "🛑 não respondeu 200 em 80 s — últimas linhas do log:"
tail -20 "${LOG}"
exit 1
