#!/usr/bin/env bash
# Sobe o Postgres do Nix e espera ele aceitar conexão.
#
# Nix, não Docker: recurso local desta máquina não roda em container (rule 23).
# A porta é 5434 porque 5432 é o Postgres do sistema e 5433 é o da PoC de
# embedding — as duas rodam juntas sem se pisar.
set -euo pipefail
cd "$(dirname "$0")/.."

LOG=/tmp/retrieval-poc-pg.log

if pg_isready -h 127.0.0.1 -p 5434 >/dev/null 2>&1; then
    echo "✅ Postgres já de pé em 127.0.0.1:5434"
    exit 0
fi

echo "subindo Postgres 17 + pgvector via Nix…"
# `path:` em vez de `.`: com `.` o Nix resolve o flake pelo repositório git de
# `labs/` e recusa arquivo ainda não versionado com
# "Path 'retrieval-poc' ... is not tracked by Git". `path:` lê o diretório
# direto, e a PoC roda antes do primeiro commit.
# `--tui=false`: sem terminal interativo o process-compose morre no arranque com
# "TUI startup error: open /dev/tty: device not configured".
nohup nix run "path:$PWD#services" -- --tui=false >"$LOG" 2>&1 &
echo "process-compose em background, log em $LOG"

for i in $(seq 1 60); do
    if pg_isready -h 127.0.0.1 -p 5434 >/dev/null 2>&1; then
        echo "✅ pronto depois de ${i}s"
        psql "postgresql://postgres@127.0.0.1:5434/retrieval" \
            -tAc "SELECT extname || ' ' || extversion FROM pg_extension WHERE extname = 'vector'"
        exit 0
    fi
    sleep 1
done

echo "🛑 Postgres não subiu em 60s — veja $LOG"
exit 1
