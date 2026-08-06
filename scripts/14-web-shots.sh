#!/usr/bin/env bash
# Um print de cada aba, em /tmp/retrieval-poc-shots.
#
# Olhar a tela é parte da entrega (rule 32): o canário prova que a rota
# responde, não que o layout ficou de pé — layout colapsado não emite erro.
#
# Cada aba tem URL própria (`?tab=…`), então basta o `--screenshot` do Chrome.
# A alternativa era um script de CDP com websocket só para clicar na aba; a URL
# resolve o mesmo problema e ainda dá link compartilhável.
set -euo pipefail
cd "$(dirname "$0")/.."

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT="${1:-/tmp/retrieval-poc-shots}"
mkdir -p "$OUT"

if ! lsof -nP -iTCP:8081 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "🛑 tela não está de pé — rode 'task web' em outro terminal" >&2
  exit 1
fi

# nome | query | altura da janela
shot() {
  local name="$1" query="$2" height="$3"
  # `--virtual-time-budget` avança o relógio da página até as chamadas de rede
  # terminarem; sem ele o print sai antes do `/api/state` responder e mostra
  # "carregando a PoC…".
  timeout 90s "$CHROME" --headless --disable-gpu --no-sandbox \
    --window-size="1440,${height}" --virtual-time-budget=20000 \
    --screenshot="$OUT/$name.png" "http://127.0.0.1:8081/$query" >/dev/null 2>&1
  printf '  ✅ %-14s %s\n' "$name" "$(ls -la "$OUT/$name.png" | awk '{print $5" B"}')"
}

shot busca        ""                            1700
shot documento    "?tab=document&doc=ch_5506"   1500
shot placar       "?tab=score"                  1000
shot discordancia "?tab=disagree"               1700

echo "==> prints em $OUT"
