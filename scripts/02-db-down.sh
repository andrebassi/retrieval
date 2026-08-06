#!/usr/bin/env bash
# Derruba o Postgres desta PoC — e só o dela.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=5434

# Identificar pela PORTA, não por `pkill -f process-compose`: o padrão genérico
# derruba junto o Postgres da PoC de embedding (5433), e o específico
# (`process-compose.*retrieval-poc`) não casa — o process-compose renomeia o
# processo e o caminho do projeto não aparece na linha de comando. Medido.
PIDS=$(lsof -nP -iTCP:${PORT} -sTCP:LISTEN -t 2>/dev/null || true)
if [ -z "$PIDS" ]; then
    echo "nada escutando na ${PORT}"
    exit 0
fi

echo "$PIDS" | xargs kill
sleep 3
if pg_isready -h 127.0.0.1 -p ${PORT} >/dev/null 2>&1; then
    echo "⚠️  ainda respondendo na ${PORT}"
    exit 1
fi
echo "✅ parado (5433, da PoC de embedding, não foi tocada)"
