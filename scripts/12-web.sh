#!/usr/bin/env bash
# Sobe a tela em http://127.0.0.1:8081.
#
# Porta 8081 porque a 8080 é do `image-embedding-poc` — subir na 8080 derrubaria
# a outra PoC ou falharia com "address already in use", e nenhum dos dois é um
# jeito aceitável de descobrir isso.
set -euo pipefail
cd "$(dirname "$0")/.."

# O banco precisa estar de pé: o startup carrega o catálogo e o cross-encoder de
# uma vez só. Falhar aqui, com mensagem clara, é melhor que a tela subir e a
# primeira busca estourar 500.
if ! lsof -nP -iTCP:5434 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "🛑 Postgres da PoC não está na 5434 — rode 'task db:up' antes" >&2
  exit 1
fi

if [ ! -f src/retrieval_poc/web/static/index.html ]; then
  echo "⚠️  front não compilado — rodando 'task web:build' antes" >&2
  bash scripts/11-web-build.sh
fi

echo "==> http://127.0.0.1:8081  (docs em /api/docs)"
exec .venv/bin/python -m retrieval_poc.web.app
